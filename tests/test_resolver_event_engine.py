from collections import deque
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from src.oracle.resolver_engine import ResolverEngine, FLOW_TTL_MS
from src.oracle.option_buyer_intelligence import _OiRollingTracker

IST = ZoneInfo("Asia/Kolkata")


def make_dt(hour: int, minute: int, second: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, tzinfo=IST)


def test_1_native_flow_freshness_rule():
    engine = ResolverEngine()
    engine.ingest_flow_snapshot({
        "revision": "REV_1",
        "source_timestamp": make_dt(10, 0, 0).isoformat(),
        "diagnostics": {"book_pressure": {"mlofi": 0.35, "l1_ofi": 0.25}},
    }, make_dt(10, 0, 0))

    engine.ingest_flow_snapshot({
        "revision": "REV_2",
        "source_timestamp": make_dt(10, 0, 1).isoformat(),
        "diagnostics": {"book_pressure": {"mlofi": 0.40, "l1_ofi": 0.30}},
    }, make_dt(10, 0, 1))

    # Fresh sample (1.0s old <= 1.5s aging)
    diag_fresh = engine.compute_flow_diagnostics(make_dt(10, 0, 2), make_dt(10, 0, 2))
    assert diag_fresh["flow_freshness_state"] == "FRESH"
    assert diag_fresh["event_mlofi"] == 0.40

    # Stale sample (4.0s old > 3.0s native TTL)
    diag_stale = engine.compute_flow_diagnostics(make_dt(10, 0, 5), make_dt(10, 0, 5))
    assert diag_stale["flow_freshness_state"] == "STALE"
    assert diag_stale["event_mlofi"] is None
    assert diag_stale["event_flow_x"] is None


def test_2_oi_boundary_single_authority():
    tracker = _OiRollingTracker()
    sid = "61647"
    tracker.record(sid, 10000.0, 100.0, make_dt(9, 15))
    tracker.record(sid, 12000.0, 105.0, make_dt(9, 20))  # delta = 2000
    tracker.record(sid, 15000.0, 110.0, make_dt(9, 25))  # delta = 3000
    tracker.record(sid, 20000.0, 115.0, make_dt(9, 30))  # current delta = 5000

    curr_metrics = tracker.closed_window_metrics(sid, 5, make_dt(9, 30))
    prior_deltas = tracker.prior_closed_window_deltas(sid, 5, make_dt(9, 30))

    assert curr_metrics["oi_delta"] == 5000.0
    assert prior_deltas == [2000.0, 3000.0]

    engine = ResolverEngine()
    diag = engine.compute_oi_diagnostics(prior_deltas, curr_metrics, make_dt(9, 30))
    assert diag["oi_delta"] == 5000.0
    assert diag["oi_prior_median"] == 2500.0
    assert diag["oi_x"] == 2.0
    assert diag["oi_new_session_extreme"] is True


def test_3_vob_alignment_lifecycle():
    engine = ResolverEngine()
    now = make_dt(10, 30, day=21)

    # Case A: Yesterday 3M bullish + Today 5M bullish -> NOT aligned!
    payload_yesterday = {
        "contract": {"security_id": "61647", "strike": 24200},
        "vob": {
            "horsepower": {
                "3m": {"status": "RESISTANCE_OUT", "event_id": "EV_OLD", "confirmed_candle": make_dt(10, 0, day=20).isoformat()},
                "5m": {"status": "RESISTANCE_OUT", "event_id": "EV_NEW", "confirmed_candle": make_dt(10, 30, day=21).isoformat()},
            }
        },
    }
    ev_a, _ = engine.synthesize_resolver_state("CE", payload_yesterday, {}, {}, {}, now)
    assert "3M+5M" not in ev_a["label"]
    assert ev_a["label"] == "RES OUT 5M"

    # Case B: Invalidated/reclaimed 3M (SUPPORT_BACK) + 5M Bearish (SUPPORT_GONE) -> NOT aligned!
    payload_invalidated = {
        "contract": {"security_id": "61647", "strike": 24200},
        "vob": {
            "horsepower": {
                "3m": {"status": "SUPPORT_BACK", "event_id": "EV_SB", "confirmed_candle": make_dt(10, 25, day=21).isoformat()},
                "5m": {"status": "SUPPORT_GONE", "event_id": "EV_SG", "confirmed_candle": make_dt(10, 30, day=21).isoformat()},
            }
        },
    }
    ev_b, _ = engine.synthesize_resolver_state("CE", payload_invalidated, {}, {}, {}, now)
    assert "3M+5M" not in ev_b["label"]

    # Case C: Valid current-session 3M + Valid current-session 5M -> ALIGNED!
    payload_aligned = {
        "contract": {"security_id": "61647", "strike": 24200},
        "vob": {
            "horsepower": {
                "3m": {"status": "SUPPORT_GONE", "event_id": "EV_SG_3M", "confirmed_candle": make_dt(10, 27, day=21).isoformat()},
                "5m": {"status": "SUPPORT_GONE", "event_id": "EV_SG_5M", "confirmed_candle": make_dt(10, 30, day=21).isoformat()},
            }
        },
    }
    ev_c, _ = engine.synthesize_resolver_state("CE", payload_aligned, {}, {}, {}, now)
    assert ev_c["label"] == "SUPPORT GONE 3M+5M"


