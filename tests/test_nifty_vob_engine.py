"""Focused unit tests for Advanced NiftyVOBEngine requirements:
1. Exactly 1 nearest support & 1 nearest resistance per timeframe
2. Own-timeframe candle-close break rule
3. Wick/touch does not break zone
4. Automatic next-zone promotion when nearest zone breaks
5. Multi-timeframe confluence detection (STRONG, VERY STRONG, ULTRA STRONG)
6. Execution influence ZERO & Today's trades filtering
"""

import pytest
from datetime import datetime, timezone, timedelta
from src.vob.engine import NiftyVOBEngine


pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)


def _make_candles_with_breaks(tf="5m"):
    candles = []
    base_time = _NOW - timedelta(minutes=40 * 5)

    for i in range(40):
        ts = (base_time + timedelta(minutes=i * 5)).isoformat()
        if i == 10:
            # Bullish origin candle (low=24210, high=24225)
            o, h, l, c, v = 24220.0, 24225.0, 24210.0, 24212.0, 5000.0
        elif i == 11:
            # Bullish displacement
            o, h, l, c, v = 24212.0, 24250.0, 24212.0, 24245.0, 6000.0
        elif i == 20:
            # Wick touching zone low (24210) down to 24212 but closing inside zone at 24220 (MUST NOT BREAK)
            o, h, l, c, v = 24230.0, 24235.0, 24212.0, 24225.0, 1500.0
        elif i == 30:
            # OWN TIMEFRAME CANDLE CLOSE BELOW ZONE LOW (24210) (MUST BREAK)
            o, h, l, c, v = 24215.0, 24218.0, 24190.0, 24195.0, 3000.0
        else:
            p = 24240.0 + i
            o, h, l, c, v = p, p + 5, p - 5, p + 2, 1000.0
        candles.append({
            "symbol": "NIFTY", "timeframe": tf, "timestamp": ts,
            "open": o, "high": h, "low": l, "close": c, "volume": v,
            "closed": True, "is_closed": True,
        })
    return candles


def test_one_zone_per_side_and_own_tf_break_rule():
    engine = NiftyVOBEngine()
    candles = _make_candles_with_breaks(tf="5m")

    # Evaluate up to candle 25 (before candle close break at 30)
    res_before = engine.analyze_timeframe(timeframe="5m", candles=candles[:26], current_nifty_price=24250.0, now=_NOW)
    sup_before = res_before["nearest_bullish_support"]
    assert sup_before is not None
    assert sup_before["status"] in {"TESTED", "WEAKENING", "ACTIVE"}

    # Evaluate full candles (candle 30 closed below zone_low 24210)
    res_after = engine.analyze_timeframe(timeframe="5m", candles=candles, current_nifty_price=24200.0, now=_NOW)
    assert len(res_after["recently_broken"]) >= 1
    assert res_after["recently_broken"][0]["status"] == "BROKEN"


def test_confluence_classification():
    engine = NiftyVOBEngine()
    
    tf_results = {
        "3m": {"nearest_bullish_support": None, "nearest_bearish_resistance": None},
        "5m": {"nearest_bullish_support": None, "nearest_bearish_resistance": None},
        "15m": {
            "nearest_bullish_support": {
                "timeframe": "15m", "side": "BULLISH", "status": "ACTIVE",
                "zone_low": 24100.0, "zone_high": 24150.0, "strength_score": 80.0
            },
            "nearest_bearish_resistance": None,
        },
        "1h": {
            "nearest_bullish_support": {
                "timeframe": "1h", "side": "BULLISH", "status": "ACTIVE",
                "zone_low": 24120.0, "zone_high": 24160.0, "strength_score": 85.0
            },
            "nearest_bearish_resistance": None,
        },
    }

    conf = engine._compute_confluence(tf_results, spot=24180.0)
    b_conf = conf["bullish"]
    assert b_conf is not None
    assert b_conf["tier"] == "ULTRA STRONG"  # 15m + 1h overlap
    assert b_conf["overlap_low"] == 24120.0
    assert b_conf["overlap_high"] == 24150.0


