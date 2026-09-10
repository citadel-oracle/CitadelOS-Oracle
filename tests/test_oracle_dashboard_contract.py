from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import assert_centralized_feed, assert_single_centralized_polling_loop


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "citadel-dashboard" / "src" / "app" / "page.tsx"


def source():
    return PAGE.read_text(encoding="utf-8")


def oracle_component():
    return source().split("function OraclePanel", 1)[1].split(
        "function AthenaPanel", 1
    )[0]


def test_dashboard_consumes_symbol_scoped_oracle_assessment_contract():
    page = source()

    assert_centralized_feed("oracle", "oracle")
    for field in (
        "oracle_status",
        "data_status",
        "symbol",
        "timeframe",
        "bias",
        "signal",
        "confidence",
        "regime",
        "reason_codes",
        "reasoning",
        "input_features",
        "warnings",
        "maturity",
        "source",
    ):
        assert field in page


def test_oracle_panel_exposes_truthful_health_and_freshness_states():
    page = source()
    component = oracle_component()

    assert "Deterministic Signal Assessment" in page
    assert "oracle.data?.data_status === 'LIVE'" in page
    assert "oracle.data.oracle_status === 'READY'" in page
    assert "oracle.data?.data_status === 'CACHED'" in page
    assert "oracle.data?.data_status === 'STALE'" in page
    for label in (
        "Health",
        "Freshness",
        "Last updated",
        "Confidence",
        "Technical signal",
        "Directional bias",
        "Regime",
        "Data age",
        "Maturity",
        "Assessment warning",
    ):
        assert label in component


def test_oracle_panel_is_read_only_and_has_no_fabricated_trade_levels():
    component = oracle_component()

    assert "<button" not in component
    assert "/orders" not in component
    assert "placeOrder" not in component
    assert "activate" not in component.lower()
    assert "deactivate" not in component.lower()
    assert "Stop Loss" not in component
    assert ">Entry<" not in component
    assert ">Target<" not in component


def test_oracle_wiring_preserves_single_polling_loop_and_existing_sections():
    page = source()

    assert_single_centralized_polling_loop()
    assert "SAFE / Risk & Paper Control" in page
    assert "dashboardFooter.build" in page
    assert "Legacy Build • Vihaann" in (ROOT / "citadel-dashboard" / "src" / "dashboard" / "adapters" / "DashboardDataAdapter.ts").read_text(encoding="utf-8")


def test_current_oracle_panel_is_exposed_as_technical_intelligence_only():
    page = source()

    assert 'eyebrow="07 / Technical Intelligence"' in page
    assert "Technical signal" in page
    assert "Loading technical assessment" in page
    assert_centralized_feed("oracle", "oracle")
    assert 'eyebrow="07 / Oracle"' not in page