def test_4_first_observation_is_not_an_extreme():
    engine = ResolverEngine()
    # 1. Empty OI baseline
    curr_oi = {"oi_delta": 50000.0, "oi_pct": 25.0, "price_delta": 10.0, "structure": "LONG BUILDUP"}
    diag_oi = engine.compute_oi_diagnostics([], curr_oi, make_dt(9, 20))
    assert diag_oi["oi_new_session_extreme"] is False
    assert diag_oi["oi_x"] is None

    # 2. Empty Flow baseline (first sample)
    engine.ingest_flow_snapshot({"revision": "R1", "source_timestamp": make_dt(9, 15, 1).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.85}}}, make_dt(9, 15, 1))
    diag_flow = engine.compute_flow_diagnostics(make_dt(9, 15, 1), make_dt(9, 15, 1))
    assert diag_flow["flow_new_session_extreme"] is False
    assert diag_flow["event_flow_x"] is None


def test_5_event_flow_vs_current_flow_separated():
    engine = ResolverEngine()
    engine.ingest_flow_snapshot({"revision": "R_BASE", "source_timestamp": make_dt(9, 59, 58).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.10}}}, make_dt(9, 59, 58))
    engine.ingest_flow_snapshot({"revision": "R_EV", "source_timestamp": make_dt(10, 0, 0).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.20}}}, make_dt(10, 0, 0))
    engine.ingest_flow_snapshot({"revision": "R_CURR", "source_timestamp": make_dt(10, 0, 1).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.40}}}, make_dt(10, 0, 1))

    diag = engine.compute_flow_diagnostics(make_dt(10, 0, 0), make_dt(10, 0, 1))
    assert diag["event_mlofi"] == 0.20
    assert diag["event_flow_timestamp"] == make_dt(10, 0, 0).isoformat()
    assert diag["current_mlofi"] == 0.40
    assert diag["current_flow_timestamp"] == make_dt(10, 0, 1).isoformat()


def test_6_confluence_state_intensity_flag():
    engine = ResolverEngine()
    contract = {
        "contract": {"security_id": "61647", "strike": 24200},
        "vob": {
            "horsepower": {
                "3m": {"status": "RESISTANCE_OUT", "event_id": "EV3M", "confirmed_candle": make_dt(10, 0).isoformat()},
                "5m": {"status": "RESISTANCE_OUT", "event_id": "EV5M", "confirmed_candle": make_dt(10, 0).isoformat()},
            }
        },
    }
    # 1. Aligned settled (Sign agreement, but no session extreme)
    oi_settled = {"oi_structure": "LONG BUILDUP", "oi_x": 1.2, "oi_new_session_extreme": False}
    flow_settled = {"event_mlofi": 0.25, "event_flow_x": 1.1, "flow_new_session_extreme": False}
    ev_settled, diag_settled = engine.synthesize_resolver_state("CE", contract, oi_settled, flow_settled, {}, make_dt(10, 0))
    assert ev_settled["confluence_state"] == "ALIGNED_SETTLED"
    assert ev_settled["variant"] == "mint"

    # 2. Full fresh (Sign agreement + fresh session extreme)
    oi_fresh = {"oi_structure": "LONG BUILDUP", "oi_x": 3.4, "oi_new_session_extreme": True}
    flow_fresh = {"event_mlofi": 0.85, "event_flow_x": 4.2, "flow_new_session_extreme": True}
    ev_fresh, diag_fresh = engine.synthesize_resolver_state("CE", contract, oi_fresh, flow_fresh, {}, make_dt(10, 0))
    assert ev_fresh["confluence_state"] == "FULL_FRESH"
    assert ev_fresh["variant"] == "mint"


