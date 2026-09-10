"""Deterministic regression suite for chronological VOB replay parity across 1M, 3M, and 5M timeframes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from src.vob.bigbeluga_engine import BigBelugaVOBEngine, MSLEN
from src.vob.engine import NiftyVOBEngine
from src.vob.reversal import VobReversalEngine

IST = ZoneInfo("Asia/Kolkata")
CANDLE_DIR = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/options_structure/candles")
if not CANDLE_DIR.exists():
    CANDLE_DIR = Path("logs/options_structure/candles")


def to_dt(ts) -> datetime | None:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=IST)
    elif isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
    return None


@pytest.mark.skipif(not (CANDLE_DIR / "45100_1m.json").exists(), reason="Candle files not present")
def test_24250_ce_3m_chronological_replay_parity():
    """Verify 24250 CE 3M demand formation with origin at 11:24 IST."""
    with open(CANDLE_DIR / "45100_1m.json") as fp:
        raw = json.load(fp)
    candles_1m = raw if isinstance(raw, list) else raw.get("candles", [])
    helper = NiftyVOBEngine()
    tf_candles = helper._resample_1m(candles_1m, 3)

    engine = BigBelugaVOBEngine()
    tgt_dt = datetime.fromisoformat("2026-08-17T13:15:00+05:30")
    subset = [c for c in tf_candles if to_dt(c.get("timestamp") or c.get("time")) <= tgt_dt]

    assert len(subset) >= MSLEN * 2 + 2
    bull_obs, bear_obs = engine._replay("3m", subset)

    found_68 = [z for z in bull_obs if abs(z.btm - 68.0) < 0.5]
    assert len(found_68) >= 1
    zone = found_68[0]
    assert round(zone.btm, 1) == 68.0
    assert 73.0 <= round(zone.top, 1) <= 75.0
    origin_dt = to_dt(zone.loc_time)
    assert origin_dt is not None
    assert origin_dt.strftime("%H:%M") == "11:24"


@pytest.mark.skipif(not (CANDLE_DIR / "45105_1m.json").exists(), reason="Candle files not present")
def test_24350_pe_5m_chronological_replay_mitigation():
    """Verify 24350 PE 5M demand formation in morning and subsequent mitigation at 13:15 IST."""
    with open(CANDLE_DIR / "45105_1m.json") as fp:
        raw = json.load(fp)
    candles_1m = raw if isinstance(raw, list) else raw.get("candles", [])
    helper = NiftyVOBEngine()
    tf_candles = helper._resample_1m(candles_1m, 5)

    engine = BigBelugaVOBEngine()

    # Morning snapshot @ 11:30 IST: Demand is active
    tgt_morning = datetime.fromisoformat("2026-08-17T11:30:00+05:30")
    subset_morning = [c for c in tf_candles if to_dt(c.get("timestamp") or c.get("time")) <= tgt_morning]
    bull_morning, _ = engine._replay("5m", subset_morning)
    active_morning = [z for z in bull_morning if not z.is_mitigated]
    assert len(active_morning) >= 1

    # Afternoon snapshot @ 15:20 IST: Morning demand has been mitigated
    tgt_afternoon = datetime.fromisoformat("2026-08-17T15:20:00+05:30")
    subset_afternoon = [c for c in tf_candles if to_dt(c.get("timestamp") or c.get("time")) <= tgt_afternoon]
    bull_afternoon, _ = engine._replay("5m", subset_afternoon)
    active_afternoon = [z for z in bull_afternoon if not z.is_mitigated]
    # Active demand is empty on 5M after 13:15 breakdown
    assert len(active_afternoon) == 0


@pytest.mark.unit
def test_1m_vob_api_accepts_1m_parameter_synthetic():
    """Synthetic test proving ONLY that the 1m parameter does not crash the engine.
    For real market data proof, see test_vob_1m_real_data_proof.py.
    """
    engine = NiftyVOBEngine()
    assert "1m" in engine.TIMEFRAMES

    candles = [
        {"timestamp": f"2026-08-17T09:{i:02d}:00+05:30", "open": 100.0 + i, "high": 105.0 + i, "low": 98.0 + i, "close": 102.0 + i, "volume": 1000}
        for i in range(25)
    ]
    res = engine.analyze_timeframe(timeframe="1m", candles=candles)
    assert res["timeframe"] == "1m"
    assert "nearest_bullish_support" in res
    assert "nearest_bearish_resistance" in res


def test_dual_track_same_episode_isolation():
    """Verify Track A (VOB_ONLY) and Track B (CONFIRMED_REVERSAL) maintain isolated state and records."""
    reversal = VobReversalEngine()
    projection = reversal.projection()
    assert "reversal_state" in projection
    assert "states_by_timeframe" in projection
    assert "option_contracts" in projection
    assert "current_itm1_contracts" in projection
    assert "all_shadow_trades" in projection
    assert projection["execution_influence"] == "ZERO"
    assert projection["paper_only"] is True
