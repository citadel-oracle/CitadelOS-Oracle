from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.order_flow.contracts import AggressorSide, DataQuality, ReconciledTradeState
from src.order_flow.flow_pulse import ArgusFlowPulseEngine

from .helpers import event


START = datetime(2026, 8, 11, 3, 45, tzinfo=timezone.utc)


def pulse_event(index: int, seconds: float, price: float, *, role="NIFTY_FUTURE", side=None, security_id="58072"):
    stamp = START + timedelta(seconds=seconds)
    return replace(
        event(
            event_id=f"e{index}", security_id=security_id, role=role,
            option_type=side, ltp=price, volume=1_000 + index * 100,
            receive_ns=1_000_000_000 + int(seconds * 1_000_000_000),
        ),
        session_id="2026-08-11",
        receive_wall_utc=stamp.isoformat(),
        strike=24500.0 if side else None,
    )


def trade(index: int, *, buy=0, sell=0, unknown=0):
    side = AggressorSide.BUY if buy else AggressorSide.SELL if sell else AggressorSide.UNKNOWN
    return ReconciledTradeState(
        f"e{index}", buy + sell + unknown, buy, sell, unknown, "TEST", 1.0,
        "RECONCILED", side, 100.0 if buy or sell else None, buy + sell, DataQuality.GOOD,
    )


def update(engine, index, seconds, price, *, buy=0, sell=0, unknown=0, response_state=None):
    response = SimpleNamespace(state=response_state) if response_state else None
    return engine.update(
        pulse_event(index, seconds, price), trade(index, buy=buy, sell=sell, unknown=unknown), response=response,
    )


def test_opening_range_freezes_after_exact_first_30_seconds():
    engine = ArgusFlowPulseEngine()
    update(engine, 1, 0, 100, buy=10)
    update(engine, 2, 10, 102, buy=10)
    update(engine, 3, 29.9, 99, sell=10)
    result = update(engine, 4, 30, 105, buy=10)
    assert result["levels"]["OR HIGH"] == 102
    assert result["levels"]["OR LOW"] == 99
    assert result["levels"]["opening_range_frozen"] is True
    assert result["levels"]["opening_range_available"] is True


def test_restart_recovers_exact_recorded_opening_range_without_live_history_scan():
    engine = ArgusFlowPulseEngine()
    engine.register_opening_range(high=102, low=99, source_timestamp="2026-08-11T09:15:29+05:30")
    result = update(engine, 1, 12_000, 100, unknown=10)
    assert result["levels"]["OR HIGH"] == 102
    assert result["levels"]["OR LOW"] == 99
    assert result["levels"]["opening_range_source_timestamp"] == "2026-08-11T09:15:29+05:30"


def test_previous_session_market_generated_levels_are_exact():
    engine = ArgusFlowPulseEngine()
    engine.register_reference_levels(previous_day_high=110, previous_day_low=90, previous_close=100, source_timestamp="2026-08-10")
    result = update(engine, 1, 31, 100, buy=10)
    assert {key: result["levels"][key] for key in ("PDH", "PDL", "PREVIOUS CLOSE")} == {
        "PDH": 110.0, "PDL": 90.0, "PREVIOUS CLOSE": 100.0,
    }


def test_incremental_profile_uses_all_observed_volume_and_70_percent_value_area():
    engine = ArgusFlowPulseEngine()
    update(engine, 1, 0, 100.0, buy=70)
    update(engine, 2, 1, 100.05, unknown=20)
    result = update(engine, 3, 2, 100.10, sell=10)
    profile = result["profile"]
    assert profile["total_observed_volume"] == 100
    assert profile["poc"] == 100.0
    assert profile["value_area_fraction"] == 0.70
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    assert "APPROXIMATION" in profile["provenance"]


def test_value_migration_is_directional_not_a_score():
    engine = ArgusFlowPulseEngine()
    update(engine, 1, 0, 100, buy=100)
    result = update(engine, 2, 1, 99, sell=500)
    assert result["value_state"] == "LOWER"
    assert result["score_authority"] == "NONE"


