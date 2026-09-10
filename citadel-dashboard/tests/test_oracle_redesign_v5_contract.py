from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "src/components/institutional/OracleWorkspacePanel.tsx").read_text(encoding="utf-8")
CSS = (ROOT / "src/app/oracle/oracle.module.css").read_text(encoding="utf-8")
LAYOUT = (ROOT / "src/app/layout.tsx").read_text(encoding="utf-8")
PROVIDER = (ROOT / "src/dashboard/providers/RestDashboardProvider.ts").read_text(encoding="utf-8")


def test_v5_preserves_the_six_provider_orbit_and_single_decision_core():
    for provider in (
        "MARKET THESIS",
        "OPTIONS FLOW — ARGUS",
        "STRUCTURE — VOB",
        "PREMIUM STRUCTURE — OSE",
        "RISK + DISCIPLINE",
        "POSITION + GUARDIAN",
    ):
        assert provider in PANEL
    assert "type NodeId = 'thesis' | 'argus' | 'vob' | 'ose' | 'risk' | 'guardian'" in PANEL
    assert 'viewBox={`0 0 ${viewport.width} ${viewport.height}`}' in PANEL
    assert "getBoundingClientRect()" in PANEL
    assert "data-provider-anchor" in PANEL and "data-hub-anchor" in PANEL
    assert "data-oracle-hub" in PANEL
    assert "liveDecision?.action" in PANEL
    assert "majority" not in PANEL.lower()


def test_v5_uses_locked_palette_typography_and_bracket_language():
    for token in (
        "--bg-0: #050506",
        "--bg-1: #0a0708",
        "--panel: #0d0a0b",
        "--red: #ff3b54",
        "--green: #4ade80",
        "--steel: #b9bcc2",
        "--ivory: #f3f1ee",
    ):
        assert token in CSS
    for font in ("Space_Grotesk", "Inter", "JetBrains_Mono"):
        assert font in LAYOUT
    assert ".cornerTop" in CSS and ".cornerBottom" in CSS
    assert ".engineNode::before" in CSS and ".engineNode::after" in CSS
    for forbidden in ("#22d3ee", "#8b5cf6", "#fbbf24"):
        assert forbidden not in CSS.lower()


def test_v5_binds_existing_authorities_without_recomputing_provider_logic():
    assert "const vob5m = record(record(vob.timeframes)['5m'])" in PANEL
    assert "const optionsStructure = record(execution.options_structure)" in PANEL
    assert "buildArgusProviderProjection" in PANEL
    assert "RiskAuthorizationService + Oracle Discipline Engine" in PANEL
    assert "Canonical Paper Engine + Independent Guardian" in PANEL
    assert "fetch(" not in PANEL
    assert "new EventSource" in PROVIDER
    assert "/v1/oracle/live-workspace/stream" in PROVIDER


def test_v5_center_exposes_truth_safety_and_missing_value_semantics():
    hub = PANEL[PANEL.index("function MissionHub"):PANEL.index("function InspectionDrawer")]
    for value in (
        "WHY / PROOF",
        "Provider evidence alignment",
        "Trigger condition",
        "Entry band",
        "Structural SL",
        "Natural targets",
        "RR after costs",
        "KNOWLEDGE",
        "MAIN BLOCKER",
        "ADVISORY ONLY · NO ORDER SENT · EXECUTION AUTHORITY FALSE",
    ):
        assert value in hub
    assert "NOT PROBABILITY" in hub
    assert "historical_probability" not in hub
    assert "NOT REPORTED" in PANEL and "UNAVAILABLE" in PANEL and "STALE" in PANEL


def test_v5_motion_is_bounded_accessible_and_responsive():
    assert "flowParticle" in PANEL and "animateMotion" in PANEL
    assert "@keyframes oracle-breathe" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "@media (max-width: 900px)" in CSS
    assert "@media (max-width: 620px)" in CSS
    assert "overflow-x: hidden" in CSS
    assert 'aria-haspopup="dialog"' in PANEL
    assert 'aria-label="Provider evidence alignment"' in PANEL
