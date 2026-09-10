"""Pure, advisory-only ARGUS option-flow classification for OSE."""

from __future__ import annotations

import json
from datetime import datetime
from statistics import median
from time import perf_counter
from typing import Any, Mapping, Sequence


FLOW_WEIGHTS = {
    "activity": 35,
    "volume_acceleration": 15,
    "spread_quality": 15,
    "bid_ask_participation": 10,
    "iv_quality": 10,
    "surrounding_confirmation": 10,
    "freshness": 5,
}

FLOW_EDGE_THRESHOLDS = {
    "balanced_max_delta": 7,
    "slight_max_delta": 17,
    "moderate_max_delta": 29,
}


def quality_band(score: int | None) -> str:
    if score is None:
        return "NOT REPORTED"
    if score < 40:
        return "LOW QUALITY"
    if score < 60:
        return "MODERATE QUALITY"
    if score < 80:
        return "STRONG QUALITY"
    return "VERY STRONG QUALITY"


def directional_edge(call: Mapping[str, Any], put: Mapping[str, Any], *, fresh: bool) -> dict[str, Any]:
    call_score, put_score = call.get("score"), put.get("score")
    if not fresh:
        delta = int(put_score) - int(call_score) if call_score is not None and put_score is not None else None
        return {
            "state": "DATA STALE", "label": "DATA STALE",
            "side": "PUT" if delta and delta > 0 else "CALL" if delta and delta < 0 else "BALANCED",
            "delta": delta, "absolute_delta": abs(delta) if delta is not None else None,
            "band": "STALE", "summary": "Last authoritative participation snapshot retained",
            "thresholds": dict(FLOW_EDGE_THRESHOLDS),
        }
    if call_score is None or put_score is None:
        return {
            "state": "INSUFFICIENT DATA", "label": "INSUFFICIENT DATA", "side": "BALANCED",
            "delta": None, "absolute_delta": None, "band": "UNAVAILABLE",
            "summary": "Required contract or context fields unavailable",
        }
    delta = int(put_score) - int(call_score)
    absolute = abs(delta)
    side = "PUT" if delta > 0 else "CALL" if delta < 0 else "BALANCED"
    if absolute <= FLOW_EDGE_THRESHOLDS["balanced_max_delta"]:
        same_active_type = call.get("activity") == put.get("activity") and call.get("activity") in {
            "FRESH LONG BUILDUP", "SHORT COVERING", "FRESH WRITING / SHORT BUILDUP",
        }
        state = "TWO-SIDED ACTIVITY" if same_active_type else "NO CLEAN EDGE"
        band = "BALANCED"
        summary = "Two-sided participation" if same_active_type else "Balanced participation"
    elif absolute <= FLOW_EDGE_THRESHOLDS["slight_max_delta"]:
        state, band, summary = f"SLIGHT {side} EDGE", "SLIGHT", f"{side.title()} participation has a slight edge"
    else:
        dominant = put if side == "PUT" else call
        activity_name = str(dominant.get("activity") or "")
        band = "CLEAR" if absolute > FLOW_EDGE_THRESHOLDS["moderate_max_delta"] else "MODERATE"
        if activity_name == "FRESH LONG BUILDUP":
            state = f"{band} {side} BUYING"
        elif activity_name == "SHORT COVERING":
            state = f"{side} SHORT COVERING"
        elif activity_name == "FRESH WRITING / SHORT BUILDUP":
            state = f"{side} WRITING DOMINANT"
        else:
            state = f"{band} {side} EDGE"
        summary = f"{side.title()} participation leads by {absolute} points"
    return {
        "state": state, "label": state, "side": side, "delta": delta,
        "absolute_delta": absolute, "band": band, "summary": summary,
        "thresholds": dict(FLOW_EDGE_THRESHOLDS),
    }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def activity(price_change: Any, oi_change: Any) -> str | None:
    price, oi = _number(price_change), _number(oi_change)
    if price is None or oi is None or price == 0 or oi == 0:
        return None
    if price > 0 and oi > 0:
        return "FRESH LONG BUILDUP"
    if price > 0 and oi < 0:
        return "SHORT COVERING"
    if price < 0 and oi > 0:
        return "FRESH WRITING / SHORT BUILDUP"
    return "LONG UNWINDING"


