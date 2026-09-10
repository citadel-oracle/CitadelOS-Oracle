from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import assert_centralized_feed, assert_single_centralized_polling_loop


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "citadel-dashboard" / "src" / "app" / "page.tsx"


def source():
    return PAGE.read_text(encoding="utf-8")


def test_dashboard_consumes_sanitized_read_only_status_contracts():
    page = source()

    assert_centralized_feed("riskStatus", "risk_status")
    assert_centralized_feed("paperStatus", "paper_status")
    for field in (
        "kill_switch_active",
        "live_trading_enabled",
        "risk_state_available",
        "realized_pnl",
        "unrealized_pnl",
        "total_daily_pnl",
        "trades_taken_today",
        "consecutive_losses",
        "open_position_count",
        "accepted_request_count",
    ):
        assert field in page


def test_dashboard_renders_compact_truthful_unavailable_and_stale_states():
    page = source()

    assert "SAFE / Risk & Paper Control" in page
    assert "Read-Only Safety State" in page
    assert "Last successful safety state preserved" in page
    assert "Kill-switch reason unavailable" in page
    assert "No authorization decision available" in page
    assert "value === 'Unavailable'" in page


def test_risk_control_section_introduces_no_mutation_control():
    page = source()
    component = page.split("function RiskPaperControl", 1)[1].split(
        "function ControlStatus", 1
    )[0]

    assert "<button" not in component
    assert "activate" not in component.lower()
    assert "deactivate" not in component.lower()
    assert "/orders" not in component
    assert "kill_switch_active" in component


def test_existing_single_polling_loop_and_argus_contract_remain_present():
    page = source()

    assert_single_centralized_polling_loop()
    assert "dashboardFooter.build" in page
    assert "Legacy Build • Vihaann" in (ROOT / "citadel-dashboard" / "src" / "dashboard" / "adapters" / "DashboardDataAdapter.ts").read_text(encoding="utf-8")
