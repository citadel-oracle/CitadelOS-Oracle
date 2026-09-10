"""Crash-isolated, paper-only Strategy Lab runtime."""

from __future__ import annotations

import threading
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from .models import DeploymentRequest, PaperExecutionPort, StrategyMetadata
from .paper_engine import calculate_institutional_statistics
from .storage import StrategyWorkspace
from ..paper_trading.contracts import ContractResolutionError, OptionContractResolver


class DisabledPaperExecution:
    """Truthful default until a reviewed isolated paper adapter is supplied."""

    def process(self, *, evaluation, context, workspace):
        return {
            "status": "NOT_CONFIGURED",
            "reason": "ISOLATED_PAPER_EXECUTION_ADAPTER_REQUIRED",
            "broker_submission": False,
            "live_trading_enabled": False,
            "paper_state_mutated": False,
        }


class IsolatedRiskInstance:
    """Per-runtime risk ownership without inventing authorization formulas."""

    def __init__(self, workspace: StrategyWorkspace, risk_model: str):
        self.workspace = workspace
        self.risk_model = risk_model

    def projection(self) -> Dict[str, Any]:
        state = self.workspace.read("risk_state")
        return {
            **state,
            "risk_model": self.risk_model,
            "instance_scope": str(self.workspace.root),
            "authorization": "NOT_EVALUATED",
            "formula_source": "DEPLOYED_STRATEGY_PACKAGE_REQUIRED",
        }


