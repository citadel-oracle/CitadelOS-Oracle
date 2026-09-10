from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "src" / "app" / "page.tsx"
ORACLE_PAGE = ROOT / "src" / "app" / "oracle" / "page.tsx"
ORACLE_PANEL = (
    ROOT / "src" / "components" / "institutional" / "OracleWorkspacePanel.tsx"
)
ORACLE_RUNTIME = ROOT / "src" / "app" / "oracle" / "useOracleMissionRuntime.ts"
ORACLE_STYLES = ROOT / "src" / "app" / "oracle" / "oracle.module.css"
PRIMARY_NAVIGATION = (
    ROOT / "src" / "components" / "institutional" / "CitadelPrimaryNavigation.tsx"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_primary_navigation_uses_shared_production_routes_without_dev_mode():
    source = read(HOME)
    nav = read(PRIMARY_NAVIGATION)
    assert nav.index("WORKSPACE") < nav.index("STRATEGIES") < nav.index(">ORACLE<")
    assert nav.index(">ORACLE<") < nav.index("ORACLE DEVELOPMENT")
    assert 'aria-label="Production dashboard"' in nav
    assert "> DEV<" not in nav
    assert "Development Mode" not in nav
    assert "CitadelPrimaryNavigation" in source
    assert "type DashboardMode = 'production' | 'workspace'" in source
    assert "stored === 'development'" not in source
    assert "dashboardMode === 'development'" not in source


def test_oracle_route_uses_centralized_dashboard_selectors():
    source = read(ORACLE_PAGE)

    for selector in (
        "feedSelectors.oracle",
        "feedSelectors.argus",
        "feedSelectors.riskStatus",
        "feedSelectors.paperStatus",
        "feedSelectors.strategyLab",
        "selectFeedMeta",
    ):
        assert selector in source
    assert "useDashboardSelector" in source
    assert "fetch(" not in source
    assert "axios" not in source


def test_oracle_route_preserves_exact_primary_navigation():
    source = read(ORACLE_PANEL)
    nav = read(PRIMARY_NAVIGATION)
    assert "CitadelPrimaryNavigation" in source
    assert nav.index("WORKSPACE") < nav.index("STRATEGIES") < nav.index(">ORACLE<")
    assert 'href="/oracle-development"' in nav


def test_oracle_workspace_has_no_static_or_simulated_opportunities():
    source = read(ORACLE_PAGE) + read(ORACLE_PANEL)

    for forbidden in (
        "ORACLE-V1-SIM",
        "Current Best Opportunity",
        "Top Ranked Opportunities",
        "Expected RR",
        "Actionable",
        "25100 CE",
        "25050 PE",
        "14:28:42",
    ):
        assert forbidden not in source


def test_oracle_workspace_is_advisory_and_paper_execution_only():
    source = read(ORACLE_PANEL)

    assert "ADVISORY ONLY · EXECUTION INFLUENCE ZERO" in source
    for node in (
        "id: 'thesis',",
        "id: 'argus',",
        "id: 'vob',",
        "id: 'ose',",
        "id: 'risk',",
        "id: 'guardian',",
    ):
        assert source.count(node) == 1
    for forbidden in (
        "placeOrder",
        "submitOrder",
        "authorizeOrder",
        "/v1/orders",
        "broker.place",
        "fetch(",
    ):
        assert forbidden not in source
    assert "LIVE LOCKED" in source
    assert "Paper Execute" in source


def test_oracle_workspace_exposes_canonical_dom_parity_fields():
    source = read(ORACLE_PANEL)

    for field in (
        "symbol",
        "signal",
        "bias",
        "confidence",
        "data-status",
        "market-data-as-of",
        "reasoning",
    ):
        assert f'data-oracle-field="{field}"' in source
    assert "NOT REPORTED" in source
    assert "oracleMeta?.stale_reason" in source


def test_mission_commands_use_backend_contracts_without_dashboard_polling_duplication():
    route = read(ORACLE_PAGE)
    runtime = read(ORACLE_RUNTIME)

    assert "useOracleMissionRuntime" in route
    assert "fetch(" not in route
    assert runtime.count("setInterval(") == 1
    assert "/v2/dashboard" not in runtime
    for endpoint in (
        "/v1/oracle/missions/active",
        "/v1/oracle/missions",
        "/evaluate",
        "/plan",
        "/paper-execute",
        "/cancel",
        "/exit",
        "/guardian",
    ):
        assert endpoint in runtime
    assert "requested_quantity" not in runtime
    assert "execution_allowed: false" in runtime
    assert "live_trading_enabled: false" in runtime
    assert "broker_submission: false" in runtime


def test_oracle_controls_are_gated_by_canonical_state():
    source = read(ORACLE_PANEL)

    assert "canonicalAvailable" in source
    assert "gate.decision !== 'NO_TRADE'" in source
    assert "['CONFIRM', 'PAPER_AUTOPILOT']" in source
    assert "guardian?.state === 'OPEN'" in source
    assert "runtime.busyAction !== null" in source
    assert "plan ? money(plan.maximum_entry)" in source


def test_oracle_execution_graph_preserves_locked_visual_contract():
    source = read(ORACLE_PANEL)
    styles = read(ORACLE_STYLES)

    assert 'aria-label="Oracle execution graph"' in source
    assert 'data-oracle-hub' in source
    assert "Evidence → Gate" not in source  # visual flow is represented, not fabricated text
    assert ".graphShell" in styles
    assert ".oracleHub" in styles
    assert ".engineNode" in styles
    assert ".evidenceEdges" in styles
    assert ".executionEdges" in styles
    assert "@media (max-width: 900px)" in styles
    assert "overflow-x: hidden" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_oracle_nodes_are_compact_truthful_and_semantically_colored():
    source = read(ORACLE_PANEL)
    styles = read(ORACLE_STYLES)

    assert "metrics.slice(0, 2)" in source
    assert "metrics.slice(2, 5)" in source
    for vote in (
        "SUPPORTS CALL",
        "SUPPORTS PUT",
        "NEUTRAL",
        "CONFLICTS",
        "BLOCKS",
        "NOT REPORTED",
    ):
        assert vote in source
    assert "NOT PROBABILITY" in source
    assert "tone_call" in styles
    assert "tone_put" in styles
    assert "tone_blocked" in styles
    assert "--oracle-block" in styles


def test_oracle_inspection_drawer_is_single_keyboard_accessible_surface():
    source = read(ORACLE_PANEL)
    styles = read(ORACLE_STYLES)

    assert source.count('id="oracle-inspection-drawer"') == 1
    assert 'aria-haspopup="dialog"' in source
    assert 'aria-modal="false"' in source
    assert "event.key === 'Escape'" in source
    assert 'aria-label="Close inspection drawer"' in source
    assert "styles.inspectionDrawer" in source
    assert ".inspectionDrawer" in styles
    assert "max-height: 48vh" in styles


def test_oracle_connector_current_is_state_aware_without_visual_polling():
    source = read(ORACLE_PANEL)
    styles = read(ORACLE_STYLES)
    runtime = read(ORACLE_RUNTIME)

    for stage in (
        "IDLE",
        "ANALYSING",
        "EVALUATED",
        "QUALIFIED",
        "PLANNED",
        "SUBMITTING",
        "OPEN",
        "EXITING",
        "CLOSED",
    ):
        assert stage in source
    assert 'data-workflow-stage={stage}' in source
    assert 'data-edge-node={id}' in source
    assert 'data-vote={vote}' in source
    assert 'data-provider-anchor={id}' in source
    assert 'data-hub-anchor={id}' in source
    assert "visibilitychange" in source
    assert runtime.count("setInterval(") == 1
    assert "@keyframes oracle-current-in" in styles
    assert '[data-page-visible="false"]' in styles


def test_oracle_uses_nested_canonical_argus_tactical_projection():
    source = read(ORACLE_PANEL)

    assert "const argusEnvelope = record(argus.data)" in source
    assert "const argusData = record(argusEnvelope.data)" in source
    assert "const tactical = record(argusData.tactical_edge)" in source
    assert "argusProvider.providerLineageAvailable" in source
    assert "argusProvider.exactContractLineageAvailable" in source
    assert "tactical.source_timestamp" in source
    assert "(!activeUnderlying || tacticalSymbol.toUpperCase() === activeUnderlying.toUpperCase())" in read(
        ORACLE_PANEL.parent / "oracleArgusProjection.ts"
    )


def test_demo_tour_visibility_reuses_the_single_oracle_workspace():
    source = read(ORACLE_PANEL)
    runtime = read(ORACLE_RUNTIME)

    assert "missionRuntime.demoTour?.status" in source
    assert "NON-CANONICAL" in source
    assert runtime.count("'/v1/oracle/demo-tour'") == 1
    assert "execution_origin?: 'DEMO_PAPER'" in runtime


def test_oracle_route_uses_one_cache_only_fast_lane_provider():
    provider = read(ROOT / "src/dashboard/providers/RestDashboardProvider.ts")
    app_providers = read(ROOT / "src/providers/AppProviders.tsx")

    assert "new RestDashboardProvider(oracleRoute)" in app_providers
    assert "[oracleRoute]" in app_providers
    assert "'/oracle'" in app_providers
    assert "/v1/oracle/fast-lane" in provider
    assert "/v1/oracle/fast-lane/stream" in provider
    assert "applyFastLaneEvent" in provider
    assert provider.count("new EventSource(") == 1
    assert "frontend calculation" not in provider.lower()