def test_low_volume_pocket_is_relational_and_not_hardcoded():
    engine = ArgusFlowPulseEngine()
    for index, (price, qty) in enumerate(((100, 100), (100.05, 100), (100.10, 5), (100.15, 100), (100.20, 100)), 1):
        result = update(engine, index, index, price, buy=qty)
    assert result["profile"]["low_volume_pocket"] == {"low": 100.1, "high": 100.1, "kind": "LOW_VOLUME_POCKET"}


def test_execution_bursts_aggregate_100ms_and_preserve_unknown():
    engine = ArgusFlowPulseEngine()
    update(engine, 1, 0.00, 100, buy=10)
    update(engine, 2, 0.05, 100, buy=20)
    result = update(engine, 3, 0.12, 100, unknown=40)
    assert result["execution_bursts"][-1]["quantity"] == 30
    assert result["execution_bursts"][-1]["side"] == "BUY"
    result = update(engine, 4, 0.25, 100, sell=1)
    assert result["execution_bursts"][-1]["side"] == "UNKNOWN"


def test_tape_speed_advances_even_when_oi_velocity_is_zero_elsewhere():
    engine = ArgusFlowPulseEngine()
    result = None
    for index in range(20):
        result = update(engine, index, index * 0.1, 100 + index * 0.01, unknown=10)
    assert result["tape"]["events_per_second"] > 0
    assert result["tape"]["executed_volume_per_second"] > 0
    assert result["tape"]["state"] in {"FAST", "FAST AGAIN", "SLOWING"}


def test_look_below_and_fail_creates_model_one_watch_before_reaction_confirms():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine.register_reference_levels(previous_day_high=110, previous_day_low=100, previous_close=105)
    update(engine, 1, 31, 101, sell=10)
    update(engine, 2, 32, 99, sell=100)
    result = update(engine, 3, 33, 100.1, buy=100)
    assert result["state"] == "WATCH"
    assert result["model"] == "MODEL 1 · RANGE"
    assert "RECLAIMED" in result["story"]


def test_look_above_and_fail_creates_model_one_watch_before_reaction_confirms():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine.register_reference_levels(previous_day_high=110, previous_day_low=100, previous_close=105)
    update(engine, 1, 31, 109, buy=10)
    update(engine, 2, 32, 111, buy=100)
    result = update(engine, 3, 33, 109.9, sell=100)
    assert result["state"] == "WATCH"
    assert "REJECTED" in result["story"]


def test_middle_of_range_does_not_authorize_action():
    engine = ArgusFlowPulseEngine()
    engine.register_reference_levels(previous_day_high=110, previous_day_low=90, previous_close=100)
    result = update(engine, 1, 31, 100, unknown=10)
    assert result["state"] in {"NO TRADE", "WATCH"}
    assert result["side"] is None


def test_option_mapping_uses_real_atm_ask_bid_identity():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 30, 100, unknown=1)
    option = pulse_event(1, 31, 63.35, role="ATM_PE", side="PE", security_id="41012")
    engine.update(option, trade(1, sell=10))
    engine._episode.update({"side": "PE", "state": "EARLY BUY PE"})
    result = update(engine, 2, 32, 100, sell=10)
    assert result["option"] == {
        "strike": 24500.0, "option_type": "PE", "security_id": "41012",
        "expiry": "2026-08-27", "bid": 99.95, "ask": 100.0,
        "spread": 0.04999999999999716, "source_timestamp": option.receive_wall_utc,
        "age_ms": 1000.0,
        "status": "AVAILABLE",
    }


def test_actionable_states_create_canonical_paper_trades_using_ask_and_bid_without_broker():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 30, 100, unknown=1)
    option = pulse_event(1, 31, 63.35, role="ATM_PE", side="PE", security_id="41012")
    engine.update(option, trade(1, sell=10))
    engine._episode.update({
        "side": "PE", "state": "EARLY BUY PE", "model": "MODEL 2 · TREND",
        "area": "OR LOW · 100", "trigger": 100, "invalidation": 101,
        "target_1": 99, "target_2": 98,
    })
    result = update(engine, 2, 32, 100, sell=10)
    [paper] = result["paper_trades"]
    assert paper["entry_type"] == "AGGRESSIVE"
    assert paper["entry_ask"] == 100.0
    assert paper["live_bid"] == 99.95
    assert paper["pnl_option_points"] == -0.04999999999999716
    assert paper["broker_submission"] is False
    assert paper["execution_influence"] == "ZERO"
    assert engine.drain_paper_events()[0]["trade_id"] == paper["trade_id"]