def _leg(row: Mapping[str, Any], side: str) -> Mapping[str, Any] | None:
    value = row.get(side.lower())
    return value if isinstance(value, Mapping) else None


def _selected(rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any], side: str) -> Mapping[str, Any] | None:
    return next((leg for row in rows if str((leg := _leg(row, side)) and leg.get("security_id")) == str(contract.get("security_id"))), None)


def _classify_leg(leg: Mapping[str, Any]) -> str | None:
    return activity(
        leg.get("intraday_price_change", leg.get("price_change")),
        leg.get("intraday_change_oi", leg.get("change_oi")),
    )


def _side_flow(
    side: str,
    contract: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    previous: Mapping[str, Any] | None,
    fresh: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected = _selected(rows, contract, side)
    if selected is None:
        return ({"side": side, "score": None, "activity": "INSUFFICIENT DATA", "status": "INSUFFICIENT DATA", "reasons": ["Selected contract unavailable"], "components": {}}, {})
    selected_activity = _classify_leg(selected)
    strike = float(contract.get("strike") or 0)
    context = [leg for row in rows if abs(float(row.get("strike") or -999999) - strike) <= 100 if isinstance((leg := _leg(row, side)), Mapping)]
    comparable = [value for leg in context if (value := _classify_leg(leg)) is not None]
    confirmation = (sum(value == selected_activity for value in comparable) / len(comparable)) if selected_activity and comparable else None
    bid, ask = _number(selected.get("top_bid_quantity")), _number(selected.get("top_ask_quantity"))
    bid_price, ask_price, ltp = _number(selected.get("top_bid_price")), _number(selected.get("top_ask_price")), _number(selected.get("ltp"))
    spread_ratio = ((ask_price - bid_price) / ltp) if ask_price is not None and bid_price is not None and ltp and ask_price >= bid_price else None
    iv = _number(selected.get("iv"))
    context_ivs = [value for leg in context if (value := _number(leg.get("iv"))) is not None and value > 0]
    iv_median = median(context_ivs) if context_ivs else None
    iv_distortion = abs(iv - iv_median) / iv_median if iv is not None and iv_median else None
    volume = _number(selected.get("volume"))
    prior_volume = _number((previous or {}).get("volume"))
    volume_acceleration = ((volume - prior_volume) / prior_volume) if volume is not None and prior_volume and volume >= prior_volume else None
    if selected_activity is None or len(comparable) < 2 or spread_ratio is None or iv_distortion is None:
        return ({
            "side": side, "score": None, "activity": selected_activity or "INSUFFICIENT DATA", "status": "INSUFFICIENT DATA",
            "reasons": ["Required selected-contract or nearby-strike fields unavailable"], "components": {},
            "surrounding_confirmation": confirmation, "evaluated_contract": str(contract.get("security_id")),
        }, {"volume": volume, "iv": iv, "ltp": ltp})

    activity_input = {"FRESH LONG BUILDUP": 1.0, "SHORT COVERING": .86, "FRESH WRITING / SHORT BUILDUP": .72, "LONG UNWINDING": .45}[selected_activity]
    volume_input = 0.0 if volume_acceleration is None else min(1.0, max(0.0, volume_acceleration / .12))
    spread_input = 1.0 if spread_ratio <= .01 else .6 if spread_ratio <= .025 else 0.0
    imbalance = ((bid - ask) / (bid + ask)) if bid is not None and ask is not None and bid + ask > 0 else 0.0
    desired = 1 if selected_activity in {"FRESH LONG BUILDUP", "SHORT COVERING"} else -1
    participation_input = max(0.0, min(1.0, .5 + desired * imbalance / 2.0))
    iv_input = 0.0 if iv_distortion > .30 else .4 if iv_distortion > .15 else 1.0
    surrounding_input = confirmation or 0.0
    freshness_input = 1.0 if fresh else 0.0
    inputs = {
        "activity": activity_input, "volume_acceleration": volume_input, "spread_quality": spread_input,
        "bid_ask_participation": participation_input, "iv_quality": iv_input,
        "surrounding_confirmation": surrounding_input, "freshness": freshness_input,
    }
    components = {name: {"weight": FLOW_WEIGHTS[name], "input": round(value, 4), "contribution": round(value * FLOW_WEIGHTS[name], 3)} for name, value in inputs.items()}
    score = int(round(sum(item["contribution"] for item in components.values())))
    reasons = [
        f"{selected_activity} from intraday premium/OI change",
        f"Nearby strikes {round(surrounding_input * 100)}% aligned",
        f"Spread {spread_ratio * 100:.2f}%",
        "IV distortion acceptable" if iv_input == 1 else "IV distortion downgraded flow quality",
        "Volume acceleration not yet reported" if volume_acceleration is None else f"Volume acceleration {volume_acceleration * 100:+.1f}%",
    ]
    return ({
        "side": side, "score": score, "activity": selected_activity, "status": "LIVE" if fresh else "DATA STALE",
        "quality_band": quality_band(score),
        "reasons": reasons, "components": components, "surrounding_confirmation": round(surrounding_input, 4),
        "surrounding_sample_size": len(comparable), "iv_distortion": round(iv_distortion, 4),
        "spread_ratio": round(spread_ratio, 6), "bid_ask_imbalance": round(imbalance, 4),
        "volume_acceleration": None if volume_acceleration is None else round(volume_acceleration, 4),
        "evaluated_contract": str(contract.get("security_id")),
    }, {"volume": volume, "iv": iv, "ltp": ltp})


def calculate_option_flow(
    rows: Sequence[Mapping[str, Any]],
    contracts: Mapping[str, Mapping[str, Any]],
    observed_at: datetime,
    source_status: str,
    previous: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = perf_counter()
    fresh = source_status.lower() == "available"
    call, call_snapshot = _side_flow("CE", contracts.get("CE") or {}, rows, (previous or {}).get("CE"), fresh)
    put, put_snapshot = _side_flow("PE", contracts.get("PE") or {}, rows, (previous or {}).get("PE"), fresh)
    if not fresh:
        call["status"] = put["status"] = "DATA STALE"
    edge = directional_edge(call, put, fresh=fresh)
    state = edge["state"]
    edge["last_authoritative_state"] = state if fresh else None
    total = (call.get("score") or 0) + (put.get("score") or 0)
    marker = 50.0 if not total else (put.get("score") or 0) / total * 100.0
    authoritative_timestamp = observed_at.isoformat() if fresh else (previous or {}).get("observed_at")
    age_seconds = None
    if authoritative_timestamp:
        try:
            age_seconds = max(0.0, (observed_at - datetime.fromisoformat(str(authoritative_timestamp))).total_seconds())
        except (TypeError, ValueError):
            age_seconds = None
    result = {
        "state": state, "status": "LIVE" if fresh and state != "INSUFFICIENT DATA" else state,
        "call": call, "put": put, "balance_marker": round(marker, 4),
        "dominant_side": "CALL" if (call.get("score") or 0) > (put.get("score") or 0) else "PUT" if (put.get("score") or 0) > (call.get("score") or 0) else "BALANCED",
        "evaluated_at": observed_at.isoformat(), "source_timestamp": authoritative_timestamp,
        "age_seconds": None if age_seconds is None else round(age_seconds, 3),
        "edge": edge,
        "prior_snapshot_available": bool(previous and previous.get("observed_at")),
        "baseline": {
            "premium_change": "DHAN_INTRADAY_SESSION_CHANGE",
            "open_interest_change": "DHAN_INTRADAY_SESSION_CHANGE",
            "volume_acceleration": "PREVIOUS_AUTHORITATIVE_ARGUS_SNAPSHOT",
        },
        "source": "ARGUS_CACHED_OPTION_CHAIN", "context_radius_points": 100,
        "weights": dict(FLOW_WEIGHTS), "advisory_only": True,
        "executionInfluence": "ZERO", "execution_influence": 0, "strategy_influence": 0, "order_influence": 0,
    }
    result["performance"] = {
        "calculation_ms": round((perf_counter() - started) * 1000, 3),
        "serialized_bytes": len(json.dumps(result, separators=(",", ":")).encode("utf-8")),
    }
    return result, {"CE": call_snapshot, "PE": put_snapshot, "observed_at": observed_at.isoformat()}