def test_7_session_reset_order():
    engine = ResolverEngine()
    engine._session_id = "2026-08-20"
    engine.ingest_flow_snapshot({"revision": "OLD_REV", "source_timestamp": "2026-08-20T15:00:00+05:30", "diagnostics": {"book_pressure": {"mlofi": 0.50}}})
    assert len(engine._flow_series) == 1

    new_dt = make_dt(9, 15, 1, day=21)
    new_session_date = str(new_dt.date())
    if engine._session_id != new_session_date:
        engine.reset_session(new_session_date)

    engine.ingest_flow_snapshot({"revision": "NEW_REV_1", "source_timestamp": new_dt.isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.30}}}, new_dt)
    assert len(engine._flow_series) == 1
    assert engine._flow_series[0][4] == "NEW_REV_1"


def test_8_fifo_deduplication_capacity():
    engine = ResolverEngine()
    for i in range(100):
        t = make_dt(10, 0, 0) + timedelta(seconds=i)
        engine.ingest_flow_snapshot({"revision": f"R_{i}", "source_timestamp": t.isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.1 * (i % 5)}}}, t)
    assert len(engine._flow_series) == 100

    engine.ingest_flow_snapshot({"revision": "R_50", "source_timestamp": make_dt(10, 5).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.99}}})
    assert len(engine._flow_series) == 100


def test_9_ce_supportive_and_hostile_semantics():
    engine = ResolverEngine()
    now = make_dt(10, 30)
    contract = {"contract": {"security_id": "61647", "strike": 24200}, "vob": {"horsepower": {"3m": {"status": "RESISTANCE_OUT", "event_id": "EV1", "confirmed_candle": now.isoformat()}}}}
    # Supportive CE
    ev_sup, _ = engine.synthesize_resolver_state("CE", contract, {"oi_structure": "LONG BUILDUP"}, {"event_mlofi": 0.40}, {}, now)
    assert ev_sup["variant"] == "mint"
    assert ev_sup["semantic_direction"] == "BULLISH"

    # Hostile CE
    contract_hostile = {"contract": {"security_id": "61647", "strike": 24200}, "vob": {"horsepower": {"3m": {"status": "SUPPORT_GONE", "event_id": "EV2", "confirmed_candle": now.isoformat()}}}}
    ev_host, _ = engine.synthesize_resolver_state("CE", contract_hostile, {"oi_structure": "SHORT BUILDUP"}, {"event_mlofi": -0.40}, {}, now)
    assert ev_host["variant"] == "red"
    assert ev_host["semantic_direction"] == "BEARISH"


def test_10_pe_supportive_and_hostile_semantics():
    engine = ResolverEngine()
    now = make_dt(10, 30)
    contract = {"contract": {"security_id": "61703", "strike": 24300}, "vob": {"horsepower": {"3m": {"status": "RESISTANCE_OUT", "event_id": "EV_PE_1", "confirmed_candle": now.isoformat()}}}}
    # Supportive PE: PE VOB breaking resistance + NIFTY Futures SELL flow + PE Long Build
    ev_sup, _ = engine.synthesize_resolver_state("PE", contract, {"oi_structure": "LONG BUILDUP"}, {"event_mlofi": -0.40}, {}, now)
    assert ev_sup["variant"] == "mint"
    assert ev_sup["semantic_direction"] == "BULLISH"

    # Hostile PE: PE VOB losing support + NIFTY Futures BUY flow
    contract_hostile = {"contract": {"security_id": "61703", "strike": 24300}, "vob": {"horsepower": {"3m": {"status": "SUPPORT_GONE", "event_id": "EV_PE_2", "confirmed_candle": now.isoformat()}}}}
    ev_host, _ = engine.synthesize_resolver_state("PE", contract_hostile, {"oi_structure": "SHORT BUILDUP"}, {"event_mlofi": 0.40}, {}, now)
    assert ev_host["variant"] == "red"
    assert ev_host["semantic_direction"] == "BEARISH"


