from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src/app/strategies/page.tsx"
CSS = ROOT / "src/app/strategies/strategies.module.css"
ACTIONS = ROOT / "src/app/strategies/useStrategyCommandActions.ts"
PROD = ROOT / "src/app/page.tsx"
ORACLE = ROOT / "src/components/institutional/OracleWorkspacePanel.tsx"
NAVIGATION = ROOT / "src/components/institutional/CitadelPrimaryNavigation.tsx"
NAVIGATION_CSS = ROOT / "src/components/institutional/CitadelPrimaryNavigation.module.css"


def test_production_navigation_exposes_strategies_between_workspace_and_oracle():
    source = NAVIGATION.read_text()
    assert source.index("WORKSPACE") < source.index("STRATEGIES") < source.index(">ORACLE<")
    assert source.index(">ORACLE<") < source.index("ORACLE DEVELOPMENT")
    assert 'href="/strategies"' in source
    assert 'href="/oracle-development"' in source
    assert 'aria-label="Production dashboard"' in source
    assert "window.location.assign(`/?mode=${mode}`)" in source
    assert "CitadelPrimaryNavigation" in PROD.read_text()


def test_command_center_uses_canonical_feed_without_component_polling():
    source = PAGE.read_text()
    actions = ACTIONS.read_text()
    assert "feedSelectors.strategies" in source
    assert "setInterval" not in source
    assert "setInterval" not in actions
    assert "NEXT_PUBLIC_CITADEL_API_URL" in actions
    assert "/v1/strategies/deployments/" in actions


def test_registry_deployment_review_notifications_and_receipt_are_real_ui_contracts():
    source = PAGE.read_text()
    for label in (
        "Strategy Registry",
        "Independent Runtime Instances",
        "FINAL DEPLOYMENT REVIEW",
        "STRATEGY DEPLOYED SUCCESSFULLY",
        "NOTIFICATION CENTRE",
        "MULTI-TIMEFRAME CONSENSUS",
        "CONFIGURATION HASH",
        "RESUME",
        "OPEN RECEIPT",
        "VIEW IN ORACLE",
        "VIEW MISSION",
        "VIEW ORDER",
        "VIEW POSITION",
        "VIEW GUARDIAN",
        "VIEW LEDGER",
        "VIEW EVIDENCE",
        "REAL PAPER LIFECYCLE",
        "Intelligence modes",
        "EVIDENCE",
    ):
        assert label in source
    assert "fixture" not in source.lower()
    assert "mock" not in source.lower()
    assert "TODO" not in source
    assert "/resume" in ACTIONS.read_text()
    assert "formatConfigValue(config.position.fixed_lots)" in source
    assert "formatConfigValue(config.position.fixed_rupee_risk)" in source


def test_simple_and_advanced_present_same_instance_configuration():
    source = PAGE.read_text()
    assert "<SimpleConfiguration instance={instance}" in source
    assert "<AdvancedConfiguration instance={instance}" in source
    assert "configuration_schema.sections" in source


def test_oracle_dynamically_renders_canonical_strategy_instances():
    source = ORACLE.read_text()
    assert "strategiesData.oracle_instances" in source
    assert "Dynamically loaded strategy deployments" in source
    assert "configuration_hash" in source
    for label in (
        "Selected contract",
        "Mission",
        "Order / fill",
        "Position / Guardian",
        "Realized / unrealized P&amp;L",
        "Latest authoritative timestamp",
        "Contract-selection evidence",
    ):
        assert label in source
    assert "NOT REPORTED PER INSTANCE" not in source


def test_institutional_responsive_visual_contract():
    css = CSS.read_text()
    navigation_css = NAVIGATION_CSS.read_text()
    assert "#05070a" in css
    assert "var(--font-mono)" in css
    assert "@media(max-width:1100px)" in css
    assert "@media(max-width:760px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert "white-space: nowrap" in navigation_css
    assert "overflow-x: auto" in navigation_css
    assert "@media (max-width: 1050px)" in navigation_css
    assert "@media (max-width: 760px)" in navigation_css
