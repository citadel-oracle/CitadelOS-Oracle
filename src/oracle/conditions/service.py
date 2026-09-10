"""Durable condition lifecycle, canonical-event evaluation and fresh revalidation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from threading import Event, RLock, Thread
from time import perf_counter
from typing import Any, Callable, Mapping

from src.strategy_lab.storage import ImmutableStream, _atomic_write

from .contracts import (
    CONDITION_POLICY_VERSION, REVALIDATION_POLICY_VERSION,
    CandleClosePredicate, ConditionCancellationPolicy, ConditionContractError,
    ConditionExpiryPolicy, ConditionPredicateAST, ConditionState,
    ConditionStateProjection, ContextPredicate, DynamicPaperPlan,
    FreshnessPredicate, OracleCondition, PremiumConfirmationPredicate,
    RetestPredicate, RevalidationRequest, RevalidationResult, SpreadPredicate,
    TriggerEvent, condition_from_dict, seal,
)


class ConditionError(RuntimeError):
    pass


class ConditionNotFound(ConditionError):
    pass


class ConditionConflict(ConditionError):
    pass


TRANSITIONS = {
    ConditionState.DRAFT: {ConditionState.CONFIRMATION_REQUIRED},
    ConditionState.CONFIRMATION_REQUIRED: {ConditionState.WATCHING, ConditionState.CANCELLED, ConditionState.EXPIRED},
    ConditionState.WATCHING: {ConditionState.TRIGGERED, ConditionState.CANCELLED, ConditionState.EXPIRED, ConditionState.FAILED_SAFE},
    ConditionState.TRIGGERED: {ConditionState.REVALIDATING, ConditionState.FAILED_SAFE},
    ConditionState.REVALIDATING: {ConditionState.RISK_APPROVED, ConditionState.REJECTED, ConditionState.FAILED_SAFE},
    ConditionState.RISK_APPROVED: {ConditionState.ORDER_SUBMITTED, ConditionState.REJECTED, ConditionState.FAILED_SAFE},
    ConditionState.ORDER_SUBMITTED: {ConditionState.PARTIALLY_FILLED, ConditionState.FILLED, ConditionState.REJECTED, ConditionState.RECONCILIATION_REQUIRED, ConditionState.FAILED_SAFE},
    ConditionState.PARTIALLY_FILLED: {ConditionState.FILLED, ConditionState.MANAGING, ConditionState.RECONCILIATION_REQUIRED, ConditionState.FAILED_SAFE},
    ConditionState.FILLED: {ConditionState.MANAGING, ConditionState.RECONCILIATION_REQUIRED, ConditionState.FAILED_SAFE},
    ConditionState.MANAGING: {ConditionState.EXITED, ConditionState.RECONCILIATION_REQUIRED, ConditionState.FAILED_SAFE},
    ConditionState.RECONCILIATION_REQUIRED: {ConditionState.MANAGING, ConditionState.EXITED, ConditionState.FAILED_SAFE},
}


def _stable(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


def _now(clock) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ConditionError("VERIFIED_TIME_UNAVAILABLE")
    return value


class OracleConditionStore:
    """Immutable definitions plus one hash-chained lifecycle stream per condition."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.definitions = self.root / "definitions"
        self.streams = self.root / "events"
        self.cursor_path = self.root / "monitor_cursor.json"
        self._lock = RLock()

    def save_definition(self, condition: OracleCondition) -> None:
        if not condition.verify_hash():
            raise ConditionError("UNSEALED_CONDITION")
        path = self.definitions / f"{condition.condition_id}.json"
        with self._lock:
            if path.exists():
                current = json.loads(path.read_text(encoding="utf-8"))
                if current != condition.to_dict():
                    raise ConditionConflict("IMMUTABLE_CONDITION_CONFLICT")
                return
            _atomic_write(path, condition.to_dict())

    def definition(self, condition_id: str) -> OracleCondition:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,160}", str(condition_id)):
            raise ConditionNotFound("CONDITION_UNAVAILABLE")
        try:
            return condition_from_dict(json.loads((self.definitions / f"{condition_id}.json").read_text(encoding="utf-8")))
        except FileNotFoundError as error:
            raise ConditionNotFound("CONDITION_UNAVAILABLE") from error
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ConditionError("CONDITION_STORE_CORRUPT") from error

    def stream(self, condition_id: str) -> ImmutableStream:
        return ImmutableStream(self.streams / f"{condition_id}.jsonl", max_bytes=100 * 1024 * 1024, max_files=1)

    def events(self, condition_id: str) -> list[dict[str, Any]]:
        self.definition(condition_id)
        if not (self.streams / f"{condition_id}.jsonl").exists():
            raise ConditionError("CONDITION_EVENT_STREAM_UNAVAILABLE")
        return self.stream(condition_id).read()

    def projection(self, condition_id: str) -> ConditionStateProjection:
        events = self.events(condition_id)
        if not events:
            raise ConditionError("CONDITION_EVENT_STREAM_EMPTY")
        transitions = [row for row in events if row.get("event_type") == "CONDITION_TRANSITION"]
        if not transitions:
            raise ConditionError("CONDITION_TRANSITION_STREAM_EMPTY")
        latest = transitions[-1]
        payload = latest["payload"]
        links: dict[str, str] = {}
        explanation = ""
        for row in events:
            event_payload = row.get("payload") or {}
            explanation = str(event_payload.get("explanation") or explanation)
            for key in ("trigger_id", "revalidation_id", "authorization_id", "risk_grant_id", "order_id", "position_id", "protection_id", "guardian_action"):
                if event_payload.get(key):
                    links[key] = str(event_payload[key])
        return seal(ConditionStateProjection(
            condition_id=condition_id, state=ConditionState(payload["to_state"]),
            version=len(transitions), latest_event_hash=latest["record_hash"],
            trigger_id=links.get("trigger_id"), revalidation_id=links.get("revalidation_id"),
            authorization_id=links.get("authorization_id") or links.get("risk_grant_id"), order_id=links.get("order_id"),
            position_id=links.get("position_id"), protection_id=links.get("protection_id"),
            guardian_action=links.get("guardian_action"), explanation=explanation,
            updated_at=str(latest["recorded_at"]),
        ))

    def cursor(self) -> dict[str, Any]:
        try:
            value = json.loads(self.cursor_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ConditionError("MONITOR_CURSOR_CORRUPT") from error

    def save_cursor(self, value: Mapping[str, Any]) -> None:
        _atomic_write(self.cursor_path, value)

    def list_watching(self) -> list[OracleCondition]:
        if not self.definitions.exists():
            return []
        values = []
        for path in sorted(self.definitions.glob("*.json")):
            condition = self.definition(path.stem)
            if self.projection(condition.condition_id).state is ConditionState.WATCHING:
                values.append(condition)
        return values


class OracleConditionService:
    def __init__(self, root: str | Path, *, clock=None,
                 source_validator: Callable[[Mapping[str, Any]], None] | None = None):
        self.store = OracleConditionStore(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.source_validator = source_validator
        self._lock = RLock()

    def propose(self, *, original_wording: str, structured: Mapping[str, Any] | None,
                actor_id: str, correlation_id: str) -> dict[str, Any]:
        if not all(str(value).strip() for value in (original_wording, actor_id, correlation_id)):
            raise ConditionError("PROPOSAL_IDENTITY_REQUIRED")
        required = {"symbol", "instrument_id", "security_id", "timeframe", "candle_level",
                    "candle_comparator", "retest_direction", "selected_option_id", "option_type",
                    "maximum_spread", "maximum_spread_percent", "expires_at", "expected_candle_close_boundary",
                    "source_decision_id", "source_decision_hash", "source_analysis_id", "source_analysis_hash"}
        missing = sorted(required - set(structured or {}))
        proposal_id = _stable("condprop", {"wording": original_wording, "actor": actor_id, "correlation": correlation_id, "structured": structured or {}})
        return {
            "proposal_id": proposal_id,
            "status": "CLARIFICATION_REQUIRED" if missing else "CONFIRMATION_REQUIRED",
            "missing_fields": missing,
            "original_user_wording": original_wording,
            "machine_readable_condition": dict(structured or {}) if not missing else None,
            "requires_exact_user_confirmation": True,
            "armed": False,
            "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
            "execution_authority": False,
        }

    def arm(self, *, original_wording: str, structured: Mapping[str, Any], actor_id: str,
            correlation_id: str, idempotency_key: str, user_confirmed: bool,
            expected_prior_version: int = 0) -> ConditionStateProjection:
        proposal = self.propose(original_wording=original_wording, structured=structured,
                                actor_id=actor_id, correlation_id=correlation_id)
        if proposal["status"] != "CONFIRMATION_REQUIRED" or not user_confirmed:
            raise ConditionError("EXACT_CONFIRMATION_REQUIRED")
        if expected_prior_version != 0:
            raise ConditionConflict("EXPECTED_PRIOR_VERSION_CONFLICT")
        if self.source_validator is not None:
            self.source_validator(structured)
        now = _now(self.clock)
        ast = self._ast(structured)
        expiry = seal(ConditionExpiryPolicy(
            expires_at=str(structured["expires_at"]),
            maximum_completed_candles=int(structured.get("maximum_completed_candles", 3)),
        ))
        cancellation = seal(ConditionCancellationPolicy())
        seed = {"proposal": proposal["proposal_id"], "idempotency": idempotency_key}
        condition_id = _stable("cond", seed)
        condition = seal(OracleCondition(
            condition_id=condition_id, correlation_id=correlation_id, actor_id=actor_id,
            user_confirmed=True, original_user_wording=original_wording, predicate_ast=ast,
            instrument_id=str(structured["instrument_id"]), security_id=str(structured["security_id"]),
            symbol=str(structured["symbol"]), timeframe=str(structured["timeframe"]),
            expected_candle_close_boundary=str(structured["expected_candle_close_boundary"]),
            selected_option_id=str(structured["selected_option_id"]),
            trigger_tolerance=float(structured.get("trigger_tolerance", 0.0)),
            expiry_policy=expiry, cancellation_policy=cancellation,
            source_decision_id=str(structured["source_decision_id"]), source_decision_hash=str(structured["source_decision_hash"]),
            source_analysis_id=str(structured["source_analysis_id"]), source_analysis_hash=str(structured["source_analysis_hash"]),
            expected_prior_version=0,
            policy_versions={"condition": CONDITION_POLICY_VERSION, "revalidation": REVALIDATION_POLICY_VERSION},
            created_at=now.isoformat(), current_state=ConditionState.WATCHING,
        ))
        with self._lock:
            self.store.save_definition(condition)
            stream = self.store.stream(condition_id)
            for index, (source, target, reason) in enumerate((
                (None, ConditionState.DRAFT, "PROPOSAL_CAPTURED"),
                (ConditionState.DRAFT, ConditionState.CONFIRMATION_REQUIRED, "EXACT_MACHINE_CONDITION_PRESENTED"),
                (ConditionState.CONFIRMATION_REQUIRED, ConditionState.WATCHING, "USER_CONFIRMED_PAPER_ONLY_CONDITION"),
            )):
                stream.append("CONDITION_TRANSITION", {
                    "condition_id": condition_id, "from_state": source.value if source else None,
                    "to_state": target.value, "reason_code": reason,
                    "actor_id": actor_id, "explanation": reason,
                }, recorded_at=now.isoformat(), idempotency_key=f"{idempotency_key}:{index}")
        return self.store.projection(condition_id)

    def transition(self, condition_id: str, target: ConditionState, *, expected_prior_version: int,
                   idempotency_key: str, actor_id: str, reason_code: str,
                   details: Mapping[str, Any] | None = None) -> ConditionStateProjection:
        with self._lock:
            projection = self.store.projection(condition_id)
            existing = next((row for row in self.store.events(condition_id) if row.get("idempotency_key") == idempotency_key), None)
            if existing:
                return self.store.projection(condition_id)
            if projection.version != expected_prior_version:
                raise ConditionConflict("EXPECTED_PRIOR_VERSION_CONFLICT")
            if target not in TRANSITIONS.get(projection.state, set()):
                raise ConditionConflict(f"INVALID_TRANSITION:{projection.state.value}->{target.value}")
            payload = {
                "condition_id": condition_id, "from_state": projection.state.value,
                "to_state": target.value, "reason_code": reason_code, "actor_id": actor_id,
                "explanation": str((details or {}).get("explanation") or reason_code),
                **dict(details or {}),
            }
            self.store.stream(condition_id).append("CONDITION_TRANSITION", payload,
                                                   recorded_at=_now(self.clock).isoformat(),
                                                   idempotency_key=idempotency_key)
            return self.store.projection(condition_id)

    def cancel(self, condition_id: str, *, expected_prior_version: int, idempotency_key: str,
               actor_id: str) -> ConditionStateProjection:
        return self.transition(condition_id, ConditionState.CANCELLED,
                               expected_prior_version=expected_prior_version,
                               idempotency_key=idempotency_key, actor_id=actor_id,
                               reason_code="USER_CANCELLED")

    @staticmethod
    def _ast(value: Mapping[str, Any]) -> ConditionPredicateAST:
        timeframe = str(value["timeframe"])
        option_id = str(value["selected_option_id"])
        level = float(value["candle_level"])
        return seal(ConditionPredicateAST(
            operator="ALL",
            candle_close=seal(CandleClosePredicate(timeframe=timeframe, comparator=str(value["candle_comparator"]), level=level)),
            retest=seal(RetestPredicate(level=level, direction=str(value["retest_direction"]), tolerance=float(value.get("retest_tolerance", 0.0)), maximum_candles=int(value.get("retest_maximum_candles", 1)))),
            premium_confirmation=seal(PremiumConfirmationPredicate(contract_id=option_id, option_type=str(value["option_type"]), minimum_price=float(value["minimum_premium"]) if value.get("minimum_premium") is not None else None)),
            spread=seal(SpreadPredicate(maximum_absolute=float(value["maximum_spread"]), maximum_percent=float(value["maximum_spread_percent"]))),
            freshness=seal(FreshnessPredicate(maximum_quote_age_seconds=float(value.get("maximum_quote_age_seconds", 10)), maximum_context_age_seconds=float(value.get("maximum_context_age_seconds", 360)))),
            context=seal(ContextPredicate(required_direction=str(value.get("required_direction") or ("BULLISH" if str(value["option_type"]) == "CE" else "BEARISH")), required_vob_state=value.get("required_vob_state"), required_ose_state=value.get("required_ose_state"), required_argus_side=value.get("required_argus_side"))),
        ))


class ConditionEvaluator:
    """Pure predicate evaluator. Inputs must already be canonical server-side events."""

    @staticmethod
    def evaluate(condition: OracleCondition, event: Mapping[str, Any], *, observed_at: datetime) -> tuple[bool, dict[str, bool]]:
        ast = condition.predicate_ast
        completed = event.get("closed") is True or event.get("is_closed") is True
        def number(value, default=float("nan")):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        close = number(event.get("close") if event.get("close") is not None else (event.get("bar") or {}).get("close"))
        low = number(event.get("low") if event.get("low") is not None else (event.get("bar") or {}).get("low"))
        high = number(event.get("high") if event.get("high") is not None else (event.get("bar") or {}).get("high"))
        comparator = ast.candle_close.comparator
        candle_ok = completed and ((close > ast.candle_close.level) if comparator == "ABOVE" else (close < ast.candle_close.level))
        tolerance = ast.retest.tolerance
        retest_ok = (low <= ast.retest.level + tolerance and close >= ast.retest.level) if ast.retest.direction == "HOLD_ABOVE" else (high >= ast.retest.level - tolerance and close <= ast.retest.level)
        quote = event.get("option_quote") or {}
        try:
            quote_time = datetime.fromisoformat(str(quote.get("timestamp") or event.get("quote_timestamp")).replace("Z", "+00:00"))
            quote_age = (observed_at - quote_time).total_seconds()
        except (TypeError, ValueError):
            quote_age = float("inf")
        bid, ask = quote.get("bid"), quote.get("ask")
        parsed_bid, parsed_ask = number(bid), number(ask)
        spread = parsed_ask - parsed_bid if math.isfinite(parsed_bid) and math.isfinite(parsed_ask) else float("inf")
        spread_pct = spread / parsed_ask * 100 if math.isfinite(parsed_ask) and parsed_ask > 0 else float("inf")
        premium_ok = str(quote.get("contract_id")) == ast.premium_confirmation.contract_id and quote.get("ose_confirmed") is True
        if ast.premium_confirmation.minimum_price is not None:
            premium_ok = premium_ok and number(ask, 0.0) >= ast.premium_confirmation.minimum_price
        context = event.get("context") or {}
        context_ok = str(context.get("direction")) == ast.context.required_direction
        if ast.context.required_vob_state:
            context_ok = context_ok and str(context.get("vob_state")) == ast.context.required_vob_state
        if ast.context.required_ose_state:
            context_ok = context_ok and str(context.get("ose_state")) == ast.context.required_ose_state
        if ast.context.required_argus_side:
            context_ok = context_ok and str(context.get("argus_side")) == ast.context.required_argus_side
        results = {
            "completed_candle": completed, "candle_close": candle_ok, "retest_hold": retest_ok,
            "acceptance_then_retest_sequence": event.get("acceptance_proven") is True,
            "premium_confirmation": premium_ok,
            "spread": spread <= ast.spread.maximum_absolute and spread_pct <= ast.spread.maximum_percent,
            "quote_freshness": 0 <= quote_age <= ast.freshness.maximum_quote_age_seconds,
            "context": context_ok,
            "symbol_identity": str(event.get("symbol", "")).upper() == condition.symbol,
            "timeframe_identity": str(event.get("timeframe")) == condition.timeframe,
        }
        boundary_value = event.get("candle_closed_at") or (event.get("bar") or {}).get("candle_closed_at") or event.get("timestamp")
        try:
            event_boundary = datetime.fromisoformat(str(boundary_value).replace("Z", "+00:00"))
            expected_boundary = datetime.fromisoformat(condition.expected_candle_close_boundary.replace("Z", "+00:00"))
            results["expected_boundary_reached"] = event_boundary >= expected_boundary
        except (TypeError, ValueError):
            results["expected_boundary_reached"] = False
        return all(results.values()), results


class Phase5RevalidationService:
    """Rebuild Phase-3 truth and reject any material drift; never authorizes."""

    def __init__(self, analysis_service: Any, *, clock=None, minimum_rr: float = 1.5):
        self.analysis_service = analysis_service
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.minimum_rr = float(minimum_rr)

    def revalidate(self, condition: OracleCondition, trigger: TriggerEvent) -> RevalidationResult:
        started = perf_counter()
        now = _now(self.clock)
        request = seal(RevalidationRequest(
            request_id=_stable("revalreq", {"condition": condition.condition_id, "trigger": trigger.trigger_id}),
            condition_id=condition.condition_id, trigger_id=trigger.trigger_id,
            source_condition_hash=condition.content_hash, requested_at=now.isoformat(),
        ))
        result = self.analysis_service.create(symbol=condition.symbol, correlation_id=condition.correlation_id)
        snapshot, decision = result.snapshot, result.decision
        estimate = result.option_capture.execution_estimate
        checks = {
            "fresh_analysis": bool(snapshot.verify_hash() and decision.verify_hash()),
            "decision_buy": decision.action == "BUY",
            "contract_identity": decision.selected_contract_id == condition.selected_option_id,
            "execution_estimate": estimate is not None and estimate.executable,
            "entry_not_extended": not result.timing.entry_extended,
            "natural_target_present": bool(result.underlying.natural_targets and estimate and estimate.target_premiums),
            "structural_invalidation_present": bool(result.underlying.invalidations and estimate and estimate.premium_hard_stop_candidate),
            "minimum_rr": bool(estimate and estimate.resulting_rr and max(estimate.resulting_rr) >= self.minimum_rr),
            "critical_sources_fresh": all(snapshot.source_states.get(name) == "FRESH" for name in ("context", "argus", "vob", "ose", "canonical_features")),
            "data_complete": snapshot.data_completeness >= self.analysis_service.policy.minimum_data_completeness,
            "condition_not_expired": now < datetime.fromisoformat(condition.expiry_policy.expires_at.replace("Z", "+00:00")),
        }
        drift = tuple(sorted(key.upper() for key, passed in checks.items() if not passed))
        plan = None
        if not drift and estimate is not None:
            selected = next(row for row in snapshot.candidate_contracts if row.contract_id == condition.selected_option_id)
            entry_band = estimate.entry_band or (float(estimate.expected_entry), float(estimate.expected_entry))
            plan = seal(DynamicPaperPlan(
                contract_id=selected.contract_id, option_type=selected.option_type,
                entry_band=tuple(float(v) for v in entry_band), expected_entry=float(estimate.expected_entry),
                structural_invalidation_id=result.underlying.invalidations[0].invalidation_id,
                premium_hard_stop=float(estimate.premium_hard_stop_candidate),
                stop_mapping_status=estimate.stop_mapping_status,
                natural_target_ids=tuple(item.target_id for item in result.underlying.natural_targets),
                natural_target_premiums=tuple(float(v) for v in estimate.target_premiums),
                resulting_rr=tuple(float(v) for v in estimate.resulting_rr),
                estimated_round_trip_cost=float(estimate.estimated_round_trip_cost or 0),
                maximum_slippage=float(estimate.estimated_one_way_slippage or 0),
            ))
        return seal(RevalidationResult(
            revalidation_id=_stable("reval", {"request": request.content_hash, "decision": decision.content_hash}),
            request_id=request.request_id, condition_id=condition.condition_id, trigger_id=trigger.trigger_id,
            fresh_analysis_id=snapshot.analysis_id, fresh_analysis_hash=snapshot.content_hash,
            fresh_decision_id=str(decision.decision_id), fresh_decision_hash=decision.content_hash,
            passed=not drift, material_drift=drift, checks=checks, dynamic_plan=plan,
            completed_at=_now(self.clock).isoformat(),
        ))


class ConditionMonitor:
    """Restart-safe backend monitor. Polling reads canonical cache only."""

    def __init__(self, conditions: OracleConditionService, *, context_provider: Callable[[], Mapping[str, Any] | None],
                 on_trigger: Callable[[OracleCondition, TriggerEvent], None], clock=None, poll_seconds: float = 1.0):
        self.conditions = conditions
        self.context_provider = context_provider
        self.on_trigger = on_trigger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = max(0.1, float(poll_seconds))
        self._stop = Event()
        self._thread: Thread | None = None
        self._health = {"status": "STOPPED", "last_cycle_at": None, "lag_seconds": None, "last_error": None, "browser_independent": True}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="oracle-condition-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._health["status"] = "STOPPED"

    def health(self) -> dict[str, Any]:
        return {**self._health, "worker_alive": bool(self._thread and self._thread.is_alive()),
                "llm_required": False, "frontend_required": False, "paper_only": True}

    def cycle(self) -> int:
        cursor = self.conditions.store.cursor()
        condition_cursors = dict(cursor.get("conditions") or {})
        candle_counts = dict(cursor.get("candle_counts") or {})
        triggered = 0
        now = _now(self.clock)
        for condition in self.conditions.store.list_watching():
            try:
                context = self.context_provider(condition)  # type: ignore[call-arg]
            except TypeError:
                context = self.context_provider()
            if not isinstance(context, Mapping):
                continue
            event_id = str(context.get("candle_id") or context.get("snapshot_id") or "")
            if not event_id or condition_cursors.get(condition.condition_id) == event_id:
                continue
            projection = self.conditions.store.projection(condition.condition_id)
            candle_counts[condition.condition_id] = int(candle_counts.get(condition.condition_id, 0)) + 1
            if now >= datetime.fromisoformat(condition.expiry_policy.expires_at.replace("Z", "+00:00")):
                self.conditions.transition(condition.condition_id, ConditionState.EXPIRED,
                    expected_prior_version=projection.version, idempotency_key=f"expire:{condition.condition_id}:{event_id}",
                    actor_id="CONDITION_MONITOR", reason_code="EXPIRY_POLICY_REACHED")
                condition_cursors[condition.condition_id] = event_id
                continue
            if candle_counts[condition.condition_id] > condition.expiry_policy.maximum_completed_candles:
                self.conditions.transition(condition.condition_id, ConditionState.EXPIRED,
                    expected_prior_version=projection.version, idempotency_key=f"candle-expire:{condition.condition_id}:{event_id}",
                    actor_id="CONDITION_MONITOR", reason_code="MAXIMUM_COMPLETED_CANDLES_REACHED")
                condition_cursors[condition.condition_id] = event_id
                continue
            progress = [row for row in self.conditions.store.events(condition.condition_id)
                        if row.get("event_type") == "PREDICATE_PROGRESS"
                        and (row.get("payload") or {}).get("predicate") == "CANDLE_CLOSE_ACCEPTANCE"]
            context = dict(context)
            context["acceptance_proven"] = bool(progress)
            passed, results = ConditionEvaluator.evaluate(condition, context, observed_at=now)
            if not passed:
                if results.get("candle_close") and not results.get("acceptance_then_retest_sequence"):
                    self.conditions.store.stream(condition.condition_id).append("PREDICATE_PROGRESS", {
                        "condition_id": condition.condition_id, "predicate": "CANDLE_CLOSE_ACCEPTANCE",
                        "canonical_event_id": event_id,
                        "candle_closed_at": str(context.get("candle_closed_at") or (context.get("bar") or {}).get("candle_closed_at") or context.get("timestamp")),
                    }, idempotency_key=f"acceptance:{condition.condition_id}:{event_id}")
                condition_cursors[condition.condition_id] = event_id
                continue
            quote = context.get("option_quote") or {}
            closed_at = str(context.get("candle_closed_at") or (context.get("bar") or {}).get("candle_closed_at") or context.get("timestamp"))
            trigger = seal(TriggerEvent(
                trigger_id=_stable("trg", {"condition": condition.condition_id, "event": event_id}),
                condition_id=condition.condition_id, correlation_id=condition.correlation_id,
                canonical_event_id=event_id, candle_id=event_id, candle_timeframe=str(context.get("timeframe")),
                candle_closed_at=closed_at, candle_close=float(context.get("close") if context.get("close") is not None else (context.get("bar") or {}).get("close")),
                quote_timestamp=str(quote.get("timestamp") or context.get("quote_timestamp")), observed_at=now.isoformat(),
                predicate_results=results, source_hashes=dict(context.get("source_hashes") or {"canonical_event": _stable("hash", context)}),
                non_live_fixture=bool(context.get("non_live_fixture", False)),
            ))
            updated = self.conditions.transition(condition.condition_id, ConditionState.TRIGGERED,
                expected_prior_version=projection.version, idempotency_key=f"trigger:{trigger.trigger_id}", actor_id="CONDITION_MONITOR",
                reason_code="ALL_CANONICAL_PREDICATES_SATISFIED", details={"trigger_id": trigger.trigger_id, "trigger_hash": trigger.content_hash})
            self.conditions.store.stream(condition.condition_id).append("TRIGGER_PROOF", trigger.to_dict(), idempotency_key=f"trigger-proof:{trigger.trigger_id}")
            self.on_trigger(condition, trigger)
            triggered += 1
            condition_cursors[condition.condition_id] = event_id
        self.conditions.store.save_cursor({"conditions": condition_cursors, "candle_counts": candle_counts,
                                           "processed_at": now.isoformat()})
        self._health.update({"status": "HEALTHY", "last_cycle_at": now.isoformat(), "lag_seconds": 0.0, "last_error": None})
        return triggered

    def _run(self) -> None:
        self._health["status"] = "STARTING"
        while not self._stop.wait(self.poll_seconds):
            try:
                self.cycle()
            except Exception as error:
                self._health.update({"status": "DEGRADED", "last_error": f"{type(error).__name__}:{error}"})