def test_11_held_state_and_pulse_governance():
    engine = ResolverEngine()
    contract = {"contract": {"security_id": "61647", "strike": 24200}, "vob": {"horsepower": {"3m": {"status": "SUPPORT_GONE", "event_id": "EV3M_SG", "confirmed_candle": make_dt(10, 0).isoformat()}}}}
    # Initial
    ev1, _ = engine.synthesize_resolver_state("CE", contract, {}, {}, {}, make_dt(10, 0))
    pulse_1 = ev1["pulse_key"]
    assert ev1["held_previous"] is False

    # Quiet market cycle
    ev2, _ = engine.synthesize_resolver_state("CE", contract, {}, {}, {}, make_dt(10, 1))
    assert ev2["label"] == "SUPPORT GONE 3M"
    assert ev2["held_previous"] is True
    assert ev2["pulse_key"] == pulse_1  # No pulse bump!


def test_12_current_flow_upgrades_held_structural_state():
    engine = ResolverEngine()
    contract = {"contract": {"security_id": "61647", "strike": 24200}, "vob": {"horsepower": {"3m": {"status": "SUPPORT_GONE", "event_id": "EV3M_SG", "confirmed_candle": make_dt(10, 0).isoformat()}}}}
    # Initial without shock
    ev1, _ = engine.synthesize_resolver_state("CE", contract, {}, {}, {}, make_dt(10, 0))
    assert ev1["label"] == "SUPPORT GONE 3M"

    # Later flow shock
    flow_shock = {"current_mlofi": -0.80, "current_flow_x": 3.8, "current_flow_timestamp": make_dt(10, 2).isoformat(), "flow_new_session_extreme": True}
    ev2, _ = engine.synthesize_resolver_state("CE", contract, {}, flow_shock, {}, make_dt(10, 2))
    assert ev2["label"] == "SUPPORT GONE 3M · FLOW 3.8X"
    assert ev2["source_event_time"] == make_dt(10, 2).isoformat()


def test_13_historical_event_flow_stale_but_current_flow_fresh():
    engine = ResolverEngine()
    now = make_dt(10, 30, 0)
    historical_event_time = make_dt(10, 0, 0)

    # Ingest baseline and recent flow samples relative to now
    engine.ingest_flow_snapshot({"revision": "R1", "source_timestamp": make_dt(10, 29, 58).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.15}}}, make_dt(10, 29, 58))
    engine.ingest_flow_snapshot({"revision": "R2", "source_timestamp": make_dt(10, 29, 59).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.20}}}, make_dt(10, 29, 59))
    recent_dt = datetime(2026, 8, 21, 10, 29, 59, 500000, tzinfo=IST)
    engine.ingest_flow_snapshot({"revision": "R3", "source_timestamp": recent_dt.isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.40}}}, recent_dt)

    diag = engine.compute_flow_diagnostics(historical_event_time, now)

    # Historical event flow must be strictly None (stale/unavailable)
    assert diag["event_mlofi"] is None
    assert diag["event_flow_x"] is None
    assert diag["event_flow_timestamp"] is None

    # Current flow must be populated and FRESH
    assert diag["current_mlofi"] == 0.40
    assert diag["current_flow_timestamp"] == recent_dt.isoformat()
    assert diag["flow_freshness_state"] == "FRESH"
    assert diag["current_flow_x"] == 2.3  # 0.40 / 0.175 median = 2.28 -> 2.3X
    assert diag["flow_new_session_extreme"] is True


def test_14_legitimate_zero_mlofi_handling():
    engine = ResolverEngine()
    now = make_dt(10, 30, 0)

    engine.ingest_flow_snapshot({"revision": "R1", "source_timestamp": make_dt(10, 29, 58).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.20}}}, make_dt(10, 29, 58))
    engine.ingest_flow_snapshot({"revision": "R2", "source_timestamp": make_dt(10, 29, 59).isoformat(), "diagnostics": {"book_pressure": {"mlofi": 0.00}}}, make_dt(10, 29, 59))

    diag = engine.compute_flow_diagnostics(None, now)

    assert diag["current_mlofi"] == 0.0
    assert isinstance(diag["current_mlofi"], float)
    assert diag["current_flow_x"] == 0.0
    assert diag["flow_freshness_state"] == "FRESH"


