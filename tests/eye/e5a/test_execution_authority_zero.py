"""E5A Test for Execution Authority Zero & Safety Invariants."""

import pytest
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService


def test_eye_oracle_projection_execution_authority_is_zero():
    service = EyeOracleProjectionService()
    proj = service.get_projection(symbol="NIFTY", timeframe="5m")

    assert proj.authority == "OBSERVATION_ONLY"
    assert proj.execution_authority is False
    assert proj.probability_status == "NOT_ESTABLISHED"
    assert proj.to_dict()["execution_authority"] is False
