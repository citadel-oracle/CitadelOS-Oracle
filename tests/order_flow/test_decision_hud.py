from __future__ import annotations

from collections import deque

from src.order_flow.contracts import DataQuality, DepthLevel, MarketEvent, ReconciledTradeState
from src.order_flow.decision_hud import (
    OracleDecisionHudEngine,
    _EdgeSample,
    _arbitrate,
    _control_relationship,
    _side_control_state,
    _structure_state,
)
from src.order_flow.features import BookMetrics


def structure(rows, *, atm=24600.0, fresh=True):
    def leg(load, liquidity, velocity, acceleration):
        return {
            "load_intensity": load,
            "liquidity_score": liquidity,
            "oi_velocity": velocity,
            "oi_acceleration": acceleration,
        }
    spine = []
    for strike, load, liquidity, velocity, acceleration in rows:
        spine.append({
            "strike": strike,
            "CE": leg(load, liquidity, -velocity, -acceleration),
            "PE": leg(load + 8, liquidity, velocity, acceleration),
        })
    return {
        "data": {
            "underlying": {"atm_strike": atm},
            "tactical_edge": {"argus_prime": {
                "freshness": "FRESH" if fresh else "STALE",
                "source_event_time": "2026-08-10T10:00:00+05:30",
                "strike_spine": spine,
                "live_pcr": {"freshness": "FRESH" if fresh else "STALE", "change_1m": 0.03},
            }},
        }
    }


def option_event(*, strike=24600.0, side="CE", price=100.0, receive_ns=1_000_000_000):
    depth = tuple(DepthLevel(i + 1, 99.5 - i * .05, 200, 2, 100.5 + i * .05, 200, 2) for i in range(5))
    return MarketEvent(
        1, "2026-08-10", 1, f"event-{side}-{receive_ns}", "NSE_FNO", f"sec-{side}", f"ATM_{side}",
        "2026-08-11", strike, side, 1_786_000_000, "2026-08-10T04:30:00+00:00", receive_ns,
        receive_ns, price, 65, 1000, price, 1000, 1100, 900, 1000, 1000, depth, DataQuality.GOOD, f"fp-{receive_ns}",
    )


def trade(*, buy=0, sell=0, unknown=0):
    total = buy + sell + unknown
    return ReconciledTradeState("trade", total, buy, sell, unknown, "TEST", 1.0, "OK", "UNKNOWN", None, 0, DataQuality.GOOD)


def book(*, micro=0.0, bid_refill=0, ask_refill=0, bid_depletion=0, ask_depletion=0):
    return BookMetrics(0, 0, 100.0, micro, bid_depletion, ask_depletion, bid_refill, ask_refill, 0, micro, 1.0, 1.0, "AVAILABLE")


def test_focus_pair_is_atomic_stale_cannot_win_and_challenger_persists():
    engine = OracleDecisionHudEngine()
    now = 1_000_000_000
    engine.register_structure(structure([(24550, 35, 95, 10, 5), (24600, 60, 95, 20, 10)]), receive_ns=now)
    first = engine.snapshot(now_ns=now)
    assert first["focus_strike"] == 24600
    assert first["call"]["contract"] == "24600 CE"
    assert first["put"]["contract"] == "24600 PE"

    engine.register_structure(structure([(24550, 99, 99, 10, 5), (24600, 5, 95, 20, 10)], fresh=False), receive_ns=now + 1)
    assert engine.snapshot(now_ns=now + 1)["focus_strike"] == 24600

    challenger = structure([(24550, 100, 100, 10, 5), (24600, 5, 30, 20, 10)])
    engine.register_structure(challenger, receive_ns=now + 2)
    engine.register_structure(challenger, receive_ns=now + 3)
    assert engine.snapshot(now_ns=now + 3)["focus_strike"] == 24600
    engine.register_structure(challenger, receive_ns=now + 4)
    rolled = engine.snapshot(now_ns=now + 4)
    assert rolled["focus_strike"] == 24550
    assert (rolled["call"]["contract"], rolled["put"]["contract"]) == ("24550 CE", "24550 PE")


