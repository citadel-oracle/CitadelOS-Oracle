from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "src/components/institutional/OracleWorkspacePanel.tsx"
COMPONENT = ROOT / "src/components/institutional/OracleFlowPulse.tsx"
STYLES = ROOT / "src/components/institutional/OracleFlowPulse.module.css"
PROVIDER = ROOT / "src/dashboard/providers/RestDashboardProvider.ts"


def source(path: Path) -> str:
    return path.read_text()


def test_real_oracle_mount_preserves_accepted_oracle_surfaces_and_uses_same_order_flow_feed():
    panel = source(PANEL)
    assert panel.count("<OracleFlowPulse feed={orderFlow} />") == 1
    assert panel.count("<FlowPulsePaperLedger feed={orderFlow} />") == 1
    assert panel.count("<OracleArgusPrime01C") == 1
    assert panel.index("<OracleLiveFlow") < panel.index("<OracleFlowPulse")
    assert panel.index("<OracleFlowPulse") < panel.index("<FlowPulsePaperLedger")
    assert panel.index("<FlowPulsePaperLedger") < panel.index("<OracleArgusPrime01C")
    assert panel.index("<OracleArgusPrime01C") < panel.index("<footer className={styles.oracleFooter}")
    for accepted_surface in (
        "<MissionHub",
        "id: 'thesis',",
        "id: 'argus',",
        "id: 'vob',",
        "id: 'ose',",
        "id: 'risk',",
        "id: 'guardian',",
        "<OracleFuturesVwapChart",
        "<OracleLiveFlow",
        "<OracleArgusPrime01C",
        "<PlanReadout",
        "<OracleAlertOverlay",
    ):
        assert accepted_surface in panel


def test_flow_pulse_is_score_free_and_has_no_transport_or_market_calculation():
    component = source(COMPONENT)
    for forbidden in (
        "axios", "EventSource(", "WebSocket(", "setInterval(",
        "prime_score", "gamma_score", "confidence", "weighted",
    ):
        assert forbidden not in component
    assert component.count("fetch(") == 1
    assert "/v1/oracle/flow-pulse/paper-history" in component
    assert "const pulse = record(data.flow_pulse)" in component
    assert "NO PRIME / GAMMA / QUALITY SCORE AUTHORITY" in component
    assert "ADVISORY · INFLUENCE ZERO" in component


def test_video_states_and_existing_liquid_glass_rails_are_rendered_without_blank_state():
    component = source(COMPONENT)
    assert "LiquidGlassRail" in component
    assert "WATCH · DATA PARTIAL" in component
    for label in ("MARKET", "PRESSURE", "SPEED", "RESULT", "KEY LEVEL", "NEXT LEVEL", "WHAT HAPPENED", "OPEN RANGE", "TRIGGER", "BUY", "EXIT IF", "TARGET 1", "TARGET 2", "HOLD"):
        assert label in component
    assert "OPTION QUOTE WAIT" in component
    for required in ("FUTURES STRUCTURAL LADDER", "NO LEVELS LOCKED", "NOW", "OPTION EXECUTION", "data-flow-pulse-paper-ledger"):
        assert required in component
    assert "paper_episodes" in component
    assert "FLOW PULSE LAB" in component
    assert "<details" in component
    assert "data-meter-revision" in component
    assert "flow.buy_volume" in component and "flow.sell_volume" in component and "flow.unknown_volume" in component
    for animation in ("invalidPulse", "entryBreatheCyan", "entryBreatheAmber", "targetPing", "liveDrift", "particleAcross"):
        assert animation in source(STYLES)


def test_strike_spine_distinguishes_oi_rate_flat_and_unavailable_and_baseline_is_bound():
    prime = source(ROOT / "src/components/institutional/OracleArgusPrime01C.tsx")
    panel = source(PANEL)
    assert "OI rate / accel / load" in prime
    assert "if (number === null) return 'UNAVAILABLE'" in prime
    assert "if (number === 0) return 'FLAT'" in prime
    assert "dominance={argusData.dominance}" in panel
    assert "WAITING FOR SESSION BASELINE" in prime
    assert "'INSUFFICIENT DATA'" not in prime


def test_production_recorder_coalesces_durable_writes_without_changing_queue_contract():
    app = source(ROOT.parent / "app/main.py")
    assert "coalesce_ms=250.0" in app


def test_single_existing_sse_and_no_flow_specific_polling():
    provider = source(PROVIDER)
    component = source(COMPONENT)
    assert provider.count("new EventSource(") == 1
    assert "EventSource(" not in component
    assert "setInterval(" not in component


def test_compact_responsive_surface_and_reduced_motion_contract():
    styles = source(STYLES)
    assert "@media(max-width:900px)" in styles
    assert "@media(max-width:620px)" in styles
    assert "@media(prefers-reduced-motion:reduce)" in styles
    assert "overflow:hidden" in styles
