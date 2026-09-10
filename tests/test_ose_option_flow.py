from datetime import datetime
from zoneinfo import ZoneInfo

from src.ose.option_flow import FLOW_EDGE_THRESHOLDS, activity, calculate_option_flow, directional_edge


IST = ZoneInfo("Asia/Kolkata")


def leg(security_id, price_change, oi_change, *, volume=1000, iv=12, bid=120, ask=80):
    return {
        "security_id": security_id, "ltp": 100, "intraday_price_change": price_change,
        "intraday_change_oi": oi_change, "volume": volume, "iv": iv,
        "top_bid_price": 99.8, "top_ask_price": 100.2,
        "top_bid_quantity": bid, "top_ask_quantity": ask,
    }


def rows(ce_activity=(5, 10), pe_activity=(8, 20), *, pe_iv=12):
    return [{
        "strike": strike,
        "ce": leg(f"ce-{strike}", *ce_activity, iv=11 + offset * .1),
        "pe": leg(f"pe-{strike}", *pe_activity, iv=pe_iv + offset * .1),
    } for offset, strike in enumerate((23900, 24000, 24100, 24200))]


def contracts():
    return {
        "CE": {"security_id": "ce-23900", "strike": 23900},
        "PE": {"security_id": "pe-24100", "strike": 24100},
    }


def calculate(values, *, status="available", previous=None):
    return calculate_option_flow(values, contracts(), datetime(2026, 7, 22, 12, 0, tzinfo=IST), status, previous)[0]


def test_core_activity_matrix():
    assert activity(1, 1) == "FRESH LONG BUILDUP"
    assert activity(1, -1) == "SHORT COVERING"
    assert activity(-1, 1) == "FRESH WRITING / SHORT BUILDUP"
    assert activity(-1, -1) == "LONG UNWINDING"


def test_call_put_isolation_and_surrounding_confirmation():
    result = calculate(rows(ce_activity=(-5, 10), pe_activity=(8, 20)))
    assert result["call"]["activity"] == "FRESH WRITING / SHORT BUILDUP"
    assert result["put"]["activity"] == "FRESH LONG BUILDUP"
    assert result["put"]["surrounding_confirmation"] == 1
    assert result["state"] == "SLIGHT PUT EDGE"


def test_short_covering_writing_and_long_unwinding_are_distinct():
    assert calculate(rows(pe_activity=(8, -20)))["put"]["activity"] == "SHORT COVERING"
    assert calculate(rows(pe_activity=(-8, 20)))["put"]["activity"] == "FRESH WRITING / SHORT BUILDUP"
    assert calculate(rows(pe_activity=(-8, -20)))["put"]["activity"] == "LONG UNWINDING"


def test_iv_distortion_downgrades_quality():
    values = rows()
    values[2]["pe"]["iv"] = 40
    result = calculate(values)
    assert result["put"]["components"]["iv_quality"]["contribution"] == 0
    assert "IV distortion downgraded" in " ".join(result["put"]["reasons"])


def test_stale_and_insufficient_data_are_truthful_and_zero_influence():
    stale = calculate(rows(), status="stale")
    assert stale["state"] == "DATA STALE"
    assert stale["source_timestamp"] is None
    assert stale["execution_influence"] == stale["strategy_influence"] == stale["order_influence"] == 0
    retained = calculate(rows(), status="stale", previous={"observed_at": "2026-07-22T11:59:00+05:30"})
    assert retained["source_timestamp"] == "2026-07-22T11:59:00+05:30"
    missing = calculate(rows()[:1])
    assert missing["state"] == "INSUFFICIENT DATA"


def test_flow_does_not_change_existing_ose_score_domain():
    result = calculate(rows())
    assert set(result["weights"]) == {"activity", "volume_acceleration", "spread_quality", "bid_ask_participation", "iv_quality", "surrounding_confirmation", "freshness"}
    assert sum(result["weights"].values()) == 100


def test_balanced_64_66_is_not_directional_buying():
    edge = directional_edge(
        {"score": 64, "activity": "FRESH WRITING / SHORT BUILDUP"},
        {"score": 66, "activity": "SHORT COVERING"},
        fresh=True,
    )
    assert FLOW_EDGE_THRESHOLDS == {
        "balanced_max_delta": 7, "slight_max_delta": 17, "moderate_max_delta": 29,
    }
    assert edge["state"] == "NO CLEAN EDGE"
    assert edge["band"] == "BALANCED"
    assert edge["delta"] == 2


def test_activity_type_and_directional_edge_are_separate():
    covering = directional_edge(
        {"score": 42, "activity": "LONG UNWINDING"},
        {"score": 66, "activity": "SHORT COVERING"},
        fresh=True,
    )
    assert covering["state"] == "PUT SHORT COVERING"
    assert "BUYING" not in covering["state"]


def test_flow_baselines_and_prior_snapshot_availability_are_explicit():
    result = calculate(rows(), previous={"observed_at": "2026-07-22T11:59:00+05:30", "CE": {}, "PE": {}})
    assert result["prior_snapshot_available"] is True
    assert result["baseline"] == {
        "premium_change": "DHAN_INTRADAY_SESSION_CHANGE",
        "open_interest_change": "DHAN_INTRADAY_SESSION_CHANGE",
        "volume_acceleration": "PREVIOUS_AUTHORITATIVE_ARGUS_SNAPSHOT",
    }