def test_universal_control_projection_is_additive_and_formula_stays_frozen():
    engine = OracleDecisionHudEngine()
    now = 1_000_000_000
    engine.register_structure(structure([(24600, 70, 96, 100, 100)]), receive_ns=now)
    engine.ingest_option(option_event(side="CE", receive_ns=now), trade(unknown=65), book(), now_ns=now)
    engine.ingest_option(option_event(side="PE", receive_ns=now + 1), trade(unknown=65), book(), now_ns=now + 1)
    value = engine.snapshot(now_ns=now + 1)

    assert value["formula_version"] == "ORACLE_DECISION_HUD_SHADOW_V2"
    assert value["presentation_version"] == "ORACLE_UNIVERSAL_CONTROL_BARS_V1"
    assert value["execution_influence"] == "ZERO"
    assert value["call"]["flow_state"] == value["call"]["edge_state"]
    assert value["call"]["oi_state"] == value["call"]["structure_state"]
    assert value["call"]["flow_strength"] == value["call"]["edge_strength"]
    assert value["call"]["oi_strength"] == value["call"]["structure_strength"]
    assert value["control_event_id"].startswith("control_")


def test_universal_control_relationship_covers_continuation_rotation_balance_and_conflict():
    assert _control_relationship(
        "BUYING STRONG", "BUY STRONG", "SELLING STRONG", "SELL STRONG", data_locked=False,
    ) == "CE TAKING CONTROL"
    assert _control_relationship(
        "SELLING STRONG", "SELL STRONG", "BUYING STRONG", "BUY STRONG", data_locked=False,
    ) == "PE TAKING CONTROL"
    assert _control_relationship(
        "REVERSAL BUILDING", "TURNING", "SELLING EXHAUSTED", "SELL FADING", data_locked=False,
    ) == "CONTROL ROTATING → CE"
    assert _control_relationship(
        "NO EDGE", "BALANCED", "NO EDGE", "BALANCED", data_locked=False,
    ) == "BALANCED / ROTATION"
    assert _control_relationship(
        "BUYING STRONG", "SELL STRONG", "NO EDGE", "BALANCED", data_locked=False,
    ) == "CONFLICT / ROTATION"
    assert _control_relationship(
        "BUYING STRONG", "BUY STRONG", "SELLING STRONG", "SELL STRONG", data_locked=True,
    ) == "DATA LOCKED"
    assert _side_control_state("BUYING STRONG", "BUY STRONG") == "BUYERS IN CONTROL"
    assert _side_control_state("SELLING EXHAUSTED", "SELL FADING") == "CONTROL WEAKENING"


def test_edge_semantic_progression_and_unknown_is_not_signed():
    engine = OracleDecisionHudEngine()
    base = 1_000_000_000
    engine.register_structure(structure([(24600, 70, 96, 100, 100)]), receive_ns=base)
    for index in range(8):
        now = base + index * 300_000_000
        for side in ("CE", "PE"):
            engine.ingest_option(
                option_event(side=side, price=100 - index * .8, receive_ns=now),
                trade(unknown=65),
                book(micro=-.75, ask_refill=100, bid_depletion=100),
                now_ns=now,
            )
    selling = engine.snapshot(now_ns=base + 2_100_000_000)["call"]
    assert selling["edge_state"] == "SELLING STRONG"
    assert selling["action"] == "WAIT"
    assert engine._sides["call"].edge_evidence["signed_flow_confirmation"] is None

    for index in range(8, 24):
        now = base + index * 300_000_000
        for side in ("CE", "PE"):
            engine.ingest_option(
                option_event(side=side, price=94.4 + (index - 8) * .1, receive_ns=now),
                trade(unknown=65),
                book(micro=.65, bid_refill=140, ask_depletion=90),
                now_ns=now,
            )
    assert engine.snapshot(now_ns=base + 6_900_000_000)["call"]["edge_state"] in {"SELLING EXHAUSTED", "REVERSAL BUILDING", "BUYING BUILDING"}

    for index in range(24, 36):
        now = base + index * 300_000_000
        for side in ("CE", "PE"):
            engine.ingest_option(
                option_event(side=side, price=96.0 + (index - 24) * .9, receive_ns=now),
                trade(buy=65),
                book(micro=.8, bid_refill=140, ask_depletion=90),
                now_ns=now,
            )
    buying = engine.snapshot(now_ns=base + 10_500_000_000)["call"]
    assert buying["edge_state"] == "BUYING STRONG"
    assert buying["action"] in {"READY+", "GO"}


