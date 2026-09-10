from src.order_flow.contracts import (
    FLOW_FORMULA_VERSION,
    DataQuality,
    DirectionalState,
    FlowProjection,
    ReversalState,
)
from src.order_flow.episodes import EpisodeEngine
from src.order_flow.reversal import ReversalEngine


def projection(snapshot, score, state, strength, reversal=ReversalState.STABLE_DIRECTION, session="2026-08-07"):
    return FlowProjection(
        1, FLOW_FORMULA_VERSION, int(snapshot), f"snap-{snapshot}", session,
        f"2026-08-07T04:45:0{snapshot}+00:00", (),
        strength if state is DirectionalState.CALL else 100 - strength,
        strength if state is DirectionalState.PUT else 100 - strength,
        score, state, True, (), {}, {}, {}, DataQuality.GOOD, 1, 1,
        reversal, {}, {"feed_receive_ns": 0, "decode_done_ns": 0, "state_done_ns": 0,
        "features_done_ns": 0, "score_done_ns": 0, "oracle_publish_ns": 0}, "DISABLED",
    )


def test_one_tick_does_not_confirm_reversal():
    engine = ReversalEngine(forming_seconds=1, confirmation_seconds=2)
    engine.update(0.6, now_ns=0)
    result = engine.update(-0.6, now_ns=100_000_000)
    assert result.state is ReversalState.PRESSURE_FLIP
    assert result.stable_direction == 1


def test_reversal_forming_then_confirmed_by_elapsed_time():
    engine = ReversalEngine(forming_seconds=1, confirmation_seconds=2)
    engine.update(0.6, now_ns=0)
    engine.update(-0.6, now_ns=1_000_000_000, futures_price=100, atm_premium=50)
    forming = engine.update(-0.6, now_ns=2_100_000_000, futures_price=99.5, atm_premium=51)
    confirmed = engine.update(-0.6, now_ns=3_100_000_000, futures_price=99, atm_premium=52)
    assert forming.state is ReversalState.REVERSAL_FORMING
    assert confirmed.state is ReversalState.REVERSAL_CONFIRMED
    assert confirmed.stable_direction == -1
    assert confirmed.lead_time_ms == 2100
    assert confirmed.futures_points_warning_to_confirmation == -1
    assert confirmed.atm_points_warning_to_confirmation == 2


def test_false_reversal_recovers_original_direction():
    engine = ReversalEngine(forming_seconds=1, confirmation_seconds=2)
    engine.update(0.7, now_ns=0)
    engine.update(-0.5, now_ns=1_000_000_000)
    result = engine.update(0.4, now_ns=1_200_000_000)
    assert result.state is ReversalState.STABLE_DIRECTION
    assert result.stable_direction == 1
    assert result.false_reversal_count == 1
    assert result.recovered_original_direction is True
    assert result.last_false_reversal_ns == 1_200_000_000


def test_data_degradation_freezes_state():
    engine = ReversalEngine(forming_seconds=0.1, confirmation_seconds=0.2)
    engine.update(0.7, now_ns=0)
    engine.update(-0.7, now_ns=100_000_000)
    frozen = engine.update(-0.7, now_ns=1_000_000_000, data_quality=DataQuality.DEGRADED)
    assert frozen.state is ReversalState.PRESSURE_FLIP
    assert frozen.stable_direction == 1


def test_hysteresis_ignores_small_opposite_score():
    engine = ReversalEngine(flip_threshold=0.35)
    engine.update(0.5, now_ns=0)
    result = engine.update(-0.25, now_ns=3_000_000_000)
    assert result.state is ReversalState.STABLE_DIRECTION
    assert result.stable_direction == 1


def test_episode_many_updates_one_identity_and_crossings_once():
    engine = EpisodeEngine()
    first = engine.update(projection("1", 0.3, DirectionalState.CALL, 65), futures_price=100)
    second = engine.update(projection("2", 0.5, DirectionalState.CALL, 75), futures_price=101, elapsed_ms=100)
    third = engine.update(projection("3", 0.7, DirectionalState.CALL, 85), futures_price=102, elapsed_ms=500)
    assert first is second is third
    assert set(third.band_crossings) == {60, 70, 80}
    assert len(third.score_path) == 3


def test_episode_duplicate_snapshot_suppressed():
    engine = EpisodeEngine()
    item = projection("1", 0.3, DirectionalState.CALL, 65)
    engine.update(item)
    engine.update(item)
    assert len(engine.active.score_path) == 1


def test_episode_rearms_only_after_neutral():
    engine = EpisodeEngine()
    first = engine.update(projection("1", 0.3, DirectionalState.CALL, 65))
    engine.update(projection("2", 0.01, DirectionalState.NEUTRAL, 50))
    second = engine.update(projection("3", 0.3, DirectionalState.CALL, 65))
    assert first.episode_id != second.episode_id
    assert len(engine.completed) == 1


def test_direction_flip_closes_and_starts_independent_episode():
    engine = EpisodeEngine()
    call = engine.update(projection("1", 0.5, DirectionalState.CALL, 75))
    put = engine.update(projection("2", -0.5, DirectionalState.PUT, 75))
    assert call.complete is True
    assert call.final_result == "DIRECTION_FLIP"
    assert put.direction == "PUT"


def test_episode_missing_horizons_remain_null():
    engine = EpisodeEngine()
    row = engine.update(projection("1", 0.5, DirectionalState.CALL, 75), futures_price=100)
    assert all(value is None for value in row.horizons.values())


def test_session_close_is_idempotent():
    engine = EpisodeEngine()
    engine.update(projection("1", 0.5, DirectionalState.CALL, 75))
    assert engine.close_session() is not None
    assert engine.close_session() is None


def test_session_rollover_closes_prior_episode_once():
    engine = EpisodeEngine()
    first = engine.update(projection("1", 0.5, DirectionalState.CALL, 75))
    second = engine.update(projection("2", 0.5, DirectionalState.CALL, 75, session="2026-08-08"))
    assert first.final_result == "SESSION_ROLLOVER"
    assert second.session_id == "2026-08-08"
