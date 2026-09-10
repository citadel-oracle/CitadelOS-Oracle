"""E5B Adversarial Test: Ensures no fake placeholder setup/prices exist in runtime code."""

import pytest
from src.eye.oracle_projection.runtime_state import EyeRuntimeState
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
from src.eye.oracle_projection.contracts import EntryGeometryStatus, StructuralStopStatus, TradePlanStatus


def test_uninitialized_runtime_returns_no_active_setup_and_unknown_structure():
    runtime = EyeRuntimeState()
    service = EyeOracleProjectionService(runtime_state=runtime)

    proj = service.get_projection(symbol="NIFTY", timeframe="5m")

    # Invariants: NO INPUT -> NO OUTPUT
    assert proj.structure.directional_structure == "UNKNOWN"
    assert proj.setup_projection.get("family") == "NO_ACTIVE_SETUP"
    assert proj.setup_projection.get("lifecycle") == "NO_ACTIVE_SETUP"

    # Abstentions
    assert proj.trade_plan.entry_geometry.entry_status == EntryGeometryStatus.ENTRY_BAND_NOT_ESTABLISHED
    assert proj.trade_plan.structural_stop.status == StructuralStopStatus.STRUCTURAL_SL_NOT_ESTABLISHED
    assert len(proj.trade_plan.natural_targets) == 0
    assert proj.trade_plan.status == TradePlanStatus.RR_NOT_ESTABLISHED


def test_no_hardcoded_placeholder_prices_in_uninitialized_projection():
    runtime = EyeRuntimeState()
    service = EyeOracleProjectionService(runtime_state=runtime)

    proj = service.get_projection(symbol="NIFTY", timeframe="5m")

    # Assert none of the forbidden E5A constants appear
    d = proj.to_dict()
    as_str = str(d)

    assert "24600" not in as_str
    assert "24575" not in as_str
    assert "24590" not in as_str
    assert "24520" not in as_str
    assert "24680" not in as_str
    assert "24720" not in as_str
    assert "DHAN_LIVE_WEBSOCKET_AND_REST" not in as_str
