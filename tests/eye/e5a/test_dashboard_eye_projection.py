"""E5A Test for /v2/dashboard Backend Projection Aggregation."""

import pytest
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
from src.eye.oracle_projection.runtime_state import EyeRuntimeState
from src.api.v2_integration import V2DashboardIntegration


def test_v2_dashboard_includes_eye_oracle_projection():
    v2 = V2DashboardIntegration(
        snapshot=lambda: {"status": "OPEN"},
        oracle=lambda sym: {"directional_bias": "BULLISH"},
        argus=lambda sym: {"status": "OK"},
        kronos_alpha=lambda: {}, chronos2=lambda: {}, athena=lambda: {}, hermes=lambda: {},
        risk_status=lambda: {}, kill_switch=lambda: {}, paper_status=lambda: {},
        personal_oracle=lambda: {}, readiness=lambda: {}, next_session_plan=lambda: {},
        order_ledger=lambda: {}, paper_trading=lambda: {},
    )

    data = v2.dashboard(symbol="NIFTY")
    assert "eye_oracle_projection" in data["feeds"]
    eye_feed = data["feeds"]["eye_oracle_projection"]
    assert eye_feed["ok"] is True
    assert eye_feed["data"]["authority"] == "OBSERVATION_ONLY"
    assert eye_feed["data"]["execution_authority"] is False


def test_eye_projection_exposes_one_scanner_owned_primary_signal_for_both_oracle_consumers():
    runtime = EyeRuntimeState()
    runtime.set_strategy_signal(
        "S02",
        {
            "strategy_id": "S02_NIFTY_VOLATILE",
            "state": "DETECTED",
            "short_label": "NIFTY VOLATILE",
            "cycle_id": "S02:2026-08-10:1",
        },
        source_timestamp=1.0,
        source_revision=1,
    )

    projection = EyeOracleProjectionService(runtime_state=runtime).get_projection().to_dict()
    signal = projection["personal_strategy_signal"]

    assert signal["state"] == "DETECTED"
    assert signal["primary_signal"]["strategy_id"] == "S02_NIFTY_VOLATILE"
    assert signal["primary_signal"] is not signal
