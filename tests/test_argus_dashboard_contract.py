from pathlib import Path

import pytest
from tests.frontend_dashboard_contract import (
    assert_centralized_feed,
    assert_last_good_stale_recovery,
    assert_single_centralized_polling_loop,
)


pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "citadel-dashboard" / "src" / "app" / "page.tsx"
TACTICAL = (
    ROOT
    / "citadel-dashboard"
    / "src"
    / "components"
    / "institutional"
    / "ArgusTacticalEdgePanel.tsx"
)


def page_source():
    return PAGE.read_text(encoding="utf-8") + TACTICAL.read_text(encoding="utf-8")


def test_argus_phase_three_compact_read_only_panel_contract():
    source = page_source()

    assert "['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']" in source
    assert "Seven strike breadth" in source
    assert "data.why?.observed" in source
    assert "data.pressure" in source
    assert "UNAVAILABLE" in source
    assert_centralized_feed("argus", "argus")
    assert "placeOrder" not in source
    assert "submitOrder" not in source
    assert "executeOrder" not in source
    assert "method: 'POST'" not in source


def test_argus_phase_three_one_polling_and_stale_preservation_contract():
    source = page_source()

    assert_single_centralized_polling_loop()
    assert_last_good_stale_recovery()
    assert "Last canonical projection retained" in source
    assert "<ArgusUnavailable error={argus.error} />" in source
    assert "ARGUS</span><strong>UNAVAILABLE" in source
    assert "No current OI assessment available" in source
    assert "AUTH_FAILED" in source
    assert "PROVIDER_ERROR" in source


def test_documented_backend_maturity_uses_truthful_states_only():
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    table = status.split("## Backend capability truth", 1)[1].split(
        "## FastAPI route inventory", 1
    )[0]
    states = {
        line.split("|")[2].strip()
        for line in table.splitlines()
        if line.startswith("|") and "Capability" not in line and "---" not in line
    }

    assert states
    assert states <= {"VERIFIED", "PARTIAL", "STUBBED", "NOT STARTED"}