def test_terminal_futures_event_records_realized_r_without_waiting_for_an_option_tick():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 30, 100, unknown=1)
    option = pulse_event(1, 31, 63.35, role="ATM_CE", side="CE", security_id="41011")
    engine.update(option, trade(1, buy=10))
    engine._episode.update({
        "side": "CE", "state": "EARLY BUY CE", "model": "MODEL 2 · TREND",
        "area": "OR HIGH · 100", "trigger": 100, "invalidation": 99,
        "target_1": 101, "target_2": 102,
    })
    update(engine, 2, 32, 100, buy=10)

    engine._episode.update({
        "state": "INVALID / EXIT",
        "reason_for_state_change": "STRUCTURAL INVALIDATION",
    })
    engine._mark_paper_trades(pulse_event(3, 33, 99.5))

    [paper] = engine.paper_trades()
    assert paper["state"] == "INVALIDATED"
    assert paper["realized_r"] == -0.5
    assert paper["exit_bid"] == 99.95


def test_known_bad_ce_target_cannot_publish_buy_or_create_paper_but_is_archived():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 30, 24540, unknown=1)
    option = pulse_event(1, 31, 168.35, role="ATM_CE", side="CE", security_id="41011")
    engine.update(option, trade(1, buy=10))
    engine._episode.update({
        "side": "CE", "state": "BUY CE · CONFIRMED", "model": "MODEL 2 · TREND",
        "area": "OR LOW · 24539", "trigger": 24541, "invalidation": 24530,
        "target_1": 24485, "target_2": 24560.7, "entry_price": 24540,
    })
    result = update(engine, 2, 32, 24540, buy=10)
    assert engine._episode["state"] == "BUY CE · CONFIRMED"
    assert result["headline"] == "NO TRADE"
    assert result["state"] == "WATCH · PLAN INVALID"
    assert result["action_contract"]["validation_reason"] == "PLAN INVALID · TARGET_DIRECTION"
    assert result["paper_trades"] == []
    [evidence] = engine.drain_validation_events()
    assert evidence["PLAN_VALIDATION"] == "FAIL"
    assert evidence["candidate_plan"]["target_1"] == 24485


def test_confirmed_entry_is_distinct_duplicate_safe_paper_trade():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 30, 100, unknown=1)
    option = pulse_event(1, 31, 63.35, role="ATM_PE", side="PE", security_id="41012")
    engine.update(option, trade(1, sell=10))
    engine._episode.update({
        "side": "PE", "state": "BUY PE · CONFIRMED", "model": "MODEL 2 · TREND",
        "area": "OR LOW · 100", "trigger": 100, "invalidation": 101,
        "target_1": 99, "target_2": 98,
    })
    first = update(engine, 2, 32, 99.8, sell=10)
    second = update(engine, 3, 33, 99.7, sell=10)
    assert len(first["paper_trades"]) == len(second["paper_trades"]) == 1
    assert first["paper_trades"][0]["entry_type"] == "CONFIRMED"


def test_stale_option_quote_preserves_futures_setup_but_locks_executable_quote():
    engine = ArgusFlowPulseEngine(option_quote_fresh_ns=1_000_000_000)
    engine.update(pulse_event(0, 30, 100), trade(0, unknown=1))
    option = pulse_event(1, 31, 63.35, role="ATM_PE", side="PE", security_id="41012")
    engine.update(option, trade(1, sell=10))
    engine._episode.update({"side": "PE", "state": "EARLY BUY PE"})
    result = engine.update(pulse_event(2, 33, 100), trade(2, sell=10))
    assert result["option"]["status"] == "STALE"
    assert result["option"]["ask"] == 100.0


def test_missing_option_quote_preserves_futures_setup():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine.register_reference_levels(previous_day_high=110, previous_day_low=100, previous_close=105)
    update(engine, 1, 31, 101, sell=10)
    update(engine, 2, 32, 99, sell=100)
    result = update(engine, 3, 33, 100.1, buy=100)
    assert result["state"] == "WATCH"
    assert result["option"] is None


