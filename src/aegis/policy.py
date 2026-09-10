"""Frozen AEGIS weights, thresholds, and strategy eligibility policy."""

from __future__ import annotations

from src.scanner.watchlist import WATCHLIST

from .models import StrategyEligibility


WEIGHTS = {
    "technical": 25.0,
    "kronos_core": 25.0,
    "argus": 20.0,
    "personal_oracle": 15.0,
    "hermes": 10.0,
    "athena": 5.0,
}
THRESHOLDS = {"approve": 80.0, "approve_reduced": 65.0, "wait": 45.0}
STALE_PENALTY = 0.75
CONFLICT_PENALTIES = {"LOW": 2.0, "MEDIUM": 5.0, "HIGH": 10.0, "CRITICAL": 20.0}


def strategy_eligibility(strategy_id, symbol, timeframe, session_state, regime=None):
    normalized = str(strategy_id or "").strip().lower().replace(" ", "_")
    known = normalized in {"simple_pullback", "simple_pullback_strategy"}
    reasons = []
    if not known: reasons.append("UNKNOWN_STRATEGY")
    if symbol not in WATCHLIST: reasons.append("SYMBOL_NOT_ALLOWED")
    if timeframe != "5m": reasons.append("TIMEFRAME_NOT_ALLOWED")
    if session_state not in {"OPEN", "SPECIAL_SESSION"}: reasons.append("SESSION_NOT_ELIGIBLE")
    allowed_regimes = ("TRENDING", "SIDEWAYS", "VOLATILE", "UNKNOWN")
    if regime and str(regime).upper() not in allowed_regimes: reasons.append("REGIME_NOT_ALLOWED")
    eligible = known and not reasons
    return StrategyEligibility(
        strategy_id=normalized or "unknown", strategy_name="Simple Pullback" if known else "Unknown",
        strategy_version=None, enabled=known, eligible=eligible,
        allowed_symbols=tuple(WATCHLIST), allowed_timeframes=("5m",),
        allowed_sessions=("OPEN", "SPECIAL_SESSION"), allowed_regimes=allowed_regimes,
        required_modules=("technical", "kronos_core", "argus", "athena"),
        maximum_freshness_seconds=30.0, minimum_setup_quality=50.0,
        minimum_option_buying_quality=50.0,
        expiry_rules={"minimum_dte": None, "maximum_dte": None, "status": "UNAVAILABLE"},
        reason_codes=tuple(reasons or ["STRATEGY_ELIGIBLE"]),
    )
