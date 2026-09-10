from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/app/page.tsx").read_text(encoding="utf-8")
PANEL = (ROOT / "src/components/institutional/ArgusEdgeLabPanel.tsx").read_text(encoding="utf-8")
CSS = (ROOT / "src/components/institutional/ArgusEdgeLabPanel.module.css").read_text(encoding="utf-8")


def test_edge_lab_is_mounted_once_directly_before_active_deployments():
    assert PAGE.count("<ArgusEdgeLabPanel") == 1
    edge_index = PAGE.index("<ArgusEdgeLabPanel")
    active_index = PAGE.index('aria-label="Active Deployments"', edge_index)
    assert edge_index < active_index
    assert "data={strategiesCommand.data?.edge_lab}" in PAGE


def test_edge_lab_ui_is_canonical_and_exposes_two_isolated_lanes():
    assert "fetch(" not in PANEL
    assert "ARGUS EDGE LAB" in PANEL
    assert "CALL LANE" in PANEL
    assert "PUT LANE" in PANEL
    assert "PAPER {healthySafety ? 'LOCKED' : 'CHECK'}" in PANEL
    assert "OPEN LEADERBOARD" in PANEL
    assert "100000" not in PANEL


def test_edge_lab_responsive_contract_and_reduced_motion():
    assert "@media (max-width: 900px)" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "overflow-x: auto" in CSS
