"""Focused parity tests for BigBeluga SMC Pine v5 VOB engine and custom Citadel lifecycle rules."""
import pytest
import json
import math
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from src.vob.engine import NiftyVOBEngine, VOBZone
from src.vob.bigbeluga_engine import (
    BigBelugaVOBEngine,
    MSState,
    OBZone,
    _apply_overlap,
    _find,
    _is_mitigated,
    compute_atr_series,
)

IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.unit


def test_canonical_path_ownership_and_warmup():
    """Verify CITADEL_STATE_ROOT is set correctly and that canonical log exists and has continuous history."""
    state_root = os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs")
    assert state_root == "/Users/ayushmudgal/Developer/CitadelOS/logs"

    vob_1m_path = Path(state_root) / "vob_1m_candles.json"
    assert vob_1m_path.exists()

    with open(vob_1m_path, "r") as f:
        data = json.load(f)
    candles = data.get("candles", [])
    assert len(candles) > 10000

    # Ensure earliest candle is well before July 7, 2026 and continues through July 21, 2026
    first_time = candles[0]["time"]
    first_dt = datetime.fromtimestamp(first_time, tz=IST)
    assert first_dt < datetime(2026, 7, 7, 0, 0, tzinfo=IST)

    last_time = candles[-1]["time"]
    last_dt = datetime.fromtimestamp(last_time, tz=IST)
    assert last_dt >= datetime(2026, 7, 21, 15, 0, tzinfo=IST)


def test_deterministic_replay_and_screenshot_parity():
    """Verify exact 15M and 1H nearest unbroken bearish VOB zones emerge on July 21, 2026."""
    state_root = "/Users/ayushmudgal/Developer/CitadelOS/logs"
    vob_1m_path = Path(state_root) / "vob_1m_candles.json"

    with open(vob_1m_path, "r") as f:
        data = json.load(f)
    candles_1m = data.get("candles", [])

    # Filter candles up to Tuesday, 21 July 2026 15:30 IST
    cutoff = datetime(2026, 7, 21, 15, 30, tzinfo=IST).timestamp()
    candles_filtered = [c for c in candles_1m if c["time"] <= cutoff]

    engine = NiftyVOBEngine()
    vob_data = engine.ingest_1m_candles(candles_filtered, current_nifty_price=24187.7)

    # 15M Bearish VOB: ~ 24,454–24,470 (nearest unbroken above spot)
    vob_15m = vob_data["timeframes"]["15m"]
    res_15m = vob_15m["nearest_bearish_resistance"]
    assert res_15m is not None
    print(f"15M Bearish VOB: {res_15m['zone_low']}–{res_15m['zone_high']}")
    assert 24450 <= res_15m["zone_low"] <= 24460
    assert 24465 <= res_15m["zone_high"] <= 24475

    # 1H Bearish VOB: ~ 24,498–24,530 (nearest unbroken above spot)
    vob_1h = vob_data["timeframes"]["1h"]
    res_1h = vob_1h["nearest_bearish_resistance"]
    assert res_1h is not None
    print(f"1H Bearish VOB: {res_1h['zone_low']}–{res_1h['zone_high']}")
    assert 24490 <= res_1h["zone_low"] <= 24505
    assert 24520 <= res_1h["zone_high"] <= 24535


def test_mitigated_zone_remains_visible_and_unbroken_until_own_tf_close():
    """Verify that touch or penetration marks TESTED, but only own-TF close beyond boundary breaks zone."""
    engine = NiftyVOBEngine()
    
    # Inject a 15M Bearish Resistance zone with top 24050, btm 24000
    z_initial = VOBZone(
        zone_id="TEST-15M-BEAR",
        symbol="NIFTY",
        timeframe="15m",
        side="BEARISH",
        role="RESISTANCE",
        zone_low=24000.0,
        zone_high=24050.0,
        origin_candle_time="2026-07-21T09:15:00+05:30",
        confirmation_candle_time="2026-07-21T09:15:00+05:30",
        origin_volume_formatted="10M",
        volume_ratio=0.5,
        displacement_strength=0.8,
        touch_count=0,
        first_tested_time=None,
        last_tested_time=None,
        distance_points=40.0,
        distance_percent=0.17,
        strength_score=50,
        status="ACTIVE",
        broken_at=None,
        calculated_at="2026-07-21T09:15:00+05:30",
        source_candle_timestamp="2026-07-21T09:15:00+05:30",
        freshness="FRESH"
    )
    engine._zones["15m"]["TEST-15M-BEAR"] = z_initial

    # 15M candles:
    # i=1: Wick beyond top=24050 (high=24055), but close inside (close=24040).
    # Must NOT break zone. Status must be TESTED.
    candles_15m = [
        {"open": 24000.0, "high": 24050.0, "low": 23950.0, "close": 24000.0, "volume": 1000.0, "timestamp": "2026-07-21T09:15:00+05:30", "closed": True},
        {"open": 24000.0, "high": 24055.0, "low": 23990.0, "close": 24040.0, "volume": 1000.0, "timestamp": "2026-07-21T09:30:00+05:30", "closed": True},
    ]

    res = engine.analyze_timeframe(timeframe="15m", candles=candles_15m, current_nifty_price=24010.0)
    nearest = res["nearest_bearish_resistance"]
    assert nearest is not None
    assert nearest["status"] == "TESTED"
    assert nearest["broken_at"] is None

    # i=2: Completed 15m candle closes above top=24050 (close=24055).
    # NOW zone becomes BROKEN.
    candles_15m.append(
        {"open": 24040.0, "high": 24060.0, "low": 24030.0, "close": 24055.0, "volume": 1000.0, "timestamp": "2026-07-21T09:45:00+05:30", "closed": True}
    )
    res_broken = engine.analyze_timeframe(timeframe="15m", candles=candles_15m, current_nifty_price=24010.0)
    recently_broken = res_broken["recently_broken"]
    assert len(recently_broken) >= 1
    assert recently_broken[0]["status"] == "BROKEN"
    assert recently_broken[0]["broken_at"] == "2026-07-21T09:45:00+05:30"