def test_structure_states_and_edge_authority_arbitration():
    assert _structure_state(-.7) == "SELL STRONG"
    assert _structure_state(-.3) == "SELL FADING"
    assert _structure_state(-.1) == "TURNING"
    assert _structure_state(0) == "BALANCED"
    assert _structure_state(.4) == "BUY BUILDING"
    assert _structure_state(.8) == "BUY STRONG"
    assert _arbitrate("SELLING STRONG", "BUY STRONG") == ("WAIT", "SELLING_STRONG")
    assert _arbitrate("SELLING EXHAUSTED", "BUY STRONG") == ("WAIT", "SELLING_EXHAUSTED")
    assert _arbitrate("REVERSAL BUILDING", "SELL STRONG") == ("WAIT", "SELLING_EXHAUSTED")
    assert _arbitrate("REVERSAL BUILDING", "TURNING") == ("READY", "REVERSAL_BUILDING")
    assert _arbitrate("BUYING BUILDING", "SELL STRONG") == ("READY", "REVERSAL_BUILDING")
    assert _arbitrate("BUYING BUILDING", "TURNING") == ("READY+", "BUYING_BUILDING")
    assert _arbitrate("BUYING STRONG", "SELL STRONG") == ("READY+", "BUYING_BUILDING")
    assert _arbitrate("BUYING STRONG", "BUY STRONG") == ("GO", "BUYING_STRONG")
    assert _arbitrate("DATA LOCKED", "BUY STRONG") == ("WAIT", "DATA_LOCKED")


def test_all_edge_classifier_states_are_distinct():
    engine = OracleDecisionHudEngine()

    def classify(prices, micro, refill):
        samples = deque(
            (_EdgeSample(i, price, 1.0, micro, refill, 0, 0, 100) for i, price in enumerate(prices)),
            maxlen=engine.EDGE_WINDOW,
        )
        return engine._edge_state(samples)[0]

    exhausted_prices = [100, 99, 98, 97] + [96] * 8
    assert classify([100 - i for i in range(12)], -.8, -.8) == "SELLING STRONG"
    assert classify(exhausted_prices, .08, .08) == "SELLING EXHAUSTED"
    assert classify(exhausted_prices, .3, .3) == "REVERSAL BUILDING"
    assert classify([100 + i * .15 for i in range(12)], .3, .2) == "BUYING BUILDING"
    assert classify([100 + i * .4 for i in range(12)], .7, .4) == "BUYING STRONG"
    assert classify([100] * 12, 0, 0) == "NO EDGE"


def test_data_quality_failure_locks_immediately_and_revision_is_atomic():
    engine = OracleDecisionHudEngine()
    now = 1_000_000_000
    engine.register_structure(structure([(24600, 70, 96, 100, 100)]), receive_ns=now)
    locked = engine.snapshot(now_ns=now + OracleDecisionHudEngine.STRUCTURE_FRESH_NS + 1)
    assert locked["data_quality"] == "LOCKED"
    assert locked["call"]["action"] == locked["put"]["action"] == "WAIT"
    assert locked["call"]["hero_state"] == locked["put"]["hero_state"] == "DATA_LOCKED"
    assert locked["call"]["display_edge_state"] == locked["put"]["display_edge_state"] == "DATA LOCKED"
    assert locked["call"]["display_structure_state"] == locked["put"]["display_structure_state"] == "DATA LOCKED"
    assert locked["call"]["edge_strength"] == locked["put"]["edge_strength"] == 0.0
    assert locked["call"]["structure_strength"] == locked["put"]["structure_strength"] == 0.0
    assert locked["call"]["contract"].split()[0] == locked["put"]["contract"].split()[0]