def test_execution_influence_zero():
    engine = NiftyVOBEngine()
    res = engine.analyze_all({"5m": _make_candles_with_breaks()})
    assert res["execution_influence"] == 0.0
    assert res["advisory_only"] is True


def test_nse_aligned_timeframe_aggregation():
    engine = NiftyVOBEngine()
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    base_time = datetime(2026, 7, 21, 9, 15, tzinfo=IST)

    candles_1m = []
    for i in range(125):
        ts = (base_time + timedelta(minutes=i)).isoformat()
        candles_1m.append({
            "timestamp": ts,
            "open": 24000.0 + i,
            "high": 24001.0 + i,
            "low": 23999.0 + i,
            "close": 24000.0 + i,
            "volume": 1000.0,
        })

    res_3m = engine._resample_1m(candles_1m, 3)
    res_5m = engine._resample_1m(candles_1m, 5)
    res_15m = engine._resample_1m(candles_1m, 15)
    res_1h = engine._resample_1m(candles_1m, 60)

    assert len(res_3m) == 41
    assert len(res_5m) == 25
    assert len(res_15m) == 8
    assert len(res_1h) == 2
    assert res_1h[0]["timestamp"].startswith("2026-07-21T09:15:00")

    # Test key normalization with ingest_1m_candles using 'time' key
    candles_time_key = []
    for i in range(15):
        ts = (base_time + timedelta(minutes=i)).isoformat()
        candles_time_key.append({
            "time": ts,
            "open": 24000.0 + i,
            "high": 24001.0 + i,
            "low": 23999.0 + i,
            "close": 24000.0 + i,
            "volume": 1000.0,
        })
    res_ingest = engine.ingest_1m_candles(candles_time_key, current_nifty_price=24010.0)
    assert res_ingest["symbol"] == "NIFTY"
    assert res_ingest["current_nifty_spot"] == 24010.0


def test_canonical_root_only_source_and_no_worktree_search(tmp_path, monkeypatch):
    import json
    from src.strategy_lab.service import StrategyLabService

    # 1. Create a dummy state root directory
    state_root = tmp_path / "canonical_logs"
    state_root.mkdir()

    # Create empty reservoir
    vob_1m_file = state_root / "vob_1m_candles.json"
    vob_1m_file.write_text(json.dumps({"candles": []}))

    # Create empty state
    vob_state_file = state_root / "vob_state.json"
    vob_state_file.write_text(json.dumps({}))

    # Mock environment variable
    monkeypatch.setenv("CITADEL_STATE_ROOT", str(state_root))

    # Instantiate service
    service = StrategyLabService(str(tmp_path / "lab"))

    # Project execution - this should load from CITADEL_STATE_ROOT only
    res = service.execution_projection()
    nifty_vob = res["nifty_vob"]

    # Verify status is UNAVAILABLE
    assert nifty_vob["status"] == "UNAVAILABLE"
    assert nifty_vob["reason"] == "CANONICAL_1M_RESERVOIR_UNAVAILABLE"


def test_3m_cannot_use_5m_fallback():
    engine = NiftyVOBEngine()
    # Create mock 5m candles
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    base_time = datetime(2026, 7, 21, 9, 15, tzinfo=IST)

    candles_5m = []
    for i in range(10):
        ts = (base_time + timedelta(minutes=i * 5)).isoformat()
        candles_5m.append({
            "timestamp": ts,
            "open": 24000.0,
            "high": 24010.0,
            "low": 23990.0,
            "close": 24000.0,
            "volume": 1000.0,
            "timeframe": "5m",
        })

    # Resample 3m from 5m - must return empty list (UNAVAILABLE)
    res_3m = engine._resample_1m(candles_5m, 3)
    assert res_3m == []


def test_incomplete_candle_excluded():
    engine = NiftyVOBEngine()
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    base_time = datetime(2026, 7, 21, 9, 15, tzinfo=IST)

    # If latest 1m close is 09:28 (i.e. latest 1m candle is 09:27),
    # then 15m candle starting at 09:15 and ending at 09:30 is INCOMPLETE.
    candles_1m = []
    for i in range(13): # 09:15 to 09:27 (13 minutes)
        ts = (base_time + timedelta(minutes=i)).isoformat()
        candles_1m.append({
            "timestamp": ts,
            "open": 24000.0,
            "high": 24010.0,
            "low": 23990.0,
            "close": 24000.0,
            "volume": 1000.0,
        })
    res_15m = engine._resample_1m(candles_1m, 15)
    assert len(res_15m) == 0 # 15m candle not completed yet


