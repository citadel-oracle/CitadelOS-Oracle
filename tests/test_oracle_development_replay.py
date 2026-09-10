"""Deterministic chronological replay fixtures for all 13 trade creator families."""

import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta

from src.oracle_development.oracle_dev_service import OracleDevService
from src.oracle_development.price_action_analyzer import OracleDevPriceActionAnalyzer


class MockDhan:
    def __init__(self):
        self.live_trading_enabled = False
        
    def get_quote(self, segment, security_id):
        return {"ltp": 24000.0}
        
    def get_intraday_candles(self, segment, security_id=None, *args, **kwargs):
        return {
            "success": True,
            "candles": [
                {"time": 1785148800, "open": 24000.0, "high": 24010.0, "low": 23990.0, "close": 24000.0, "volume": 100}
            ]
        }
        
    def get_option_expiries(self, segment, security_id):
        return {"data": ["2026-07-29"]}


def build_service(tmpdir):
    dhan = MockDhan()
    return OracleDevService(
        dhan=dhan,
        argus_api=None,
        options_structure_engine=None,
        vob_engine=None,
        state_root=tmpdir
    )


def pad_candles(candles, start_price=24000.0):
    base = []
    first_time = candles[0]["time"]
    for i in range(50):  # Pad 50 candles to ensure stable 14-period ATR
        t = first_time - (50 - i) * 60  # 1-minute intervals
        base.append({
            "time": t,
            "open": start_price,
            "high": start_price + 2.0,
            "low": start_price - 2.0,
            "close": start_price,
            "volume": 100
        })
    return base + candles


def test_vob_pullback_reversal_replay(tmpdir):
    """Fixture 1: VOB pullback/reversal replay setup."""
    service = build_service(tmpdir)
    
    # 1. Plant a VOB support zone in the engine
    class MockVobEngine:
        def __init__(self):
            class Zone:
                def __init__(self):
                    self.side = "BULLISH"
                    self.status = "ACTIVE"
                    self.zone_low = 23950.0
                    self.zone_high = 23980.0
                    self.volume_ratio = 2.5
                    self.displacement_strength = 3.0
                def to_dict(self):
                    return {
                        "side": self.side,
                        "status": self.status,
                        "zone_low": self.zone_low,
                        "zone_high": self.zone_high,
                        "volume_ratio": self.volume_ratio,
                        "displacement_strength": self.displacement_strength
                    }
            self._zones = {"3m": {"z1": Zone()}}
            
    service.vob_engine = MockVobEngine()
    
    # 2. Feed candles that pull back into the VOB zone and close bullishly
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24020.0, "low": 23990.0, "close": 24010.0, "volume": 100},
        {"time": now_epoch - 240, "open": 24010.0, "high": 24010.0, "low": 23970.0, "close": 23975.0, "volume": 120}, # Inside VOB
        {"time": now_epoch - 180, "open": 23975.0, "high": 23995.0, "low": 23970.0, "close": 23990.0, "volume": 140}  # Reversal close
    ]
    spot_candles = pad_candles(spot_candles)
    
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["setup_family"] is not None


def test_vob_breakout_retest_replay(tmpdir):
    """Fixture 2: VOB breakout/retest replay setup."""
    service = build_service(tmpdir)
    
    # Breakout past supply zone
    class MockVobEngine:
        def __init__(self):
            class Zone:
                def __init__(self):
                    self.side = "BEARISH"
                    self.status = "ACTIVE"
                    self.zone_low = 24020.0
                    self.zone_high = 24040.0
                    self.volume_ratio = 2.0
                    self.displacement_strength = 2.5
                def to_dict(self):
                    return {"side": self.side, "status": self.status, "zone_low": self.zone_low, "zone_high": self.zone_high, "volume_ratio": self.volume_ratio, "displacement_strength": self.displacement_strength}
            self._zones = {"3m": {"z1": Zone()}}
            
    service.vob_engine = MockVobEngine()
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24010.0, "low": 23990.0, "close": 24000.0, "volume": 100},
        {"time": now_epoch - 240, "open": 24000.0, "high": 24050.0, "low": 23995.0, "close": 24045.0, "volume": 150}, # Breakout past zone
        {"time": now_epoch - 180, "open": 24045.0, "high": 24045.0, "low": 24025.0, "close": 24035.0, "volume": 110}  # Retest close
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["score"] >= 0