class StrategyRuntime:
    """One daemon thread, state tree, strategy instance, and failure boundary."""

    def __init__(
        self,
        *,
        request: DeploymentRequest,
        workspace: StrategyWorkspace,
        catchup_semaphore: threading.BoundedSemaphore | None = None,
    ):
        self.metadata = request.metadata
        self.strategy = self._restore_strategy(request.adapter, workspace)
        self.context_provider = request.context_provider
        self.execution: PaperExecutionPort = request.execution or DisabledPaperExecution()
        self.option_resolver = request.option_resolver or OptionContractResolver()
        self.workspace = workspace
        self.risk = IsolatedRiskInstance(workspace, request.metadata.risk_model)
        self.interval = max(1.0, float(request.scheduler_interval_seconds))
        self._stop = threading.Event()
        self._tick_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._catchup_semaphore = catchup_semaphore
        self._catchup_waits = 0
        self._catchup_active = False
        self._gap_replay_contexts: List[Dict[str, Any]] = []
        self._pending_evaluation_contexts: List[Dict[str, Any]] = []
        # Strategy mathematics are finalized-candle based.  Some live candle
        # providers can expose their current immutable revision without
        # rebuilding/deep-copying thousands of history rows.  Remember the
        # last revision that reached the existing exactly-once gate so the
        # scheduler can coalesce redundant timer wakes before that expensive
        # context construction.  Direct tick_once/replay calls are unchanged.
        self._last_scheduled_context_revision: Optional[str] = None
        self._unchanged_context_coalesces = 0
        self._bootstrap_evaluation_cursor()
        self._reconcile_restored_scheduler_truth(request)

    def _reconcile_restored_scheduler_truth(self, request: DeploymentRequest) -> None:
        """A persisted RUNNING flag cannot represent a thread in a new process."""

        scheduler = self.workspace.read("scheduler_state")
        runtime = self.workspace.read("runtime")

        changed = False
        if "activation_enabled" not in scheduler or scheduler["activation_enabled"] is None:
            scheduler["activation_enabled"] = bool(request.activation_enabled)
            changed = True
        if "activation_reason" not in scheduler:
            scheduler["activation_reason"] = (
                None if request.activation_enabled
                else request.activation_reason or "DEPLOYMENT_ACTIVATION_DISABLED"
            )
            changed = True

        if scheduler.get("state") == "RUNNING" or runtime.get("state") == "RUNNING":
            scheduler["state"] = "STOPPED"
            scheduler["activation_enabled"] = bool(request.activation_enabled)
            scheduler["activation_reason"] = (
                None if request.activation_enabled
                else request.activation_reason or "DEPLOYMENT_ACTIVATION_DISABLED"
            )
            self.workspace.write("scheduler_state", scheduler)
            self.workspace.write("readiness_state", {
                "DATA_READY": False,
                "not_ready_reason": "HISTORY_LOADING",
                "runtime_state": "STOPPED",
                "scheduler_state": "STOPPED",
                "thread_alive": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self._set_runtime(
                "STOPPED",
                "HEALTHY",
                "READY",
                reason="SCHEDULER_RESTART_PENDING",
            )
        elif changed:
            self.workspace.write("scheduler_state", scheduler)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            if not self._stop.is_set():
                self._set_scheduler_started_runtime()
                scheduler = self.workspace.read("scheduler_state")
                scheduler["state"] = "RUNNING"
                scheduler["activation_enabled"] = True
                scheduler["activation_reason"] = None
                self.workspace.write("scheduler_state", scheduler)
            return
        self._stop.clear()
        self._set_scheduler_started_runtime()
        scheduler = self.workspace.read("scheduler_state")
        scheduler["state"] = "RUNNING"
        scheduler["activation_enabled"] = True
        scheduler["activation_reason"] = None
        self.workspace.write("scheduler_state", scheduler)
        self._thread = threading.Thread(
            target=self._loop,
            name=f"strategy-lab-{self.metadata.strategy_id}",
            daemon=True,
        )
        self._thread.start()

    def gate_activation(self, reason: str) -> None:
        """Keep a reviewed deployment loaded without evaluating market data."""

        scheduler = self.workspace.read("scheduler_state")
        scheduler["state"] = "STOPPED"
        scheduler["activation_enabled"] = False
        scheduler["activation_reason"] = reason
        self.workspace.write("scheduler_state", scheduler)
        self._set_runtime(
            "REGISTERED",
            "HEALTHY",
            "BLOCKED",
            reason=reason,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=min(5.0, self.interval + 1.0))
        scheduler = self.workspace.read("scheduler_state")
        scheduler["state"] = "STOPPED"
        self.workspace.write("scheduler_state", scheduler)
        self._set_runtime("STOPPED", "HEALTHY", "READY", reason="SCHEDULER_STOPPED")

    def _loop(self) -> None:
        immediate = False
        while not self._stop.wait(0.0 if immediate else self.interval):
            has_backlog = bool(
                self._pending_evaluation_contexts
                or (self._gap_replay_contexts and self._has_open_paper_position())
            )
            revision = None if has_backlog else self._scheduled_context_revision()
            if (
                revision is not None
                and revision == self._last_scheduled_context_revision
            ):
                self._unchanged_context_coalesces += 1
                immediate = False
                continue

            semaphore = self._catchup_semaphore
            acquired = semaphore is None or semaphore.acquire(timeout=min(0.25, self.interval))
            if not acquired:
                self._catchup_waits += 1
                immediate = False
                continue
            try:
                self._catchup_active = True
                outcome = self._drain_backlog_pass()
            finally:
                self._catchup_active = False
                if semaphore is not None:
                    semaphore.release()
            # Only freeze a revision after the existing runtime has either
            # evaluated it or proved it was already processed.  Unavailable,
            # stale, or malformed inputs continue to retry on the established
            # cadence so recovery cannot be hidden by this serving-plane fix.
            if revision is not None and (
                outcome.get("last_status") == "EVALUATED"
                or outcome.get("last_reason") == "CANDLE_ALREADY_PROCESSED"
            ):
                self._last_scheduled_context_revision = revision
            immediate = bool(
                self._pending_evaluation_contexts
                or (self._gap_replay_contexts and self._has_open_paper_position())
            )

    def _scheduled_context_revision(self) -> Optional[str]:
        """Return a cheap provider-owned revision when one is available."""

        revision_provider = getattr(self.context_provider, "current_revision", None)
        if not callable(revision_provider):
            return None
        try:
            revision = revision_provider()
        except Exception:
            return None
        return str(revision) if revision is not None else None

    def _drain_backlog_pass(self) -> Dict[str, Any]:
        """Refresh once, then drain one bounded chronological recovery batch."""

        started = perf_counter()
        results = [self.tick_once()]
        drain_started = perf_counter()
        while (
            len(results) < 25
            and perf_counter() - drain_started < 0.300
            and not self._stop.is_set()
        ):
            if self._gap_replay_contexts and self._has_open_paper_position():
                context = self._gap_replay_contexts.pop(0)
            elif self._pending_evaluation_contexts:
                context = self._pending_evaluation_contexts.pop(0)
            else:
                break
            results.append(self.tick_once(context_override=context))
        last = results[-1] if results else {}
        return {
            "processed": len(results),
            "remaining": len(self._pending_evaluation_contexts),
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "last_status": last.get("status"),
            "last_reason": last.get("reason"),
        }

    def bootstrap_data(self) -> Dict[str, Any]:
        """Prime authoritative history/readiness without evaluating the strategy."""

        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            context = deepcopy(dict(self.context_provider()))
        except Exception:
            context = {"data_readiness": {"DATA_READY": False, "not_ready_reason": "HISTORY_LOADING"}}
        readiness = context.get("data_readiness")
        payload = deepcopy(dict(readiness)) if isinstance(readiness, Mapping) else {
            "DATA_READY": False,
            "not_ready_reason": "HISTORY_LOADING",
        }
        ready = payload.get("DATA_READY") is True
        if ready:
            self._queue_completed_contexts(context, reason="SERVICE_RESTART")
        pipeline = getattr(self.strategy, "pipeline", None)
        certify = getattr(pipeline, "certify_source_data", None)
        if ready and callable(certify) and certify(context):
            state = self.workspace.read("strategy_state")
            serialized = self._serialize_strategy()
            try:
                state["adapter_state"] = json.loads(serialized) if isinstance(serialized, str) else serialized
            except (TypeError, ValueError, json.JSONDecodeError):
                state["adapter_state"] = serialized
            self.workspace.write("strategy_state", state)
        payload.update({
            "DATA_READY": ready,
            "runtime_state": "STARTING",
            "scheduler_state": "STOPPED",
            "thread_alive": False,
            "updated_at": timestamp,
        })
        self.workspace.write("readiness_state", payload)
        return payload

    def tick_once(self, context_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        if not self._tick_lock.acquire(blocking=False):
            self._increment_scheduler("skipped_count")
            return {"status": "SKIPPED", "reason": "TICK_ALREADY_RUNNING"}
        started = perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            provider_context = deepcopy(dict(
                context_override if context_override is not None else self.context_provider()
            ))
            if context_override is None:
                provider_rows = provider_context.get("completed_candles") or []
                provider_latest = provider_rows[-1] if provider_rows else provider_context.get("bar")
                self._queue_completed_contexts(provider_context, reason="CANDLE_GAP")
            else:
                provider_latest = None
            if context_override is None and self._gap_replay_contexts and self._has_open_paper_position():
                context = self._gap_replay_contexts.pop(0)
            else:
                if not self._has_open_paper_position():
                    self._gap_replay_contexts.clear()
                context = provider_context
                if context_override is None:
                    if self._pending_evaluation_contexts:
                        context = self._pending_evaluation_contexts.pop(0)
                        if provider_latest and self._candle_time(context.get("bar") or context) < self._candle_time(provider_latest):
                            context["historical_recovery"] = True
                            context["gap_replay"] = True
                            context["gap_replay_source"] = "CURRENT_SESSION_CATCH_UP"
            data_readiness = context.get("data_readiness")
            if isinstance(data_readiness, Mapping) and data_readiness.get("DATA_READY") is not True:
                reason = str(data_readiness.get("not_ready_reason") or "HISTORY_LOADING")
                self._begin_interruption(self._interruption_reason(reason), [], timestamp)
                self.workspace.write("readiness_state", {
                    **deepcopy(dict(data_readiness)), "DATA_READY": False,
                    "runtime_state": "RUNNING", "scheduler_state": "RUNNING",
                    "thread_alive": bool(self._thread and self._thread.is_alive()),
                    "updated_at": timestamp,
                })
                self._increment_scheduler("skipped_count")
                self._set_runtime("RUNNING", "DEGRADED", "BLOCKED", reason=reason)
                return {"status": "SKIPPED", "reason": reason, "DATA_READY": False}
            if not self._completed_candle(context):
                self._begin_interruption("CANDLE_GAP", [self._candle_id(context)], timestamp)
                self._increment_scheduler("skipped_count")
                return {"status": "SKIPPED", "reason": "COMPLETED_CANDLE_REQUIRED"}
            candle_id = self._candle_id(context)
            checkpoint = self.workspace.read("evaluation_checkpoint")
            cached = dict((checkpoint.get("processed_candles") or {}).get(candle_id) or {}) if candle_id else {}
            if not cached and candle_id:
                legacy = self.workspace.read_fields("strategy_state", ("processed_candles",))
                cached = dict((legacy.get("processed_candles") or {}).get(candle_id) or {})
            recover_cached_exit = self._recoverable_gap_exit(context, cached)
            if cached and not recover_cached_exit:
                self._increment_scheduler("skipped_count")
                return {"status": "SKIPPED", "reason": "CANDLE_ALREADY_PROCESSED", "decision": cached}
            serialized_before_evaluation = self._serialize_strategy()
            evaluation = dict(cached if recover_cached_exit else self.strategy.evaluate(context))
            # Fallback evaluation_id calculation (deterministic, stable after restart, and unique per evaluation)
            if not evaluation.get("evaluation_id"):
                eval_raw = f"{self.metadata.strategy_id}:{candle_id or timestamp}"
                evaluation["evaluation_id"] = f"eval_{hashlib.sha256(eval_raw.encode()).hexdigest()[:16]}"

            signal = str(evaluation.get("signal") or "WAIT").upper()
            if signal not in {"BUY", "SELL", "WAIT"}:
                raise ValueError("strategy adapter returned an invalid signal")
            evaluation["signal"] = signal

            # Shadow evaluation
            if signal == "BUY" and (self.metadata.parameters.get("mode") == "SHADOW" or self.metadata.parameters.get("argus_mode") == "SHADOW"):
                self._handle_shadow_evaluation(evaluation, context, timestamp)
            evaluation["strategy_id"] = self.metadata.strategy_id
            evaluation["evaluated_at"] = timestamp
            evaluation["paper_only"] = True
            evaluation["live_trading_enabled"] = False
            evaluation["broker_submission"] = False
            evaluation["risk_source"] = evaluation.get("risk_source") or "STRATEGY_RUNTIME_DECISION"
            evaluation["risk_source_timestamp"] = evaluation.get("risk_source_timestamp") or timestamp
            evaluation["strategy_version"] = evaluation.get("strategy_version") or self.metadata.version
            evaluation["risk_rule_version"] = evaluation.get("risk_rule_version") or evaluation.get("rule_version") or self.metadata.version
            if context.get("gap_replay") is True:
                evaluation["gap_replay"] = True
                evaluation["evaluation_id"] = (
                    f"{evaluation.get('evaluation_id')}:gap-replay:{self.metadata.strategy_id}:{candle_id}"
                )
            if candle_id:
                evaluation["candle_id"] = candle_id
            evaluation["bar_timestamp"] = evaluation.get("bar_timestamp") or (
                context.get("bar") or {}
            ).get("timestamp") or context.get("timestamp")
            evaluation["timeframe"] = evaluation.get("timeframe") or context.get("timeframe")
            evaluation["input_security_id"] = self._security_id(context)
            if (
                context.get("historical_recovery") is True
                and signal == "BUY"
                and not self._has_open_paper_position()
            ):
                evaluation.update({
                    "would_signal": "BUY",
                    "signal": "WAIT",
                    "reason": "MISSED_SIGNAL_DUE_TO_INFRA",
                    "recovery_result": "AUDIT_ONLY_NO_LATE_ENTRY",
                })
                self.workspace.logs.append(
                    "MISSED_SIGNAL_DUE_TO_INFRA",
                    {
                        "deployment_id": self.metadata.strategy_id,
                        "candle_id": candle_id,
                        "instrument_security_id": self._security_id(context),
                        "timeframe": context.get("timeframe"),
                        "would_signal": "BUY",
                        "execution_influence": "ZERO",
                    },
                    recorded_at=timestamp,
                    idempotency_key=f"missed-entry:{self.metadata.strategy_id}:{candle_id}",
                )
            suppressed = self._position_guard(evaluation)

            # ── Risk Engine Shadow Integration (post-guard) ────────────────────
            # Called for every BUY signal from any deployment.
            # EXECUTION INFLUENCE: ZERO — evaluation dict is never modified.
            # Captures suppression truth: candidate_status, suppression_reason, actionable.
            if signal == "BUY":
                try:
                    from src.risk_engine.service import UnifiedRiskEngineService
                    _risk_svc = UnifiedRiskEngineService.get_instance()
                    _candidate_key = (
                        f"{self.metadata.strategy_id}:{candle_id}" if candle_id else None
                    )
                    _status_str = "SUPPRESSED" if suppressed else "ENTRY_CANDIDATE"
                    _risk_plan = _risk_svc.evaluate_shadow_from_evaluation(
                        deployment_id=self.metadata.strategy_id,
                        evaluation=evaluation,
                        candidate_key=_candidate_key,
                        candidate_status=_status_str,
                        suppression_reason=suppressed,
                    )
                    # Store plan_id in evaluation for audit trail (read-only annotation)
                    evaluation.setdefault("_shadow_risk_plan_id", _risk_plan.plan_id)
                    evaluation.setdefault("_shadow_risk_skipped", _risk_plan.is_skipped)
                    evaluation.setdefault("_shadow_risk_skip_reason", _risk_plan.skip_reason.value)
                    evaluation.setdefault("_shadow_risk_actionable", _risk_plan.provenance.get("actionable"))
                except Exception as _exc:
                    try:
                        from src.risk_engine.service import UnifiedRiskEngineService
                        UnifiedRiskEngineService.get_instance().record_hook_failure(
                            self.metadata.strategy_id, _exc
                        )
                    except Exception:
                        pass

            # ── Premium Intelligence Shadow Integration ───────────────────────
            # Captures PRE regime & PLI lead for every strategy evaluation.
            # EXECUTION INFLUENCE: ZERO — strategy signal, decision, stop/target unchanged.
            try:
                from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
                _pi_svc = UnifiedPremiumIntelligenceService.get_instance()
                _pi_snap = _pi_svc.get_latest_snapshot()
                if _pi_snap:
                    _pre_state = _pi_snap.premium_layer_state
                    _pli_lead = _pi_snap.pli_snapshot.lead_side
                    _strategy_side = str(evaluation.get("side") or getattr(self.metadata, "option_side", "CALL")).upper()
                    _align = "NEUTRAL"
                    if _pli_lead == "CALL_LEAD" and _strategy_side in ("CALL", "LONG"):
                        _align = "SUPPORTIVE"
                    elif _pli_lead == "PUT_LEAD" and _strategy_side in ("PUT", "SHORT"):
                        _align = "SUPPORTIVE"
                    elif _pli_lead in ("CALL_LEAD", "PUT_LEAD"):
                        _align = "OPPOSED"

                    _pi_status = _pi_svc.get_status()
                    _auth_bar_id = _pi_status.get("authority_bar_id")
                    _auth_close_ts = _pi_status.get("authority_bar_close_timestamp")
                    _auth_status = "AUTHORITY_LIVE" if _auth_bar_id else "RESTORED_RAW_NOT_AUTHORITY"

                    evaluation.setdefault("_shadow_pi_snapshot_id", _pi_snap.snapshot_id)
                    evaluation.setdefault("_shadow_pre_state", _pre_state if _auth_bar_id else "RESTORED_PARTIAL")
                    evaluation.setdefault("_shadow_pre_regime", _pi_snap.pre_snapshot.regime)
                    evaluation.setdefault("_shadow_pli_lead", _pli_lead)
                    evaluation.setdefault("_shadow_pi_alignment", _align)
                    evaluation.setdefault("_shadow_authority_status", _auth_status)
                    evaluation.setdefault("_shadow_authority_bar_id", _auth_bar_id)
                    evaluation.setdefault("_shadow_authority_bar_close_timestamp", _auth_close_ts)
            except Exception as _exc:
                try:
                    from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
                    UnifiedPremiumIntelligenceService.get_instance().record_hook_failure(
                        self.metadata.strategy_id, _exc
                    )
                except Exception:
                    pass
            # ─────────────────────────────────────────────────────────────────
            if suppressed:
                decision = {
                    **evaluation,
                    "signal": "WAIT",
                    "reason": suppressed,
                    "paper_execution": {
                        "status": "NO_ACTION", "reason": suppressed, "paper_only": True,
                        "paper_state_mutated": False, "live_trading_enabled": False,
                        "broker_submission": False,
                    },
                }
                self._persist_runtime_state(decision, candle_id, timestamp)
                self._finish_interruption(candle_id, timestamp)
                
                # Check for counterfactual shadow outcome
                if self.metadata.parameters.get("mode") == "SHADOW" or self.metadata.parameters.get("argus_mode") == "SHADOW":
                    self._handle_shadow_outcome(timestamp, evaluation)

                self._increment_scheduler("tick_count", timestamp=timestamp, latency_ms=round((perf_counter() - started) * 1000, 3))
                return {"status": "SKIPPED", "reason": suppressed, "decision": decision}
            self._resolve_option(evaluation, context)
            self._bind_open_position_risk_identity(evaluation, context)
            evaluation["forensics"] = {
                "entry": evaluation.get("entry"),
                "exit": evaluation.get("exit"),
                "why_trade": evaluation.get("why_trade"),
                "why_not_trade": evaluation.get("why_not_trade") or evaluation.get("reason"),
                "technical_snapshot": evaluation.get("technical_snapshot") or context.get("technical"),
                "kronos": evaluation.get("kronos") or context.get("kronos"),
                "chronos": evaluation.get("chronos") or context.get("chronos"),
                "argus": evaluation.get("argus") or context.get("argus"),
                "athena": evaluation.get("athena") or context.get("athena"),
                "oracle": evaluation.get("oracle") or context.get("oracle"),
                "aegis": evaluation.get("aegis") or context.get("aegis"),
                "risk": evaluation.get("risk") or context.get("risk"),
                "module_votes": evaluation.get("module_votes"),
                "weights": evaluation.get("weights"),
                "confidence": evaluation.get("confidence"),
                "coverage": evaluation.get("coverage"),
                "mfe": evaluation.get("mfe"),
                "mae": evaluation.get("mae"),
            }
            latency = round((perf_counter() - started) * 1000, 3)
            compact_wait = (
                str(evaluation.get("signal") or "WAIT").upper() == "WAIT"
                and not self._has_open_paper_position()
                and not self._has_active_paper_orders()
                and not any(evaluation.get(key) is not None for key in (
                    "pending_setup", "setup_state", "position_state", "stop_update",
                    "target_update", "trailing_update",
                ))
            )
            if compact_wait:
                decision = {
                    **evaluation,
                    "latency_ms": latency,
                    "paper_execution": {
                        "status": "NO_ACTION", "reason": "STRATEGY_WAIT", "paper_only": True,
                        "paper_state_mutated": False, "live_trading_enabled": False,
                        "broker_submission": False,
                    },
                }
                self._persist_runtime_state(decision, candle_id, timestamp)
                self._finish_interruption(candle_id, timestamp)
                self.workspace.write("readiness_state", {
                    **(deepcopy(dict(data_readiness)) if isinstance(data_readiness, Mapping) else {}),
                    "DATA_READY": True,
                    "runtime_state": "CATCHING_UP" if self._pending_evaluation_contexts else "RUNNING",
                    "scheduler_state": "RUNNING",
                    "thread_alive": bool(self._thread and self._thread.is_alive()), "updated_at": timestamp,
                })
                self._increment_scheduler("tick_count", timestamp=timestamp, latency_ms=latency)
                self._set_post_evaluation_runtime(latency)
                return {"status": "EVALUATED", "decision": decision}
            evidence_payload = {
                "context": context,
                "evaluation": evaluation,
                "latency_ms": latency,
                "input_type": self.metadata.input_type.value,
            }
            evidence = self.workspace.evidence.append(
                "STRATEGY_EVIDENCE",
                evidence_payload,
                recorded_at=timestamp,
                idempotency_key=str(evaluation.get("evaluation_id") or "") or None,
            )
            replay = self.workspace.replay.append(
                "STRATEGY_REPLAY_ENVELOPE",
                {"evidence_record_id": evidence["record_id"], **evidence_payload},
                recorded_at=timestamp,
                idempotency_key=evidence["record_id"],
            )
            evaluation["evidence_record_id"] = evidence["record_id"]
            evaluation["replay_id"] = replay["record_id"]
            execution = self.execution.process(
                evaluation=evaluation,
                context=context,
                workspace=self.workspace,
            )
            # Record CAPITAL_UNAVAILABLE and set counterfactual active signal ID
            if (
                str(evaluation.get("signal")).upper() == "BUY"
                and str(execution.get("status")).upper() == "REJECTED"
                and str(execution.get("reason")).upper() in {"CAPITAL_UNAVAILABLE", "INSUFFICIENT_AVAILABLE_MARGIN"}
            ):
                self.workspace.journal.append(
                    "CAPITAL_UNAVAILABLE",
                    {
                        "strategy_id": self.metadata.strategy_id,
                        "evaluation_id": evaluation.get("evaluation_id"),
                        "reason": execution.get("reason"),
                        "required_margin": (evaluation.get("entry") or 0.0) * int(context.get("lot_size", 50)),
                    },
                    recorded_at=timestamp,
                )
                if hasattr(self.strategy.state, "counterfactual_active_signal_id"):
                    state = self.workspace.read("strategy_state")
                    active_signal_id = state.get("active_trade_signal_id")
                    if active_signal_id:
                        self.strategy.state.counterfactual_active_signal_id = active_signal_id
                        serialized = self._serialize_strategy()
                        try:
                            state["adapter_state"] = json.loads(serialized) if isinstance(serialized, str) else serialized
                        except Exception:
                            state["adapter_state"] = serialized
                        self.workspace.write("strategy_state", state)

            if self._failed_session_exit(evaluation, execution) or self._failed_gap_replay_exit(evaluation, execution):
                self._restore_serialized_strategy(serialized_before_evaluation)
            decision = {
                **evaluation,
                "latency_ms": latency,
                "evidence_record_id": evidence["record_id"],
                "replay_id": replay["record_id"],
                "paper_execution": dict(execution),
            }
            journal = self.workspace.journal.append(
                "STRATEGY_DECISION",
                decision,
                recorded_at=timestamp,
                idempotency_key=str(evaluation.get("evaluation_id") or evidence["record_id"]),
            )
            finalize = getattr(self.execution, "finalize_decision_lineage", None)
            if callable(finalize):
                finalize(
                    journal_id=journal["record_id"],
                    replay_id=replay["record_id"],
                    execution=execution,
                )
            self._persist_runtime_state(decision, candle_id, timestamp)
            self._finish_interruption(candle_id, timestamp)
            self.workspace.write("readiness_state", {
                **(deepcopy(dict(data_readiness)) if isinstance(data_readiness, Mapping) else {}),
                "DATA_READY": True,
                "runtime_state": "CATCHING_UP" if self._pending_evaluation_contexts else "RUNNING",
                "scheduler_state": "RUNNING",
                "thread_alive": bool(self._thread and self._thread.is_alive()), "updated_at": timestamp,
            })
            # Shadow outcome checking
            if self.metadata.parameters.get("mode") == "SHADOW" or self.metadata.parameters.get("argus_mode") == "SHADOW":
                self._handle_shadow_outcome(timestamp)

            self._increment_scheduler("tick_count", timestamp=timestamp, latency_ms=latency)
            self._set_post_evaluation_runtime(latency)
            return {"status": "EVALUATED", "decision": decision}
        except Exception as error:
            latency = round((perf_counter() - started) * 1000, 3)
            if "serialized_before_evaluation" in locals():
                self._restore_serialized_strategy(serialized_before_evaluation)
            if (
                isinstance(locals().get("context"), Mapping)
                and context.get("ordered_delivery") is True
                and all(self._candle_id(item) != self._candle_id(context) for item in self._pending_evaluation_contexts)
            ):
                self._pending_evaluation_contexts.insert(0, deepcopy(dict(context)))
            self._begin_interruption("EVALUATION_ERROR", [self._candle_id(locals().get("context", {}))], timestamp)
            self.workspace.logs.append(
                "RUNTIME_ERROR",
                {"error_type": type(error).__name__, "message": str(error)[:240], "latency_ms": latency},
                recorded_at=timestamp,
            )
            self._increment_scheduler("tick_count", timestamp=timestamp, latency_ms=latency)
            self._set_runtime("RUNNING", "DEGRADED", "LIMITED", reason="STRATEGY_RUNTIME_ERROR", latency_ms=latency)
            return {"status": "ERROR", "reason": "STRATEGY_RUNTIME_ERROR", "error_type": type(error).__name__}
        finally:
            self._tick_lock.release()

    def _has_open_paper_position(self) -> bool:
        projection = getattr(self.execution, "projection", None)
        if not callable(projection):
            return False
        try:
            return any(str(row.get("status") or "").upper() == "OPEN" for row in projection().get("positions") or [])
        except Exception:
            return False

    def _has_active_paper_orders(self) -> bool:
        projection = getattr(self.execution, "projection", None)
        if not callable(projection):
            return False
        try:
            return any(
                str(row.get("status") or "").upper() in {"PENDING", "PARTIAL"}
                for row in projection().get("orders") or []
            )
        except Exception:
            return False

    def _bootstrap_evaluation_cursor(self) -> None:
        """Restore a durable cursor from authoritative successful evaluations."""

        checkpoint = self.workspace.read("evaluation_checkpoint")
        if checkpoint.get("cursor"):
            return
        compact_processed = checkpoint.get("processed_candles") or {}
        compact_evaluated = [
            (self._parse_datetime(row.get("bar_timestamp")), str(candle_id), row)
            for candle_id, row in compact_processed.items() if isinstance(row, Mapping)
        ]
        compact_evaluated = [row for row in compact_evaluated if row[0] is not None]
        if compact_evaluated:
            _, candle_id, decision = max(compact_evaluated, key=lambda item: item[0])
            checkpoint["cursor"] = {
                "deployment_id": self.metadata.strategy_id,
                "instrument_security_id": str(decision.get("security_id") or ""),
                "timeframe": str(decision.get("timeframe") or ""),
                "last_completed_candle_id": candle_id,
                "last_completed_candle_timestamp": str(decision.get("bar_timestamp") or ""),
                "last_evaluated_candle_id": candle_id,
                "last_evaluated_candle_timestamp": str(decision.get("bar_timestamp") or ""),
                "evaluation_timestamp": str(decision.get("evaluated_at") or datetime.now(timezone.utc).isoformat()),
                "strategy_rule_version": self.metadata.version,
                "canonical_comparison_pending": True,
            }
            checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.workspace.write("evaluation_checkpoint", checkpoint)
            return
        state = self.workspace.read("strategy_state")
        if state.get("evaluation_cursor"):
            processed = state.get("processed_candles") or {}
            checkpoint.update({
                "deployment_id": self.metadata.strategy_id,
                "cursor": deepcopy(state["evaluation_cursor"]),
                "processed_candles": {
                    key: self._compact_evaluation_record(key, value)
                    for key, value in processed.items() if isinstance(value, Mapping)
                },
                "interruption": deepcopy(state.get("evaluation_interruption")),
                "historical_audit_backlog": deepcopy(state.get("historical_audit_backlog")),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self.workspace.write("evaluation_checkpoint", checkpoint)
            return
        processed = state.get("processed_candles") or {}
        evaluated = []
        for candle_id, decision in processed.items():
            if not isinstance(decision, Mapping):
                continue
            timestamp = (
                decision.get("bar_timestamp")
                or decision.get("timestamp")
                or (decision.get("bar") or {}).get("timestamp")
            )
            parsed = self._parse_datetime(timestamp)
            if parsed is not None:
                evaluated.append((parsed, str(candle_id), dict(decision), str(timestamp)))
        if not evaluated:
            return
        _, candle_id, decision, timestamp = max(evaluated, key=lambda item: item[0])
        option_contract = decision.get("option_contract")
        security_id = option_contract.get("security_id") if isinstance(option_contract, Mapping) else None
        now = datetime.now(timezone.utc).isoformat()
        state["evaluation_cursor"] = {
            "deployment_id": self.metadata.strategy_id,
            "instrument_security_id": str(
                decision.get("input_security_id") or decision.get("contract") or security_id or ""
            ),
            "timeframe": str(decision.get("timeframe") or ""),
            "last_completed_candle_id": candle_id,
            "last_completed_candle_timestamp": timestamp,
            "last_evaluated_candle_id": candle_id,
            "last_evaluated_candle_timestamp": timestamp,
            "evaluation_timestamp": str(state.get("last_evaluated_at") or now),
            "strategy_rule_version": self.metadata.version,
            "canonical_comparison_pending": True,
        }
        self.workspace.write("strategy_state", state)
        checkpoint.update({
            "deployment_id": self.metadata.strategy_id,
            "cursor": deepcopy(state["evaluation_cursor"]),
            "processed_candles": {
                key: self._compact_evaluation_record(key, value)
                for key, value in processed.items() if isinstance(value, Mapping)
            },
            "interruption": deepcopy(state.get("evaluation_interruption")),
            "historical_audit_backlog": deepcopy(state.get("historical_audit_backlog")),
            "updated_at": now,
        })
        self.workspace.write("evaluation_checkpoint", checkpoint)
        interruption = state.get("evaluation_interruption")
        if (
            isinstance(interruption, Mapping)
            and interruption.get("status") == "ACTIVE"
            and not interruption.get("affected_candle_ids")
        ):
            self._finish_interruption(candle_id, now)

    def _queue_completed_contexts(self, context: Mapping[str, Any], *, reason: str) -> None:
        """Queue every unseen canonical candle after the durable cursor in order."""

        history = context.get("completed_candles")
        if not isinstance(history, list) or not history:
            return
        checkpoint = self.workspace.read("evaluation_checkpoint")
        cursor = dict(checkpoint.get("cursor") or {})
        processed = checkpoint.get("processed_candles") or {}
        rows = [deepcopy(dict(item)) for item in history if isinstance(item, Mapping) and item.get("timestamp")]
        rows.sort(key=lambda item: self._candle_time(item))
        if not rows:
            return
        latest = rows[-1]
        latest_id = self._history_candle_id(context, latest)
        last_time = self._parse_datetime(cursor.get("last_evaluated_candle_timestamp"))
        if cursor.pop("canonical_comparison_pending", False):
            row_ids = [self._history_candle_id(context, item) for item in rows]
            processed_indexes = [index for index, candle_id in enumerate(row_ids) if candle_id in processed]
            if processed_indexes:
                anchor = processed_indexes[0]
                while anchor + 1 < len(rows) and row_ids[anchor + 1] in processed:
                    anchor += 1
                last_time = self._candle_time(rows[anchor])
                cursor.update({
                    "last_evaluated_candle_id": row_ids[anchor],
                    "last_evaluated_candle_timestamp": str(rows[anchor].get("timestamp")),
                })
            else:
                last_time = None
        if last_time is None:
            processed_times = [
                self._parse_datetime((item or {}).get("bar_timestamp") or (item or {}).get("timestamp"))
                for item in processed.values() if isinstance(item, Mapping)
            ]
            last_time = max((item for item in processed_times if item is not None), default=None)
        candidates = [
            item for item in rows
            if (last_time is None or self._candle_time(item) > last_time)
            and self._history_candle_id(context, item) not in processed
        ]
        if last_time is None and not processed:
            candidates = candidates[-1:]
        checkpoint["cursor"] = {
            **cursor,
            "deployment_id": self.metadata.strategy_id,
            "instrument_security_id": str(
                cursor.get("instrument_security_id") or self._security_id(context, latest)
            ),
            "last_completed_security_id": self._security_id(context, latest),
            "timeframe": str(context.get("timeframe") or latest.get("timeframe") or ""),
            "last_completed_candle_id": latest_id,
            "last_completed_candle_timestamp": str(latest.get("timestamp")),
            "strategy_rule_version": self.metadata.version,
        }
        checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.workspace.write("evaluation_checkpoint", checkpoint)
        if not candidates:
            self._finish_interruption(cursor.get("last_evaluated_candle_id"), datetime.now(timezone.utc).isoformat())
            return
        latest_security = self._security_id(context, latest)
        cursor_security = str(cursor.get("instrument_security_id") or "")
        interruption_reason = "CONTRACT_ROTATION" if cursor_security and latest_security and cursor_security != latest_security else reason
        newest_time = self._candle_time(latest)
        session_date = newest_time.astimezone(ZoneInfo("Asia/Kolkata")).date()
        live_candidates = []
        historical_candidates = []
        for item in candidates:
            item_security = self._security_id(context, item)
            is_current_session = self._candle_time(item).astimezone(ZoneInfo("Asia/Kolkata")).date() == session_date
            if is_current_session and item_security == latest_security:
                live_candidates.append(item)
            else:
                historical_candidates.append(item)

        checkpoint = self.workspace.read("evaluation_checkpoint")
        checkpoint["cursor"] = {
            **dict(checkpoint.get("cursor") or {}),
            "instrument_security_id": latest_security,
        }
        existing_audit = dict(checkpoint.get("historical_audit_backlog") or {})
        audit_ids = list(dict.fromkeys([
            *(existing_audit.get("candle_ids") or []),
            *[self._history_candle_id(context, item) for item in historical_candidates],
        ]))
        checkpoint["historical_audit_backlog"] = {
            "status": "AUDIT_PENDING" if audit_ids else "CLEAR",
            "reason": "OBSOLETE_SESSION_OR_CONTRACT",
            "candle_ids": audit_ids,
            "count": len(audit_ids),
            "execution_influence": "ZERO",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.workspace.write("evaluation_checkpoint", checkpoint)

        pending_ids = [self._history_candle_id(context, item) for item in live_candidates]
        if pending_ids:
            self._begin_interruption(interruption_reason, pending_ids, datetime.now(timezone.utc).isoformat())
        existing = {self._candle_id(item) for item in self._pending_evaluation_contexts}
        for item in live_candidates:
            candidate = self._context_for_history_candle(context, item)
            candidate["ordered_delivery"] = True
            candidate["historical_recovery"] = self._candle_time(item) < newest_time
            if candidate["historical_recovery"]:
                candidate["gap_replay"] = True
                candidate["gap_replay_source"] = "CANONICAL_COMPLETED_CANDLE"
            if self._candle_id(candidate) not in existing:
                self._pending_evaluation_contexts.append(candidate)
                existing.add(self._candle_id(candidate))
        self._pending_evaluation_contexts.sort(key=lambda item: self._candle_time(item.get("bar") or item))

    def _context_for_history_candle(
        self,
        context: Mapping[str, Any],
        item: Mapping[str, Any],
    ) -> Dict[str, Any]:
        result = deepcopy(dict(context))
        result.pop("completed_candles", None)
        result.pop("warmup_candle_count", None)
        timestamp = str(item["timestamp"])
        result.update({
            "candle_id": self._history_candle_id(context, item),
            "timestamp": timestamp,
            "source_timestamp": timestamp,
            "bar": deepcopy(dict(item)),
            "closed": True,
            "is_closed": True,
        })
        if item.get("contract"):
            result.update({
                "contract": str(item["contract"]),
                "option_contract": str(item["contract"]),
                "chart_contract": deepcopy(dict(item.get("chart_contract") or {})),
                "lot_size": item.get("lot_size"),
                "current_price": float(item["close"]),
                "paper_price": float(item["close"]),
                "option_price": float(item["close"]),
            })
        return result

    def _history_candle_id(self, context: Mapping[str, Any], item: Mapping[str, Any]) -> str:
        symbol = str(context.get("symbol") or context.get("underlying") or "UNKNOWN").upper()
        timeframe = str(context.get("timeframe") or item.get("timeframe") or "UNKNOWN")
        return f"{symbol}:{timeframe}:{item.get('timestamp')}"

    @staticmethod
    def _candle_time(item: Mapping[str, Any]) -> datetime:
        parsed = StrategyRuntime._parse_datetime(item.get("timestamp"))
        return parsed or datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _security_id(context: Mapping[str, Any], item: Mapping[str, Any] | None = None) -> str:
        source = item or context
        chart = source.get("chart_contract") if isinstance(source.get("chart_contract"), Mapping) else {}
        return str(source.get("contract") or chart.get("security_id") or context.get("contract") or context.get("symbol") or "")

    @staticmethod
    def _interruption_reason(reason: str) -> str:
        value = str(reason or "").upper()
        if "QUOTE" in value or "OPTION_CHAIN" in value:
            return "QUOTE_UNAVAILABLE"
        if "RECONNECT" in value or "STALE" in value:
            return "FEED_RECONNECT"
        if "GAP" in value or "CANDLE" in value:
            return "CANDLE_GAP"
        return "NOT_READY"

    def _begin_interruption(self, reason: str, candle_ids: List[Optional[str]], timestamp: str) -> None:
        checkpoint = self.workspace.read("evaluation_checkpoint")
        current = checkpoint.get("interruption")
        affected = [str(item) for item in candle_ids if item]
        if isinstance(current, Mapping) and current.get("status") == "ACTIVE" and current.get("reason") == reason:
            merged = list(dict.fromkeys([*(current.get("affected_candle_ids") or []), *affected]))
            checkpoint["interruption"] = {**dict(current), "affected_candle_ids": merged}
            checkpoint["updated_at"] = timestamp
            self.workspace.write("evaluation_checkpoint", checkpoint)
            return
        interruption = {
            "deployment_id": self.metadata.strategy_id,
            "status": "ACTIVE",
            "reason": reason,
            "started_at": timestamp,
            "ended_at": None,
            "affected_candle_ids": affected,
            "recovery_result": None,
        }
        checkpoint["interruption"] = interruption
        checkpoint["updated_at"] = timestamp
        self.workspace.write("evaluation_checkpoint", checkpoint)
        self.workspace.logs.append(
            "EVALUATION_INTERRUPTION_STARTED",
            interruption,
            recorded_at=timestamp,
            idempotency_key=f"interruption:{self.metadata.strategy_id}:{reason}:{affected[0] if affected else timestamp}",
        )

    def _finish_interruption(self, candle_id: Optional[str], timestamp: str) -> None:
        if len(self._pending_evaluation_contexts) > 1:
            return
        checkpoint = self.workspace.read("evaluation_checkpoint")
        current = checkpoint.get("interruption")
        if not isinstance(current, Mapping) or current.get("status") != "ACTIVE":
            return
        recovered = {
            **dict(current),
            "status": "RECOVERED",
            "ended_at": timestamp,
            "recovery_result": "ALL_AFFECTED_CANDLES_EVALUATED",
            "last_recovered_candle_id": candle_id,
        }
        checkpoint["interruption"] = recovered
        checkpoint["updated_at"] = timestamp
        self.workspace.write("evaluation_checkpoint", checkpoint)
        self.workspace.logs.append(
            "EVALUATION_INTERRUPTION_RECOVERED",
            recovered,
            recorded_at=timestamp,
            idempotency_key=f"interruption-recovered:{self.metadata.strategy_id}:{current.get('started_at')}",
        )

    def _prepare_gap_replay(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Replay authoritative completed candles only while recovering an open position."""

        history = context.get("completed_candles")
        if not self._has_open_paper_position() or not isinstance(history, list):
            return context
        strategy_state = self.workspace.read("strategy_state")
        processed = strategy_state.get("processed_candles") or {}
        current_decision = strategy_state.get("current_decision") or {}
        positioned_decisions = [
            row for row in (strategy_state.get("processed_candles") or {}).values()
            if isinstance(row, Mapping) and isinstance(row.get("position_state"), Mapping)
        ]
        last_positioned = positioned_decisions[-1] if positioned_decisions else current_decision
        last_bar_index = last_positioned.get("bar_index")
        if not isinstance(last_bar_index, int):
            adapter_state = strategy_state.get("adapter_state") or {}
            engine_state = adapter_state.get("engine", {}).get("state", {}) if isinstance(adapter_state, Mapping) else {}
            candidate = engine_state.get("last_bar_index") if isinstance(engine_state, Mapping) else None
            last_bar_index = candidate if isinstance(candidate, int) else None
        symbol = str(context.get("symbol") or "").upper()
        timeframe = str(context.get("timeframe") or "")
        pending: List[Dict[str, Any]] = []
        for item in history:
            if not isinstance(item, Mapping):
                continue
            timestamp = str(item.get("timestamp") or "")
            candle_id = f"{symbol}:{timeframe}:{timestamp}"
            item_index = item.get("index")
            cached = dict(processed.get(candle_id) or {})
            if (
                not timestamp
                or (candle_id in processed and not self._recoverable_gap_exit({"gap_replay": True}, cached))
                or (isinstance(last_bar_index, int) and isinstance(item_index, int) and item_index <= last_bar_index)
            ):
                continue
            replay = deepcopy(context)
            replay.pop("completed_candles", None)
            replay.pop("warmup_candle_count", None)
            replay.update({
                "candle_id": candle_id,
                "timestamp": timestamp,
                "source_timestamp": timestamp,
                "bar": deepcopy(dict(item)),
                "current_price": float(item["close"]),
                "paper_price": float(item["close"]),
                "option_price": float(item["close"]),
                "gap_replay": True,
                "gap_replay_source": "CANONICAL_COMPLETED_CANDLE",
            })
            pending.append(replay)
        if not pending:
            return context
        pending.sort(key=lambda item: str(item["timestamp"]))
        self._gap_replay_contexts = pending[1:]
        return pending[0]

    def _recoverable_gap_exit(self, context: Mapping[str, Any], cached: Mapping[str, Any]) -> bool:
        execution = cached.get("paper_execution") if isinstance(cached, Mapping) else None
        return (
            context.get("gap_replay") is True
            and str(cached.get("signal") or "").upper() == "SELL"
            and str((execution or {}).get("status") or "").upper() != "FILLED"
            and self._has_open_paper_position()
        )

    def _restore_strategy(self, adapter: Any, workspace: StrategyWorkspace) -> Any:
        payload = workspace.read("strategy_state").get("adapter_state")
        restore = getattr(type(adapter), "deserialize", None)
        if payload and callable(restore):
            serialized = (
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
                if isinstance(payload, (Mapping, list))
                else str(payload)
            )
            return restore(serialized)
        return adapter

    def _serialize_strategy(self) -> Any:
        serialize = getattr(self.strategy, "serialize", None)
        return serialize() if callable(serialize) else None

    def _restore_serialized_strategy(self, payload: Any) -> None:
        restore = getattr(type(self.strategy), "deserialize", None)
        if payload is not None and callable(restore):
            self.strategy = restore(payload if isinstance(payload, str) else json.dumps(payload))

    @staticmethod
    def _failed_session_exit(
        evaluation: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> bool:
        reason = str(evaluation.get("exit_reason") or evaluation.get("reason") or "").upper()
        return (
            str(evaluation.get("signal") or "").upper() == "SELL"
            and ("SESSION" in reason or "SQUARE_OFF" in reason)
            and str(execution.get("status") or "").upper() != "FILLED"
        )

    @staticmethod
    def _failed_gap_replay_exit(
        evaluation: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> bool:
        return (
            evaluation.get("gap_replay") is True
            and str(evaluation.get("signal") or "").upper() == "SELL"
            and str(execution.get("status") or "").upper() != "FILLED"
        )

    def _handle_shadow_evaluation(self, evaluation: Dict[str, Any], context: Mapping[str, Any], timestamp: str) -> None:
        signal = str(evaluation.get("signal") or "WAIT").upper()
        if signal != "BUY":
            return
            
        import hashlib
        strategy_id = self.metadata.strategy_id
        strategy_version = self.metadata.version
        
        # Get session date and bar timestamp
        bar = context.get("bar") or {}
        signal_timestamp = bar.get("timestamp") or context.get("timestamp") or timestamp
        try:
            dt = datetime.fromisoformat(signal_timestamp.replace("Z", "+00:00"))
            session_date = dt.date().isoformat()
        except Exception:
            session_date = datetime.now(timezone.utc).date().isoformat()
            
        # Get target contract security_id
        contract_info = evaluation.get("option_contract") or {}
        security_id = str(contract_info.get("security_id") or "")
        
        if not security_id:
            security_id = str(self._security_id(context) or "")
            
        signal_id = hashlib.sha256(f"{strategy_id}_{session_date}_{signal_timestamp}_{security_id}".encode()).hexdigest()
        
        # Save signal_id in strategy_state for later outcome correlation
        try:
            state = self.workspace.read("strategy_state")
            state["active_trade_signal_id"] = signal_id
            self.workspace.write("strategy_state", state)
        except Exception as error:
            self.workspace.logs.append(
                "ARGUS_SHADOW_EVALUATION_ERROR",
                {
                    "strategy_id": self.metadata.strategy_id,
                    "signal_id": locals().get("active_signal_id"),
                    "error_type": type(error).__name__,
                    "message": str(error)[:240],
                    "execution_influence": "ZERO",
                },
                recorded_at=timestamp,
            )
            
        # Evaluate ARGUS
        argus = context.get("argus")
        shadow_status = "LIVE"
        
        if not argus or not isinstance(argus, Mapping):
            shadow_status = "ARGUS_UNAVAILABLE"
        else:
            # Check freshness
            from src.argus.tactical_edge import ArgusTacticalEdgeEngine
            if not ArgusTacticalEdgeEngine._is_fresh(argus):
                shadow_status = "ARGUS_STALE"
                
        pressure = None
        breadth = None
        persistence = None
        iv_state = None
        gamma_lifecycle = None
        continuation_reversal = None
        confidence = None
        suggested_action = shadow_status
        suggested_contract = None
        reason_codes = ["ARGUS_OFFLINE"] if shadow_status != "LIVE" else []
        hypothetical_allow_block_delay = "BLOCK"
        argus_snapshot_timestamp = None
        
        if shadow_status == "LIVE":
            tactical_edge = argus.get("data", {}).get("tactical_edge") or {}
            decision = tactical_edge.get("decision") or {}
            
            argus_snapshot_timestamp = tactical_edge.get("source_timestamp")
            pressure = tactical_edge.get("pressure")
            breadth = tactical_edge.get("breadth")
            persistence = tactical_edge.get("persistence")
            iv_state = tactical_edge.get("iv_intelligence")
            gamma_lifecycle = tactical_edge.get("gamma")
            continuation_reversal = tactical_edge.get("continuation_reversal")
            
            confidence = decision.get("readiness_score")
            suggested_action = decision.get("current_action")
            suggested_contract = tactical_edge.get("contract_selection")
            reason_codes = [tactical_edge.get("why", "")] if tactical_edge.get("why") else []
            
            gate = decision.get("gate")
            action_enabled = decision.get("action_enabled")
            if action_enabled:
                hypothetical_allow_block_delay = "ALLOW"
            elif gate == "ADVISORY_WAIT":
                entry_lifecycle = tactical_edge.get("entry_lifecycle") or {}
                if entry_lifecycle.get("hard_invalidation") or entry_lifecycle.get("evidence_cancelled"):
                    hypothetical_allow_block_delay = "BLOCK"
                else:
                    hypothetical_allow_block_delay = "DELAY"
            else:
                hypothetical_allow_block_delay = "BLOCK"
                
        shadow_record = {
            "signal_id": signal_id,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "native_timestamp": signal_timestamp,
            "direction": "BUY",
            "contract": contract_info,
            "entry": evaluation.get("entry") or evaluation.get("theoretical_entry_price"),
            "sl": evaluation.get("sl") or evaluation.get("active_leg_stop"),
            "argus_snapshot_timestamp": argus_snapshot_timestamp,
            "pressure": pressure,
            "breadth": breadth,
            "persistence": persistence,
            "iv_state": iv_state,
            "gamma_lifecycle": gamma_lifecycle,
            "continuation_reversal": continuation_reversal,
            "confidence": confidence,
            "suggested_action": suggested_action,
            "suggested_contract": suggested_contract,
            "reason_codes": reason_codes,
            "hypothetical_allow_block_delay": hypothetical_allow_block_delay,
            "native_outcome": "PENDING",
            "counterfactual_shadow_outcome": "PENDING",
            "avoided_loss": None,
            "missed_winner": None,
        }
        
        self.workspace.journal.append(
            "ARGUS_SHADOW_EVALUATION",
            shadow_record,
            recorded_at=timestamp,
            idempotency_key=f"shadow-eval:{signal_id}"
        )

    def _handle_shadow_outcome(self, timestamp: str, evaluation: Optional[Mapping[str, Any]] = None) -> None:
        if not (self.metadata.parameters.get("mode") == "SHADOW" or self.metadata.parameters.get("argus_mode") == "SHADOW"):
            return
            
        try:
            state = self.workspace.read("strategy_state")
            active_signal_id = state.get("active_trade_signal_id")
            if not active_signal_id:
                return
                
            # Check if this was a counterfactual-only trade (due to capital/margin rejection)
            counterfactual_only = False
            strategy_adapter_state = state.get("adapter_state") or {}
            if isinstance(strategy_adapter_state, str):
                try:
                    strategy_adapter_state = json.loads(strategy_adapter_state)
                except Exception:
                    strategy_adapter_state = {}
            
            strat_state = strategy_adapter_state.get("state") or {}
            if strat_state.get("counterfactual_active_signal_id") == active_signal_id:
                counterfactual_only = True

            if counterfactual_only:
                if not evaluation or evaluation.get("status") != "EXIT_CANDIDATE":
                    return
                rows = self.workspace.journal.read()
                eval_row = next((r for r in rows if r.get("event_type") == "ARGUS_SHADOW_EVALUATION" and r.get("payload", {}).get("signal_id") == active_signal_id), None)
                if not eval_row:
                    return
                    
                hypothetical = eval_row["payload"].get("hypothetical_allow_block_delay")
                net_pnl = float(evaluation.get("pnl") or 0.0)
                
                avoided_loss = 0.0
                missed_winner = 0.0
                
                if net_pnl <= 0:
                    counterfactual_shadow_outcome = "AVOIDED_LOSS"
                    avoided_loss = abs(net_pnl)
                else:
                    counterfactual_shadow_outcome = "MISSED_WINNER"
                    missed_winner = net_pnl

                        
                outcome_record = {
                    "signal_id": active_signal_id,
                    "trade_id": f"cf-{active_signal_id[:16]}",
                    "native_outcome": "WIN" if net_pnl > 0 else "LOSS",
                    "counterfactual_shadow_outcome": counterfactual_shadow_outcome,
                    "avoided_loss": avoided_loss,
                    "missed_winner": missed_winner,
                    "net_pnl": net_pnl,
                    "gross_pnl": net_pnl
                }
                
                self.workspace.journal.append(
                    "ARGUS_SHADOW_OUTCOME",
                    outcome_record,
                    recorded_at=timestamp,
                    idempotency_key=f"shadow-outcome:cf-{active_signal_id}"
                )
                
                state["active_trade_signal_id"] = None
                self.workspace.write("strategy_state", state)
                if hasattr(self.strategy.state, "counterfactual_active_signal_id"):
                    self.strategy.state.counterfactual_active_signal_id = None
                # Persist strategy state change
                serialized = self._serialize_strategy()
                try:
                    state["adapter_state"] = json.loads(serialized) if isinstance(serialized, str) else serialized
                except Exception:
                    state["adapter_state"] = serialized
                self.workspace.write("strategy_state", state)
                return

            paper_state = self.workspace.read("paper_state")
            closed_trades = paper_state.get("closed_trades") or []
            if not closed_trades:
                return
                
            last_trade = closed_trades[-1]
            trade_id = last_trade["trade_id"]
            
            # Check if we already processed this outcome using idempotency check on journal
            rows = self.workspace.journal.read()
            if any(r.get("event_type") == "ARGUS_SHADOW_OUTCOME" and r.get("idempotency_key") == f"shadow-outcome:{trade_id}" for r in rows):
                return
                
            # Find the shadow evaluation row to check hypothetical allow/block/delay
            eval_row = next((r for r in rows if r.get("event_type") == "ARGUS_SHADOW_EVALUATION" and r.get("payload", {}).get("signal_id") == active_signal_id), None)
            if not eval_row:
                return
                
            hypothetical = eval_row["payload"].get("hypothetical_allow_block_delay")
            net_pnl = float(last_trade.get("realized_pnl") or last_trade.get("pnl") or 0.0)
            
            avoided_loss = 0.0
            missed_winner = 0.0
            
            if hypothetical == "ALLOW":
                counterfactual_shadow_outcome = "EXECUTED_AS_ALLOWED"
            else:  # BLOCK or DELAY
                if net_pnl <= 0:
                    counterfactual_shadow_outcome = "AVOIDED_LOSS"
                    avoided_loss = abs(net_pnl)
                else:
                    counterfactual_shadow_outcome = "MISSED_WINNER"
                    missed_winner = net_pnl
                    
            outcome_record = {
                "signal_id": active_signal_id,
                "trade_id": trade_id,
                "native_outcome": "WIN" if net_pnl > 0 else "LOSS",
                "counterfactual_shadow_outcome": counterfactual_shadow_outcome,
                "avoided_loss": avoided_loss,
                "missed_winner": missed_winner,
                "net_pnl": net_pnl,
                "gross_pnl": float(last_trade.get("realized_gross_pnl") or last_trade.get("gross_pnl") or 0.0)
            }
            
            self.workspace.journal.append(
                "ARGUS_SHADOW_OUTCOME",
                outcome_record,
                recorded_at=timestamp,
                idempotency_key=f"shadow-outcome:{trade_id}"
            )
            
            # Clear active signal ID
            state["active_trade_signal_id"] = None
            self.workspace.write("strategy_state", state)
            if hasattr(self.strategy.state, "counterfactual_active_signal_id"):
                self.strategy.state.counterfactual_active_signal_id = None
            # Persist strategy state change
            serialized = self._serialize_strategy()
            try:
                state["adapter_state"] = json.loads(serialized) if isinstance(serialized, str) else serialized
            except Exception:
                state["adapter_state"] = serialized
            self.workspace.write("strategy_state", state)

        except Exception as error:
            self.workspace.logs.append(
                "ARGUS_SHADOW_OUTCOME_ERROR",
                {
                    "strategy_id": self.metadata.strategy_id,
                    "signal_id": locals().get("active_signal_id"),
                    "error_type": type(error).__name__,
                    "message": str(error)[:240],
                    "execution_influence": "ZERO",
                },
                recorded_at=timestamp,
            )

    def _persist_runtime_state(
        self,
        decision: Mapping[str, Any],
        candle_id: Optional[str],
        timestamp: str,
    ) -> None:
        checkpoint = self.workspace.read("evaluation_checkpoint")
        cursor = dict(checkpoint.get("cursor") or {})
        option_contract = decision.get("option_contract")
        option_security_id = option_contract.get("security_id") if isinstance(option_contract, Mapping) else None
        next_cursor = {
            **cursor,
            "deployment_id": self.metadata.strategy_id,
            "instrument_security_id": str(
                decision.get("input_security_id") or decision.get("contract") or option_security_id
                or cursor.get("instrument_security_id") or ""
            ),
            "timeframe": str(decision.get("timeframe") or cursor.get("timeframe") or ""),
            "last_evaluated_candle_id": candle_id,
            "last_evaluated_candle_timestamp": str(
                decision.get("bar_timestamp") or (decision.get("bar") or {}).get("timestamp")
                or cursor.get("last_completed_candle_timestamp") or ""
            ),
            "evaluation_timestamp": timestamp,
            "strategy_rule_version": self.metadata.version,
        }
        execution = decision.get("paper_execution") if isinstance(decision.get("paper_execution"), Mapping) else {}
        material = (
            str(decision.get("signal") or "WAIT").upper() in {"BUY", "SELL"}
            or execution.get("paper_state_mutated") is True
            or str(execution.get("status") or "NO_ACTION").upper() not in {"NO_ACTION", "SKIPPED"}
            or any(decision.get(key) is not None for key in (
                "pending_setup", "setup_state", "position_state", "stop_update",
                "target_update", "trailing_update",
            ))
        )
        if material:
            state = self.workspace.read("strategy_state")
            state.update({"current_decision": dict(decision), "last_evaluated_at": timestamp})
            serialized = self._serialize_strategy()
            try:
                state["adapter_state"] = json.loads(serialized) if isinstance(serialized, str) else serialized
            except (TypeError, ValueError, json.JSONDecodeError):
                state["adapter_state"] = serialized
            if candle_id:
                processed = dict(state.get("processed_candles") or {})
                processed[candle_id] = dict(decision)
                state["processed_candles"] = dict(list(processed.items())[-5000:])
                state["last_processed_candle_id"] = candle_id
                state["evaluation_cursor"] = next_cursor
            self.workspace.write("strategy_state", state)

        if candle_id:
            processed = dict(checkpoint.get("processed_candles") or {})
            processed[candle_id] = self._compact_evaluation_record(candle_id, decision)
            checkpoint["processed_candles"] = dict(list(processed.items())[-5000:])
        checkpoint.update({
            "deployment_id": self.metadata.strategy_id,
            "cursor": next_cursor,
            "latest_evaluation": self._compact_evaluation_record(candle_id, decision),
            "updated_at": timestamp,
        })
        self.workspace.write("evaluation_checkpoint", checkpoint)

    def _compact_evaluation_record(self, candle_id: Optional[str], decision: Mapping[str, Any]) -> Dict[str, Any]:
        execution = decision.get("paper_execution") if isinstance(decision.get("paper_execution"), Mapping) else {}
        return {
            "deployment_id": self.metadata.strategy_id,
            "candle_id": candle_id,
            "security_id": str(decision.get("input_security_id") or decision.get("contract") or ""),
            "timeframe": str(decision.get("timeframe") or ""),
            "evaluation_result_type": str(decision.get("reason") or decision.get("signal") or "WAIT"),
            "signal": str(decision.get("signal") or "WAIT"),
            "evaluated_at": decision.get("evaluated_at"),
            "bar_timestamp": decision.get("bar_timestamp"),
            "strategy_version": self.metadata.version,
            "execution_status": execution.get("status"),
            "paper_execution": execution,
        }

    def _position_guard(self, evaluation: Mapping[str, Any]) -> Optional[str]:
        signal = str(evaluation.get("signal") or "WAIT").upper()
        state = self.workspace.read("paper_engine_state")
        has_open = any(row.get("status") == "OPEN" for row in state.get("positions") or [])
        has_entry_order = any(
            row.get("position_effect") == "OPEN" and row.get("status") in {"PENDING", "PARTIAL"}
            for row in state.get("orders") or []
        )
        if signal == "BUY" and (has_open or has_entry_order):
            return "ACTIVE_POSITION_SUPPRESSED" if has_open else "ENTRY_ORDER_PENDING_SUPPRESSED"
        if signal == "SELL" and not has_open:
            return "DUPLICATE_EXIT_SUPPRESSED"
        return None

    def _resolve_option(self, evaluation: Dict[str, Any], context: Mapping[str, Any]) -> None:
        signal = str(evaluation.get("signal") or "WAIT").upper()
        if signal == "WAIT":
            return
        projection = getattr(self.execution, "projection", None)
        paper_state = (
            dict(projection())
            if callable(projection)
            else self.workspace.read("paper_engine_state")
        )
        open_positions = [
            row for row in paper_state.get("positions") or []
            if row.get("status") == "OPEN"
        ]
        open_position = open_positions[0] if len(open_positions) == 1 else None
        argus = context.get("argus") or context.get("argus_response") or {}
        if signal == "SELL" and len(open_positions) != 1:
            return
        try:
            if signal == "SELL" and open_position:
                held_contract = str(open_position["contract"])
                evaluation.update({
                    "position_id": open_position.get("position_id"),
                    "contract": held_contract,
                    "option_contract": open_position.get("option_contract"),
                    "lot_size": (open_position.get("option_contract") or {}).get("lot_size"),
                })
                context_contract = str(context.get("contract") or context.get("option_contract") or "")
                if context_contract and context_contract != held_contract:
                    evaluation.update({"exit": None, "execution_price": None, "paper_price": None})
                return
            if evaluation.get("contract") and self._number(evaluation.get("entry", evaluation.get("execution_price"))) is not None:
                validate_existing = getattr(self.option_resolver, "validate_existing", None)
                if callable(validate_existing):
                    evidence = validate_existing(
                        argus,
                        str(evaluation["contract"]),
                        evaluation.get("option_contract")
                        if isinstance(evaluation.get("option_contract"), Mapping)
                        else None,
                    )
                    evaluation["contract_selection"] = deepcopy(dict(evidence))
                return
            selection = dict(self.metadata.parameters.get("option_selection") or {})
            underlying = str(selection.get("underlying") or context.get("underlying") or context.get("symbol") or "").upper()
            normalized_direction = str(evaluation.get("direction") or "").upper()
            option_type = (
                "CE" if normalized_direction == "CALL"
                else "PE" if normalized_direction == "PUT"
                else selection.get("option_type")
            )
            resolved = self.option_resolver.resolve(
                argus,
                signal,
                underlying=underlying,
                option_type=option_type,
                strike_offset=int(selection.get("strike_offset") or 0),
                expiry=selection.get("expiry"),
            )
            price = float(resolved.ltp)
            evaluation.update({
                "contract": str(resolved.security_id), "entry": price,
                "execution_price": price, "paper_price": price,
                "lot_size": int(resolved.lot_size),
                "option_contract": resolved.to_dict(),
            })
            selection_evidence = getattr(self.option_resolver, "last_selection", None)
            if isinstance(selection_evidence, Mapping):
                evaluation["contract_selection"] = deepcopy(dict(selection_evidence))
        except (ContractResolutionError, KeyError, TypeError, ValueError) as error:
            reason = str(error)
            reason = (
                reason
                if reason.startswith("NO_ELIGIBLE_CONTRACT")
                else "CONTRACT_RESOLUTION_UNAVAILABLE"
            )
            evaluation.update({
                "signal": "WAIT", "reason": reason,
                "contract": None, "entry": None, "exit": None,
                "execution_price": None,
            })

    def _bind_open_position_risk_identity(
        self,
        evaluation: Dict[str, Any],
        context: Mapping[str, Any],
    ) -> None:
        """Bind metadata updates only to the exact held contract and position."""

        if not isinstance(evaluation.get("position_state"), Mapping):
            return
        projection = getattr(self.execution, "projection", None)
        if not callable(projection):
            return
        open_positions = [
            row for row in projection().get("positions") or []
            if str(row.get("status") or "").upper() == "OPEN"
        ]
        if len(open_positions) != 1:
            return
        position = open_positions[0]
        held_contract = str(position.get("contract") or "")
        if not held_contract:
            return

        def contract_id(value: Any) -> str:
            if isinstance(value, Mapping):
                return str(value.get("security_id") or "")
            return str(value or "")

        candidate = contract_id(
            evaluation.get("option_contract")
            or evaluation.get("contract")
            or context.get("chart_contract")
            or context.get("contract")
        )
        if candidate and candidate != held_contract:
            return
        evaluation["risk_position_id"] = position.get("position_id")
        evaluation["risk_contract"] = held_contract

    @staticmethod
    def _completed_candle(context: Mapping[str, Any]) -> bool:
        bar = context.get("bar")
        sources = [bar] if isinstance(bar, Mapping) else []
        sources.append(context)
        for source in sources:
            for key in ("confirmed", "is_closed", "candle_closed", "closed"):
                if key in source:
                    return source.get(key) is True
        return True

    @staticmethod
    def _candle_id(context: Mapping[str, Any]) -> Optional[str]:
        explicit = context.get("candle_id")
        if explicit:
            return str(explicit)
        bar = context.get("bar") if isinstance(context.get("bar"), Mapping) else {}
        timestamp = bar.get("timestamp", bar.get("time", context.get("timestamp")))
        index = bar.get("index", bar.get("bar_index"))
        if timestamp is None and index is None:
            return None
        identity = {
            "symbol": str(context.get("symbol") or context.get("underlying") or "UNKNOWN").upper(),
            "timeframe": str(context.get("timeframe") or "UNKNOWN"),
            "timestamp": str(timestamp) if timestamp is not None else None,
            "index": index,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
        return f"candle_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None

    def status(self) -> Dict[str, Any]:
        runtime = self.workspace.read_fields(
            "runtime",
            ("state", "health", "readiness", "reason", "latency_ms", "updated_at"),
        )
        scheduler = self.workspace.read_fields(
            "scheduler_state",
            (
                "state", "activation_enabled", "activation_reason", "last_tick_at",
                "tick_count", "skipped_count", "latency_ms",
            ),
        )
        scheduler = {
            **scheduler,
            "unchanged_context_coalesces": self._unchanged_context_coalesces,
            "last_scheduled_context_revision": self._last_scheduled_context_revision,
            "bounded_catchup_waits": self._catchup_waits,
            "catchup_active": self._catchup_active,
            "pending_recovery_contexts": len(self._pending_evaluation_contexts)
            + len(self._gap_replay_contexts),
        }
        thread_alive = bool(self._thread and self._thread.is_alive())
        scheduler_running = thread_alive and not self._stop.is_set()
        if scheduler_running:
            runtime = {**runtime, "state": "RUNNING"}
            scheduler = {
                **scheduler,
                "state": "RUNNING",
                "activation_enabled": True,
                "activation_reason": None,
            }
        elif self._stop.is_set() or not thread_alive:
            scheduler = {**scheduler, "state": "STOPPED"}
            if scheduler.get("activation_enabled", True):
                runtime = {**runtime, "state": "STOPPED"}
        strategy_state = self.workspace.read_fields("strategy_state", ("current_decision",))
        paper = self.workspace.read_fields(
            "paper_state",
            (
                "open_position",
                "open_positions",
                "closed_trades",
                "missions",
                "orders",
                "fills",
                "positions",
            ),
        )
        readiness_state = self.workspace.read("readiness_state")
        data_ready = readiness_state.get("DATA_READY") is True
        if not data_ready:
            runtime = {
                **runtime,
                "health": "DEGRADED",
                "readiness": "BLOCKED",
                "reason": str(readiness_state.get("not_ready_reason") or "HISTORY_LOADING"),
            }
        stats = calculate_statistics(paper.get("closed_trades") or [])
        lifecycle = self._lifecycle_projection(
            paper,
            strategy_state.get("current_decision"),
            runtime,
        )
        diagnostics = self._session_diagnostics(
            paper.get("open_position"),
            strategy_state.get("current_decision"),
        )
        return {
            "strategy_id": self.metadata.strategy_id,
            "metadata": self.metadata.to_dict(),
            "state": runtime.get("state"),
            "health": runtime.get("health"),
            "readiness": runtime.get("readiness"),
            "reason": runtime.get("reason"),
            "latency_ms": runtime.get("latency_ms"),
            "last_updated": runtime.get("updated_at"),
            "scheduler": {**scheduler, "thread_alive": thread_alive},
            "current_position": paper.get("open_position"),
            "current_positions": list(paper.get("open_positions") or []),
            "current_position_count": len(paper.get("open_positions") or []),
            "current_decision": strategy_state.get("current_decision"),
            "deployment_instance_id": self.metadata.parameters.get("deployment_instance_id"),
            "canonical_strategy_id": self.metadata.parameters.get("canonical_strategy_id"),
            "configuration_hash": self.metadata.parameters.get("configuration_hash"),
            "lifecycle": lifecycle,
            "today_trades": stats["completed_trades"],
            "statistics": stats,
            "risk": self.risk.projection(),
            "diagnostics": diagnostics,
            "data_readiness": readiness_state,
            "DATA_READY": data_ready,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "production_state_mutated": False,
            "development_state_mutated": False,
        }

    def _lifecycle_projection(
        self,
        state: Mapping[str, Any],
        decision: Any,
        runtime: Mapping[str, Any],
    ) -> Dict[str, Any]:
        missions = list(state.get("missions") or [])
        orders = list(state.get("orders") or [])
        fills = list(state.get("fills") or [])
        positions = list(state.get("positions") or [])
        closed = list(state.get("closed_trades") or [])
        mission = missions[-1] if missions else None
        order = orders[-1] if orders else None
        fill = fills[-1] if fills else None
        position = next(
            (row for row in reversed(positions) if row.get("status") == "OPEN"),
            None,
        )
        trade = closed[-1] if closed else None
        decision_map = decision if isinstance(decision, Mapping) else {}
        blockers = list(decision_map.get("blockers") or [])
        runtime_state = "WAITING_FOR_TRIGGER"
        reason = (
            decision_map.get("next_required_condition")
            or runtime.get("reason")
            or "AWAITING_COMPLETED_CANDLE"
        )
        if str(runtime.get("readiness") or "").upper() == "BLOCKED":
            runtime_state = "WAITING_FOR_DATA"
        if blockers:
            runtime_state = "BLOCKED"
            reason = blockers[0]
        if mission is not None:
            runtime_state = str(mission.get("status") or "MISSION_READY")
            reason = mission.get("exit_reason") or runtime_state
        if position is not None:
            runtime_state = "GUARDIAN_ACTIVE"
            reason = position.get("pnl_status") or "POSITION_MONITORED"
        if trade is not None and position is None and mission and mission.get("status") == "EXITED":
            runtime_state = "EXITED"
            reason = trade.get("exit_reason") or "POSITION_EXITED"
        analytics = deepcopy(dict(state.get("statistics") or {}))
        blocker_frequency: Dict[str, int] = {}
        for result in (state.get("processed_evaluations") or {}).values():
            if not isinstance(result, Mapping):
                continue
            status = str(result.get("status") or "").upper()
            reason_code = str(result.get("reason") or "").upper()
            if status in {"REJECTED", "NO_ACTION"} and reason_code not in {
                "",
                "STRATEGY_WAIT",
            }:
                blocker_frequency[reason_code] = (
                    blocker_frequency.get(reason_code, 0) + 1
                )
        analytics.update({
            "signals": len(state.get("processed_evaluations") or {}),
            "accepted_signals": len(missions),
            "rejected_signals": sum(
                row.get("status") == "REJECTED" for row in orders
            ),
            "missions": len(missions),
            "orders": len(orders),
            "fills": len(fills),
            "trades": len(closed),
            "contract_selection_rejection_rate": (
                round(
                    100.0
                    * sum(
                        "CONTRACT" in str(row.get("rejection_reason") or "")
                        for row in orders
                    )
                    / len(orders),
                    4,
                )
                if orders
                else None
            ),
            "blocker_frequency": dict(sorted(blocker_frequency.items())),
            "guardian_impact": {
                "guardian_exits": sum(
                    row.get("guardian_contribution") == "PAPER_GUARDIAN"
                    for row in closed
                ),
                "completed_trades": len(closed),
                "status": "AVAILABLE" if closed else "ZERO_SAMPLE",
            },
        })
        guardian = None
        if position is not None:
            guardian = {
                "state": "ACTIVE",
                "position_id": position.get("position_id"),
                "contract": position.get("contract"),
                "entry_price": position.get("average_price"),
                "current_quote": position.get("current_price"),
                "unrealized_pnl": position.get("pnl"),
                "mfe": position.get("mfe"),
                "mae": position.get("mae"),
                "active_stop": position.get("current_stop"),
                "active_target": position.get("target"),
                "next_action": "MONITOR",
                "action_reason": position.get("quote_stale_reason") or "RISK_LEVELS_ACTIVE",
                "evidence_timestamp": position.get("quote_timestamp"),
                "freshness": position.get("quote_status"),
            }
        return {
            "runtime_state": runtime_state,
            "runtime_reason": reason,
            "mission": deepcopy(mission),
            "order": deepcopy(order),
            "fill": deepcopy(fill),
            "position": deepcopy(position),
            "guardian": guardian,
            "latest_trade": deepcopy(trade),
            "analytics": analytics,
            "latest_authoritative_timestamp": (
                position.get("quote_timestamp")
                if position is not None
                else decision_map.get("evaluated_at")
            ),
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    def _session_diagnostics(
        self,
        position: Any,
        current_decision: Any,
    ) -> List[Dict[str, Any]]:
        if not isinstance(position, Mapping) or position.get("status") != "OPEN":
            return []
        entry = self._parse_datetime(position.get("entry_time"))
        if entry is None:
            return []
        zone = ZoneInfo("Asia/Kolkata")
        entry_date = entry.astimezone(zone).date()
        current_date = datetime.now(zone).date()
        if entry_date >= current_date:
            return []
        state = self.execution.projection()
        close_orders = [
            row for row in state.get("orders") or []
            if row.get("position_effect") == "CLOSE"
            and (
                row.get("position_id") == position.get("position_id")
                or str(row.get("contract") or "") == str(position.get("contract") or "")
            )
        ]
        last_order = close_orders[-1] if close_orders else None
        config = getattr(getattr(self.strategy, "engine", self.strategy), "config", None)
        automatic = (
            str(getattr(config, "trading_mode", "")).lower() == "intraday"
            and bool(getattr(config, "square_off_session", None))
        )
        paper_execution = (
            current_decision.get("paper_execution")
            if isinstance(current_decision, Mapping)
            else None
        )
        last_attempt = None
        if isinstance(last_order, Mapping):
            last_attempt = {
                "status": last_order.get("status"),
                "reason": last_order.get("rejection_reason") or last_order.get("exit_reason"),
                "timestamp": last_order.get("updated_at") or last_order.get("created_at"),
                "order_id": last_order.get("order_id"),
            }
        elif isinstance(paper_execution, Mapping):
            last_attempt = {
                "status": paper_execution.get("status"),
                "reason": paper_execution.get("reason"),
                "timestamp": current_decision.get("evaluated_at"),
                "order_id": paper_execution.get("order_id"),
            }
        return [{
            "status": "STALE_PREVIOUS_SESSION_POSITION",
            "strategy_id": self.metadata.strategy_id,
            "position_id": position.get("position_id"),
            "contract": position.get("contract"),
            "security_id": position.get("contract"),
            "entry_timestamp": position.get("entry_time"),
            "position_trading_date": entry_date.isoformat(),
            "current_session_trading_date": current_date.isoformat(),
            "age_session_count": (current_date - entry_date).days,
            "automatic_square_off_configured": automatic,
            "last_exit_attempt_result": last_attempt,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }]

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def detail(self) -> Dict[str, Any]:
        status = self.status()
        paper = self.workspace.read("paper_state")
        return {
            "status": "available",
            "strategy": status,
            "overview": {
                "workspace": str(self.workspace.root),
                "paper_state": paper,
                "integrity": self.workspace.integrity(),
            },
            "statistics": status["statistics"],
            "journal": self.workspace.journal.read(limit=100),
            "replay": self.workspace.replay.read(limit=100),
            "evidence": self.workspace.evidence.read(limit=100),
            "trades": list(paper.get("closed_trades") or []),
            "equity_curve": status["statistics"]["equity_curve"],
            "parameters": dict(self.metadata.parameters),
            "logs": self.workspace.logs.read(limit=100),
            "order_ledger": self.workspace.order_ledger.read(limit=100),
            "fill_ledger": self.workspace.fill_ledger.read(limit=100),
        }

    def _increment_scheduler(self, field: str, *, timestamp: Optional[str] = None, latency_ms: Optional[float] = None) -> None:
        state = self.workspace.read("scheduler_state")
        state[field] = int(state.get(field) or 0) + 1
        if field == "skipped_count":
            state["tick_count"] = int(state.get("tick_count") or 0) + 1
            timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        if timestamp:
            state["last_tick_at"] = timestamp
        if latency_ms is not None:
            state["last_latency_ms"] = latency_ms
        state["state"] = "RUNNING" if not self._stop.is_set() else "STOPPED"
        self.workspace.write("scheduler_state", state)

    def _set_runtime(self, state: str, health: str, readiness: str, *, reason: str, latency_ms: Optional[float] = None) -> None:
        self.workspace.write(
            "runtime",
            {
                "state": state,
                "health": health,
                "readiness": readiness,
                "reason": reason,
                "latency_ms": latency_ms,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _set_post_evaluation_runtime(self, latency_ms: float) -> None:
        if self._pending_evaluation_contexts:
            self._set_runtime(
                "CATCHING_UP",
                "HEALTHY",
                "BLOCKED",
                reason="CANDLE_BACKLOG",
                latency_ms=latency_ms,
            )
            return
        self._set_runtime(
            "RUNNING",
            "HEALTHY",
            "READY",
            reason="EVALUATION_COMPLETE",
            latency_ms=latency_ms,
        )

    def _set_scheduler_started_runtime(self) -> None:
        if self._pending_evaluation_contexts:
            self._set_runtime(
                "CATCHING_UP",
                "HEALTHY",
                "BLOCKED",
                reason="CANDLE_BACKLOG",
            )
            return
        data_readiness = self.workspace.read("readiness_state")
        if data_readiness.get("DATA_READY") is True:
            self._set_runtime("RUNNING", "HEALTHY", "READY", reason="SCHEDULER_RUNNING")
            return
        self._set_runtime(
            "RUNNING",
            "DEGRADED",
            "BLOCKED",
            reason=str(data_readiness.get("not_ready_reason") or "HISTORY_LOADING"),
        )


def calculate_statistics(trades: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = [dict(row) for row in trades if str(row.get("status") or "").upper() == "CLOSED" and row.get("realized_pnl") is not None]
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for row in rows:
        cumulative += float(row["realized_pnl"])
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return calculate_institutional_statistics(rows, drawdown)
