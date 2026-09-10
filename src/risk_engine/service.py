"""
CITADEL — Unified Risk Engine Service (SHADOW_ONLY Mode).

Integrates with real active strategy evaluation paths without modifying
any existing strategy logic, entry, contract, or paper execution.

Unit rule:
  option premium domain — entry/stop/target in premium points
  underlying domain     — context only; never subtracted from premium

Execution influence: ZERO.
"""

from __future__ import annotations
import uuid
import time
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Mapping

from src.risk_engine.contracts import (
    RiskPlan, ExitDecision, TargetStep, SkipReason,
    UnitSafeOptionContext,
)
from src.risk_engine.inventory import DeploymentLane, get_lane, enabled_lanes, all_lanes
from src.risk_engine.stop_engine import LayeredStopEngine
from src.risk_engine.quality_gates import QualityGateEvaluator
from src.risk_engine.exit_policies import ExitPolicyRegistry


# Maximum shadow plans kept in memory per process.
_MAX_ACTIVE_PLANS = 200


def _build_option_context(
    deployment_id: str,
    evaluation: Mapping[str, Any],
    lane: DeploymentLane,
) -> UnitSafeOptionContext:
    """
    Extract unit-safe option context from a strategy evaluation dict.

    TrendCatcher / BullPulse:
      evaluation["entry"]            → option_premium_entry (premium pts)
      evaluation["sl"]               → option_premium_stop  (premium pts)
      evaluation["option_contract"]  → symbol, strike, expiry, lot_size

    PullbackMaster / BreakoutMain:
      evaluation["entry"]            → option_premium_entry (underlying pts — NOT used here)
      evaluation["option_contract"]  → symbol, strike, expiry, lot_size

    pullback-master-pine-v5:
      Underlying-domain strategy; premium UNAVAILABLE.
    """
    contract: Mapping[str, Any] = evaluation.get("option_contract") or {}

    # Underlying-domain strategy
    if lane.underlying_domain:
        return UnitSafeOptionContext(
            underlying_price=evaluation.get("entry"),
            underlying_structural_invalidation=evaluation.get("sl"),
            option_symbol=None,
            option_type=None,
            option_strike=None,
            option_expiry=None,
            option_premium_entry=None,
            option_premium_stop=None,
            option_premium_target=None,
            option_lot_size=None,
            option_source_timestamp=evaluation.get("evaluated_at"),
            translation_method="UNAVAILABLE",
            translation_confidence="UNAVAILABLE",
        )

    # Option-chart domain strategies
    entry_premium = evaluation.get("entry")
    stop_premium  = evaluation.get("sl")
    target_premium = evaluation.get("target")

    # Validate units: option premiums are always < underlying (spot ~24_000)
    # If the value looks like an underlying index level, mark as unavailable
    if entry_premium is not None and entry_premium > 5000:
        # This would be an underlying price, not a premium — safety check
        entry_premium = None

    confidence = "HIGH" if (entry_premium is not None and stop_premium is not None) else "UNAVAILABLE"

    return UnitSafeOptionContext(
        underlying_price=None,             # strategies don't expose spot in evaluation output
        underlying_structural_invalidation=None,
        option_symbol=contract.get("trading_symbol"),
        option_type=contract.get("option_type") or lane.option_side,
        option_strike=contract.get("strike"),
        option_expiry=contract.get("expiry"),
        option_premium_entry=float(entry_premium) if entry_premium is not None else None,
        option_premium_stop=float(stop_premium) if stop_premium is not None else None,
        option_premium_target=float(target_premium) if target_premium is not None else None,
        option_lot_size=evaluation.get("lot_size") or contract.get("lot_size"),
        option_source_timestamp=evaluation.get("evaluated_at") or evaluation.get("bar_timestamp"),
        translation_method="STRATEGY_NATIVE_PREMIUM",
        translation_confidence=confidence,
    )


