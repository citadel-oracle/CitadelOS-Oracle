"""Canonical presentation contract for Oracle's read-only LIVE FLOW surface."""

from __future__ import annotations

from typing import Any, Callable, Mapping


def publish_order_flow(
    projection_provider: Callable[[], Mapping[str, Any]],
    research_provider: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach presentation truth without changing P2 scores or authorizing a trade."""
    value = dict(projection_provider())
    quality = str(value.get("data_quality") or "UNUSABLE")
    direction = str(value.get("directional_state") or "DATA_LOCKED")
    locks = [str(item) for item in (value.get("action_lock_reasons") or [])]
    unavailable = value.get("status") == "UNAVAILABLE"
    blocked = unavailable or quality == "UNUSABLE" or direction == "DATA_LOCKED"
    action = "NO TRADE" if blocked else "WAIT"
    reason = (
        str(value.get("reason") or (locks[0] if locks else "ORDER_FLOW_PROJECTION_NOT_READY"))
        if blocked
        else "LEVELS_UNAVAILABLE"
    )
    family = value.get("family_values") if isinstance(value.get("family_values"), Mapping) else {}
    profile = family.get("LOCATION") if isinstance(family.get("LOCATION"), Mapping) else {}
    response = family.get("RESPONSE_QUALITY") if isinstance(family.get("RESPONSE_QUALITY"), Mapping) else {}
    option = family.get("OPTION_CONFIRMATION") if isinstance(family.get("OPTION_CONFIRMATION"), Mapping) else {}
    book = family.get("BOOK_PRESSURE") if isinstance(family.get("BOOK_PRESSURE"), Mapping) else {}
    reversal = str(value.get("reversal_state") or "UNAVAILABLE")
    reversal_risk = {
        "STABLE_DIRECTION": "LOW",
        "PRESSURE_FLIP": "RISING",
        "REVERSAL_FORMING": "HIGH",
        "REVERSAL_CONFIRMED": "CONFIRMED",
    }.get(reversal, "UNAVAILABLE")
    value["decision"] = {
        "action": action,
        "reason": reason,
        "flow_state": "UNAVAILABLE",
        "entry_quality": "UNAVAILABLE",
        "reversal_risk": reversal_risk,
        "contract": None,
        "entry_low": None,
        "entry_high": None,
        "invalidation": None,
        "target_1": None,
        "target_2": None,
        "rr_1": None,
        "rr_2": None,
        "levels_status": "UNAVAILABLE",
        "levels_reason": "NO_CANONICAL_FLOW_TRADE_PLANNER",
        "do_not_chase": False,
        "advisory_only": True,
        "execution_influence": "ZERO",
    }
    value["diagnostics"] = {
        "profile": dict(profile),
        "response": dict(response),
        "option_confirmation": dict(option),
        "book_pressure": dict(book),
        "signed_flow_coverage": value.get("signed_flow_coverage"),
        "profile_coverage": value.get("profile_coverage"),
        "validation": "SHADOW_LIVE_VALIDATION_PENDING",
        "score_is_probability": False,
    }
    value["research"] = dict(research_provider())
    value["advisory_only"] = True
    value["execution_influence"] = "ZERO"
    return value
