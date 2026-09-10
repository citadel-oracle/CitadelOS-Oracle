"""Canonical, advisory-only explanatory projections for the OSE workspace."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


SSI_COMPONENTS = (
    ("vob_direction", "VOB Structure"),
    ("timeframe_agreement", "3M–5M Agreement"),
    ("ema_50", "EMA50"),
    ("supertrend", "Supertrend"),
    ("break_retest_quality", "Break / Retest"),
    ("freshness", "Freshness"),
    ("zone_distance", "Zone Distance"),
    ("lifecycle_quality", "Lifecycle"),
)

DECISION_THRESHOLDS = {"poor_reward_max_points": 5.0, "near_zone_max_points": 12.0}


def ssi_band(score: int) -> str:
    if score <= 20:
        return "VERY WEAK"
    if score <= 39:
        return "WEAK"
    if score <= 59:
        return "MIXED"
    if score <= 79:
        return "STRONG"
    return "VERY STRONG"


def build_ssi(score: int, raw_breakdown: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Expose positive 0..weight points without changing the signed SSI formula."""

    rows: list[dict[str, Any]] = []
    for key, label in SSI_COMPONENTS:
        item = raw_breakdown[key]
        maximum = float(item["weight"])
        points = round((maximum + float(item["contribution"])) / 2.0, 2)
        rows.append({"key": key, "label": label, "points": points, "maximum": int(maximum)})
    difference = round(float(score) - sum(float(row["points"]) for row in rows), 2)
    rows[-1]["points"] = round(float(rows[-1]["points"]) + difference, 2)
    return {
        "name": "STRUCTURAL STRENGTH INDEX", "abbreviation": "SSI",
        "score": int(score), "maximum": 100, "band": ssi_band(int(score)),
        "meaning": "Selected option contract structural strength; not probability, expected return, win rate, or a trade signal.",
        "breakdown": rows,
    }

def _direction(state: str) -> str:
    normalized = state.upper()
    if "BULLISH" in normalized:
        return "BULLISH"
    if "BEARISH" in normalized:
        return "BEARISH"
    return "NEUTRAL"


def decision_window(contract: Mapping[str, Any]) -> dict[str, Any]:
    vob = contract.get("vob") or {}
    five = (contract.get("structures") or {}).get("5m") or {}
    premium = contract.get("premium")
    demand, supply = five.get("demand"), five.get("supply")
    direction = _direction(str(vob.get("state") or "NEUTRAL"))

    def inside(zone: Mapping[str, Any] | None) -> bool:
        return bool(zone and premium is not None and float(zone["zone_low"]) <= float(premium) <= float(zone["zone_high"]))

    if inside(demand):
        state, explanation, role, distance = "INSIDE DEMAND", "Awaiting structural confirmation", "DEMAND", 0.0
    elif inside(supply):
        state, explanation, role, distance = "INSIDE SUPPLY", "A confirmed break is required", "SUPPLY", 0.0
    elif (direction == "BULLISH" and five.get("bullish_retest")) or (direction == "BEARISH" and five.get("bearish_retest")):
        state, explanation, role, distance = "BREAKOUT EXTENSION", "Retest risk remains elevated after the confirmed break", "SUPPLY" if direction == "BULLISH" else "DEMAND", None
    else:
        if direction == "BULLISH":
            zone, role = supply, "SUPPLY"
        elif direction == "BEARISH":
            zone, role = demand, "DEMAND"
        else:
            candidates = [(demand, "DEMAND"), (supply, "SUPPLY")]
            available = [(zone, name) for zone, name in candidates if isinstance(zone, Mapping)]
            zone, role = min(available, key=lambda value: abs(float(value[0].get("distance_points") or 0))) if available else (None, "BOTH")
        distance = abs(float(zone.get("distance_points") or 0)) if isinstance(zone, Mapping) else None
        if distance is None:
            state, explanation = "INSUFFICIENT DATA", "Opposing-zone distance not reported"
        elif distance <= DECISION_THRESHOLDS["poor_reward_max_points"]:
            state, explanation = "POOR REWARD SPACE", f"Opposing {role.lower()} is only {distance:.2f} points away"
        elif distance <= DECISION_THRESHOLDS["near_zone_max_points"]:
            state, explanation = "NEAR OPPOSING ZONE", f"{distance:.2f} points to opposing {role.lower()}"
        else:
            state, explanation = "ROOM AVAILABLE", f"{distance:.2f} points to opposing {role.lower()}"
    return {
        "state": state, "explanation": explanation, "direction": direction,
        "opposing_role": role, "distance_points": distance,
        "thresholds": dict(DECISION_THRESHOLDS), "advisory_only": True,
    }


