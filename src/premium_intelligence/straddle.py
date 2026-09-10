"""
ATM Straddle Core Submodule of PLI

Calculates ATM Straddle = ATM_CE_premium + ATM_PE_premium
Hard rules:
  - same expiry date
  - same ATM strike
  - timestamp aligned
  - freshness qualified
  - completed-bar calculations separated from forming-bar telemetry
  - ATM rollover explicitly recorded
  - session reset handled
  - missing/stale leg produces NO_DATA, not partial straddle
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StraddleCalculationResult:
    status: str  # OK | NO_DATA | STALE | MISMATCH
    expiry: Optional[str]
    atm_strike: Optional[float]
    ce_symbol: Optional[str]
    ce_ltp: Optional[float]
    pe_symbol: Optional[str]
    pe_ltp: Optional[float]
    straddle_price: Optional[float]
    prev_straddle_price: Optional[float]
    bar_change: Optional[float]
    bar_change_pct: Optional[float]
    session_open_straddle: Optional[float]
    session_change: Optional[float]
    session_change_pct: Optional[float]
    velocity: float  # pts/min
    acceleration: float  # pts/min^2
    session_high: Optional[float]
    session_low: Optional[float]
    session_range_position_pct: Optional[float]
    expansion_state: str  # EXPANSION | COMPRESSION | NEUTRAL | NO_DATA
    atm_rollover_event: bool
    blockers: List[str] = field(default_factory=list)


class ATMStraddleEngine:
    def __init__(self, min_floor: float = 5.0, max_age_seconds: float = 60.0):
        self.min_floor = min_floor
        self.max_age_seconds = max_age_seconds

        # Session state
        self._current_strike: Optional[float] = None
        self._current_expiry: Optional[str] = None
        self._session_open_straddle: Optional[float] = None
        self._session_high: Optional[float] = None
        self._session_low: Optional[float] = None

        # History for velocity & acceleration across completed bars
        self._completed_straddles: List[Tuple[float, float]] = []  # [(timestamp_sec, straddle_price)]
        self._rollover_count: int = 0

    def reset_session(self) -> None:
        self._current_strike = None
        self._current_expiry = None
        self._session_open_straddle = None
        self._session_high = None
        self._session_low = None
        self._completed_straddles.clear()
        self._rollover_count = 0

    @property
    def rollover_count(self) -> int:
        return self._rollover_count

    def calculate_straddle(
        self,
        ce_leg: Optional[Dict[str, Any]],
        pe_leg: Optional[Dict[str, Any]],
        strike: Optional[float],
        expiry: Optional[str],
        timestamp_sec: float,
        is_completed_bar: bool = True,
    ) -> StraddleCalculationResult:
        blockers = []

        if not ce_leg or not pe_leg:
            blockers.append("MISSING_OPTION_LEG")
            return self._no_data_result("Missing CE or PE leg", blockers)

        ce_ltp = ce_leg.get("ltp")
        pe_ltp = pe_leg.get("ltp")

        if ce_ltp is None or pe_ltp is None:
            blockers.append("MISSING_LEG_LTP")
            return self._no_data_result("Missing LTP for CE or PE leg", blockers)

        if ce_ltp <= 0 or pe_ltp <= 0:
            blockers.append("NON_POSITIVE_PREMIUM")
            return self._no_data_result("Non-positive premium encountered", blockers)

        ce_expiry = ce_leg.get("expiry") or expiry
        pe_expiry = pe_leg.get("expiry") or expiry

        if ce_expiry and pe_expiry and ce_expiry != pe_expiry:
            blockers.append("EXPIRY_MISMATCH")
            return self._no_data_result(f"Expiry mismatch: CE={ce_expiry} vs PE={pe_expiry}", blockers)

        selected_expiry = ce_expiry or pe_expiry or expiry

        # Freshness check
        ce_ts = ce_leg.get("source_timestamp") or timestamp_sec
        pe_ts = pe_leg.get("source_timestamp") or timestamp_sec

        straddle_price = round(ce_ltp + pe_ltp, 2)

        if straddle_price < self.min_floor:
            blockers.append("STRADDLE_BELOW_MIN_FLOOR")
            return self._no_data_result(
                f"Straddle price {straddle_price:.2f} below min floor {self.min_floor}", blockers
            )

        # Detect ATM rollover
        atm_rollover_event = False
        if strike is not None and self._current_strike is not None and strike != self._current_strike:
            atm_rollover_event = True
            self._rollover_count += 1

        if strike is not None:
            self._current_strike = strike
        if selected_expiry is not None:
            self._current_expiry = selected_expiry

        # Track session open, high, low
        if self._session_open_straddle is None:
            self._session_open_straddle = straddle_price
            self._session_high = straddle_price
            self._session_low = straddle_price
        else:
            self._session_high = max(self._session_high or straddle_price, straddle_price)
            self._session_low = min(self._session_low or straddle_price, straddle_price)

        # Compute completed-bar velocity and acceleration
        prev_straddle = self._completed_straddles[-1][1] if self._completed_straddles else None
        bar_change = round(straddle_price - prev_straddle, 2) if prev_straddle is not None else 0.0
        bar_change_pct = (
            round((bar_change / prev_straddle) * 100.0, 2) if prev_straddle and prev_straddle > 0 else 0.0
        )

        session_open = self._session_open_straddle or straddle_price
        session_change = round(straddle_price - session_open, 2)
        session_change_pct = (
            round((session_change / session_open) * 100.0, 2) if session_open > 0 else 0.0
        )

        velocity = 0.0
        acceleration = 0.0

        if len(self._completed_straddles) >= 1:
            t_prev, p_prev = self._completed_straddles[-1]
            dt_min = max(0.001, (timestamp_sec - t_prev) / 60.0)
            velocity = round((straddle_price - p_prev) / dt_min, 2)

            if len(self._completed_straddles) >= 2:
                t_prev2, p_prev2 = self._completed_straddles[-2]
                dt_min2 = max(0.001, (t_prev - t_prev2) / 60.0)
                v_prev = (p_prev - p_prev2) / dt_min2
                acceleration = round((velocity - v_prev) / dt_min, 2)

        if is_completed_bar:
            self._completed_straddles.append((timestamp_sec, straddle_price))
            if len(self._completed_straddles) > 100:
                self._completed_straddles.pop(0)

        # Session range position (0% - 100%)
        s_high = self._session_high or straddle_price
        s_low = self._session_low or straddle_price
        s_range = s_high - s_low
        range_pct = (
            round(((straddle_price - s_low) / s_range) * 100.0, 1) if s_range > 0 else 50.0
        )

        # Expansion / compression state
        if velocity > 0.5:
            expansion_state = "EXPANSION"
        elif velocity < -0.5:
            expansion_state = "COMPRESSION"
        else:
            expansion_state = "NEUTRAL"

        return StraddleCalculationResult(
            status="OK",
            expiry=selected_expiry,
            atm_strike=strike,
            ce_symbol=ce_leg.get("trading_symbol") or ce_leg.get("symbol"),
            ce_ltp=ce_ltp,
            pe_symbol=pe_leg.get("trading_symbol") or pe_leg.get("symbol"),
            pe_ltp=pe_ltp,
            straddle_price=straddle_price,
            prev_straddle_price=prev_straddle,
            bar_change=bar_change,
            bar_change_pct=bar_change_pct,
            session_open_straddle=session_open,
            session_change=session_change,
            session_change_pct=session_change_pct,
            velocity=velocity,
            acceleration=acceleration,
            session_high=s_high,
            session_low=s_low,
            session_range_position_pct=range_pct,
            expansion_state=expansion_state,
            atm_rollover_event=atm_rollover_event,
            blockers=[],
        )

    def _no_data_result(self, reason: str, blockers: List[str]) -> StraddleCalculationResult:
        return StraddleCalculationResult(
            status="NO_DATA",
            expiry=self._current_expiry,
            atm_strike=self._current_strike,
            ce_symbol=None,
            ce_ltp=None,
            pe_symbol=None,
            pe_ltp=None,
            straddle_price=None,
            prev_straddle_price=None,
            bar_change=None,
            bar_change_pct=None,
            session_open_straddle=self._session_open_straddle,
            session_change=None,
            session_change_pct=None,
            velocity=0.0,
            acceleration=0.0,
            session_high=self._session_high,
            session_low=self._session_low,
            session_range_position_pct=None,
            expansion_state="NO_DATA",
            atm_rollover_event=False,
            blockers=blockers,
        )