class UnifiedRiskEngineService:
    """
    Shadow-only risk engine. Generates parallel RiskPlans without touching
    any existing strategy evaluation, paper-trading state, or order path.
    """
    _instance: Optional[UnifiedRiskEngineService] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        enabled: bool = True,
        shadow_mode: bool = True,
        max_plans: int = _MAX_ACTIVE_PLANS,
    ):
        self.enabled = enabled
        self.shadow_mode = shadow_mode
        self._max_plans = max_plans
        self.stop_engine = LayeredStopEngine()
        self.quality_evaluator = QualityGateEvaluator()
        self.exit_policy = ExitPolicyRegistry()

        # Per-deployment enable flag (keyed by deployment_id)
        self._deployment_flags: Dict[str, bool] = {
            lane.deployment_id: lane.risk_engine_enabled
            for lane in all_lanes()
        }

        # Active shadow plans: plan_id → RiskPlan (bounded, LRU via OrderedDict)
        self._shadow_plans: OrderedDict[str, RiskPlan] = OrderedDict()
        self._lock = threading.Lock()

        # Idempotency: candidate_key → plan_id  (candidate_key = strategy_id:candle_id)
        self._candidate_index: Dict[str, str] = {}

        # ── Shadow hook failure telemetry (bounded, never propagates) ─────────
        self._hook_failure_count: int = 0
        self._last_failure_at: Optional[str] = None
        self._last_failure_deployment: Optional[str] = None
        self._last_failure_type: Optional[str] = None
        self._last_failure_message: Optional[str] = None
        # Bounded warning ring: max 20 entries
        self._failure_log: list = []

    # ─────────────────────────────────────────────────────────────────────────
    # Singleton
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> UnifiedRiskEngineService:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = UnifiedRiskEngineService()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    # ─────────────────────────────────────────────────────────────────────────
    # Primary integration: called by StrategyRuntime after every BUY signal
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_shadow_from_evaluation(
        self,
        deployment_id: str,
        evaluation: Mapping[str, Any],
        *,
        candidate_key: Optional[str] = None,
        candidate_status: str = "ENTRY_CANDIDATE",
        suppression_reason: Optional[str] = None,
    ) -> RiskPlan:
        """
        Generate a shadow RiskPlan from a real strategy evaluation dict.

        Arguments:
          deployment_id  — exact deployment lane ID (e.g., "TC_NIFTY_PE_1M")
          evaluation     — the evaluation dict returned by strategy.evaluate(context)
          candidate_key  — optional idempotency key (e.g., "TC_NIFTY_PE_1M:candle_id_xyz")
                           If the same candidate was already processed, returns existing plan.

        Returns an immutable RiskPlan. Execution influence is ZERO.
        The strategy evaluation dict is never modified.
        """
        # ── Idempotency ───────────────────────────────────────────────────────
        if candidate_key:
            with self._lock:
                existing_id = self._candidate_index.get(candidate_key)
                if existing_id and existing_id in self._shadow_plans:
                    existing = self._shadow_plans[existing_id]
                    self._shadow_plans.move_to_end(existing_id)
                    return existing

        lane = get_lane(deployment_id)

        # Unknown deployment — generate skipped plan
        if lane is None:
            return self._skipped_plan(
                deployment_id=deployment_id,
                strategy_id=deployment_id,
                skip_reason=SkipReason.RISK_ENGINE_DISABLED,
                skip_details=f"Unknown deployment_id: {deployment_id}",
                evaluation=evaluation,
                candidate_status=candidate_status,
                suppression_reason=suppression_reason,
            )

        # ── Engine or deployment disabled ────────────────────────────────────
        if not self.enabled or not self._deployment_flags.get(deployment_id, False):
            return self._skipped_plan(
                deployment_id=deployment_id,
                strategy_id=lane.strategy_class,
                skip_reason=SkipReason.RISK_ENGINE_DISABLED,
                skip_details=f"Risk engine disabled for {deployment_id}",
                evaluation=evaluation,
                candidate_key=candidate_key,
                candidate_status=candidate_status,
                suppression_reason=suppression_reason,
            )

        # ── Build unit-safe option context ───────────────────────────────────
        oc = _build_option_context(deployment_id, evaluation, lane)

        # ── Underlying-domain or premium unavailable → skip ──────────────────
        if not oc.is_premium_available():
            return self._skipped_plan(
                deployment_id=deployment_id,
                strategy_id=lane.strategy_class,
                skip_reason=SkipReason.OPTION_PREMIUM_UNAVAILABLE,
                skip_details=(
                    f"{deployment_id}: option premium translation unavailable "
                    f"(confidence={oc.translation_confidence}, "
                    f"premium_entry={oc.option_premium_entry}). "
                    f"translation_method={oc.translation_method}"
                ),
                evaluation=evaluation,
                option_context=oc,
                candidate_key=candidate_key,
                candidate_status=candidate_status,
                suppression_reason=suppression_reason,
            )

        entry_premium = oc.option_premium_entry  # premium points only
        stop_premium  = oc.option_premium_stop   # premium points only or None

        # ── Compute layered stop in premium space ─────────────────────────────
        # structural_price = strategy-native stop (premium pts), not underlying
        eff_stop, skip_r, details = self.stop_engine.compute_layered_stop(
            entry_price=entry_premium,
            side="LONG",           # all option-chart strategies are long premium
            structural_price=stop_premium,   # already in premium pts
            atr=None,              # premium ATR unavailable without option OHLCV series
            spread=0.0,            # spread gate DISABLED (no live bid/ask feed)
        )

        # ── Quality gates (only gates with LOCKED or enabled thresholds) ─────
        if skip_r == SkipReason.NONE and stop_premium is not None:
            approved, gate_skip_r, gate_details = self.quality_evaluator.evaluate_entry_quality(
                entry_price=entry_premium,
                side="LONG",
                effective_stop=eff_stop,
                first_target=oc.option_premium_target,
                spread=0.0,            # DISABLED: no live bid/ask
                structural_level=stop_premium,
            )
            if not approved:
                skip_r = gate_skip_r
                details = gate_details

        # ── Build target ladder in premium space ──────────────────────────────
        target_ladder: List[TargetStep] = []
        if oc.option_premium_target and oc.option_premium_target > entry_premium:
            target_ladder.append(
                TargetStep(
                    target_price=oc.option_premium_target,
                    exit_ratio=0.5,
                    move_stop_to=entry_premium,
                    description="T1 50% partial + stop to breakeven (premium pts)",
                )
            )

        plan = self._build_plan(
            deployment_id=deployment_id,
            lane=lane,
            oc=oc,
            entry_premium=entry_premium,
            stop_premium=stop_premium,
            eff_stop=eff_stop,
            skip_r=skip_r,
            skip_details=details,
            target_ladder=target_ladder,
            evaluation=evaluation,
            candidate_status=candidate_status,
            suppression_reason=suppression_reason,
        )

        self._store_plan(plan, candidate_key)
        return plan

    # ─────────────────────────────────────────────────────────────────────────
    # Legacy surface kept for backward compatibility with existing tests/APIs
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_shadow_risk_plan(
        self,
        strategy_id: str,
        instrument: str,
        side: str,
        entry_price: float,
        structural_invalidation: Optional[float],
        atr: Optional[float] = None,
        spread: float = 0.0,
        first_target: Optional[float] = None,
        option_symbol: Optional[str] = None,
        deployment_id: Optional[str] = None,
    ) -> RiskPlan:
        """
        Legacy API for direct numeric inputs (backward compatibility + test use).
        All price inputs are interpreted as option premium points.
        """
        dep_id = deployment_id or strategy_id
        lane = get_lane(dep_id)

        if not self.enabled or (lane and not self._deployment_flags.get(dep_id, True)):
            return self._skipped_plan(
                deployment_id=dep_id,
                strategy_id=strategy_id,
                skip_reason=SkipReason.RISK_ENGINE_DISABLED,
                skip_details=f"Risk engine disabled for {dep_id}",
                evaluation={},
            )

        eff_stop, skip_r, details = self.stop_engine.compute_layered_stop(
            entry_price=entry_price,
            side=side,
            structural_price=structural_invalidation,
            atr=atr,
            spread=spread,
        )

        if skip_r == SkipReason.NONE:
            approved, gate_skip_r, gate_details = self.quality_evaluator.evaluate_entry_quality(
                entry_price=entry_price,
                side=side,
                effective_stop=eff_stop,
                first_target=first_target,
                spread=spread,
                structural_level=structural_invalidation,
            )
            if not approved:
                skip_r = gate_skip_r
                details = gate_details

        target_ladder: List[TargetStep] = []
        if first_target and first_target > 0:
            target_ladder.append(
                TargetStep(
                    target_price=first_target,
                    exit_ratio=0.5,
                    move_stop_to=entry_price,
                    description="T1 50% Partial + Move Stop to Breakeven",
                )
            )

        oc = UnitSafeOptionContext(
            underlying_price=None,
            underlying_structural_invalidation=None,
            option_symbol=option_symbol,
            option_type=lane.option_side if lane else None,
            option_strike=None,
            option_expiry=None,
            option_premium_entry=entry_price,
            option_premium_stop=structural_invalidation,
            option_premium_target=first_target,
            option_lot_size=None,
            option_source_timestamp=None,
            translation_method="STRATEGY_NATIVE_PREMIUM",
            translation_confidence="HIGH" if structural_invalidation is not None else "UNAVAILABLE",
        )

        plan = RiskPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            strategy_id=strategy_id,
            deployment_id=dep_id,
            instrument=instrument,
            option_context=oc,
            option_symbol=option_symbol,
            side=side,
            entry_price=entry_price,
            structural_invalidation=structural_invalidation,
            noise_spread_floor=5.0,   # UNVALIDATED_DEFAULT
            volatility_buffer=round(atr * 0.5, 2) if atr else 0.0,  # UNVALIDATED_DEFAULT
            effective_stop=round(eff_stop, 2),
            maximum_risk_cap=round(entry_price * 0.02, 2),  # UNVALIDATED_DEFAULT
            position_size=1,
            target_ladder=target_ladder,
            trailing_policy="TRAILING_STRUCTURE",
            time_decay_policy="DISABLED",       # DISABLED: no bar-count calibration
            lifecycle_exit_policy="DISABLED",   # DISABLED: no DTE feed
            is_skipped=(skip_r != SkipReason.NONE),
            skip_reason=skip_r,
            skip_details=details,
            provenance={"shadow_mode": True, "execution_influence": "ZERO",
                        "api": "legacy_numeric"},
        )
        self._store_plan(plan, None)
        return plan

    # ─────────────────────────────────────────────────────────────────────────
    # Offline bootstrap replay from persisted journal records
    # ─────────────────────────────────────────────────────────────────────────

    def bootstrap_from_journal(
        self,
        journal_path: str,
        deployment_id: str,
        max_records: int = 50,
    ) -> Dict[str, Any]:
        """
        Load persisted journal records and generate shadow plans.
        Returns a rich evidence summary — never fabricates plans.
        """
        import json, pathlib, os
        path = pathlib.Path(journal_path)
        if not path.exists():
            return {
                "status": "FILE_NOT_FOUND", "path": str(path),
                "records_scanned": 0, "buy_candidates": 0,
                "plans_generated": 0, "plans_skipped": 0,
                "duplicates": 0, "failures": 0,
            }

        stat = path.stat()
        evidence_meta = {
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        }

        loaded = buy_candidates = plans_generated = skipped = duplicates = failures = 0
        with open(path) as f:
            for line in f:
                if loaded >= max_records:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    failures += 1
                    loaded += 1
                    continue
                payload = record.get("payload", {})
                signal = str(payload.get("signal", "")).upper()
                entry  = payload.get("entry")
                status = str(payload.get("status", "")).upper()
                is_candidate = (
                    signal == "BUY" or
                    (entry is not None and status == "ENTRY_CANDIDATE")
                )
                if is_candidate:
                    buy_candidates += 1
                    candle_id = payload.get("candle_id") or record.get("idempotency_key", "")
                    key = f"{deployment_id}:{candle_id}" if candle_id else None
                    # Idempotency check before calling evaluate
                    if key and key in self._candidate_index:
                        duplicates += 1
                        loaded += 1
                        continue
                    try:
                        plan = self.evaluate_shadow_from_evaluation(
                            deployment_id=deployment_id,
                            evaluation=payload,
                            candidate_key=key,
                        )
                        if plan.is_skipped:
                            skipped += 1
                        else:
                            plans_generated += 1
                    except Exception as exc:
                        failures += 1
                        self.record_hook_failure(deployment_id, exc)
                loaded += 1

        return {
            "status": "COMPLETE",
            "deployment_id": deployment_id,
            "evidence": evidence_meta,
            "records_scanned": loaded,
            "buy_candidates": buy_candidates,
            "plans_generated": plans_generated,
            "plans_skipped": skipped,
            "duplicates": duplicates,
            "failures": failures,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Offline bootstrap: replay across all known deployment journals
    # ─────────────────────────────────────────────────────────────────────────

    def bootstrap_all_journals(
        self,
        strategy_lab_root: str = "/Users/ayushmudgal/Developer/CitadelOS/logs/strategy_lab/runtimes",
        max_per_deployment: int = 50,
    ) -> Dict[str, Any]:
        import pathlib, os
        root = pathlib.Path(strategy_lab_root)
        results = {}
        journals_found = 0
        for lane in enabled_lanes():
            journal = root / lane.deployment_id / "journal.jsonl"
            if journal.exists():
                journals_found += 1
                results[lane.deployment_id] = self.bootstrap_from_journal(
                    str(journal), lane.deployment_id, max_records=max_per_deployment
                )
        # Aggregate totals
        total_scanned  = sum(r["records_scanned"]  for r in results.values())
        total_buy      = sum(r["buy_candidates"]    for r in results.values())
        total_gen      = sum(r["plans_generated"]   for r in results.values())
        total_skipped  = sum(r["plans_skipped"]     for r in results.values())
        total_dup      = sum(r["duplicates"]        for r in results.values())
        total_fail     = sum(r["failures"]          for r in results.values())
        return {
            "journals_found": journals_found,
            "total_records_scanned": total_scanned,
            "total_buy_candidates": total_buy,
            "total_plans_generated": total_gen,
            "total_plans_skipped": total_skipped,
            "total_duplicates": total_dup,
            "total_failures": total_fail,
            "active_plan_count": len(self._shadow_plans),
            "per_deployment": results,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Shadow hook failure telemetry
    # ─────────────────────────────────────────────────────────────────────────

    def record_hook_failure(
        self,
        deployment_id: Optional[str],
        exc: Exception,
    ) -> None:
        """
        Record a bounded telemetry entry for a shadow hook failure.
        Never propagates the exception. Never blocks the caller.
        Maximum 20 entries retained (ring); count always increments.
        """
        import traceback
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        exc_type = type(exc).__name__
        exc_msg  = str(exc)[:200]
        entry = {
            "at": ts,
            "deployment_id": deployment_id,
            "type": exc_type,
            "message": exc_msg,
        }
        with self._lock:
            self._hook_failure_count += 1
            self._last_failure_at = ts
            self._last_failure_deployment = deployment_id
            self._last_failure_type = exc_type
            self._last_failure_message = exc_msg
            if len(self._failure_log) >= 20:
                self._failure_log.pop(0)
            self._failure_log.append(entry)
        import warnings
        warnings.warn(
            f"[RiskEngine] shadow hook failure [{exc_type}] dep={deployment_id}: {exc_msg}",
            stacklevel=3,
        )

    def get_hook_telemetry(self) -> Dict[str, Any]:
        """Read-only hook failure telemetry."""
        with self._lock:
            return {
                "risk_hook_failures": self._hook_failure_count,
                "last_failure_at": self._last_failure_at,
                "last_failure_deployment": self._last_failure_deployment,
                "last_failure_type": self._last_failure_type,
                "last_failure_message": self._last_failure_message,
                "failure_log_tail": list(self._failure_log[-5:]),
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Status & read-only projections
    # ─────────────────────────────────────────────────────────────────────────

    def get_shadow_status(self) -> Dict[str, Any]:
        with self._lock:
            plans = list(self._shadow_plans.values())
        skipped_count = sum(1 for p in plans if p.is_skipped)
        return {
            "enabled": self.enabled,
            "shadow_mode": self.shadow_mode,
            "execution_influence": "ZERO",
            "active_plans_count": len(plans),
            "skipped_plans_count": skipped_count,
            "max_plans_retention": self._max_plans,
            "deployment_flags": self._deployment_flags,
            "total_deployment_lanes": len(all_lanes()),
            "enabled_lanes": [l.deployment_id for l in enabled_lanes()],
            "hook_telemetry": self.get_hook_telemetry(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_shadow_plans(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._shadow_plans.values()]

    def set_deployment_enabled(self, deployment_id: str, enabled: bool) -> bool:
        """Per-deployment enable/disable. Returns True if deployment_id is known."""
        if deployment_id not in self._deployment_flags:
            return False
        with self._lock:
            self._deployment_flags[deployment_id] = enabled
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_plan(
        self,
        deployment_id: str,
        lane: DeploymentLane,
        oc: UnitSafeOptionContext,
        entry_premium: float,
        stop_premium: Optional[float],
        eff_stop: float,
        skip_r: SkipReason,
        skip_details: str,
        target_ladder: List[TargetStep],
        evaluation: Mapping[str, Any],
        candidate_status: str = "ENTRY_CANDIDATE",
        suppression_reason: Optional[str] = None,
    ) -> RiskPlan:
        # Extract WOULD_SKIP_IF_ENFORCED tags from stop engine details
        would_skip_tags = [
            part.strip() for part in skip_details.split("|")
            if "WOULD_SKIP_IF_ENFORCED" in part
        ]
        return RiskPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            strategy_id=lane.strategy_class,
            deployment_id=deployment_id,
            instrument=lane.underlying,
            option_context=oc,
            option_symbol=oc.option_symbol,
            side="LONG",
            entry_price=entry_premium,
            structural_invalidation=stop_premium,
            noise_spread_floor=5.0,     # UNVALIDATED_DEFAULT — shadow only
            volatility_buffer=0.0,      # UNVALIDATED_DEFAULT — no option ATR series
            effective_stop=round(eff_stop, 2),
            maximum_risk_cap=round(entry_premium * 0.02, 2),  # UNVALIDATED_DEFAULT
            position_size=int(oc.option_lot_size or 1),
            target_ladder=target_ladder,
            trailing_policy="TRAILING_STRUCTURE",
            time_decay_policy="DISABLED",
            lifecycle_exit_policy="DISABLED",
            is_skipped=(skip_r != SkipReason.NONE),
            skip_reason=skip_r,
            skip_details=skip_details,
            provenance={
                "shadow_mode": True,
                "execution_influence": "ZERO",
                "deployment_id": deployment_id,
                "bar_timestamp": evaluation.get("bar_timestamp"),
                "evaluated_at": evaluation.get("evaluated_at"),
                "candle_id": evaluation.get("candle_id"),
                # Task 4 — suppression truth
                "candidate_status": candidate_status,
                "suppression_reason": suppression_reason,
                "actionable": suppression_reason is None and skip_r == SkipReason.NONE,
                # Task 2 — UNVALIDATED telemetry
                "would_skip_if_enforced": would_skip_tags if would_skip_tags else None,
            },
        )

    def _skipped_plan(
        self,
        deployment_id: str,
        strategy_id: str,
        skip_reason: SkipReason,
        skip_details: str,
        evaluation: Mapping[str, Any],
        option_context: Optional[UnitSafeOptionContext] = None,
        candidate_key: Optional[str] = None,
        candidate_status: str = "ENTRY_CANDIDATE",
        suppression_reason: Optional[str] = None,
    ) -> RiskPlan:
        oc = option_context or UnitSafeOptionContext(
            underlying_price=None, underlying_structural_invalidation=None,
            option_symbol=None, option_type=None, option_strike=None,
            option_expiry=None, option_premium_entry=None, option_premium_stop=None,
            option_premium_target=None, option_lot_size=None, option_source_timestamp=None,
            translation_method="UNAVAILABLE", translation_confidence="UNAVAILABLE",
        )
        plan = RiskPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            instrument="NIFTY",
            option_context=oc,
            option_symbol=None,
            side="LONG",
            entry_price=0.0,
            structural_invalidation=None,
            noise_spread_floor=0.0,
            volatility_buffer=0.0,
            effective_stop=0.0,
            maximum_risk_cap=0.0,
            position_size=1,
            target_ladder=[],
            trailing_policy="DISABLED",
            time_decay_policy="DISABLED",
            lifecycle_exit_policy="DISABLED",
            is_skipped=True,
            skip_reason=skip_reason,
            skip_details=skip_details,
            provenance={
                "shadow_mode": True,
                "execution_influence": "ZERO",
                "deployment_id": deployment_id,
                "candidate_status": candidate_status,
                "suppression_reason": suppression_reason,
                "actionable": False,
            },
        )
        self._store_plan(plan, candidate_key)
        return plan

    def _store_plan(self, plan: RiskPlan, candidate_key: Optional[str]) -> None:
        """Bounded LRU storage — evicts oldest when limit reached."""
        with self._lock:
            while len(self._shadow_plans) >= self._max_plans:
                self._shadow_plans.popitem(last=False)
            self._shadow_plans[plan.plan_id] = plan
            if candidate_key:
                self._candidate_index[candidate_key] = plan.plan_id