def test_mandatory_vob_terminology_and_formatting():
    """Verify forbidden terms (Bearish Support, Bullish Resistance) are absent and prices are rounded to 2 decimals."""
    engine = NiftyVOBEngine()
    candles_15m = [
        {"open": 24000.12345, "high": 24050.67891, "low": 23950.11111, "close": 24000.22222, "volume": 1000.0, "timestamp": "2026-07-21T09:15:00+05:30", "closed": True},
        {"open": 23950.0, "high": 23960.0, "low": 23900.0, "close": 23910.0, "volume": 5000.0, "timestamp": "2026-07-21T09:30:00+05:30", "closed": True},
    ]

    res = engine.analyze_timeframe(timeframe="15m", candles=candles_15m, current_nifty_price=23950.0)
    res_str = json.dumps(res)

    assert "Bearish Support" not in res_str
    assert "Bullish Resistance" not in res_str

    nearest_bear = res["nearest_bearish_resistance"]
    if nearest_bear:
        assert nearest_bear["role"] == "RESISTANCE"
        assert nearest_bear["side"] == "BEARISH"
        # Verify decimal precision capped at 2
        assert len(str(nearest_bear["zone_low"]).split(".")[-1]) <= 2
        assert len(str(nearest_bear["zone_high"]).split(".")[-1]) <= 2


def test_authoritative_pine_primitives_are_not_approximated():
    candles = [
        {"open": 10.0, "high": 12.0, "low": 8.0, "close": 11.0},
        {"open": 11.0, "high": 12.0, "low": 8.0, "close": 9.0},
    ]
    state = MSState(loc=0, xloc=0)

    # Pine's max == high[i] / min == low[i] assignment selects the older
    # equal extreme, and the span==1 branch includes both bars.
    assert _find(state, candles, 1, use_max=True, sweep=False, useob=False) == 1
    assert _find(state, candles, 1, use_max=False, sweep=False, useob=False) == 1

    # ta.atr(200) remains na until its complete seed window.
    short_atr = compute_atr_series(candles * 99, 200)
    assert all(math.isnan(value) for value in short_atr)
    seeded_atr = compute_atr_series(candles * 100, 200)
    assert math.isnan(seeded_atr[198])
    assert math.isfinite(seeded_atr[199])

    bullish = OBZone(True, 105.0, 100.0, 102.5, 0, 0.0, 1.0, 1)
    bearish = OBZone(False, 110.0, 105.0, 107.5, 0, 0.0, 1.0, -1)
    # obmiti="Close" is Pine candle-body mitigation, not close-only.
    assert _is_mitigated(bullish, {"open": 99.0, "close": 101.0}) is True
    assert _is_mitigated(bearish, {"open": 111.0, "close": 109.0}) is True

    older = OBZone(True, 104.0, 99.0, 101.5, 0, 0.0, 1.0, 1)
    recent = OBZone(True, 105.0, 100.0, 102.5, 1, 1.0, 1.0, 1)
    active = [recent, older]
    _apply_overlap(active, [])
    assert active == [recent]


def test_authoritative_pine_phase_one_creates_the_correct_ob_side():
    candles = [
        {"open": 5.0, "high": 10.0, "low": 0.0, "close": 5.0, "volume": 1.0, "time": 1.0, "closed": True},
        {"open": 5.0, "high": 12.0, "low": 4.0, "close": 11.0, "volume": 1.0, "time": 2.0, "closed": True},
    ]
    bulls, bears = BigBelugaVOBEngine()._replay("5m", candles)
    assert not bulls
    assert len(bears) == 1
    assert bears[0].bull is False


def test_july_22_completed_bucket_pine_replay_levels():
    """Lock the raw-candle replay that exposed the 15M parity defect."""
    state_root = Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs"))
    candles = json.loads((state_root / "vob_1m_candles.json").read_text(encoding="utf-8"))["candles"]
    cutoff_1m = datetime(2026, 7, 22, 14, 8, tzinfo=IST).timestamp()
    source = [c for c in candles if float(c["time"]) <= cutoff_1m]
    engine = NiftyVOBEngine()
    expected = {
        "3m": ((23937.65, 23953.15), (24041.35, 24050.65), "2026-07-22T14:06:00+05:30"),
        "5m": ((23925.70, 23949.04), (24038.20, 24049.00), "2026-07-22T14:00:00+05:30"),
        "15m": ((23925.70, 23965.71), (24248.25, 24266.10), "2026-07-22T13:45:00+05:30"),
        "1h": ((23829.20, 23972.45), (24499.30, 24530.90), "2026-07-22T12:15:00+05:30"),
    }
    interval = {"3m": 3, "5m": 5, "15m": 15, "1h": 60}

    for timeframe, (support, resistance, evaluated_through) in expected.items():
        buckets = engine._resample_1m(source, interval[timeframe])
        buckets = [row for row in buckets if row["timestamp"] <= evaluated_through]
        result = engine.analyze_timeframe(
            timeframe=timeframe,
            candles=buckets,
            current_nifty_price=23979.65,
            now=datetime(2026, 7, 22, 14, 9, tzinfo=IST),
        )
        actual_support = result["nearest_bullish_support"]
        actual_resistance = result["nearest_bearish_resistance"]
        assert (actual_support["zone_low"], actual_support["zone_high"]) == support
        assert (actual_resistance["zone_low"], actual_resistance["zone_high"]) == resistance
        assert buckets[-1]["timestamp"] == evaluated_through
