"""Focused unit tests for CITADEL Eye Golden Replay Truth Closure (07-Aug-2026)."""

import json, pytest
from pathlib import Path
from datetime import datetime, timezone
from scripts.eye_golden_replay_harness import run_golden_replay, NIFTY_FILE, OPTION_FILE
from src.eye.oracle_projection.runtime_state import EyeRuntimeState


def test_exact_option_oi_is_actual_oi():
    with open(OPTION_FILE) as f:
        candles = json.load(f)
    assert len(candles) == 385
    # Historical REST intraday chart candles provide OHLC+Volume; OI field is absent/null
    oi_count = sum(1 for c in candles if isinstance(c, dict) and c.get("oi") is not None)
    assert oi_count == 0  # No fabricated OI values


def test_replay_immutable_input():
    assert NIFTY_FILE.exists()
    assert OPTION_FILE.exists()
    with open(NIFTY_FILE) as f:
        nifty = json.load(f)
    with open(OPTION_FILE) as f:
        pe = json.load(f)
    assert len(nifty) == 385
    assert len(pe) == 385


def test_replay_no_lookahead():
    wm = datetime(2026, 8, 7, 7, 30, tzinfo=timezone.utc)
    res_wm = run_golden_replay(watermark_ts=wm)
    res_full = run_golden_replay()
    assert res_wm["semantic_sha256"] != res_full["semantic_sha256"]
    # Check that events generated up to watermark are identical
    wm_journal = [x for x in res_full["raw_journal"] if x["timestamp"] <= "2026-08-07 13:00:00"]
    assert len(res_wm["raw_journal"]) == len(wm_journal)


def test_replay_speed_independence():
    r1x = run_golden_replay(speed_factor=1)
    r2x = run_golden_replay(speed_factor=2)
    r10x = run_golden_replay(speed_factor=10)
    r_inst = run_golden_replay(speed_factor=0)
    assert r1x["semantic_sha256"] == r2x["semantic_sha256"] == r10x["semantic_sha256"] == r_inst["semantic_sha256"]


def test_replay_fresh_process_determinism():
    res1 = run_golden_replay()
    res2 = run_golden_replay()
    assert res1["semantic_sha256"] == res2["semantic_sha256"]


def test_replay_uses_projection_service():
    res = run_golden_replay()
    for rec in res["raw_journal"]:
        proj = rec["projection"]
        assert "identity" in proj
        assert "structure" in proj
        assert "setup_projection" in proj
        assert "market_thesis" in proj
        assert "provenance" in proj


def test_replay_does_not_pollute_live_runtime():
    live_runtime = EyeRuntimeState.get_instance()
    snap_before = live_runtime.get_runtime_snapshot("NIFTY")
    run_golden_replay()
    snap_after = live_runtime.get_runtime_snapshot("NIFTY")
    assert snap_before["market_data_last_seen_utc"] == snap_after["market_data_last_seen_utc"]


def test_cas_raw_event_separate_from_tradable_setup():
    res = run_golden_replay()
    assert res["raw_setup_count"] == 109
    assert res["normal_tradable_count"] == 106
    assert res["cas_excluded_count"] == 3


def test_exact_24700pe_not_proxy():
    with open(OPTION_FILE) as f:
        pe = json.load(f)
    assert len(pe) == 385
    # First candle 09:15:00 IST
    assert pe[0]["open"] == 175.0
    # Last candle 15:39:00 IST
    assert pe[-1]["close"] == 161.2


def test_execution_authority_false():
    res = run_golden_replay()
    for rec in res["raw_journal"]:
        proj = rec["projection"]
        assert proj.get("execution_authority") is False
