from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "citadel-dashboard/src/components/institutional/OracleWorkspacePanel.tsx"
CSS = ROOT / "citadel-dashboard/src/app/oracle/oracle.module.css"


def source() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_primary_orbit_has_exactly_six_role_aligned_providers():
    panel = source()
    assert "type NodeId = 'thesis' | 'argus' | 'vob' | 'ose' | 'risk' | 'guardian'" in panel
    for label in (
        "MARKET THESIS",
        "OPTIONS FLOW — ARGUS",
        "STRUCTURE — VOB",
        "PREMIUM STRUCTURE — OSE",
        "RISK + DISCIPLINE",
        "POSITION + GUARDIAN",
    ):
        assert label in panel
    for removed in ("title: 'OpenAlgo Analyzer'", "title: 'Trade Planner'", "title: 'Paper Engine'"):
        assert removed not in panel


def test_every_provider_exposes_truth_lineage_and_unavailable_semantics():
    panel = source()
    assert panel.count("title: 'Truth lineage'") == 6
    for field in ("Authority", "Instrument / timeframe", "Source timestamp", "Freshness"):
        assert field in panel
    assert "NOT REPORTED" in panel and "UNAVAILABLE" in panel and "STALE" in panel
    assert "paper.open_position_count)" in panel  # null remains NOT REPORTED, never zero-filled


def test_contract_lineage_is_exact_and_argus_feeds_ose():
    panel = source()
    assert "exactOption?.exact_contract.trading_symbol" in panel
    assert "exactOption?.exact_contract.security_id" in panel
    assert "ARGUS → OSE dependency" in panel
    assert "ARGUS existing rank + canonical Dhan quote" in panel
    assert "OSE pair context" not in panel


def test_center_is_decision_envelope_authority_without_probability_label():
    panel = source()
    hub = panel[panel.index("function MissionHub"):panel.index("function InspectionDrawer")]
    for field in (
        "Setup quality", "Entry band", "Structural SL", "Natural targets", "Trigger",
        "RR after costs", "WHY", "WHY NOT", "AUTHORITY FALSE",
    ):
        assert field in hub
    assert "Confidence" not in hub
    assert "historical_probability" not in hub
    assert "liveDecision?.action" in hub


def test_proof_drawer_binds_evidence_second_brain_and_source_locators():
    panel = source()
    for field in (
        "Supporting evidence", "Conflicting evidence", "Missing evidence", "Visual claims",
        "Knowledge source locators", "Related historical trades", "Journal links",
        "OBSIDIAN links", "Constitution", "Snapshot hashes",
    ):
        assert field in panel
    assert "PROBABILITY NOT AVAILABLE" in panel


def test_system_diagnostics_are_secondary_and_openalgo_has_zero_vote():
    panel = source()
    system = panel[panel.index('aria-label="System and execution health"'):panel.index('aria-label="Oracle execution graph"')]
    assert "SYSTEM / EXECUTION HEALTH" in system
    assert "OpenAlgo diagnostic" in system and "ZERO ANALYSIS VOTE" in system
    assert "Strategy / research registry" in system
    assert "data-engine-node=\"openalgo\"" not in panel


def test_position_guardian_projection_is_read_only_and_truthful_when_inactive():
    panel = source()
    guardian = panel[panel.index("title: 'POSITION + GUARDIAN'"):panel.index("const selectedNode")]
    assert "Read-only paper supervision" in guardian
    assert "NO ACTIVE POSITION" in guardian
    assert "Guardian action" in guardian and "Reconciliation" in guardian
    assert "onClick" not in guardian


def test_tradingview_strip_and_frozen_geometry_remain():
    panel = source()
    css = CSS.read_text(encoding="utf-8")
    for label in ("RAW / NORMALIZED", "EXACT IDENTITY", "TIMEFRAME", "CHART READY", "SOURCE AGE", "TRANSPORT"):
        assert label in panel
    assert 'viewBox="0 0 1200 760"' in panel
    assert "className={styles.graphShell}" in panel
    assert "className={styles.oracleHub}" in panel
    assert ".node_thesis" in css and ".node_ose" in css
    assert "radial-gradient" in css and "oracle-rotate" in css


def test_alert_preferences_and_deduplication_survive_realignment():
    panel = source()
    for value in (
        "deduplication_key", "cooldown_seconds", "criticalOnly", "marketHoursOnly",
        "Alert volume", "DISCIPLINE_REVIEW", "DISCIPLINE_COOLDOWN",
    ):
        assert value in panel


def test_provider_cards_and_inspection_drawer_have_no_mutation_action():
    panel = source()
    provider_surface = panel[panel.index("const EngineNode"):panel.index("function CommandControls")]
    for mutation in ("runtime.exitNow", "runtime.paperExecute", "runtime.createPlan", "runtime.cancel"):
        assert mutation not in provider_surface
