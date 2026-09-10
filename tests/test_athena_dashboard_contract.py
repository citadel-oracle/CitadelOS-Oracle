from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import assert_centralized_feed, assert_single_centralized_polling_loop


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "citadel-dashboard" / "src" / "app" / "page.tsx"


def source():
    return PAGE.read_text(encoding="utf-8")


def athena_component():
    return source().split("function AthenaPanel", 1)[1].split(
        "function InsightsPanel", 1
    )[0]


def test_frontend_consumes_authoritative_athena_contract():
    page = source()

    assert_centralized_feed("athena", "athena")
    for field in (
        "athena_status",
        "risk_state",
        "recommendation",
        "recommended_size_multiplier",
        "daily_loss_used_percentage",
        "daily_loss_headroom",
        "trade_usage_percentage",
        "loss_streak_usage_percentage",
        "exposure_usage_percentage",
        "current_drawdown",
        "available_capital",
        "risk_headroom_percentage",
        "reason_codes",
        "warnings",
        "missing_inputs",
        "maturity_label",
        "source_metadata",
    ):
        assert field in page


def test_athena_panel_is_compact_truthful_and_advisory():
    page = source()
    component = athena_component()

    assert 'eyebrow="08 / Athena"' in page
    assert 'title="Risk & Capital Intelligence"' in page
    for label in (
        "Risk state",
        "Recommendation",
        "Advisory size",
        "Daily loss used",
        "Daily risk headroom",
        "Trades used",
        "Loss-streak usage",
        "Open positions",
        "Drawdown",
        "Exposure usage",
        "Risk headroom",
        "Top reason codes",
        "Advisory warnings",
    ):
        assert label in component
    assert "data.available_capital !== null" in component
    assert "formatMoney(data.current_drawdown)" in component


def test_malformed_and_unavailable_athena_values_fail_visibly():
    page = source()

    assert_centralized_feed("athena", "athena")
    assert "<FeedPlaceholder error={athena.error} label=\"Athena intelligence\" />" in page
    assert "value === 'Unavailable'" in page


def test_athena_panel_has_no_mutation_controls_and_dashboard_is_intact():
    page = source()
    component = athena_component()

    for forbidden in (
        "<button",
        "/orders",
        "placeOrder",
        "activate",
        "deactivate",
        "kill-switch toggle",
    ):
        assert forbidden not in component
    assert_single_centralized_polling_loop()
    assert 'eyebrow="07 / Technical Intelligence"' in page
    assert "SAFE / Risk & Paper Control" in page
    assert "dashboardFooter.build" in page
    assert "Legacy Build • Vihaann" in (ROOT / "citadel-dashboard" / "src" / "dashboard" / "adapters" / "DashboardDataAdapter.ts").read_text(encoding="utf-8")