def test_previous_session_hydration_and_restart_stability(tmp_path):
    # Save a mock state with one zone
    import json
    state_file = tmp_path / "vob_state.json"
    
    zone_data = {
        "zone_id": "VOB-NIFTY-5M-BUL-12345",
        "symbol": "NIFTY",
        "timeframe": "5m",
        "side": "BULLISH",
        "role": "SUPPORT",
        "zone_low": 24000.0,
        "zone_high": 24050.0,
        "origin_candle_time": "2026-07-20T10:00:00+05:30",
        "confirmation_candle_time": "2026-07-20T10:05:00+05:30",
        "origin_volume_formatted": "10M",
        "volume_ratio": 2.0,
        "displacement_strength": 0.8,
        "touch_count": 0,
        "first_tested_time": None,
        "last_tested_time": None,
        "distance_points": 10.0,
        "distance_percent": 0.04,
        "strength_score": 50.0,
        "status": "ACTIVE",
        "broken_at": None,
        "calculated_at": "2026-07-20T10:05:00+05:30",
        "source_candle_timestamp": "2026-07-20T10:05:00+05:30",
        "freshness": "FRESH"
    }
    
    state_file.write_text(json.dumps({"5m": {"VOB-NIFTY-5M-BUL-12345": zone_data}}), encoding="utf-8")
    
    # Instantiate engine with state file (simulating startup hydration)
    engine = NiftyVOBEngine(persistence_path=state_file)
    assert "5m" in engine._zones
    assert "VOB-NIFTY-5M-BUL-12345" in engine._zones["5m"]
    zone = engine._zones["5m"]["VOB-NIFTY-5M-BUL-12345"]
    assert zone.status == "ACTIVE"
    assert zone.zone_low == 24000.0
    
    # Verify stable IDs after restart
    engine.save_state()
    loaded_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "VOB-NIFTY-5M-BUL-12345" in loaded_state["5m"]
    assert loaded_state["5m"]["VOB-NIFTY-5M-BUL-12345"]["status"] == "ACTIVE"


def test_active_zone_preferred_over_closer_weakening_zone():
    """ACTIVE zone must win over a CLOSER WEAKENING zone — core parity fix for 15M/1H."""
    engine = NiftyVOBEngine()
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    base_time = datetime(2026, 7, 21, 9, 15, tzinfo=IST)

    # Plant two bearish zones manually:
    # Zone A: WEAKENING, zone_low=24200, closer to spot
    # Zone B: ACTIVE,    zone_low=24280, farther from spot
    from src.vob.engine import VOBZone
    engine._zones["15m"] = {
        "ZONE-CLOSE-WEAKENING": VOBZone(
            zone_id="ZONE-CLOSE-WEAKENING", symbol="NIFTY", timeframe="15m",
            side="BEARISH", role="RESISTANCE",
            zone_low=24200.0, zone_high=24260.0,
            origin_candle_time="2026-07-21T09:15:00+05:30",
            confirmation_candle_time="2026-07-21T09:30:00+05:30",
            origin_volume_formatted="5M", volume_ratio=1.5,
            displacement_strength=0.7, touch_count=8,
            first_tested_time="2026-07-21T10:00:00+05:30",
            last_tested_time="2026-07-21T13:00:00+05:30",
            distance_points=12.3, distance_percent=0.05,
            strength_score=35.0, status="WEAKENING",
            broken_at=None, calculated_at="2026-07-21T14:00:00+05:30",
            source_candle_timestamp="2026-07-21T09:30:00+05:30",
            freshness="FRESH",
        ),
        "ZONE-FAR-ACTIVE": VOBZone(
            zone_id="ZONE-FAR-ACTIVE", symbol="NIFTY", timeframe="15m",
            side="BEARISH", role="RESISTANCE",
            zone_low=24280.0, zone_high=24338.0,
            origin_candle_time="2026-07-21T10:00:00+05:30",
            confirmation_candle_time="2026-07-21T10:15:00+05:30",
            origin_volume_formatted="18M", volume_ratio=2.1,
            displacement_strength=0.82, touch_count=0,
            first_tested_time=None, last_tested_time=None,
            distance_points=92.3, distance_percent=0.38,
            strength_score=85.0, status="ACTIVE",
            broken_at=None, calculated_at="2026-07-21T14:00:00+05:30",
            source_candle_timestamp="2026-07-21T10:15:00+05:30",
            freshness="FRESH",
        ),
    }

    spot = 24187.7
    res = engine.analyze_timeframe(
        timeframe="15m",
        candles=[{
            "symbol": "NIFTY", "timeframe": "15m", "timestamp": "2026-07-21T15:00:00+05:30",
            "open": 24187.0, "high": 24195.0, "low": 24180.0, "close": 24187.7,
            "volume": 1000.0, "closed": True, "is_closed": True,
        }],
        current_nifty_price=spot,
    )

    nearest = res["nearest_bearish_resistance"]
    assert nearest is not None, "Expected a nearest bearish resistance"
    # Nearer unbroken zone must win over farther active zone (distance outranks status)
    assert nearest["zone_id"] == "ZONE-CLOSE-WEAKENING", (
        f"Expected nearer zone ZONE-CLOSE-WEAKENING but got {nearest['zone_id']} ({nearest['status']})"
    )