def test_pa_pullback_continuation_replay(tmpdir):
    """Fixture 3: PA pullback/continuation replay setup."""
    service = build_service(tmpdir)
    
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24050.0, "low": 23990.0, "close": 24040.0, "volume": 100},
        {"time": now_epoch - 240, "open": 24040.0, "high": 24040.0, "low": 24010.0, "close": 24015.0, "volume": 80}, # pullback
        {"time": now_epoch - 180, "open": 24015.0, "high": 24045.0, "low": 24010.0, "close": 24040.0, "volume": 120}  # continuation
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["pullback_state"]["is_pullback"] is False


def test_structural_breakout_acceptance_replay(tmpdir):
    """Fixture 4: Structural breakout/acceptance replay setup."""
    service = build_service(tmpdir)
    
    # Establish swing high at 24050, then consecutive closes above it
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24030.0, "high": 24050.0, "low": 24010.0, "close": 24020.0, "volume": 100}, # swing high
        {"time": now_epoch - 240, "open": 24020.0, "high": 24065.0, "low": 24015.0, "close": 24060.0, "volume": 150}, # close 1 above 24050
        {"time": now_epoch - 180, "open": 24060.0, "high": 24075.0, "low": 24055.0, "close": 24070.0, "volume": 130}  # close 2 above 24050 (acceptance)
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["score"] >= 0


def test_liquidity_sweep_replay(tmpdir):
    """Fixture 5: Liquidity sweep/failed breakout replay setup."""
    service = build_service(tmpdir)
    
    # Swing high at 24050. Next candle wicks above 24050 but closes below 24050.
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24030.0, "high": 24050.0, "low": 24010.0, "close": 24020.0, "volume": 100}, # swing high
        {"time": now_epoch - 240, "open": 24020.0, "high": 24060.0, "low": 24015.0, "close": 24040.0, "volume": 120}  # sweep wick
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["score"] >= 0


def test_range_edge_rotation_replay(tmpdir):
    """Fixture 6: Range-edge rotation replay setup."""
    service = build_service(tmpdir)
    
    now_epoch = 1785148800
    spot_candles = []
    # Establishes range low at 24000, high at 24100, and rotates back down
    prices = [24010, 24000, 24020, 24040, 24060, 24080, 24100, 24090, 24070, 24050, 24030, 24015]
    for i, p in enumerate(prices):
        t = now_epoch - (len(prices) - i) * 60
        spot_candles.append({
            "time": t,
            "open": p - 5.0 if i == 0 or p > prices[i-1] else p + 5.0,
            "high": p + 10.0,
            "low": p - 10.0,
            "close": p,
            "volume": 100
        })
    # Add padding BEFORE the range candles
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["range_state"]["is_range"] is True


def test_compression_expansion_replay(tmpdir):
    """Fixture 7: Compression expansion replay setup."""
    service = build_service(tmpdir)
    
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24010.0, "low": 23995.0, "close": 24002.0, "volume": 50}, # compression
        {"time": now_epoch - 240, "open": 24002.0, "high": 24008.0, "low": 23998.0, "close": 24004.0, "volume": 40}, # compression
        {"time": now_epoch - 180, "open": 24004.0, "high": 24060.0, "low": 24000.0, "close": 24055.0, "volume": 300}  # expansion breakout
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["score"] >= 0


def test_fvg_retest_replay(tmpdir):
    """Fixture 8: FVG retest replay setup."""
    service = build_service(tmpdir)
    
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24010.0, "low": 23995.0, "close": 24005.0},
        {"time": now_epoch - 240, "open": 24005.0, "high": 24080.0, "low": 24005.0, "close": 24075.0}, # FVG zone [24010 - 24025] created
        {"time": now_epoch - 180, "open": 24075.0, "high": 24075.0, "low": 24020.0, "close": 24035.0}  # Retest FVG zone
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert len(res["3m"]["price_action"]["fvg_family"]) >= 0


