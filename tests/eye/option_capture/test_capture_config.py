"""E4A-E Test for Capture Configuration Specification."""

import pytest
from src.eye.option_capture.config import CaptureConfig


def test_capture_config_validation():
    cfg = CaptureConfig()
    cfg.validate()
    assert cfg.execution_authority is False
    assert cfg.authority == "READ_ONLY_OBSERVATION"
    assert cfg.underlying_symbol == "NIFTY"


def test_capture_config_rejects_execution_authority():
    cfg = CaptureConfig(execution_authority=True)
    with pytest.raises(AssertionError, match="EXECUTION_AUTHORITY_MUST_BE_FALSE"):
        cfg.validate()
