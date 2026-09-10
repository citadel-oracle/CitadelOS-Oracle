"""S06 — canonical ARGUS probable-flow adapter and premium recovery evaluator.

The evaluator only consumes canonical ARGUS flow labels.  It intentionally does
not classify OI/price quadrants a second time inside EYE.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from src.eye.personal_strategies.contracts import PersonalStrategyId, PersonalStrategySignal, StrategyLifecycleState
from src.eye.personal_strategies.indicators import compute_atr


@dataclass
class S06State:
    session_date: Optional[str] = None
    active_side: Optional[str] = None
    selected_contract: Optional[str] = None
    reexecution_count: int = 0
    daily_pnl: float = 0.0
    last_state: str = "SCANNING"


class S06Evaluator:
    """Opening premium recovery; all flow semantics come from canonical ARGUS."""

    def __init__(self, state: Optional[S06State] = None):
        self.state = state or S06State()
        self.flash_epoch = 0

    def serialize_state(self) -> dict[str, Any]:
        return asdict(self.state)

    def restore_state(self, value: Mapping[str, Any]) -> None:
        self.state = S06State(**dict(value))

    def evaluate(
        self,
        ce_contract: Optional[str] = None,
        pe_contract: Optional[str] = None,
        bars_1m_ce: Optional[Sequence[Mapping[str, float]]] = None,
        bars_1m_pe: Optional[Sequence[Mapping[str, float]]] = None,
        prev_close_ce: Optional[float] = None,
        prev_close_pe: Optional[float] = None,
        strike_buying_provider_available: bool = False,
        timestamp_str: str = "09:25:00",
        active_position: Optional[Mapping[str, Any]] = None,
        *,
        context: Optional[Mapping[str, Any]] = None,
    ) -> PersonalStrategySignal:
        """Evaluate from canonical context; legacy positional values remain read-only.

        Legacy callers without a context are fail-closed and never receive a
        fabricated entry band, contract, or flow conclusion.
        """
        if not isinstance(context, Mapping):
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_CE", None, 0, [], ["CANONICAL_ARGUS_FLOW_CONTEXT"], "WAIT_FOR_CANONICAL_ARGUS", timestamp_str, blocker="S06_CANONICAL_FLOW_UNAVAILABLE")
        timestamp = str(context.get("timestamp") or timestamp_str)
        session_date = self._session_date(timestamp)
        if self.state.session_date != session_date:
            self.state = S06State(session_date=session_date)
        time_of_day = self._time_of_day(timestamp)
        if time_of_day is None or not ("09:20" <= time_of_day <= "15:05"):
            return self._signal(StrategyLifecycleState.BLOCKED, "BUY_CE", None, 0, [], ["SESSION_09_20_TO_15_05"], "SESSION_WINDOW", timestamp, blocker="S06_OUTSIDE_SESSION")
        if context.get("fresh") is not True or context.get("completed") is not True:
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_CE", None, 0, [], ["FRESH_CANONICAL_ARGUS_AND_1M_BARS"], "WAIT_FOR_FRESH_CONTEXT", timestamp, blocker="S06_FRESHNESS_UNAVAILABLE")
        daily_pnl = context.get("daily_pnl")
        if isinstance(daily_pnl, (int, float)) and not isinstance(daily_pnl, bool):
            self.state.daily_pnl = float(daily_pnl)
        if self.state.daily_pnl <= -900 or self.state.daily_pnl >= 1600:
            return self._signal(StrategyLifecycleState.BLOCKED, "BUY_CE", self.state.selected_contract, 0, [], ["DAILY_PNL_WITHIN_LIMIT"], "SESSION_LIMIT_BLOCKED", timestamp, blocker="S06_DAILY_PNL_LIMIT")
        if self.state.reexecution_count >= 4:
            return self._signal(StrategyLifecycleState.EXHAUSTED, "BUY_CE", self.state.selected_contract, 0, [], ["MAX_4_REEXECUTIONS"], "SESSION_COMPLETE", timestamp, blocker="S06_MAX_REEXECUTIONS")
        if isinstance(active_position, Mapping) or context.get("active_position"):
            return self._signal(StrategyLifecycleState.MANAGING, "BUY_CE" if self.state.active_side != "PE" else "BUY_PE", self.state.selected_contract, 2, ["POSITION_ACTIVE"], [], "GUARDIAN_MANAGEMENT", timestamp)

        rows = context.get("flow_rows")
        candidates = context.get("contract_candidates")
        bars_by_side = context.get("bars_1m")
        prev_close = context.get("previous_close")
        session_open = context.get("session_open")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not isinstance(candidates, Mapping) or not isinstance(bars_by_side, Mapping) or not isinstance(prev_close, Mapping) or not isinstance(session_open, Mapping):
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_CE", None, 0, [], ["ARGUS_FLOW_ROWS", "CONTRACT_CANDIDATES", "OPTION_1M_BARS_SINCE_09_20", "PREVIOUS_CLOSE", "SESSION_OPEN"], "WAIT_FOR_CANONICAL_CONTEXT", timestamp, blocker="S06_CANONICAL_CONTEXT_INCOMPLETE")

        counts = {"CE": self._fresh_buying_count(rows, "CE", "CALL_BUYING"), "PE": self._fresh_buying_count(rows, "PE", "PUT_BUYING")}
        eligible = [side for side, count in counts.items() if count >= 2]
        if self.state.active_side and self.state.active_side not in eligible:
            # First valid side remains the only candidate until an explicit reset.
            return self._signal(StrategyLifecycleState.SCANNING, f"BUY_{self.state.active_side}", self.state.selected_contract, counts.get(self.state.active_side, 0), [], [f"{self.state.active_side}_2_OF_3_FRESH_BUYING"], "WAIT_FOR_RESET", timestamp)
        if not self.state.active_side:
            if len(eligible) != 1:
                reason = "S06_FLOW_CONFLICT" if len(eligible) > 1 else "S06_2_OF_3_BUYING_NOT_MET"
                return self._signal(StrategyLifecycleState.PARTIAL if any(counts.values()) else StrategyLifecycleState.SCANNING, "BUY_CE", None, max(counts.values()), [], ["EXACTLY_ONE_SIDE_WITH_2_OF_3_FRESH_BUYING"], "WAIT_FOR_CLEAN_SIDE", timestamp, blocker=reason if len(eligible) > 1 else None)
            self.state.active_side = eligible[0]

        side = self.state.active_side
        direction = f"BUY_{side}"
        contract = self._select_contract(candidates.get(side))
        if contract is None:
            return self._signal(StrategyLifecycleState.MISSING_DATA, direction, None, counts[side], [f"{side}_2_OF_3_FRESH_BUYING"], ["LIQUID_DELTA_045_OR_OTM1_CONTRACT"], "WAIT_FOR_CONTRACT", timestamp, blocker="S06_CONTRACT_UNAVAILABLE")
        bars = bars_by_side.get(side)
        if not isinstance(bars, Sequence) or isinstance(bars, (str, bytes)) or len(bars) < 15:
            return self._signal(StrategyLifecycleState.MISSING_DATA, direction, contract, counts[side], [f"{side}_2_OF_3_FRESH_BUYING"], ["15_COMPLETED_1M_PREMIUM_BARS"], "WAIT_FOR_1M_BARS", timestamp, blocker="S06_INSUFFICIENT_1M_BARS")
        previous = prev_close.get(side)
        if not isinstance(previous, (int, float)) or isinstance(previous, bool):
            return self._signal(StrategyLifecycleState.MISSING_DATA, direction, contract, counts[side], [f"{side}_2_OF_3_FRESH_BUYING"], ["PREVIOUS_SESSION_CLOSE"], "WAIT_FOR_PREVIOUS_CLOSE", timestamp, blocker="S06_PREVIOUS_CLOSE_UNAVAILABLE")
        session_open_premium = session_open.get(side)
        if not isinstance(session_open_premium, (int, float)) or isinstance(session_open_premium, bool):
            return self._signal(StrategyLifecycleState.MISSING_DATA, direction, contract, counts[side], [f"{side}_2_OF_3_FRESH_BUYING"], ["SESSION_OPEN_PREMIUM"], "WAIT_FOR_SESSION_OPEN", timestamp, blocker="S06_SESSION_OPEN_UNAVAILABLE")
        normal = self._normalise_bars(bars)
        if normal is None:
            return self._signal(StrategyLifecycleState.MISSING_DATA, direction, contract, counts[side], [], ["VALID_1M_PREMIUM_BARS"], "WAIT_FOR_VALID_BARS", timestamp, blocker="S06_PREMIUM_BAR_INVALID")
        current = normal[-1]["close"]
        anchor_low = min(row["low"] for row in normal[5:])
        recovery_pct = ((current - anchor_low) / anchor_low * 100.0) if anchor_low > 0 else 0.0
        mode_a = float(session_open_premium) <= float(previous)
        mode_b = context.get("mode_b_source_proven") is True and bool(context.get("mode_b_pullback_confirmed"))
        if not mode_a and not mode_b:
            return self._signal(StrategyLifecycleState.SCANNING, direction, contract, counts[side], [f"{side}_2_OF_3_FRESH_BUYING"], ["MODE_A_OPEN_LE_PREVIOUS_CLOSE_OR_SOURCE_PROVEN_MODE_B"], "WAIT_FOR_OPENING_MODE", timestamp)
        if recovery_pct < 8.0:
            return self._signal(StrategyLifecycleState.PARTIAL, direction, contract, counts[side], [f"{side}_2_OF_3_FRESH_BUYING"], ["PREMIUM_RECOVERY_GE_8_PCT"], "WAIT_FOR_8_PCT_RECOVERY", timestamp)
        atr_values = compute_atr([r["high"] for r in normal], [r["low"] for r in normal], [r["close"] for r in normal], 14)
        atr = atr_values[-1] if atr_values else None
        if not isinstance(atr, (int, float)):
            return self._signal(StrategyLifecycleState.MISSING_DATA, direction, contract, counts[side], [f"{side}_2_OF_3_FRESH_BUYING", "PREMIUM_RECOVERY_GE_8_PCT"], ["ATR14_1M"], "WAIT_FOR_ATR", timestamp, blocker="S06_ATR_UNAVAILABLE")
        structural_risk = current - anchor_low
        risk_points = max(float(structural_risk), float(atr))
        guardian_budget = context.get("guardian_risk_approved")
        if guardian_budget is not True:
            return self._signal(StrategyLifecycleState.DETECTED, direction, contract, 2, [f"{side}_2_OF_3_FRESH_BUYING", "PREMIUM_RECOVERY_GE_8_PCT", "STRUCTURAL_RISK_PLUS_ATR"], ["GUARDIAN_RISK_APPROVAL"], "RISK_AND_ANALYZER_VERIFICATION", timestamp, structural_sl=round(current - risk_points, 2), targets={"trail_activation_r": 0.8, "lock_increment_r": 0.3, "risk_points": round(risk_points, 2)})
        self.state.selected_contract = contract
        return self._signal(StrategyLifecycleState.DETECTED, direction, contract, 3, [f"{side}_2_OF_3_FRESH_BUYING", "PREMIUM_RECOVERY_GE_8_PCT", "STRUCTURAL_RISK_PLUS_ATR", "GUARDIAN_APPROVED"], [], "EXECUTION_INTENT_READY", timestamp, structural_sl=round(current - risk_points, 2), entry_band={"low": round(current, 2), "high": round(current, 2)}, targets={"trail_activation_r": 0.8, "lock_increment_r": 0.3, "risk_points": round(risk_points, 2)})

    @staticmethod
    def _fresh_buying_count(rows: Sequence[Any], side: str, canonical_label: str) -> int:
        return sum(1 for row in rows if isinstance(row, Mapping) and str(row.get("option_type") or row.get("side") or "").upper() == side and row.get("fresh") is True and str(row.get("probable_flow") or row.get("flow") or "").upper() == canonical_label)

    @staticmethod
    def _select_contract(value: Any) -> Optional[str]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return None
        # Canonical resolver ranks delta/lower spread/liquidity.  We only choose
        # the first eligible value it supplies; no local comparable tolerance.
        for row in value:
            if isinstance(row, Mapping) and row.get("eligible") is True:
                contract = row.get("security_id") or row.get("contract") or row.get("trading_symbol")
                if contract:
                    return str(contract)
        return None

    @staticmethod
    def _normalise_bars(values: Sequence[Any]) -> Optional[list[dict[str, float]]]:
        result: list[dict[str, float]] = []
        for row in values:
            if not isinstance(row, Mapping):
                return None
            try:
                normal = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            except (KeyError, TypeError, ValueError):
                return None
            if normal["low"] <= 0 or normal["high"] < normal["low"]:
                return None
            result.append(normal)
        return result

    def _signal(self, state: StrategyLifecycleState, direction: str, contract: Optional[str], match_count: int, satisfied: list[str], missing: list[str], next_event: str, timestamp: str, *, blocker: Optional[str] = None, entry_band: Optional[dict[str, float]] = None, structural_sl: Optional[float] = None, targets: Optional[dict[str, Any]] = None) -> PersonalStrategySignal:
        if self.state.last_state != state.value:
            self.flash_epoch += 1
            self.state.last_state = state.value
        return PersonalStrategySignal(
            signal_id=f"SIG:S06:{contract or 'NONE'}:{timestamp}", strategy_id=PersonalStrategyId.S06,
            strategy_name="OPENING PREMIUM MOMENTUM RECOVERY v1.2", short_label="OPENING MOMENTUM RECOVERY", strategy_version="1.2",
            state=state, direction=direction, match_count=match_count, match_total=3,
            satisfied_conditions=satisfied, missing_conditions=missing, next_required_event=next_event,
            contract_status="RESOLVED" if contract else "UNRESOLVED", preferred_contract=contract,
            geometry_status="CANONICAL" if structural_sl is not None else "ESTABLISHING", entry_band=entry_band,
            structural_sl=structural_sl, informational_targets=targets or {}, risk_status="BLOCKED" if blocker else "PENDING",
            blocker=blocker, execution_status="FAIL_CLOSED", event_timestamp=timestamp, source_timestamp=timestamp,
            freshness=0.0, cycle_id=f"S06:{self.state.session_date or 'SESSION'}", flash_epoch=self.flash_epoch,
            raw_reason="CANONICAL_ARGUS_PROBABLE_FLOW", execution_exit_authority=state == StrategyLifecycleState.MANAGING,
        )

    @staticmethod
    def _time_of_day(value: str) -> Optional[str]:
        try:
            return value[-8:-3] if "T" not in value else datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _session_date(value: str) -> str:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except (TypeError, ValueError):
            return "SESSION"