def test_raw_edge_is_immediate_while_display_state_keeps_existing_hysteresis():
    engine = OracleDecisionHudEngine()
    base = 1_000_000_000
    engine.register_structure(structure([(24600, 70, 96, 100, 100)]), receive_ns=base)
    for index in range(8):
        now = base + index * 100_000_000
        for side in ("CE", "PE"):
            engine.ingest_option(
                option_event(side=side, price=100 - index, receive_ns=now),
                trade(unknown=65),
                book(micro=-.8, ask_refill=100, bid_depletion=100),
                now_ns=now,
            )
    value = engine.snapshot(now_ns=base + 700_000_000)["call"]
    assert value["raw_edge_state"] == "SELLING STRONG"
    assert value["display_edge_state"] == value["edge_state"] == "NO EDGE"

    for index in range(8, 17):
        now = base + index * 100_000_000
        for side in ("CE", "PE"):
            engine.ingest_option(
                option_event(side=side, price=100 - index, receive_ns=now),
                trade(unknown=65),
                book(micro=-.8, ask_refill=100, bid_depletion=100),
                now_ns=now,
            )
    committed = engine.snapshot(now_ns=now)["call"]
    assert committed["raw_edge_state"] == committed["display_edge_state"] == "SELLING STRONG"
    assert engine.transitions()[-1]["call"]["raw_edge_state"] == "SELLING STRONG"


def test_data_lock_is_immediate_but_last_raw_evidence_remains_observable():
    engine = OracleDecisionHudEngine()
    now = 1_000_000_000
    engine.register_structure(structure([(24600, 70, 96, 100, 100)]), receive_ns=now)
    locked = engine.snapshot(now_ns=now + OracleDecisionHudEngine.STRUCTURE_FRESH_NS + 1)["call"]
    assert locked["display_edge_state"] == "DATA LOCKED"
    assert locked["display_structure_state"] == "DATA LOCKED"
    assert locked["raw_edge_state"] == "NO EDGE"


def test_one_stale_leg_locks_both_sides_and_atomic_recovery_has_display_revision():
    engine = OracleDecisionHudEngine()
    base = 1_000_000_000
    engine.register_structure(structure([(24600, 70, 96, 100, 100)]), receive_ns=base)
    engine.ingest_option(option_event(side="CE", receive_ns=base), trade(unknown=65), book(), now_ns=base)
    partial = engine.snapshot(now_ns=base)
    assert partial["data_quality"] == "LOCKED"
    assert partial["call"]["display_edge_state"] == partial["put"]["display_edge_state"] == "DATA LOCKED"
    locked_revision = partial["display_revision"]

    engine.ingest_option(option_event(side="PE", receive_ns=base + 1), trade(unknown=65), book(), now_ns=base + 1)
    recovered = engine.snapshot(now_ns=base + 1)
    assert recovered["data_quality"] == "GOOD"
    assert recovered["call"]["display_edge_state"] == recovered["put"]["display_edge_state"] == "NO EDGE"
    assert recovered["display_revision"] == locked_revision + 1
    assert recovered["raw_revision"] == recovered["revision"]


def test_focus_switch_clears_old_pair_strength_before_atomic_handoff():
    engine = OracleDecisionHudEngine()
    now = 1_000_000_000
    engine.register_structure(structure([(24550, 100, 100, 10, 5), (24600, 5, 30, 20, 10)]), receive_ns=now)
    engine._sides["call"].strength = 88.0
    engine._sides["put"].strength = 77.0
    engine._focus_strike = 24600.0
    engine._focus_score = 0.0
    challenger = structure([(24550, 100, 100, 10, 5), (24600, 5, 30, 20, 10)])
    for index in range(3):
        engine.register_structure(challenger, receive_ns=now + index + 1)
    assert engine._focus_strike == 24550.0
    assert engine._sides["call"].strength == engine._sides["put"].strength == 0.0