def test_15_exhaustive_oi_state_matrix_and_shocks():
    engine = ResolverEngine()
    now = make_dt(10, 0)
    contract = {"contract": {"security_id": "61670", "strike": 24200}}
    
    # 1. Four Pure Closed-5M OI states (without flow -> amber/NEUTRAL; with flow -> mint/red)
    oi_map = {
        "LONG BUILDUP": ("LONG BUILD OI", "amber", "NEUTRAL"),
        "SHORT BUILDUP": ("SHORT BUILD OI", "amber", "NEUTRAL"),
        "SHORT COVERING": ("SHORT COVER OI", "amber", "NEUTRAL"),
        "LONG UNWINDING": ("LONG UNWIND OI", "amber", "NEUTRAL"),
    }
    for struct, (exp_label, exp_var, exp_dir) in oi_map.items():
        engine.reset_session("2026-08-21")
        oi_diag = {"oi_structure": struct, "oi_x": None, "oi_new_session_extreme": False}
        ev, _ = engine.synthesize_resolver_state("CE", contract, oi_diag, {}, {}, now)
        assert ev["label"] == exp_label
        assert ev["variant"] == exp_var
        assert ev["semantic_direction"] == exp_dir

    # With supportive flow -> mint/BULLISH
    engine.reset_session("2026-08-21")
    ev_flow, _ = engine.synthesize_resolver_state(
        "CE", contract, {"oi_structure": "LONG BUILDUP"}, {"event_mlofi": 0.45}, {}, now
    )
    assert ev_flow["label"] == "LONG BUILD OI"
    assert ev_flow["variant"] == "mint"
    assert ev_flow["semantic_direction"] == "BULLISH"

    # 2. Four OI Session-Extreme Shocks
    shock_map = {
        "LONG BUILDUP": ("LONG BUILD · OI 3.5X", 3.5),
        "SHORT BUILDUP": ("SHORT BUILD · OI 2.8X", 2.8),
        "SHORT COVERING": ("SHORT COVER · OI 4.8X", 4.8),
        "LONG UNWINDING": ("LONG UNWIND · OI 2.1X", 2.1),
    }
    for struct, (exp_label, oix) in shock_map.items():
        engine.reset_session("2026-08-21")
        oi_diag = {"oi_structure": struct, "oi_x": oix, "oi_new_session_extreme": True}
        ev, _ = engine.synthesize_resolver_state("CE", contract, oi_diag, {}, {}, now)
        assert ev["label"] == exp_label


def test_16_exhaustive_vob_single_and_multi_tf_labels():
    now = make_dt(11, 0)

    # 1. Single TF labels
    for tf in ["1m", "3m", "5m"]:
        for status, exp_prefix in [
            ("SUPPORT_GONE", "SUPPORT GONE"),
            ("RESISTANCE_OUT", "RES OUT"),
            ("SUPPORT_BACK", "SUPPORT BACK"),
            ("BREAKOUT_LOST", "BREAKOUT LOST"),
        ]:
            engine = ResolverEngine()
            c = {
                "contract": {"security_id": f"61670_{tf}_{status}", "strike": 24200},
                "vob": {"horsepower": {tf: {"status": status, "event_id": f"EV_{tf}_{status}", "confirmed_candle": now.isoformat()}}},
            }
            ev, _ = engine.synthesize_resolver_state("PE", c, {}, {}, {}, now)
            assert ev["label"] == f"{exp_prefix} {tf.upper()}"

    # 2. Multi-TF Alignments
    multi_alignments = [
        ("SUPPORT_GONE", "SUPPORT_GONE", "SUPPORT GONE 3M+5M"),
        ("RESISTANCE_OUT", "RESISTANCE_OUT", "RES OUT 3M+5M"),
        ("SUPPORT_BACK", "SUPPORT_BACK", "SUPPORT BACK 3M+5M"),
        ("BREAKOUT_LOST", "BREAKOUT_LOST", "BREAKOUT LOST 3M+5M"),
    ]
    for st3, st5, exp_label in multi_alignments:
        engine = ResolverEngine()
        c = {
            "contract": {"security_id": f"61670_multi_{st3}_{st5}", "strike": 24200},
            "vob": {
                "horsepower": {
                    "3m": {"status": st3, "event_id": f"EV3_{st3}", "confirmed_candle": now.isoformat()},
                    "5m": {"status": st5, "event_id": f"EV5_{st5}", "confirmed_candle": now.isoformat()},
                }
            },
        }
        ev, _ = engine.synthesize_resolver_state("PE", c, {}, {}, {}, now)
        assert ev["label"] == exp_label

    # FULL VOB ALIGN
    c_full_bull = {
        "contract": {"security_id": "61670", "strike": 24200},
        "vob": {
            "horsepower": {
                "1m": {"status": "RESISTANCE_OUT", "event_id": "EV1", "confirmed_candle": now.isoformat()},
                "3m": {"status": "RESISTANCE_OUT", "event_id": "EV3", "confirmed_candle": now.isoformat()},
                "5m": {"status": "RESISTANCE_OUT", "event_id": "EV5", "confirmed_candle": now.isoformat()},
            }
        },
    }
    ev_full, _ = engine.synthesize_resolver_state("PE", c_full_bull, {}, {}, {}, now)
    assert ev_full["label"] == "FULL VOB ALIGN ↑"