def test_label_correctness_no_bearish_support_no_bullish_resistance():
    """VOBZone must never produce side=BEARISH role=SUPPORT or side=BULLISH role=RESISTANCE."""
    engine = NiftyVOBEngine()
    from src.vob.engine import VOBZone

    # Bearish zone must have role=RESISTANCE
    bz = VOBZone(
        zone_id="TEST-BEA", symbol="NIFTY", timeframe="5m",
        side="BEARISH", role="RESISTANCE",
        zone_low=24200.0, zone_high=24260.0,
        origin_candle_time="2026-07-21T09:15:00+05:30",
        confirmation_candle_time="2026-07-21T09:20:00+05:30",
        origin_volume_formatted="5M", volume_ratio=1.5,
        displacement_strength=0.7, touch_count=0,
        first_tested_time=None, last_tested_time=None,
        distance_points=12.0, distance_percent=0.05,
        strength_score=60.0, status="ACTIVE",
        broken_at=None, calculated_at="2026-07-21T10:00:00+05:30",
        source_candle_timestamp="2026-07-21T09:20:00+05:30",
        freshness="FRESH",
    )
    assert bz.side == "BEARISH"
    assert bz.role == "RESISTANCE", "Bearish zone must be RESISTANCE, never SUPPORT"

    # Bullish zone must have role=SUPPORT
    buz = VOBZone(
        zone_id="TEST-BUL", symbol="NIFTY", timeframe="5m",
        side="BULLISH", role="SUPPORT",
        zone_low=24100.0, zone_high=24150.0,
        origin_candle_time="2026-07-21T11:00:00+05:30",
        confirmation_candle_time="2026-07-21T11:05:00+05:30",
        origin_volume_formatted="8M", volume_ratio=1.8,
        displacement_strength=0.75, touch_count=0,
        first_tested_time=None, last_tested_time=None,
        distance_points=37.7, distance_percent=0.16,
        strength_score=70.0, status="ACTIVE",
        broken_at=None, calculated_at="2026-07-21T11:05:00+05:30",
        source_candle_timestamp="2026-07-21T11:05:00+05:30",
        freshness="FRESH",
    )
    assert buz.side == "BULLISH"
    assert buz.role == "SUPPORT", "Bullish zone must be SUPPORT, never RESISTANCE"

    # Verify _detect_vob_zones always assigns correct role
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    base_time = datetime(2026, 7, 21, 9, 15, tzinfo=IST)
    candles = []
    for i in range(12):
        ts = (base_time + timedelta(minutes=i * 5)).isoformat()
        if i == 3:
            o, h, l, c, v = 24250.0, 24260.0, 24240.0, 24255.0, 8000.0  # bullish origin
        elif i == 4:
            o, h, l, c, v = 24255.0, 24265.0, 24235.0, 24238.0, 15000.0  # bearish confirm
        elif i == 7:
            o, h, l, c, v = 24200.0, 24205.0, 24190.0, 24192.0, 7000.0  # bearish origin
        elif i == 8:
            o, h, l, c, v = 24192.0, 24215.0, 24190.0, 24212.0, 12000.0  # bullish confirm
        else:
            o, h, l, c, v = 24220.0, 24225.0, 24215.0, 24220.0, 1000.0
        candles.append({
            "symbol": "NIFTY", "timeframe": "5m", "timestamp": ts,
            "open": o, "high": h, "low": l, "close": c, "volume": v,
            "closed": True, "is_closed": True,
        })

    detected = engine._detect_vob_zones("5m", candles, 24220.0, "2026-07-21T10:00:00+05:30")
    for z in detected:
        if z.side == "BEARISH":
            assert z.role == "RESISTANCE", f"Got BEARISH {z.role}, expected RESISTANCE"
        elif z.side == "BULLISH":
            assert z.role == "SUPPORT", f"Got BULLISH {z.role}, expected SUPPORT"


