"""Frozen PULLBACK V2 settings and exact numeric parity helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .strategy import PullbackMasterConfig

MANIFEST_PATH = Path(__file__).with_name("parity_manifest_20260814.json")


def load_parity_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def parity_config_hash(manifest: Mapping[str, Any] | None = None) -> str:
    payload = json.dumps(
        dict(manifest or load_parity_manifest()),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def active_config_mismatches(config: PullbackMasterConfig) -> dict[str, tuple[Any, Any]]:
    """Return TV expected vs native values for strategy-affecting inputs."""

    expected = PullbackMasterConfig.tradingview_v2_20260814()
    names = (
        "trading_mode", "pullback_mode", "entry_mode", "buy_touch_mode",
        "sell_touch_mode", "stop_trigger_mode", "target_mode", "rr_target",
        "require_target", "use_min_target_room", "min_target_room_rr",
        "require_pullback", "min_bars_after_ob", "move_away_points",
        "buy_on_close", "broker_safe", "trail_new_bull_ob",
        "use_supertrend_trail", "supertrend_factor", "supertrend_atr_length",
        "supertrend_only_bullish", "use_fvg_filter", "fvg_filter_mode",
        "use_liquidity_filter", "liquidity_lookback_bars",
        "liquidity_after_ob_only", "liquidity_same_vob_touch",
        "use_pullback_type_filter", "allow_sweeping", "allow_corrective",
        "allow_aggressive", "aggressive_body_pct", "aggressive_range_atr",
        "use_htf_confirmation", "use_ltf_confirmation", "alerts_enabled",
        "alert_details",
    )
    return {
        name: (getattr(expected, name), getattr(config, name))
        for name in names
        if getattr(expected, name) != getattr(config, name)
    }


@dataclass(frozen=True)
class VobNumericObservation:
    contract: str
    timeframe: str
    formed_at: str
    side: str
    top: float
    bottom: float
    touch_at: str | None = None


@dataclass(frozen=True)
class VobNumericComparison:
    status: str
    differences: Mapping[str, Mapping[str, Any]]
    tradingview: Mapping[str, Any] | None
    citadel: Mapping[str, Any]


def compare_vob_numeric(
    *,
    citadel: VobNumericObservation,
    tradingview: VobNumericObservation | None,
    price_tolerance: float = 0.0,
) -> VobNumericComparison:
    """Exact comparator that stays UNKNOWN until numeric TV data is supplied."""

    if tradingview is None:
        return VobNumericComparison(
            status="TV_NUMERIC_EVIDENCE_REQUIRED",
            differences={},
            tradingview=None,
            citadel=asdict(citadel),
        )
    differences: dict[str, Mapping[str, Any]] = {}
    for name in ("contract", "timeframe", "formed_at", "side", "touch_at"):
        expected, actual = getattr(tradingview, name), getattr(citadel, name)
        if expected != actual:
            differences[name] = {"tradingview": expected, "citadel": actual}
    for name in ("top", "bottom"):
        expected, actual = float(getattr(tradingview, name)), float(getattr(citadel, name))
        if abs(expected - actual) > float(price_tolerance):
            differences[name] = {"tradingview": expected, "citadel": actual}
    return VobNumericComparison(
        status="MATCH" if not differences else "MISMATCH",
        differences=differences,
        tradingview=asdict(tradingview),
        citadel=asdict(citadel),
    )