def test_17_contract_rotation_memory_preservation():
    engine = ResolverEngine()
    t1 = make_dt(10, 55, 0)
    
    # 1. 24300 PE experiences meaningful shock event
    c_24300 = {"contract": {"security_id": "61640", "strike": 24300}}
    oi_diag = {"oi_structure": "SHORT COVERING", "oi_x": 4.8, "oi_new_session_extreme": True}
    ev1, _ = engine.synthesize_resolver_state("PE", c_24300, oi_diag, {}, {}, t1)
    assert ev1["label"] == "SHORT COVER · OI 4.8X"
    assert ev1["last_meaningful_event"]["label"] == "SHORT COVER · OI 4.8X"
    assert ev1["last_meaningful_event"]["is_previous_contract"] is False

    # 2. Spot moves, contract rotates to 24200 PE (security_id: 61670) at T2
    t2 = make_dt(11, 0, 0)
    c_24200 = {"contract": {"security_id": "61670", "strike": 24200}}
    # New contract has no active events yet
    ev2, _ = engine.synthesize_resolver_state("PE", c_24200, {}, {}, {}, t2)
    assert ev2["label"] == "ACTIVE RESOLVER · 24,200 PE"
    
    # Previous contract meaningful event is preserved with context badge!
    lm = ev2["last_meaningful_event"]
    assert lm is not None
    assert lm["label"] == "SHORT COVER · OI 4.8X"
    assert lm["security_id"] == "61640"
    assert lm["is_previous_contract"] is True
    assert lm["context_badge"] == "PREVIOUS CONTRACT (24,300 PE)"
    assert lm["age_seconds"] == 300.0


def test_18_held_state_strict_90s_ttl_lifecycle():
    engine = ResolverEngine()
    t0 = make_dt(10, 55, 0)
    contract = {"contract": {"security_id": "61703", "strike": 24300}}
    oi_diag = {"oi_structure": "SHORT COVERING", "oi_x": 4.8, "oi_new_session_extreme": True}
    
    # T0: Initial meaningful shock event generated
    ev0, _ = engine.synthesize_resolver_state("PE", contract, oi_diag, {}, {}, t0)
    assert ev0["label"] == "SHORT COVER · OI 4.8X"
    assert ev0["held_previous"] is False
    assert ev0["source_event_time"] == t0.isoformat()

    # T+89s: Within 90s TTL -> legitimately held
    t_89 = make_dt(10, 56, 29)
    ev_89, _ = engine.synthesize_resolver_state("PE", contract, oi_diag, {}, {}, t_89)
    assert ev_89["label"] == "SHORT COVER · OI 4.8X"
    assert ev_89["held_previous"] is True
    assert ev_89["source_event_time"] == t0.isoformat()

    # T+91s: Beyond 90s TTL -> held state expired, refreshes to current timestamp
    t_91 = make_dt(10, 56, 31)
    ev_91, _ = engine.synthesize_resolver_state("PE", contract, oi_diag, {}, {}, t_91)
    assert ev_91["label"] == "SHORT COVER · OI 4.8X"
    assert ev_91["held_previous"] is False
    assert ev_91["source_event_time"] == t_91.isoformat()

    # T+600s: 10 minutes later -> primary pill reflects fresh/fallback state, last meaningful retains shock
    t_600 = make_dt(11, 5, 0)
    oi_diag_quiet = {"oi_structure": "LONG BUILDUP", "oi_x": None, "oi_new_session_extreme": False}
    ev_600, _ = engine.synthesize_resolver_state("PE", contract, oi_diag_quiet, {}, {}, t_600)
    assert ev_600["label"] == "LONG BUILD OI"
    assert ev_600["held_previous"] is False
    assert ev_600["source_event_time"] == t_600.isoformat()
    assert ev_600["last_meaningful_event"]["label"] == "LONG BUILD OI"


