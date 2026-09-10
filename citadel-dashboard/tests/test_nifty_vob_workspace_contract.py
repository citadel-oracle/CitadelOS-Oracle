from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/app/page.tsx").read_text(encoding="utf-8")
COMPONENT = (ROOT / "src/components/institutional/NiftyVOBPanel.tsx").read_text(encoding="utf-8")
STYLES = (ROOT / "src/components/institutional/NiftyVOBPanel.module.css").read_text(encoding="utf-8")
AXIS_GEOMETRY = (ROOT / "src/components/institutional/vobAxisGeometry.ts").read_text(encoding="utf-8")
WORKSPACE_STYLES = (ROOT / "src/app/trading-workspace.module.css").read_text(encoding="utf-8")


def workspace_source() -> str:
    start = PAGE.index("function TradingWorkspace")
    end = PAGE.index("function PersonalOraclePanel")
    return PAGE[start:end]


def test_vob_has_one_mount_and_it_is_inside_trading_workspace():
    workspace = workspace_source()
    assert PAGE.count("<NiftyVOBPanel") == 1
    assert workspace.count("<NiftyVOBPanel") == 1
    assert workspace.index('aria-label="Operator Summary"') < workspace.index("<NiftyVOBPanel")
    assert workspace.index("<NiftyVOBPanel") < workspace.index('aria-label="Active Deployments"')


def test_vob_renders_only_timeframes_with_valid_zones_from_existing_projection():
    assert "const TIMEFRAMES: TimeframeKey[] = ['1m', '3m', '5m', '15m', '1h']" in COMPONENT
    assert "const visibleTimeframes = TIMEFRAMES.filter((timeframe) =>" in COMPONENT
    assert "timeframeData?.nearest_bullish_support || timeframeData?.nearest_bearish_resistance" in COMPONENT
    assert "visibleTimeframes.map((timeframe) =>" in COMPONENT
    assert "timeframe !== '1m'" not in COMPONENT
    assert 'data-timeframe={timeframe}' in COMPONENT
    assert "timeframeData?.nearest_bearish_resistance" in COMPONENT
    assert "timeframeData?.nearest_bullish_support" in COMPONENT
    assert "sourceSync?.latest_evaluated_1m" in COMPONENT
    assert 'className={`${styles.timeframeRow}' in COMPONENT
    assert 'role="table" aria-label="VOB timeframe matrix"' in COMPONENT


def test_vob_preserves_authoritative_strongest_and_lifecycle_fields():
    assert "data?.strongest_support ?? data?.nearest_support" in COMPONENT
    assert "data?.strongest_resistance ?? data?.nearest_resistance" in COMPONENT
    assert "supportZone?.status" in COMPONENT
    assert "resistanceZone?.status" in COMPONENT
    assert "zone.status === 'BROKEN'" in COMPONENT
    assert "zone.status === 'WEAKENING'" in COMPONENT
    assert "zone.status === 'TESTED'" in COMPONENT
    assert "timeframe.recently_broken" in COMPONENT
    assert "supportZone?.status" in COMPONENT
    assert "resistanceZone?.status" in COMPONENT
    assert "data?.strongest_confluence?.bullish" in COMPONENT
    assert "data?.strongest_confluence?.bearish" in COMPONENT


def test_vob_restores_one_semantic_axis_and_compact_operator_rows():
    assert 'aria-label="Nearest support spot resistance axis"' in COMPONENT
    assert "buildVobAxisGeometry(spot, data?.nearest_support, data?.nearest_resistance)" in COMPONENT
    assert "left: `${axisGeometry.spot}%`" in COMPONENT
    assert "width: `${axisGeometry.supportWidth}%`" in COMPONENT
    assert "width: `${axisGeometry.resistanceWidth}%`" in COMPONENT
    assert "styles.axisSupport" in COMPONENT
    assert "styles.axisResistance" in COMPONENT
    assert "buildVobAxisGeometry(spot, supportZone, resistanceZone)" in COMPONENT
    assert 'data-row-spot={timeframe}' in COMPONENT
    assert "left: `${rowAxisGeometry.spot}%`" in COMPONENT
    assert "supportZone.touch_count" in COMPONENT
    assert "resistanceZone.touch_count" in COMPONENT
    assert "Evaluated through" in COMPONENT
    assert 'aria-label="Strongest VOB confluence"' in COMPONENT
    assert 'aria-label="Recent broken VOB zones"' in COMPONENT
    assert "timeframeBlock" not in COMPONENT