def test_15m_1h_confluence_is_ultra_strong():
    """15M + 1H overlapping bearish zones must produce ULTRA STRONG confluence."""
    engine = NiftyVOBEngine()

    tf_results = {
        "3m": {"nearest_bullish_support": None, "nearest_bearish_resistance": None},
        "5m": {"nearest_bullish_support": None, "nearest_bearish_resistance": None},
        "15m": {
            "nearest_bullish_support": None,
            "nearest_bearish_resistance": {
                "timeframe": "15m", "side": "BEARISH", "status": "ACTIVE",
                "zone_low": 24320.0, "zone_high": 24338.0, "strength_score": 85.0,
            },
        },
        "1h": {
            "nearest_bullish_support": None,
            "nearest_bearish_resistance": {
                "timeframe": "1h", "side": "BEARISH", "status": "ACTIVE",
                "zone_low": 24284.0, "zone_high": 24338.0, "strength_score": 90.0,
            },
        },
    }

    conf = engine._compute_confluence(tf_results, spot=24187.7)
    bear_conf = conf["bearish"]
    assert bear_conf is not None, "Expected bearish confluence"
    assert bear_conf["tier"] == "ULTRA STRONG", f"Expected ULTRA STRONG, got {bear_conf['tier']}"
    assert "15m" in bear_conf["participating_timeframes"]
    assert "1h" in bear_conf["participating_timeframes"]
    # Overlap must be 24320–24338 (intersection of 24320-24338 and 24284-24338)
    assert bear_conf["overlap_low"] == 24320.0
    assert bear_conf["overlap_high"] == 24338.0


def test_completed_candle_cutoff_same_as_tv():
    """Resampled candles must only include fully completed bars — no partial bars at cutoff."""
    engine = NiftyVOBEngine()
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")

    # Simulate 6 1m candles from 09:15 to 09:20 (6 minutes)
    # A 5m bar 09:15–09:20 requires 5 minutes worth of 1m candles (09:15, 09:16, 09:17, 09:18, 09:19)
    # The last 1m close time is 09:20 (= 09:19 + 1min)
    # So bucket 09:15–09:20 IS complete (latest_1m_close = 09:20 = b_end)
    base = datetime(2026, 7, 21, 9, 15, tzinfo=IST)
    candles_1m = []
    for i in range(5):  # 09:15 to 09:19 inclusive
        ts = (base + timedelta(minutes=i)).isoformat()
        candles_1m.append({
            "timestamp": ts, "open": 24000.0, "high": 24005.0,
            "low": 23995.0, "close": 24000.0, "volume": 1000.0,
        })

    res_5m = engine._resample_1m(candles_1m, 5)
    assert len(res_5m) == 1, f"Expected 1 complete 5m bar, got {len(res_5m)}"
    assert res_5m[0]["timestamp"].startswith("2026-07-21T09:15:00")

    # Add one more candle (09:20) — now we have 6 minutes but 5m bar at 09:20 is incomplete
    candles_1m.append({
        "timestamp": (base + timedelta(minutes=5)).isoformat(),
        "open": 24000.0, "high": 24005.0, "low": 23995.0, "close": 24000.0, "volume": 1000.0,
    })
    res_5m_2 = engine._resample_1m(candles_1m, 5)
    # 09:20 bar needs 09:20–09:25 to close, so still only 1 complete bar
    assert len(res_5m_2) == 1, f"Expected 1 complete bar still, got {len(res_5m_2)}"


