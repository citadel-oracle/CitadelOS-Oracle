from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import assert_centralized_feed, assert_single_centralized_polling_loop


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "citadel-dashboard" / "src" / "app" / "page.tsx"


def source():
    return PAGE.read_text(encoding="utf-8")


def hermes_component():
    return source().split("function HermesPanel", 1)[1].split(
        "function InsightsPanel", 1
    )[0]


def test_frontend_consumes_cached_read_only_hermes_contract():
    page = source()

    assert_centralized_feed("hermes", "hermes")
    for field in (
        "hermes_status",
        "overall_event_risk",
        "recommendation",
        "dominant_sentiment",
        "next_major_event",
        "top_events",
        "affected_markets",
        "reason_codes",
        "warnings",
        "missing_inputs",
        "maturity_label",
        "source_metadata",
        "freshness_metadata",
    ):
        assert field in page


def test_hermes_panel_labels_fixture_freshness_and_unknowns_truthfully():
    page = source()
    component = hermes_component()

    assert 'eyebrow="09 / Hermes"' in page
    assert 'title="News & Event Intelligence"' in page
    assert "Fixture / development intelligence · Not live news" in component
    assert "Unavailable — no configured provider data" in component
    for label in (
        "Event risk",
        "Recommendation",
        "Sentiment",
        "Next major event",
        "Imminent events",
        "High / critical",
        "Conflicts",
        "Affected scope",
        "Top normalized events",
        "Source / coverage warnings",
    ):
        assert label in component
    assert "hermes.data?.hermes_status === 'READY'\n    ? 'cached'" in page


def test_malformed_hermes_response_fails_visibly_without_normal_default():
    page = source()

    assert_centralized_feed("hermes", "hermes")
    assert "<FeedPlaceholder error={hermes.error} label=\"Hermes intelligence\" />" in page
    assert "overall_event_risk: 'NONE' | 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL' | 'UNKNOWN'" in page


def test_hermes_has_no_controls_and_existing_dashboard_contract_is_intact():
    page = source()
    component = hermes_component()

    for forbidden in (
        "<button",
        "/orders",
        "placeOrder",
        "refresh_from_provider",
        "activate",
        "deactivate",
        "breaking-news ticker",
    ):
        assert forbidden not in component
    assert_single_centralized_polling_loop()
    assert 'eyebrow="07 / Technical Intelligence"' in page
    assert 'eyebrow="08 / Athena"' in page
    assert "SAFE / Risk & Paper Control" in page
    assert "dashboardFooter.build" in page
    assert "Legacy Build • Vihaann" in (ROOT / "citadel-dashboard" / "src" / "dashboard" / "adapters" / "DashboardDataAdapter.ts").read_text(encoding="utf-8")
