from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "src/app/page.tsx").read_text(encoding="utf-8")
COMPONENT = (ROOT / "src/components/institutional/OptionsStructurePanel.tsx").read_text(encoding="utf-8")
STYLES = (ROOT / "src/components/institutional/OptionsStructurePanel.module.css").read_text(encoding="utf-8")
GEOMETRY = (ROOT / "src/components/institutional/oseVisualGeometry.ts").read_text(encoding="utf-8")
FLAGSHIP = (ROOT / "src/components/institutional/OseFlagshipComponents.tsx").read_text(encoding="utf-8")


def workspace():
    start = PAGE.index("function TradingWorkspace")
    return PAGE[start:]


def test_ose_renders_once_after_frozen_vob_before_deployments():
    body = workspace()
    assert PAGE.count("<OptionsStructurePanel") == 1
    assert body.index("<NiftyVOBPanel") < body.index("<OptionsStructurePanel")
    assert body.index("<OptionsStructurePanel") < body.index('aria-label="Active Deployments"')


def test_ose_renders_backend_projection_without_fetch_or_authoritative_recalculation():
    assert "strategyLab.data?.execution?.options_structure" in PAGE
    assert "fetch(" not in COMPONENT
    assert "EMA" in COMPONENT and "Supertrend" in COMPONENT
    assert "executionInfluence" in COMPONENT
    assert "Advisory only" in COMPONENT
    assert "data-canonical-digest" in COMPONENT


def test_flagship_contract_comparison_and_progressive_disclosure_exist():
    for text in (
        "CE VS PE", "structure.timeframe.toUpperCase()", "Structural Strength Index",
        "Raw score inputs and reasons", "Canonical / API / Render",
    ):
        assert text in COMPONENT
    for text in ("VOB STRUCTURE", "TREND ENGINE", "WHY {ssi.score}?", "ARGUS LIVE OPTION FLOW"):
        assert text in FLAGSHIP
    assert "contractGrid" in COMPONENT
    assert "@media (max-width: 1180px)" in STYLES
    assert "@media (max-width: 720px)" in STYLES


def test_dynamic_axes_render_only_backend_events_and_real_premium():
    assert "structure.premium" in COMPONENT
    assert "structure.demand_break" in COMPONENT
    assert "structure.supply_break" in COMPONENT
    assert "structure.bullish_retest" in COMPONENT
    assert "structure.bearish_retest" in COMPONENT
    assert 'data-event-type="TOUCH"' in COMPONENT
    assert 'data-event-type="BREAK"' in COMPONENT
    assert 'data-event-type="RETEST"' in COMPONENT


def test_five_state_wheel_and_normalized_duel_geometry_are_centralized():
    assert "wheelPosition(state)" in FLAGSHIP
    assert "precisionWheelNeedle(state)" in FLAGSHIP
    assert "duelMarkerPosition(duel.ce_score, duel.pe_score)" in COMPONENT
    assert "50 + duel.delta / 2" not in COMPONENT
    for value in ("ULTRA BEARISH", "BEARISH", "NEUTRAL", "BULLISH", "ULTRA BULLISH"):
        assert value in GEOMETRY
    assert "(pe / total) * 100" in GEOMETRY


def test_distinct_vob_precision_and_trend_energy_wheels_share_geometry():
    assert "<VobPrecisionWheel" in COMPONENT and "<TrendEnergyRing" in COMPONENT
    assert FLAGSHIP.count('data-arc-layer=') == 3
    assert "energyContinuous" in FLAGSHIP and "energyTexture" in FLAGSHIP and "energyTrace" in FLAGSHIP
    assert "precisionWheelNeedle(state)" in FLAGSHIP and "trendInstrumentNeedle(state)" in FLAGSHIP
    assert 'data-wheel-kind="VOB"' in FLAGSHIP and 'data-wheel-kind="TREND"' in FLAGSHIP
    assert "feTurbulence" in FLAGSHIP and "feDisplacementMap" in FLAGSHIP


def test_trend_animation_is_live_state_driven_and_stale_static():
    assert "state.quality.status === 'LIVE' && state.quality.freshness === 'FRESH'" in COMPONENT
    assert "animated ? 'ACTIVE' : 'STATIC'" in FLAGSHIP
    assert "energyAnimated.energyUltraBull" in STYLES
    assert "energyAnimated.energyBear" in STYLES
    assert "energyAnimated.energyUltraBear" in STYLES
    assert "prefers-reduced-motion: reduce" in STYLES
    assert ".energyAnimated, .energySparkAnimated { animation: none !important; }" in STYLES
    assert "instrumentStale .energyContinuous" in STYLES


def test_argus_flow_is_one_backend_authored_advisory_section():
    assert FLAGSHIP.count('aria-label="ARGUS Live Option Flow Edge"') == 1
    assert "data?.option_flow" in COMPONENT
    assert "flow.balance_marker" in FLAGSHIP
    assert "Last snapshot:" in FLAGSHIP and "flowDeadZone" in FLAGSHIP
    assert "fetch(" not in COMPONENT + FLAGSHIP


def test_composite_explanation_and_timeframe_hierarchy_are_presentation_only():
    assert "state.composite.explanation" in COMPONENT
    assert "Composite explanation unavailable" in COMPONENT
    assert "EARLY STRUCTURE" in COMPONENT
    assert "PRIMARY CONFIRMATION" in COMPONENT
    assert 'data-timeframe-role={primary ? \'PRIMARY_CONFIRMATION\' : \'EARLY_STRUCTURE\'}' in COMPONENT
    assert "primaryAxis" in STYLES and "earlyAxis" in STYLES


def test_latest_lifecycle_fallback_and_axis_mount_count_are_deterministic():
    assert "latestLifecycleSummary(structure)" in COMPONENT
    assert "Latest: No confirmed break" in GEOMETRY
    assert COMPONENT.count("<StructureAxis structure=") == 2
    assert "recently_broken" in COMPONENT


def test_structural_read_is_compact_advisory_backend_authored_copy():
    assert 'aria-label="Current structural read"' in COMPONENT
    assert "Advisory only" in COMPONENT
    assert "data.structural_read.lines" in COMPONENT
    assert "buy" not in COMPONENT.lower()
    assert "sell" not in COMPONENT.lower()


def test_no_execution_or_mutation_surface_exists():
    forbidden = ("fetch(", "method: 'POST'", "method: 'PUT'", "method: 'PATCH'", "method: 'DELETE'", "placeOrder", "submitOrder", "executeTrade")
    assert not any(value in COMPONENT + FLAGSHIP for value in forbidden)
    assert "live_trading_enabled" in COMPONENT
    assert "broker_submission" in COMPONENT


def test_ssi_agreement_decision_and_transition_are_backend_rendered():
    assert "state.ssi" in COMPONENT
    assert "state.decision_window" in COMPONENT
    assert "state.latest_state_change" in COMPONENT
    assert "data?.engine_agreement" in COMPONENT
    assert "ssi.breakdown.map" in FLAGSHIP
    assert "sum(" not in FLAGSHIP


def test_unique_svg_filters_accessibility_and_static_glow_contract():
    assert FLAGSHIP.count("useId()") == 2
    assert "ose-vob-glow-${instance}" in FLAGSHIP
    assert "ose-energy-glow-${instance}" in FLAGSHIP
    assert FLAGSHIP.count('role="img"') == 2
    assert "aria-label={`VOB Structure:" in FLAGSHIP
    assert "aria-label={`Trend Engine:" in FLAGSHIP
    assert "overflow: visible" in STYLES