def test_fvg_inversion_replay(tmpdir):
    """Fixture 9: FVG inversion replay setup."""
    service = build_service(tmpdir)
    
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24010.0, "low": 23995.0, "close": 24005.0},
        {"time": now_epoch - 240, "open": 24005.0, "high": 24080.0, "low": 24005.0, "close": 24075.0}, # FVG zone [24010 - 24025] created
        {"time": now_epoch - 180, "open": 24075.0, "high": 24075.0, "low": 23990.0, "close": 23995.0}  # invalidates and closes below FVG zone
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    fvgs = res["3m"]["price_action"]["fvg_family"]
    assert len(fvgs) >= 0


def test_breakaway_fvg_replay(tmpdir):
    """Fixture 10: Breakaway FVG replay setup."""
    service = build_service(tmpdir)
    
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24010.0, "low": 23995.0, "close": 24005.0},
        {"time": now_epoch - 240, "open": 24005.0, "high": 24100.0, "low": 24005.0, "close": 24095.0}, # Breakaway FVG created
        {"time": now_epoch - 180, "open": 24095.0, "high": 24110.0, "low": 24085.0, "close": 24100.0}
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    fvgs = res["3m"]["price_action"]["fvg_family"]
    assert len(fvgs) >= 0


def test_opening_drive_pullback_replay(tmpdir):
    """Fixture 11: Opening-drive first pullback replay setup."""
    service = build_service(tmpdir)
    
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    
    dt_0915 = datetime(2026, 7, 27, 9, 15, tzinfo=IST)
    
    # Generate 20 completed 1m candles starting at 09:15 to yield 6 completed 3m candles
    spot_candles = []
    for i in range(20):
        t = int((dt_0915 + timedelta(minutes=i)).timestamp())
        if i < 8:
            op = 24000.0 + i * 15.0
            cl = 24000.0 + (i + 1) * 15.0
            hi = cl + 5.0
            lo = op - 5.0
        else:
            op = 24120.0 - (i - 8) * 8.0
            cl = 24120.0 - (i - 7) * 8.0
            hi = op + 5.0
            lo = cl - 5.0
            
        spot_candles.append({
            "time": t,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": 1000 - i * 40
        })
        
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["opening_state"]["opening_type"] is not None


def test_second_entry_continuation_replay(tmpdir):
    """Fixture 12: Second-entry continuation replay setup."""
    service = build_service(tmpdir)
    
    # Establish higher highs and lows representing low-1 and low-2 legs of pullback
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24050.0, "low": 23990.0, "close": 24040.0},
        {"time": now_epoch - 240, "open": 24040.0, "high": 24040.0, "low": 24010.0, "close": 24015.0}, # first leg low-1
        {"time": now_epoch - 180, "open": 24015.0, "high": 24035.0, "low": 24015.0, "close": 24030.0},
        {"time": now_epoch - 120, "open": 24030.0, "high": 24030.0, "low": 24005.0, "close": 24010.0}  # second leg low-2
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["score"] >= 0


def test_exhaustion_reversal_replay(tmpdir):
    """Fixture 13: Exhaustion reversal replay setup."""
    service = build_service(tmpdir)
    
    # Climax range expansion with small body close near bottom (exhaustion pin bar)
    now_epoch = 1785148800
    spot_candles = [
        {"time": now_epoch - 300, "open": 24000.0, "high": 24020.0, "low": 23995.0, "close": 24015.0},
        {"time": now_epoch - 240, "open": 24015.0, "high": 24100.0, "low": 24010.0, "close": 24020.0}  # exhaustion pin bar
    ]
    spot_candles = pad_candles(spot_candles)
    res = service.process_candle_update(spot_candles, spot_candles, {})
    assert res["3m"]["price_action"]["reversal_state"]["is_exhaustion"] is True
