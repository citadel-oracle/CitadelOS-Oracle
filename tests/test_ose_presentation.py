from src.ose.presentation import (
    build_ssi,
    decision_window,
    detect_transition,
    engine_agreement,
    ssi_band,
)


def breakdown():
    weights = {
        "vob_direction": 32, "timeframe_agreement": 15, "ema_50": 15,
        "supertrend": 15, "break_retest_quality": 10, "freshness": 5,
        "zone_distance": 4, "lifecycle_quality": 4,
    }
    return {key: {"weight": value, "input": 0, "contribution": 0} for key, value in weights.items()}


def contract(*, vob="BULLISH", trend="BULLISH", premium=100, supply_distance=18, demand_distance=22):
    return {
        "contract": {"security_id": "101", "trading_symbol": "NIFTY 28 JUL 23900 CE"},
        "premium": premium, "score": 50,
        "composite": {"state": "STRONG BULLISH ALIGNMENT"},
        "vob": {"state": vob, "reasons": ["Supply break confirmed"], "evaluated_through": "2026-07-22T15:25:00+05:30"},
        "trend": {"state": trend, "reason": "Close above EMA", "evaluated_through": "2026-07-22T15:25:00+05:30"},
        "structures": {"5m": {
            "demand": {"zone_low": 70, "zone_high": 80, "distance_points": demand_distance},
            "supply": {"zone_low": 120, "zone_high": 130, "distance_points": supply_distance},
            "bullish_retest": False, "bearish_retest": False,
        }},
    }


def test_ssi_bands_and_canonical_breakdown_sum_exactly_to_score():
    assert [ssi_band(value) for value in (20, 21, 40, 60, 80)] == [
        "VERY WEAK", "WEAK", "MIXED", "STRONG", "VERY STRONG",
    ]
    projection = build_ssi(50, breakdown())
    assert sum(row["maximum"] for row in projection["breakdown"]) == 100
    assert sum(row["points"] for row in projection["breakdown"]) == projection["score"]
    assert projection["meaning"].startswith("Selected option contract structural strength")


def test_decision_window_uses_canonical_zone_distance_thresholds():
    assert decision_window(contract(supply_distance=18))["state"] == "ROOM AVAILABLE"
    assert decision_window(contract(supply_distance=8))["state"] == "NEAR OPPOSING ZONE"
    assert decision_window(contract(supply_distance=3))["state"] == "POOR REWARD SPACE"
    assert decision_window(contract(premium=125))["state"] == "INSIDE SUPPLY"


def test_engine_agreement_separates_structure_from_stale_flow():
    stale = engine_agreement(contract(), {"score": 80, "activity": "FRESH LONG BUILDUP"}, "DATA STALE")
    assert stale["state"] == "STRUCTURE LEADS"
    assert stale["qualifier"] == "FLOW UNCONFIRMED"
    assert stale["execution_influence"] == 0
    full = engine_agreement(contract(), {"score": 80, "activity": "FRESH LONG BUILDUP"}, "LIVE")
    assert full["state"] == "FULL AGREEMENT"


def test_latest_transition_is_authoritative_and_absent_without_change():
    current = contract()
    prior = {"security_id": "101", "composite_state": "TRANSITION", "score": 44}
    event = detect_transition("CE", prior, current)
    assert event == {
        "side": "CE", "security_id": "101", "trading_symbol": "NIFTY 28 JUL 23900 CE",
        "previous_state": "TRANSITION", "current_state": "STRONG BULLISH ALIGNMENT",
        "previous_score": 44, "current_score": 50, "reason": "Supply break confirmed",
        "evaluated_through": "2026-07-22T15:25:00+05:30",
    }
    assert detect_transition("CE", {"security_id": "101", "composite_state": "STRONG BULLISH ALIGNMENT", "score": 50}, current) is None