def test_model_one_confirmation_requires_reclaim_to_hold_with_real_reaction_or_tape():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine.register_reference_levels(previous_day_high=110, previous_day_low=100, previous_close=105)
    update(engine, 1, 31, 101, sell=10)
    update(engine, 2, 32, 99, sell=100)
    update(engine, 3, 33, 100.1, buy=100)
    update(engine, 4, 33.2, 100.2, buy=10, response_state="CLEAN_BULL")
    result = update(engine, 5, 33.4, 100.3, buy=10, response_state="CLEAN_BULL")
    assert any(item["to"] == "BUY CE · CONFIRMED" for item in engine.drain_transitions())
    assert engine._episode["state"] in {"BUY CE · CONFIRMED", "T1 HIT · PROTECT", "RUNNER"}
    assert result["state"] == "BUY CE · CONFIRMED"
    assert result["action_contract"]["plan_validation"] == "PASS"
    assert result["futures"]["invalidation"] == 99


def test_model_two_bearish_and_bullish_are_mirrors_without_score_gate():
    bearish = ArgusFlowPulseEngine()
    bearish.session_id = "2026-08-11"
    bearish._profile_snapshot = {"migration": "LOWER", "low_volume_pocket": {"low": 100, "high": 100}, "poc": 99, "vah": 101, "val": 98}
    bearish._start_continuation("PE", "PDL", 100, "2026-08-11T09:16:00+05:30", 99)
    assert bearish._episode["state"] == "EARLY BUY PE"
    bullish = ArgusFlowPulseEngine()
    bullish.session_id = "2026-08-11"
    bullish._profile_snapshot = {"migration": "HIGHER", "low_volume_pocket": {"low": 100, "high": 100}, "poc": 101, "vah": 102, "val": 99}
    bullish._start_continuation("CE", "PDH", 100, "2026-08-11T09:16:00+05:30", 101)
    assert bullish._episode["state"] == "EARLY BUY CE"


def test_raw_packet_updates_do_not_create_blank_or_duplicate_hero_transitions():
    engine = ArgusFlowPulseEngine()
    states = []
    for index in range(100):
        states.append(update(engine, index, 31 + index * 0.05, 100, unknown=1)["state"])
    assert all(states)
    assert len(engine.drain_transitions()) <= 1


def test_invalidation_is_immediate_and_runner_uses_structure_not_score():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 0, 100, unknown=1)
    engine._episode.update({"state": "BUY PE · CONFIRMED", "side": "PE", "invalidation": 101, "target_1": 98, "transition_count": 1})
    result = update(engine, 1, 60, 101.1, buy=10)
    assert result["state"] == "INVALID / EXIT"
    assert result["score_authority"] == "NONE"


def test_t1_protect_then_runner_only_with_directional_value_migration():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 0, 100, unknown=1)
    engine._episode.update({
        "state": "BUY CE · CONFIRMED", "side": "CE", "setup_id": "setup-protect",
        "entry_price": 100, "trigger": 99.5, "invalidation": 99,
        "original_invalidation": 99, "target_1": 101, "target_2": 103,
        "transition_count": 1,
    })
    first = update(engine, 1, 60, 101.1, buy=10)
    assert engine._episode["state"] == "T1 HIT · PROTECT"
    assert first["state"] == "T1 HIT · PROTECT"
    assert first["futures"]["invalidation"] == 99.5
    assert first["action_contract"]["plan_validation"] == "PASS"
    assert first["action_contract"]["candidate_plan"]["level_revisions"][-1]["reason"] == "T1_PROTECTION_COMMITTED"
    engine._profile_snapshot["migration"] = "HIGHER"
    engine._evaluate_episode(pulse_event(2, 61, 101.2), tape={"state": "FAST"}, reaction="BUYING WORKING")
    assert engine._episode["state"] == "RUNNER"
    engine._evaluate_episode(pulse_event(3, 62, 101.3), tape={"state": "FAST"}, reaction="BUYING WORKING")
    assert engine._episode["state"] == "RUNNER"
    transitions = engine.drain_transitions()
    assert sum(item["to"] == "T1 HIT · PROTECT" for item in transitions) == 1


