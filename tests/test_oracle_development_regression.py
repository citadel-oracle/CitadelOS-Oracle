"""Regression tests for Oracle Development runtime truth and V2 projection lag rules."""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from src.oracle_development.oracle_dev_service import OracleDevService
from src.oracle_development.paper_autopilot_dev import OracleDevPaperAutopilot
from src.oracle_development.mission_dev import OracleDevMissionService
from src.api.v2_integration import V2DashboardIntegration, ProjectionValidationError


class MockDhanClient:
    def __init__(self, spot_candles=None, futures_candles=None):
        self.spot_candles = spot_candles or []
        self.futures_candles = futures_candles or []

    def get_quote(self, security_id, segment):
        return {"ltp": 24000.0}

    def get_intraday_candles(self, segment, security_id, instrument):
        if instrument == "INDEX":
            return {"candles": self.spot_candles}
        elif instrument == "FUTIDX":
            return {"candles": self.futures_candles}
        return {"candles": []}


def test_regression_score_2_no_vob_stale_quote_no_position():
    """Asserts that score=2 + no VOB + stale quote prevents any position from opening."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        
        # 1. Setup stale candle (older than 30s)
        _IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(_IST).replace(hour=11, minute=0, second=0, microsecond=0)
        now_dt = now_ist.astimezone(timezone.utc)
        stale_time = int((now_dt - timedelta(seconds=60)).timestamp())
        
        spot_candles = [
            {"time": stale_time, "open": 24000.0, "high": 24005.0, "low": 23995.0, "close": 24000.0, "volume": 100}
        ]
        
        # 2. Mock Dhan and Service
        dhan = MockDhanClient(spot_candles=spot_candles, futures_candles=spot_candles)
        
        # Create service
        service = OracleDevService(
            dhan,
            None,
            None,
            None,
            state_root=tmp_root,
            clock=lambda: now_dt
        )
        
        # Run assessment and execution
        results = service.assess_and_execute()
        
        # Verify 1m lane has no active position and is IDLE/CLOSED (not open)
        lane_status = results.get("1m", {}).get("lane_status", {})
        assert lane_status.get("position") is None
        assert lane_status.get("state") in ("IDLE", "CLOSED")


def test_lifecycle_state_consistency_sanitizer():
    """Asserts that state consistency sanitizer heals any loaded mismatched lifecycle states."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        missions = OracleDevMissionService(tmp_root)
        
        # 1. Mismatch Type A: Active position exists but state is CLOSED
        guardian_file = tmp_root / "oracle_dev_guardian_state.json"
        mismatched_state = {
            "schema_version": 1,
            "lanes": {
                "1m": {
                    "timeframe": "1m",
                    "state": "CLOSED",
                    "position": {
                        "trade_id": "VT-1m-test",
                        "mission_id": "mission-1",
                        "status": "OPEN",
                        "entry_price": 100.0,
                        "quantity": 75
                    }
                }
            }
        }
        
        with open(guardian_file, "w", encoding="utf-8") as f:
            json.dump(mismatched_state, f)
            
        # Re-initialize autopilot which triggers _load()
        autopilot = OracleDevPaperAutopilot(tmp_root, missions, None)
        
        # Sanitizer must force state to OPEN
        lane_status = autopilot.get_lane_status("1m")
        assert lane_status["position"] is not None
        assert lane_status["state"] == "OPEN"
        
        # 2. Mismatch Type B: No active position but state is OPEN
        mismatched_state_b = {
            "schema_version": 1,
            "lanes": {
                "1m": {
                    "timeframe": "1m",
                    "state": "OPEN",
                    "position": None
                }
            }
        }
        with open(guardian_file, "w", encoding="utf-8") as f:
            json.dump(mismatched_state_b, f)
            
        autopilot_b = OracleDevPaperAutopilot(tmp_root, missions, None)
        
        # Sanitizer must force state to CLOSED
        lane_status_b = autopilot_b.get_lane_status("1m")
        assert lane_status_b["position"] is None
        assert lane_status_b["state"] == "CLOSED"


def test_v2_live_fail_closed_replay_degraded():
    """Asserts that V2 intelligence boundary fails closed in live but degrades in replay."""
    boundary = datetime(2026, 7, 27, 11, 35, tzinfo=timezone.utc)
    generated = boundary + timedelta(minutes=5, seconds=1)
    
    # Lagging/mismatched feeds
    timestamp_stale = (boundary - timedelta(minutes=5)).isoformat()
    contracts = {
        side: {
            "vob": {"evaluated_through": timestamp_stale},
            "trend": {"evaluated_through": timestamp_stale},
        }
        for side in ("CE", "PE")
    }
    
    # 1. LIVE Mode feeds (live_trading_enabled=True, market_open=True)
    live_feeds = {
        "mission": {
            "data": {
                "system": {
                    "live_trading_enabled": True,
                    "session": {"market_open": True}
                }
            }
        },
        "strategy_lab": {
            "data": {
                "execution": {
                    "options_structure": {"contracts": contracts},
                    "nifty_vob": {
                        "timeframes": {
                            "5m": {"evaluated_through": timestamp_stale}
                        }
                    },
                }
            }
        },
        "oracle": {
            "data": {
                "timeframe": "5m",
                "market_data_as_of": boundary.isoformat(),  # Mismatch (lagging vs current)
            }
        },
    }
    
    # LIVE must fail closed with ProjectionValidationError
    with pytest.raises(ProjectionValidationError, match="MODULE_LAG:"):
        V2DashboardIntegration._intelligence_boundary(live_feeds, generated.isoformat())
        
    # 2. REPLAY Mode feeds (live_trading_enabled=False)
    replay_feeds = {
        "mission": {
            "data": {
                "system": {
                    "live_trading_enabled": False,
                    "session": {"market_open": False}
                }
            }
        },
        "strategy_lab": live_feeds["strategy_lab"],
        "oracle": live_feeds["oracle"]
    }
    
    # REPLAY/POST-MARKET must degrade gracefully and return DEGRADED dictionary
    res = V2DashboardIntegration._intelligence_boundary(replay_feeds, generated.isoformat())
    assert res["status"] == "DEGRADED"
    assert res["reason"] == "REPLAY_POST_MARKET_INTELLIGENCE_DEGRADED"