def test_vob_axis_history_uses_only_authoritative_zone_events():
    assert "zone.touch_count > 0 && zone.first_tested_time" in COMPONENT
    assert "zone.touch_count > 1 && zone.first_tested_time && zone.last_tested_time" in COMPONENT
    assert "if (!zone.broken_at) return" in COMPONENT
    assert "geometry.position((zone.zone_low + zone.zone_high) / 2)" in COMPONENT
    assert "data-axis-event={event.kind.toLowerCase()}" in COMPONENT
    assert "event.lane * 12" in COMPONENT
    assert "lanePositions.findIndex" in COMPONENT
    assert "MITIGATION" not in COMPONENT
    for glyph in ("'●'", "'◇'", "'↶'"):
        assert glyph in COMPONENT


def test_vob_runtime_states_and_unavailable_data_remain_truthful():
    for token in ("LIVE", "CATCHING_UP", "DEGRADED", "UNAVAILABLE", "VOB_PROJECTION_UNAVAILABLE"):
        assert token in COMPONENT
    assert "const formatPrice = (value" in COMPONENT
    assert "? 'Unavailable'" in COMPONENT
    assert "sourceSync?.runtime_status" in COMPONENT
    assert "Execution influence {data?.execution_influence ?? 0}%" in COMPONENT


def test_vob_strength_lifecycle_and_row_emphasis_are_presentation_only():
    for token in (
        "strengthUltra",
        "strengthStrong",
        "strengthModerate",
        "strengthWeak",
        "lifecycleActive",
        "lifecycleTested",
        "lifecycleBroken",
        "lifecycleWeakening",
        "rowActionable",
        "rowUltra",
        "rowBroken",
    ):
        assert f"styles.{token}" in COMPONENT
        assert f".{token}" in STYLES
    assert "supportZone?.status" in COMPONENT
    assert "resistanceZone?.status" in COMPONENT
    assert "supportZone.strength_score.toFixed(0)" in COMPONENT
    assert "resistanceZone.strength_score.toFixed(0)" in COMPONENT
    assert "Support strength ${supportStrength ?? 'not reported'}" in COMPONENT
    assert "Resistance strength ${resistanceStrength ?? 'not reported'}" in COMPONENT
    assert "supportStrength ?? 'Not reported'" in COMPONENT
    assert "resistanceStrength ?? 'Not reported'" in COMPONENT
    assert "sharedStrength" not in COMPONENT
    assert "confluence_info?.tier" in COMPONENT
    assert ".timeframeRows .lifecycleTested" in STYLES
    assert ".timeframeRows .strengthStrong" in STYLES
    assert ".confluenceStrip .strengthUltra" in STYLES


def test_vob_piecewise_axis_has_readable_bands_and_safe_clamping():
    for token in (
        "BELOW_SUPPORT_END = 10",
        "SUPPORT_END = 26",
        "RESISTANCE_START = 74",
        "RESISTANCE_END = 90",
        "if (value <= supportLow)",
        "if (value <= supportHigh)",
        "if (value <= resistanceLow)",
        "if (value <= resistanceHigh)",
        "clamp((value - priceStart)",
    ):
        assert token in AXIS_GEOMETRY
    assert "supportHigh >= resistanceLow" in AXIS_GEOMETRY


def test_vob_reuses_citadel_tokens_and_has_responsive_no_overflow_layout():
    for token in (
        "var(--cds-color-surface)",
        "var(--cds-border-default)",
        "var(--cds-radius-md)",
        "var(--cds-font-mono)",
        "var(--cds-type-caption-size)",
        "@media (max-width: 1180px)",
        "@media (max-width: 760px)",
        ".timeframeRow { grid-template-columns:",
        ".centralAxis",
        ".axisSpot",
        ".axisEventTouch",
        ".axisEventBreak",
        ".axisEventRetest",
        ".confluenceStrip",
        ".auditTable",
    ):
        assert token in STYLES
    assert "min-width: 0" in STYLES
    assert "overflow: hidden" in STYLES
    assert "grid-template-columns: minmax(0, 1fr);" in WORKSPACE_STYLES
    assert "style={{ marginBottom" not in COMPONENT
    assert "#f43f5e" not in COMPONENT
    assert "#10b981" not in COMPONENT