def _vob_contract(status: str, confirmed_at, event_id: str = "EV1"):
    return {
        "contract": {"security_id": "61670", "strike": 24200},
        "vob": {
            "horsepower": {
                "1m": {
                    "status": status,
                    "event_id": event_id,
                    "confirmed_candle": confirmed_at.isoformat(),
                }
            }
        },
    }


def test_19_future_resistance_out_rejected_then_consumed_after_close():
    engine = ResolverEngine()
    confirmed_at = make_dt(12, 39, 0)
    contract = _vob_contract("RESISTANCE_OUT", confirmed_at)

    future, _ = engine.synthesize_resolver_state(
        "PE", contract, {}, {}, {}, make_dt(12, 38, 7)
    )
    assert future["label"] == "ACTIVE RESOLVER · 24,200 PE"

    eligible, _ = engine.synthesize_resolver_state(
        "PE", contract, {}, {}, {}, make_dt(12, 39, 10)
    )
    assert eligible["label"] == "RES OUT 1M"
    assert eligible["source_event_time"] == confirmed_at.isoformat()


def test_20_future_support_back_rejected_then_consumed_after_close():
    engine = ResolverEngine()
    confirmed_at = make_dt(13, 32, 0)
    contract = _vob_contract("SUPPORT_BACK", confirmed_at, "EV_SUPPORT_BACK")

    future, _ = engine.synthesize_resolver_state(
        "PE", contract, {}, {}, {}, make_dt(13, 31, 5)
    )
    assert future["label"] == "ACTIVE RESOLVER · 24,200 PE"

    eligible, _ = engine.synthesize_resolver_state(
        "PE", contract, {}, {}, {}, make_dt(13, 32, 3)
    )
    assert eligible["label"] == "SUPPORT BACK 1M"


def test_21_future_vob_rejected_while_valid_oi_still_synthesizes():
    engine = ResolverEngine()
    contract = _vob_contract("RESISTANCE_OUT", make_dt(12, 39, 0))
    oi_diag = {
        "oi_structure": "SHORT COVERING",
        "oi_x": 4.8,
        "oi_new_session_extreme": True,
        "oi_window_closed_at": "12:35",
    }

    event, _ = engine.synthesize_resolver_state(
        "PE", contract, oi_diag, {}, {}, make_dt(12, 38, 7)
    )
    assert event["label"] == "SHORT COVER · OI 4.8X"
    assert "RES OUT" not in event["label"]


def test_22_last_meaningful_timestamp_is_immutable_until_new_event_and_rotation():
    engine = ResolverEngine()
    t0 = make_dt(10, 55, 2)
    contract = {"contract": {"security_id": "61703", "strike": 24300}}
    same_window = {
        "oi_structure": "SHORT COVERING",
        "oi_x": 4.8,
        "oi_new_session_extreme": True,
        "oi_window_closed_at": "10:55",
    }

    first, _ = engine.synthesize_resolver_state("PE", contract, same_window, {}, {}, t0)
    repeated, _ = engine.synthesize_resolver_state("PE", contract, same_window, {}, {}, t0 + timedelta(seconds=60))
    ttl_expired, _ = engine.synthesize_resolver_state("PE", contract, same_window, {}, {}, t0 + timedelta(seconds=120))
    assert first["last_meaningful_event"]["event_timestamp"] == t0.isoformat()
    assert repeated["last_meaningful_event"]["event_timestamp"] == t0.isoformat()
    assert ttl_expired["last_meaningful_event"]["event_timestamp"] == t0.isoformat()

    new_window = {**same_window, "oi_x": 5.1, "oi_window_closed_at": "11:00"}
    new_time = t0 + timedelta(seconds=300)
    new_event, _ = engine.synthesize_resolver_state("PE", contract, new_window, {}, {}, new_time)
    assert new_event["last_meaningful_event"]["event_timestamp"] == new_time.isoformat()

    rotated = {"contract": {"security_id": "61670", "strike": 24200}}
    after_rotation, _ = engine.synthesize_resolver_state(
        "PE", rotated, {}, {}, {}, new_time + timedelta(seconds=120)
    )
    previous = after_rotation["last_meaningful_event"]
    assert previous["event_timestamp"] == new_time.isoformat()
    assert previous["age_seconds"] == 120.0
    assert previous["is_previous_contract"] is True



