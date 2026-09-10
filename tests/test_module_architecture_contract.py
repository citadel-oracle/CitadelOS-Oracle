import json
from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import assert_single_centralized_polling_loop


pytestmark = [pytest.mark.unit, pytest.mark.safety]
ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "docs" / "CITADEL_MODULE_ARCHITECTURE.md"
DECISIONS = ROOT / "docs" / "DECISIONS.md"
PAGE = ROOT / "citadel-dashboard" / "src" / "app" / "page.tsx"


def test_permanent_module_roles_and_veto_are_documented():
    architecture = ARCHITECTURE.read_text(encoding="utf-8")

    for role in (
        "ARGUS — Options Positioning Intelligence",
        "KRONOS — Setup Quality & Timing Intelligence",
        "Technical Market Engine — Current `OracleService`",
        "ATHENA — Risk & Capital Intelligence",
        "HERMES — News & Event Intelligence",
        "ORACLE — Personal AI Trading Coach",
        "AEGIS — Final Decision Controller",
        "Risk Authorization — Absolute Hard Safety Gate",
    ):
        assert role in architecture
    assert "AEGIS cannot bypass Risk Authorization" in architecture
    assert "live_trading_enabled=false" in architecture


def test_compatibility_routes_and_frozen_dashboard_contract_remain_intact():
    page = PAGE.read_text(encoding="utf-8")
    decisions = DECISIONS.read_text(encoding="utf-8")

    assert "/v1/oracle/status" in decisions
    assert "/v1/oracle/assessment/{symbol}" in decisions
    assert "/v1/oracle/reasoning" in decisions
    assert 'eyebrow="07 / Technical Intelligence"' in page
    assert_single_centralized_polling_loop()
    assert "SAFE / Risk & Paper Control" in page
    assert "dashboardFooter.build" in page
    assert "Legacy Build • Vihaann" in (ROOT / "citadel-dashboard" / "src" / "dashboard" / "adapters" / "DashboardDataAdapter.ts").read_text(encoding="utf-8")


def test_live_trading_remains_disabled():
    settings = json.loads(
        (ROOT / "config" / "settings.json").read_text(encoding="utf-8")
    )

    assert settings["live_trading_enabled"] is False
