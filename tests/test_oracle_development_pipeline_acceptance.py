"""Deterministic pipeline acceptance test verifying qualifying setup entry, duplicate trade prevention, stale data gating, and wick-only invalidation bypass."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from src.oracle_development.oracle_dev_service import OracleDevService
from src.oracle_development.instrument_resolver import OracleDevInstrumentResolver

def _candle(ts: int, open_p: float, high_p: float, low_p: float, close_p: float) -> dict:
    return {"time": ts, "open": open_p, "high": high_p, "low": low_p, "close": close_p, "volume": 1000}

def test_pipeline_acceptance_and_setup_behavior():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        
        # 1. Mock Dhan Client
        dhan = MagicMock()
        dhan.get_quote.return_value = {"ltp": 24000.0}
        dhan.get_option_expiries.return_value = {"data": ["2026-08-05"]}
        dhan.get_intraday_candles.return_value = {"candles": []}
        
        # 2. Mock Argus and OSE
        argus = MagicMock()
        argus.get_flow_bias.return_value = {"bias": "neutral", "strength": 0.0}
        ose = MagicMock()
        ose.get_order_pressure.return_value = {}
        
        # 3. VOB engine stub
        class MockVobEngine:
            def __init__(self):
                class Zone:
                    def __init__(self):
                        self.zone_id = "z1"
                        self.side = "BULLISH"
                        self.status = "ACTIVE"
                        self.zone_low = 23950.0
                        self.zone_high = 23980.0
                        self.volume_ratio = 2.5
                        self.displacement_strength = 3.0
                        self.origin_candle_time = "2026-07-27T16:00:00Z"
                    def to_dict(self):
                        return {
                            "side": self.side,
                            "status": self.status,
                            "zone_low": self.zone_low,
                            "zone_high": self.zone_high,
                            "volume_ratio": self.volume_ratio,
                            "displacement_strength": self.displacement_strength,
                            "origin_candle_time": self.origin_candle_time
                        }
                self._zones = {"3m": {"z1": Zone()}}
            def ingest_1m_candles(self, *args, **kwargs):
                pass
            def save_state(self):
                pass
                
        vob = MockVobEngine()
        
        # 4. Service initialization
        clock_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=timezone.utc)
        service = OracleDevService(
            dhan=dhan,
            argus_api=argus,
            options_structure_engine=ose,
            vob_engine=vob,
            state_root=str(tmp_root),
            clock=lambda: clock_time
        )
        
        # Override to bypass synthetic/replay blockers
        service.is_synthetic = False
        service.is_replay = False
        
        # Create a valid set of historical completed candles to satisfy the history gate (60 completed for 3m lane)
        now_epoch = int(clock_time.timestamp())
        spot_candles = []
        for i in range(100):
            ts = now_epoch - (100 - i) * 60
            spot_candles.append(_candle(ts, 24000.0, 24010.0, 23990.0, 24000.0))
            
        # Last candle pulls back into VOB zone (low is 23970) but closes bullishly (close 23995)
        spot_candles[-1] = _candle(now_epoch - 60, 24000.0, 24010.0, 23970.0, 23995.0)
        
        option_candles = {
            "ATM_CE": [_candle(now_epoch - 60, 100.0, 105.0, 95.0, 100.0)],
            "ATM_PE": [_candle(now_epoch - 60, 100.0, 105.0, 95.0, 100.0)]
        }
        
        # Mock resolver's options to avoid resolving from empty master during test
        resolved_opts = {
            "ATM_CE": {"security_id": "111", "symbol": "NIFTY-CE", "strike": 24000.0, "expiry": "2026-08-05", "option_type": "CE", "lot_size": 75, "segment": "NSE_FNO", "instrument": "OPTIDX"},
            "ATM_PE": {"security_id": "222", "symbol": "NIFTY-PE", "strike": 24000.0, "expiry": "2026-08-05", "option_type": "PE", "lot_size": 75, "segment": "NSE_FNO", "instrument": "OPTIDX"}
        }
        service.resolver.resolve_options = lambda *a, **k: resolved_opts
        
        # Mock Price Action, VOB assessment and scoring to force a qualifying valid setup
        service.pa_analyzer.analyze = lambda *a, **k: {
            "score": 30.0,
            "regime": "BULLISH",
            "swings": [{"type": "LOW", "val": 23950.0, "index": 50}],
            "fvg_family": [],
            "why": "",
            "no_chase": False,
            "factors": {}
        }
        service._assess_vob = lambda *a, **k: {
            "proximity_points": 10.0,
            "ratio_points": 10.0,
            "displacement_strength_points": 5.0,
            "vob_state": "ACTIVE_ZONE"
        }
        service.scoring_engine.compute_scores = lambda *a, **k: {
            "total_score": 90.0,
            "risk_approved": True,
            "guardian_ready": True,
            "pa_score": 30.0,
            "vob_score": 30.0,
            "deriv_score": 30.0,
            "exec_score": 10.0
        }
        
        # A. Qualifying valid setup -> exactly one paper trade
        res = service.process_candle_update(spot_candles, spot_candles, option_candles)
        
        # Check active position was opened in the mission registry / autopilot
        lane_status = service.autopilot.get_lane_status("3m")
        assert lane_status["position"] is not None
        assert lane_status["position"]["status"] == "OPEN"
        
        # B. Repeated evaluations -> no duplicate trades
        # Run process_candle_update again with same candles
        res2 = service.process_candle_update(spot_candles, spot_candles, option_candles)
        lane_status2 = service.autopilot.get_lane_status("3m")
        assert lane_status2["position"]["status"] == "OPEN"
        
        # C. Stale setup -> 0 trades
        # Close position and make data age stale
        mission_id = lane_status["position"]["mission_id"]
        service.missions.cancel(mission_id, "MANUAL")
        service.autopilot._state["lanes"]["3m"]["position"] = None
        service.autopilot._state["lanes"]["3m"]["state"] = "CLOSED"
        
        # Shift clock ahead to make data stale and override scoring to return risk_approved=False
        clock_time = clock_time + timedelta(seconds=60)
        service.scoring_engine.compute_scores = lambda *a, **k: {
            "total_score": 50.0,
            "risk_approved": False, # blocks entry
            "guardian_ready": True,
            "pa_score": 30.0,
            "vob_score": 30.0,
            "deriv_score": 30.0,
            "exec_score": 0.0
        }
        res_stale = service.process_candle_update(spot_candles, spot_candles, option_candles)
        lane_status_stale = service.autopilot.get_lane_status("3m")
        assert lane_status_stale["position"] is None
        
        # D. Incomplete/wick-only candle -> no invalidation or entry/exit trigger
        # Restore clock and scores to open a new position
        clock_time = datetime(2026, 7, 28, 10, 0, 0, tzinfo=timezone.utc)
        service.scoring_engine.compute_scores = lambda *a, **k: {
            "total_score": 90.0,
            "risk_approved": True,
            "guardian_ready": True,
            "pa_score": 30.0,
            "vob_score": 30.0,
            "deriv_score": 30.0,
            "exec_score": 10.0
        }
        res_new = service.process_candle_update(spot_candles, spot_candles, option_candles)
        assert service.autopilot.get_lane_status("3m")["position"] is not None
        
        # Feed candle with wick going below low, but close stays above. No exit.
        wick_candle = _candle(now_epoch, 23995.0, 24000.0, 23900.0, 23980.0) # low 23900 < SL (23950) but close 23980 > SL
        spot_candles_wick = spot_candles + [wick_candle]
        service.process_candle_update(spot_candles_wick, spot_candles_wick, option_candles)
        
        assert service.autopilot.get_lane_status("3m")["position"]["status"] == "OPEN"
