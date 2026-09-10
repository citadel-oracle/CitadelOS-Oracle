import pytest

from scripts.certify_pullback_v2_parity import _compare_case
from src.strategy_lab.strategies.pullback_master.parity import load_parity_manifest


@pytest.mark.unit
def test_frozen_trade_sample_remains_exactly_eleven_cases():
    manifest = load_parity_manifest()
    assert len(manifest["trade_cases"]) == 11
    assert {row["timeframe"] for row in manifest["trade_cases"]} == {"1m", "3m", "5m"}


@pytest.mark.unit
def test_trade_comparator_requires_all_machine_readable_event_fields():
    case = {
        "contract": "NIFTY260818P24400",
        "timeframe": "5m",
        "trade": 9,
        "entry": "2026-08-12T09:15:00+05:30",
        "entry_price": 108.2,
        "exit": "2026-08-12T09:20:00+05:30",
        "exit_price": 102.0,
        "exit_signal": "SELL",
    }
    replay = {
        "chart_range": ["2026-08-12T09:15:00+05:30", "2026-08-12T15:30:00+05:30"],
        "trades": [{
            "entry": case["entry"], "entry_price": case["entry_price"],
            "exit": case["exit"], "exit_price": case["exit_price"],
            "exit_reason": "TARGET", "initial_sl": 90.0, "target": 120.0, "trails": [],
        }],
    }
    comparison = _compare_case(case, replay)
    assert comparison["observable_event_match"] is True
    assert comparison["cause"] == "NONE"
    assert comparison["tv_initial_sl"] == "NOT_MACHINE_READABLE_FROM_SUPPLIED_TV_EVIDENCE"


@pytest.mark.unit
def test_trade_comparator_distinguishes_missing_history_from_entry_divergence():
    case = {
        "contract": "NIFTY260818C24300", "timeframe": "3m", "trade": 23,
        "entry": "2026-08-14T13:33:00+05:30", "entry_price": 118.9,
        "exit": "2026-08-14T13:39:00+05:30", "exit_price": 132.35, "exit_signal": "SELL",
    }
    comparison = _compare_case(case, {
        "chart_range": ["2026-08-14T09:15:00+05:30", "2026-08-14T12:51:00+05:30"],
        "trades": [],
    })
    assert comparison["observable_event_match"] is False
    assert comparison["cause"] == "STORED_CANDLE_RANGE_INCOMPLETE"