def test_model_one_uses_breach_extreme_and_never_selects_wrong_side_profile_target():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._profile_snapshot = {
        "migration": "HIGHER", "low_volume_pocket": None,
        "poc": 99.0, "vah": 103.0, "val": 98.0,
    }
    engine._profile_revision = 7
    engine._start_model_one(
        "CE", "PDL", 100.0, "2026-08-11T09:16:00+05:30", 101.0,
        "LOW BROKE → SELLERS FAILED → LOW RECLAIMED",
        invalidation=98.5, event_id="event-reclaim",
    )
    assert engine._episode["trigger"] == 100.0
    assert engine._episode["original_invalidation"] == 98.5
    assert engine._episode["target_1"] is None
    assert engine._episode["target_2"] == 103.0
    assert engine._episode["level_lineage"]["target_1"] == {
        "level_type": "POC", "level_value": None, "source_revision": 7,
        "event_id": "event-reclaim",
        "why_selected": "RANGE MIDPOINT / POC · UNAVAILABLE ON FORWARD SIDE",
        "source_level_value": 99.0,
    }


def test_t1_without_directionally_valid_protection_never_claims_protect():
    engine = ArgusFlowPulseEngine()
    update(engine, 0, 0, 100, unknown=1)
    engine._episode.update({
        "state": "BUY CE · CONFIRMED", "side": "CE", "setup_id": "setup-no-protect",
        "entry_price": 100, "trigger": 100, "invalidation": 99,
        "original_invalidation": 99, "target_1": 101, "target_2": 103,
        "transition_count": 1,
    })
    update(engine, 1, 60, 101.1, buy=10)
    assert engine._episode["state"] == "RUNNER"
    assert engine._episode["t1_hit_timestamp"] == pulse_event(1, 60, 101.1).receive_wall_utc
    assert all(item["to"] != "T1 HIT · PROTECT" for item in engine.drain_transitions())


def test_hot_path_has_no_filesystem_or_history_scan():
    engine = ArgusFlowPulseEngine()
    for index in range(200):
        update(engine, index, index * 0.01, 100 + (index % 5) * 0.05, unknown=1)
    telemetry = engine.telemetry()
    assert telemetry["filesystem_calls_per_event"] == 0
    assert telemetry["full_history_scans_per_event"] == 0
    assert telemetry["deep_copies_per_event"] == 0
    assert telemetry["p99_ms"] is not None


def test_safety_and_probability_contract():
    engine = ArgusFlowPulseEngine()
    result = update(engine, 1, 0, 100, unknown=1)
    assert result["advisory_only"] is True
    assert result["execution_influence"] == "ZERO"
    assert result["score_authority"] == "NONE"
    assert "probability" not in result


def test_live_meters_keep_updating_in_no_trade_and_preserve_unknown():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    first = update(engine, 1, 31, 100.00, buy=10, unknown=90)
    second = update(engine, 2, 32, 100.05, buy=20, unknown=80)
    assert first["state"] == second["state"] == "NO TRADE"
    assert second["profile"]["revision"] > first["profile"]["revision"]
    assert second["flow"]["unknown_volume"] > 0
    assert second["flow"]["buy_volume"] > 0
    assert second["flow"]["buy_volume"] + second["flow"]["sell_volume"] + second["flow"]["unknown_volume"] == second["flow"]["total_volume"]
    assert second["reaction"] == "NO CLEAN RESPONSE"
    assert second["revision"] > first["revision"]


def test_aggressive_and_confirmation_are_two_legs_of_one_episode():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    update(engine, 0, 30, 100, unknown=1)
    option = pulse_event(1, 31, 63.35, role="ATM_PE", side="PE", security_id="41012")
    engine.update(option, trade(1, sell=10))
    setup_id = "pulse_setup_same_market_story"
    engine._episode.update({
        "setup_id": setup_id, "setup_started_at": option.receive_wall_utc,
        "side": "PE", "state": "EARLY BUY PE", "model": "MODEL 2 · TREND",
        "area": "PDL · 100", "trigger": 100, "invalidation": 101,
        "target_1": 99, "target_2": 98, "entry_price": 100,
    })
    engine._update_paper_trades(pulse_event(2, 32, 99.8))
    engine._episode.update({"state": "BUY PE · CONFIRMED", "trigger": 99.5})
    engine._update_paper_trades(pulse_event(3, 33, 99.4))
    [episode] = engine.paper_episodes()
    assert len(episode["entry_legs"]) == 2
    assert {leg["entry_type"] for leg in episode["entry_legs"]} == {"AGGRESSIVE", "CONFIRMED"}