def engine_agreement(contract: Mapping[str, Any], flow_side: Mapping[str, Any] | None, flow_status: str) -> dict[str, Any]:
    vob_state = str((contract.get("vob") or {}).get("state") or "INSUFFICIENT DATA")
    trend_state = str((contract.get("trend") or {}).get("state") or "INSUFFICIENT DATA")
    activity = str((flow_side or {}).get("activity") or "INSUFFICIENT DATA")
    vob_direction, trend_direction = _direction(vob_state), _direction(trend_state)
    flow_direction = (
        "BULLISH" if activity in {"FRESH LONG BUILDUP", "SHORT COVERING"}
        else "BEARISH" if activity in {"FRESH WRITING / SHORT BUILDUP", "LONG UNWINDING"}
        else "NEUTRAL"
    )
    flow_available = flow_status == "LIVE" and (flow_side or {}).get("score") is not None
    if "INSUFFICIENT" in vob_state or "INSUFFICIENT" in trend_state:
        result = "INSUFFICIENT DATA"
    elif not flow_available:
        result = "STRUCTURE LEADS" if vob_direction == trend_direction != "NEUTRAL" else "PARTIAL AGREEMENT"
    elif vob_direction == trend_direction == flow_direction != "NEUTRAL":
        result = "FULL AGREEMENT"
    elif vob_direction == trend_direction != "NEUTRAL":
        result = "STRUCTURE LEADS"
    elif trend_direction == flow_direction != "NEUTRAL":
        result = "TREND LEADS"
    elif len({vob_direction, trend_direction, flow_direction} - {"NEUTRAL"}) > 1:
        result = "CONFLICT"
    else:
        result = "PARTIAL AGREEMENT"
    qualifier = "FLOW UNCONFIRMED" if not flow_available else result
    return {
        "state": result, "qualifier": qualifier,
        "vob": {"state": vob_state, "direction": vob_direction},
        "trend": {"state": trend_state, "direction": trend_direction},
        "flow": {"state": activity if flow_available else flow_status, "direction": flow_direction if flow_available else "UNCONFIRMED"},
        "execution_influence": 0,
    }


def detect_transition(side: str, previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any] | None:
    if not previous:
        return None
    before = str(previous.get("composite_state") or "NOT REPORTED")
    after = str((current.get("composite") or {}).get("state") or "NOT REPORTED")
    before_score, after_score = previous.get("score"), current.get("score")
    if before == after and before_score == after_score:
        return None
    vob = current.get("vob") or {}
    trend = current.get("trend") or {}
    reasons = list(vob.get("reasons") or []) or [str(trend.get("reason") or "Reason not reported")]
    contract = current.get("contract") or {}
    return {
        "side": side, "security_id": str(contract.get("security_id") or ""),
        "trading_symbol": contract.get("trading_symbol"), "previous_state": before,
        "current_state": after, "previous_score": before_score, "current_score": after_score,
        "reason": reasons[0],
        "evaluated_through": vob.get("evaluated_through") or trend.get("evaluated_through"),
    }


def transition_snapshot(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "security_id": str((contract.get("contract") or {}).get("security_id") or ""),
        "composite_state": (contract.get("composite") or {}).get("state"),
        "score": contract.get("score"),
    }


def structural_read(contracts: Mapping[str, Mapping[str, Any]], duel: Mapping[str, Any], flow: Mapping[str, Any] | None) -> dict[str, Any]:
    dominant = "CE" if int(duel.get("delta") or 0) >= 0 else "PE"
    contract = contracts[dominant]
    agreement = contract.get("engine_agreement") or {}
    window = contract.get("decision_window") or {}
    flow_status = str((flow or {}).get("status") or "UNAVAILABLE")
    flow_line = (
        f"ARGUS flow {flow_status.lower()} — participation unconfirmed"
        if flow_status != "LIVE"
        else f"ARGUS {(flow or {}).get('edge', {}).get('label', 'flow edge not reported')}"
    )
    return {
        "headline": f"{duel.get('state', 'STRUCTURAL BALANCE')}",
        "lines": [
            f"{dominant} VOB {(contract.get('vob') or {}).get('state', 'not reported')}; Trend {(contract.get('trend') or {}).get('state', 'not reported')}",
            flow_line,
            f"{agreement.get('state', 'INSUFFICIENT DATA')} · {window.get('explanation', 'Decision window unavailable')}",
        ],
        "advisory_only": True, "execution_influence": 0,
    }