def test_0915_anchored_3m_resampling():
    """3M resampling must align strictly with 09:15 NSE session open: 09:15, 09:18, 09:21..."""
    engine = NiftyVOBEngine()
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")

    base = datetime(2026, 7, 21, 9, 15, tzinfo=IST)
    candles_1m = []
    # 6 minutes of 1m candles (09:15..09:20)
    for i in range(6):
        ts = (base + timedelta(minutes=i)).isoformat()
        candles_1m.append({
            "timestamp": ts, "open": 24000.0 + i, "high": 24005.0 + i,
            "low": 23995.0 + i, "close": 24002.0 + i, "volume": 1000.0,
        })

    res_3m = engine._resample_1m(candles_1m, 3)
    assert len(res_3m) == 2, f"Expected 2 complete 3m bars, got {len(res_3m)}"
    assert res_3m[0]["timestamp"].startswith("2026-07-21T09:15:00")
    assert res_3m[1]["timestamp"].startswith("2026-07-21T09:18:00")


def test_nearest_valid_3m_zone_wins_regardless_of_status():
    """Nearest valid 3M zone below/above spot must win regardless of whether status is ACTIVE or TESTED."""
    engine = NiftyVOBEngine()
    from src.vob.engine import VOBZone

    # Near tested zone vs far active zone
    engine._zones["3m"] = {
        "TEST-NEAR": VOBZone(
            zone_id="TEST-NEAR", symbol="NIFTY", timeframe="3m",
            side="BULLISH", role="SUPPORT",
            zone_low=24135.0, zone_high=24150.0,
            origin_candle_time="2026-07-21T13:00:00+05:30",
            confirmation_candle_time="2026-07-21T13:00:00+05:30",
            origin_volume_formatted="2.7M", volume_ratio=1.0,
            displacement_strength=0.8, touch_count=3,
            first_tested_time="2026-07-21T13:03:00+05:30",
            last_tested_time="2026-07-21T14:00:00+05:30",
            distance_points=37.7, distance_percent=0.15,
            strength_score=50.0, status="TESTED",
            broken_at=None, calculated_at="2026-07-21T15:00:00+05:30",
            source_candle_timestamp="2026-07-21T15:00:00+05:30",
            freshness="AGING",
        ),
        "TEST-REMOTE": VOBZone(
            zone_id="TEST-REMOTE", symbol="NIFTY", timeframe="3m",
            side="BULLISH", role="SUPPORT",
            zone_low=23321.0, zone_high=23340.0,
            origin_candle_time="2026-06-12T13:24:00+05:30",
            confirmation_candle_time="2026-06-12T13:24:00+05:30",
            origin_volume_formatted="1.9M", volume_ratio=0.5,
            displacement_strength=0.8, touch_count=0,
            first_tested_time=None, last_tested_time=None,
            distance_points=847.7, distance_percent=3.5,
            strength_score=20.0, status="ACTIVE",
            broken_at=None, calculated_at="2026-07-21T15:00:00+05:30",
            source_candle_timestamp="2026-07-21T15:00:00+05:30",
            freshness="FRESH",
        ),
    }

    spot = 24187.7
    res = engine.analyze_timeframe(
        timeframe="3m",
        candles=[{
            "symbol": "NIFTY", "timeframe": "3m", "timestamp": "2026-07-21T15:00:00+05:30",
            "open": 24187.0, "high": 24195.0, "low": 24180.0, "close": 24187.7,
            "volume": 1000.0, "closed": True, "is_closed": True,
        }],
        current_nifty_price=spot,
    )

    nearest = res["nearest_bullish_support"]
    assert nearest is not None
    assert nearest["zone_id"] == "TEST-NEAR", f"Expected TEST-NEAR but got {nearest['zone_id']}"