def test_model_two_terminal_structure_failure_rearms_without_stale_breach_memory():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine._episode.update({
        "state": "BUY PE · CONFIRMED", "model": "MODEL 2 · TREND", "side": "PE",
        "invalidation": 110, "target_1": None, "target_2": None,
        "entry_price": 100, "transition_count": 1,
    })
    engine._bars[120] = [
        {"time": 1, "open": 96, "high": 97, "low": 95, "close": 96},
        {"time": 2, "open": 97, "high": 98, "low": 96, "close": 97},
        {"time": 3, "open": 98, "high": 99, "low": 97, "close": 98},
    ]
    terminal = update(engine, 1, 31, 99, buy=100, response_state="CLEAN_BULL")
    assert terminal["state"] == "INVALID / EXIT"
    engine._breaches["PDL"] = {"direction": "BELOW"}
    rearmed = update(engine, 2, 32, 99.1, buy=10)
    assert rearmed["state"] == "NO TRADE"
    assert engine._breaches == {}
    engine._profile_snapshot.update({"migration": "HIGHER", "low_volume_pocket": None})
    engine._start_continuation("CE", "PDH", 101, pulse_event(3, 33, 101).receive_wall_utc, 101.1)
    assert engine._episode["state"] == "EARLY BUY CE"


def test_semantic_plane_records_evidence_and_does_not_follow_every_raw_update():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    for index in range(1, 18):
        result = update(engine, index, 31 + index * 0.05, 100 - index * 0.01, sell=50, unknown=10, response_state="CLEAN_BEAR")
    assert result["semantic"]["pressure"] in {"SELLERS ACTIVE", "SELLERS STRONG"}
    assert result["semantic"]["result"] == "PRICE FALLING WITH SELLERS"
    raw_updates = result["update_count"]
    semantic_revisions = result["semantic_revision"]
    assert raw_updates > semantic_revisions
    transitions = engine.drain_semantic_transitions()
    assert transitions
    assert all({"previous_state", "new_state", "raw_evidence", "timestamp", "reason"} <= item.keys() for item in transitions)


def test_level_radar_is_visible_before_break_and_records_failed_reclaim_sequence():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine.register_reference_levels(previous_day_high=None, previous_day_low=100, previous_close=None)
    far = update(engine, 1, 31, 101.0, sell=10)
    approaching = update(engine, 2, 32, 100.15, sell=10)
    testing = update(engine, 3, 33, 100.0, sell=10)
    broke = update(engine, 4, 34, 99.8, sell=20)
    held = update(engine, 5, 35, 99.7, sell=20)
    failed = update(engine, 6, 36, 100.1, buy=20)
    assert far["next_level"]["name"] == "PDL"
    assert approaching["next_level"]["state"] == "APPROACHING"
    assert testing["next_level"]["state"] == "TESTING"
    assert broke["next_level"]["state"] == "BROKE BELOW"
    assert held["next_level"]["state"] == "HOLDING BELOW"
    assert failed["next_level"]["state"] == "BREAK FAILED"
    states = [item["new_state"] for item in engine.drain_level_transitions() if item["level"] == "PDL"]
    assert "BACK ABOVE" in states and "BREAK FAILED" in states
    assert failed["what_happened"] == "BACK ABOVE PDL → SELLERS FAILED"


def test_no_trade_dead_screen_fields_remain_populated_and_profile_never_rebuilds():
    engine = ArgusFlowPulseEngine()
    engine.session_id = "2026-08-11"
    engine._or_frozen = True
    engine.register_opening_range(high=101, low=99, source_timestamp="2026-08-11T09:15:29+05:30")
    engine.register_reference_levels(previous_day_high=110, previous_day_low=90, previous_close=100)
    result = None
    for index in range(1, 25):
        result = update(engine, index, 31 + index * 0.1, 100 + (index % 3) * 0.05, unknown=10)
    assert result is not None
    assert all(result["semantic"][field] != "UNAVAILABLE" for field in ("market", "pressure", "result", "speed"))
    assert result["open_range"]["status"] == "SET"
    assert result["next_level"]["name"] != "NONE NEARBY"
    assert result["what_happened"]
    assert engine.telemetry()["profile_rebuilds"] == 0
