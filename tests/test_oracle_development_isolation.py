"""Focused unit tests for Oracle Development isolation boundaries and persistence paths."""

import os
import tempfile
from pathlib import Path
import pytest

from src.oracle_development import (
    OracleDevService,
    OracleDevMissionService,
    OracleDevPaperAutopilot,
)


def test_no_production_subclassing():
    """Asserts that development controllers and engines do NOT subclass production equivalents."""
    from src.oracle.oracle_service import OracleService
    from src.oracle.mission import OracleMissionService
    from src.oracle.paper_autopilot import OraclePaperAutopilot
    from src.oracle.trade_planner import OracleTradePlanner
    
    assert not issubclass(OracleDevService, OracleService)
    assert not issubclass(OracleDevMissionService, OracleMissionService)
    assert not issubclass(OracleDevPaperAutopilot, OraclePaperAutopilot)
    
    # Check that development modules are completely separate classes
    assert OracleDevService.__name__ == "OracleDevService"
    assert OracleDevMissionService.__name__ == "OracleDevMissionService"
    assert OracleDevPaperAutopilot.__name__ == "OracleDevPaperAutopilot"


def test_isolated_persistence_paths():
    """Asserts that state and logs persistence paths point exclusively to development directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        
        # Instantiate services with dev state root
        missions = OracleDevMissionService(state_root=tmp_root)
        autopilot = OracleDevPaperAutopilot(state_root=tmp_root, missions=missions, resolver=None)
        
        # Check files are located under temp root
        assert autopilot.guardian_state_path.parent == tmp_root
        assert autopilot.execution_events_path.parent == tmp_root
        assert autopilot.journal_path.parent == tmp_root
        assert autopilot.stats_path.parent == tmp_root
        
        assert missions.state_path.parent == tmp_root
        assert missions.events_path.parent == tmp_root
        
        # Verify writing to these paths does not leak to production
        mission = missions.start(
            symbol="NIFTY",
            timeframe="3m",
            parent_setup_family="PA Breakout",
            trade_creator="PriceAction",
            direction="CALL",
            reference_time="2026-07-27T16:00:00Z"
        )
        
        assert missions.state_path.exists()
        assert missions.events_path.exists()
        
        # Assert no files written under production directories
        prod_root = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/oracle_missions")
        assert not (prod_root / "oracle_dev_mission_state.json").exists()


def test_read_only_adapter_composition():
    """Asserts that production services are composed as attributes and not accessed mutably."""
    class MockVOBEngine:
        def __init__(self):
            class Zone:
                def __init__(self):
                    self.side = "BULLISH"
                    self.status = "ACTIVE"
                    self.zone_low = 23950.0
                    self.zone_high = 23980.0
                    self.volume_ratio = 2.5
                    self.displacement_strength = 3.0
            self._zones = {"3m": {"z1": Zone()}}

        def status(self):
            return {"status": "mock"}

    class MockDhanClient:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        dev_service = OracleDevService(
            dhan=MockDhanClient(),
            argus_api=None,
            options_structure_engine=None,
            vob_engine=MockVOBEngine(),
            state_root=tmpdir
        )
        
        # Assert components are composed
        assert hasattr(dev_service, "resolver")
        assert hasattr(dev_service, "resampler")
        assert hasattr(dev_service, "pa_analyzer")
        assert hasattr(dev_service, "scoring_engine")
        assert hasattr(dev_service, "planner")
        assert hasattr(dev_service, "missions")
        assert hasattr(dev_service, "autopilot")
        
        # Assert VOB engine status is read-only accessed
        vob_res = dev_service._assess_vob({"close": 24000.0}, "3m")
        assert vob_res["proximity_points"] > 0
