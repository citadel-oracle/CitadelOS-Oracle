from copy import deepcopy

from src.vob.horsepower import HorsepowerStateEngine


def technical(close=100.0, candle="2026-08-20T10:00:00+05:30"):
    lanes = {}
    for timeframe in ("1m", "3m", "5m"):
        lanes[timeframe] = {
            "latest_finalized_bar": {
                "timestamp": candle, "candle_closed_at": candle,
                "close": close, "high": 999.0, "low": 1.0, "finalized": True,
            },
            "session_finalized_bars": [{
                "timestamp": candle, "candle_closed_at": candle,
                "close": close, "finalized": True,
            }],
            "zone_ladder": [
                {"zone_id": f"support-{timeframe}", "role": "SUPPORT", "zone_low": 90.0, "zone_high": 95.0, "origin_candle_time": "2026-08-20T09:15:00+05:30"},
                {"zone_id": f"resistance-{timeframe}", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-20T09:15:00+05:30"},
            ],
        }
    return {"security_id": "61623", "vob_timeframes": lanes}


def update(value, timeframe, close, candle):
    result = deepcopy(value)
    result["vob_timeframes"][timeframe]["latest_finalized_bar"].update(
        {"close": close, "timestamp": candle, "candle_closed_at": candle}
    )
    result["vob_timeframes"][timeframe]["session_finalized_bars"].append({
        "close": close, "timestamp": candle, "candle_closed_at": candle,
        "finalized": True,
    })
    return result


def test_close_only_break_reclaim_and_duplicate_deduplication():
    engine = HorsepowerStateEngine()
    base = technical()
    seeded = engine.observe("CE:61623", base)
    assert seeded["events"] == []

    broken = engine.observe("CE:61623", update(base, "3m", 89.0, "2026-08-20T10:03:00+05:30"))
    assert broken["timeframes"]["3m"]["status"] == "SUPPORT_GONE"
    assert len(broken["events"]) == 1
    duplicate = engine.observe("CE:61623", update(base, "3m", 89.0, "2026-08-20T10:03:00+05:30"))
    assert len(duplicate["events"]) == 1

    reclaimed = engine.observe("CE:61623", update(update(base, "3m", 89.0, "2026-08-20T10:03:00+05:30"), "3m", 96.0, "2026-08-20T10:06:00+05:30"))
    assert reclaimed["timeframes"]["3m"]["status"] == "SUPPORT_BACK"
    assert reclaimed["events"][-1]["zone_id"] == "support-3m"


def test_resistance_break_breakout_lost_and_main_timeframe_combination():
    engine = HorsepowerStateEngine()
    base = technical()
    engine.observe("PE:61684", base)
    three = engine.observe("PE:61684", update(base, "3m", 111.0, "2026-08-20T10:03:00+05:30"))
    assert three["combined"] == "RESISTANCE OUT · 1X POWER"
    both_input = update(update(base, "3m", 111.0, "2026-08-20T10:03:00+05:30"), "5m", 111.0, "2026-08-20T10:05:00+05:30")
    both = engine.observe("PE:61684", both_input)
    assert both["combined"] == "BOTH RESISTANCES OUT · 2X HORSEPOWER"
    lost = engine.observe("PE:61684", update(both_input, "3m", 104.0, "2026-08-20T10:06:00+05:30"))
    assert lost["timeframes"]["3m"]["status"] == "BREAKOUT_LOST"


def test_one_minute_is_context_only_and_instrument_identity_isolated():
    engine = HorsepowerStateEngine()
    base = technical()
    engine.observe("CE:61623", base)
    pulse = engine.observe("CE:61623", update(base, "1m", 89.0, "2026-08-20T10:01:00+05:30"))
    assert pulse["pulse_1m"] == "HORSEPOWER DOWN ↓"
    assert pulse["combined"] == "IDLE"
    other = engine.observe("PE:61684", update(base, "1m", 100.0, "2026-08-20T10:01:00+05:30"))
    assert other["pulse_1m"] == "NEUTRAL"


def test_wick_values_do_not_trigger_without_close_crossing():
    engine = HorsepowerStateEngine()
    base = technical()
    engine.observe("CE:61623", base)
    wick = update(base, "5m", 92.0, "2026-08-20T10:05:00+05:30")
    wick["vob_timeframes"]["5m"]["latest_finalized_bar"].update({"low": 1.0, "high": 999.0})
    result = engine.observe("CE:61623", wick)
    assert result["timeframes"]["5m"]["support_broken"] == 0
    assert result["timeframes"]["5m"]["resistance_broken"] == 0


def test_session_bootstrap_matches_continuous_run_and_is_silent():
    base = technical()
    first = update(base, "3m", 89.0, "2026-08-20T10:03:00+05:30")
    complete = update(first, "3m", 96.0, "2026-08-20T10:06:00+05:30")

    continuous_engine = HorsepowerStateEngine()
    continuous_engine.observe("CE:61623", base)
    continuous_engine.observe("CE:61623", first)
    continuous = continuous_engine.observe("CE:61623", complete)

    restarted = HorsepowerStateEngine().observe("CE:61623", complete)
    assert restarted["bootstrap"] is True
    assert restarted["continuity"] == "SESSION_RECONSTRUCTED"
    assert restarted["timeframes"] == continuous["timeframes"]
    assert restarted["combined"] == continuous["combined"]
    assert all(event["notification_eligible"] is False for event in restarted["events"])


def test_full_ladder_preserves_two_distinct_same_bar_breaks():
    value = technical()
    value["vob_timeframes"]["3m"]["zone_ladder"].append({
        "zone_id": "resistance-3m-stacked", "role": "RESISTANCE",
        "zone_low": 106.0, "zone_high": 109.0,
        "origin_candle_time": "2026-08-20T09:15:00+05:30",
    })
    engine = HorsepowerStateEngine()
    engine.observe("CE:61623", value)
    result = engine.observe(
        "CE:61623", update(value, "3m", 111.0, "2026-08-20T10:03:00+05:30")
    )
    breaks = [
        event for event in result["events"]
        if event["timeframe"] == "3M" and event["event"] == "RESISTANCE_OUT"
    ]
    assert {event["zone_id"] for event in breaks} == {
        "resistance-3m", "resistance-3m-stacked",
    }
    assert result["timeframes"]["3m"]["status"] == "DOUBLE_RESISTANCE_OUT"
    assert result["combined"] == "DOUBLE RESISTANCE OUT · 2X HORSEPOWER"
    assert all(event["notification_eligible"] for event in breaks)


def test_contract_identity_does_not_carry_session_ledger_to_new_instrument():
    engine = HorsepowerStateEngine()
    broken = update(technical(), "5m", 89.0, "2026-08-20T10:05:00+05:30")
    old_contract = engine.observe("CE:OLD", broken)
    new_contract = engine.observe("CE:NEW", technical())
    assert old_contract["timeframes"]["5m"]["status"] == "SUPPORT_GONE"
    assert new_contract["timeframes"]["5m"]["status"] == "NEUTRAL"
    assert new_contract["events"] == []


def test_previous_session_zone_preserved_and_event_not_carried():
    engine = HorsepowerStateEngine()
    # Zone formed on previous day (2026-08-20)
    base_yesterday = technical(close=100.0, candle="2026-08-20T15:30:00+05:30")
    yesterday_broken = update(base_yesterday, "3m", 112.0, "2026-08-20T15:30:00+05:30")
    res_yesterday = engine.observe("NIFTY", yesterday_broken)
    assert res_yesterday["session_id"] == "2026-08-20"
    assert res_yesterday["timeframes"]["3m"]["status"] == "RESISTANCE_OUT"

    # Today (2026-08-21) opens with the same historical zone preserved in zone_ladder
    base_today = {
        "security_id": "NIFTY",
        "vob_timeframes": {
            "1m": {
                "latest_finalized_bar": {"timestamp": "2026-08-21T09:16:00+05:30", "candle_closed_at": "2026-08-21T09:16:00+05:30", "close": 100.0, "finalized": True},
                "session_finalized_bars": [{"timestamp": "2026-08-21T09:16:00+05:30", "candle_closed_at": "2026-08-21T09:16:00+05:30", "close": 100.0, "finalized": True}],
                "zone_ladder": [{"zone_id": "resistance-3m-yesterday", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-20T11:00:00+05:30"}],
            },
            "3m": {
                "latest_finalized_bar": {"timestamp": "2026-08-21T09:18:00+05:30", "candle_closed_at": "2026-08-21T09:18:00+05:30", "close": 100.0, "finalized": True},
                "session_finalized_bars": [{"timestamp": "2026-08-21T09:18:00+05:30", "candle_closed_at": "2026-08-21T09:18:00+05:30", "close": 100.0, "finalized": True}],
                "zone_ladder": [{"zone_id": "resistance-3m-yesterday", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-20T11:00:00+05:30"}],
            },
            "5m": {
                "latest_finalized_bar": {"timestamp": "2026-08-21T09:20:00+05:30", "candle_closed_at": "2026-08-21T09:20:00+05:30", "close": 100.0, "finalized": True},
                "session_finalized_bars": [{"timestamp": "2026-08-21T09:20:00+05:30", "candle_closed_at": "2026-08-21T09:20:00+05:30", "close": 100.0, "finalized": True}],
                "zone_ladder": [{"zone_id": "resistance-5m-yesterday", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-18T15:00:00+05:30"}],
            },
        },
    }
    res_today = engine.observe("NIFTY", base_today)
    # Regression 1: Previous session zone preserved in ladder
    assert res_today["timeframes"]["3m"]["resistance_total"] == 1
    # Regression 2: Previous session event NOT carried over into today's state
    assert res_today["session_id"] == "2026-08-21"
    assert res_today["timeframes"]["3m"]["status"] == "NEUTRAL"
    assert res_today["timeframes"]["5m"]["status"] == "NEUTRAL"
    assert res_today["combined"] == "IDLE"
    assert res_today["events"] == []


def test_historical_zone_current_day_break_and_restart_parity():
    engine = HorsepowerStateEngine()
    base_today = {
        "security_id": "NIFTY",
        "vob_timeframes": {
            "1m": {
                "latest_finalized_bar": {"timestamp": "2026-08-21T09:16:00+05:30", "candle_closed_at": "2026-08-21T09:16:00+05:30", "close": 100.0, "finalized": True},
                "session_finalized_bars": [{"timestamp": "2026-08-21T09:16:00+05:30", "candle_closed_at": "2026-08-21T09:16:00+05:30", "close": 100.0, "finalized": True}],
                "zone_ladder": [{"zone_id": "resistance-3m-yesterday", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-20T11:00:00+05:30"}],
            },
            "3m": {
                "latest_finalized_bar": {"timestamp": "2026-08-21T09:18:00+05:30", "candle_closed_at": "2026-08-21T09:18:00+05:30", "close": 100.0, "finalized": True},
                "session_finalized_bars": [
                    {"timestamp": "2026-08-21T09:18:00+05:30", "candle_closed_at": "2026-08-21T09:18:00+05:30", "close": 100.0, "finalized": True},
                    {"timestamp": "2026-08-21T09:21:00+05:30", "candle_closed_at": "2026-08-21T09:21:00+05:30", "close": 112.0, "finalized": True},
                ],
                "zone_ladder": [{"zone_id": "resistance-3m-yesterday", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-20T11:00:00+05:30"}],
            },
            "5m": {
                "latest_finalized_bar": {"timestamp": "2026-08-21T09:20:00+05:30", "candle_closed_at": "2026-08-21T09:20:00+05:30", "close": 100.0, "finalized": True},
                "session_finalized_bars": [{"timestamp": "2026-08-21T09:20:00+05:30", "candle_closed_at": "2026-08-21T09:20:00+05:30", "close": 100.0, "finalized": True}],
                "zone_ladder": [{"zone_id": "resistance-5m-yesterday", "role": "RESISTANCE", "zone_low": 105.0, "zone_high": 110.0, "origin_candle_time": "2026-08-18T15:00:00+05:30"}],
            },
        },
    }
    # Regression 5: Historical zone CAN break today if today close genuinely crosses above zone_high
    res = engine.observe("NIFTY", base_today)
    assert res["session_id"] == "2026-08-21"
    assert res["timeframes"]["3m"]["status"] == "RESISTANCE_OUT"
    assert len(res["events"]) == 1
    assert res["events"][0]["event"] == "RESISTANCE_OUT"
    assert res["events"][0]["confirmed_candle"] == "2026-08-21T09:21:00+05:30"

    # Regression 4: Restart parity
    fresh_engine = HorsepowerStateEngine()
    restarted = fresh_engine.observe("NIFTY", base_today)
    assert restarted["session_id"] == "2026-08-21"
    assert restarted["timeframes"]["3m"]["status"] == "RESISTANCE_OUT"
    assert restarted["combined"] == res["combined"]
    assert restarted["events"] == res["events"]


def test_event_confirmation_time_does_not_advance_with_evaluation_watermark():
    engine = HorsepowerStateEngine()
    base = technical()
    broken = update(base, "3m", 111.0, "2026-08-20T10:03:00+05:30")
    later = update(broken, "3m", 112.0, "2026-08-20T10:06:00+05:30")
    latest = update(later, "3m", 113.0, "2026-08-20T10:09:00+05:30")

    result = engine.observe("PE:61684", latest)
    lane = result["timeframes"]["3m"]
    assert lane["status"] == "RESISTANCE_OUT"
    assert lane["confirmed_candle"] == "2026-08-20T10:03:00+05:30"
    assert lane["latest_event"]["confirmed_candle"] == "2026-08-20T10:03:00+05:30"
    assert lane["evaluation_watermark"] == "2026-08-20T10:09:00+05:30"