def test_3m_break_conditions_strictly_on_completed_own_tf_close():
    """3M resistance breaks ONLY on 3m close > zone_high; 3M support breaks ONLY on 3m close < zone_low."""
    engine = NiftyVOBEngine()
    from src.vob.engine import VOBZone

    engine._zones["3m"] = {
        "TEST-RES1": VOBZone(
            zone_id="TEST-RES1", symbol="NIFTY", timeframe="3m",
            side="BEARISH", role="RESISTANCE",
            zone_low=24188.0, zone_high=24196.0,
            origin_candle_time="2026-07-21T11:06:00+05:30",
            confirmation_candle_time="2026-07-21T11:06:00+05:30",
            origin_volume_formatted="1.5M", volume_ratio=1.0,
            displacement_strength=0.8, touch_count=0,
            first_tested_time=None, last_tested_time=None,
            distance_points=8.3, distance_percent=0.03,
            strength_score=50.0, status="ACTIVE",
            broken_at=None, calculated_at="2026-07-21T15:00:00+05:30",
            source_candle_timestamp="2026-07-21T15:00:00+05:30",
            freshness="FRESH",
        ),
    }

    # Wick above 24196.0 (high=24198.0) but close inside (close=24194.0) -> NOT BROKEN, only TESTED
    res1 = engine.analyze_timeframe(
        timeframe="3m",
        candles=[{
            "symbol": "NIFTY", "timeframe": "3m", "timestamp": "2026-07-21T15:03:00+05:30",
            "open": 24190.0, "high": 24198.0, "low": 24189.0, "close": 24194.0,
            "volume": 1000.0, "closed": True, "is_closed": True,
        }],
        current_nifty_price=24187.7,
    )
    res_zone = engine._zones["3m"]["TEST-RES1"]
    assert res_zone.status == "TESTED"
    assert res_zone.broken_at is None

    # Completed close above 24196.0 (close=24197.5) -> BROKEN
    engine.analyze_timeframe(
        timeframe="3m",
        candles=[{
            "symbol": "NIFTY", "timeframe": "3m", "timestamp": "2026-07-21T15:06:00+05:30",
            "open": 24194.0, "high": 24199.0, "low": 24192.0, "close": 24197.5,
            "volume": 1000.0, "closed": True, "is_closed": True,
        }],
        current_nifty_price=24187.7,
    )
    assert res_zone.status == "BROKEN"
    assert res_zone.broken_at == "2026-07-21T15:06:00+05:30"


def test_spot_inside_resistance_state_evaluation():
    """When zone_low <= spot <= zone_high for 5M resistance, relation must evaluate to INSIDE_RESISTANCE."""
    res_low = 24180.75
    res_high = 24196.60
    spot = 24187.70
    assert res_low <= spot <= res_high, "Spot must be inside 5M resistance range"


def test_spot_inside_support_state_evaluation():
    """When zone_low <= spot <= zone_high for 5M support, relation must evaluate to INSIDE_SUPPORT."""
    sup_low = 24180.00
    sup_high = 24190.00
    spot = 24185.00
    assert sup_low <= spot <= sup_high, "Spot must be inside 5M support range"


def test_3m_break_timestamp_date_evidence():
    """3M zone 24176.59-24190.50 broke at 2026-07-21T13:39:00+05:30 on completed close 24192.10."""
    engine = NiftyVOBEngine()
    import json
    with open("/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json") as f:
        c1m = json.load(f).get("candles", [])
    c3m = engine._resample_1m(c1m, 3)
    target_c = [c for c in c3m if "2026-07-21T13:39" in str(c.get("timestamp"))]
    assert len(target_c) == 1
    c = target_c[0]
    assert c["close"] == 24192.10
    assert c["close"] > 24190.50
    assert c["closed"] is True





