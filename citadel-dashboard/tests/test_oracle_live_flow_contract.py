from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "src/components/institutional/OracleWorkspacePanel.tsx"
PAGE = ROOT / "src/app/oracle/page.tsx"
FLOW = ROOT / "src/components/institutional/OracleLiveFlow.tsx"
FLOW_CSS = ROOT / "src/components/institutional/OracleLiveFlow.module.css"
FIXTURE = ROOT / "src/components/institutional/OracleLiveFlow.fixture.ts"
CHART = ROOT / "src/components/institutional/OracleFuturesVwapChart.tsx"
CHART_CSS = ROOT / "src/components/institutional/OracleFuturesVwapChart.module.css"
TYPES = ROOT / "src/dashboard/types/index.ts"
SELECTORS = ROOT / "src/dashboard/selectors/index.ts"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_oracle_order_is_main_then_futures_then_live_flow_then_argus_prime():
    panel = read(PANEL)
    assert panel.count("<OracleFuturesVwapChart") == 1
    assert panel.count("<OracleLiveFlow") == 1
    assert panel.count("<OracleArgusPrime01C") == 1
    # Component definitions precede the workspace JSX, so compare the final
    # render-site occurrences instead of import/helper locations.
    assert panel.rindex("<OracleAlertOverlay") < panel.rindex("<OracleFuturesVwapChart")
    assert panel.rindex("<OracleFuturesVwapChart") < panel.rindex("<FlowPulseStoreBridge")
    assert panel.rindex("<FlowPulseStoreBridge") < panel.rindex("<OracleArgusPrime01C")
    assert panel.rindex("<OracleArgusPrime01C") < panel.rindex("<footer className={styles.oracleFooter}")


def test_live_flow_uses_provider_store_selector_path_without_fetch_or_scoring():
    page = read(PAGE)
    flow = read(FLOW)
    types = read(TYPES)
    selectors = read(SELECTORS)
    panel = read(PANEL)
    # Order Flow is selected in the memoized store bridge so tick updates do
    # not rerender the full Oracle workspace.
    assert "feedSelectors.orderFlow" in panel
    assert "feedSelectors.futuresChart" in page
    assert "'order_flow', 'futures_chart'" in types
    assert "selectFeed<unknown>('order_flow')" in selectors
    assert "selectFeed<unknown>('futures_chart')" in selectors
    for forbidden in ("fetch(", "axios", "EventSource(", "WebSocket(", "setInterval(", "calculateFlow", "computeFlow", "scoreFlow"):
        assert forbidden not in flow


def test_live_flow_renders_backend_action_and_truthful_missing_levels():
    flow = read(FLOW)
    for action in ("BUY CALL", "BUY PUT", "PROTECT / EXIT", "NO TRADE"):
        assert action in flow
    assert "WAIT — LEVELS UNAVAILABLE" in flow
    assert "NO AUTHORIZED CONTRACT" in flow
    assert "SHADOW · LIVE VALIDATION PENDING" in flow
    assert "SCORE IS NOT PROBABILITY" in flow
    assert "NOT YET AVAILABLE" in flow
    assert "GREEKS UNAVAILABLE" in flow
    assert 'profile.status === \'AVAILABLE\'' in flow


def test_flow_lab_has_locked_research_sections_and_no_claimed_validation():
    flow = read(FLOW)
    for label in (
        "Current episode", "Today", "Score edge · researching", "Best combination",
        "Reversal log", "Event timeline", "Edge health", "Shadow P&amp;L", "Provenance",
    ):
        assert label in flow
    assert "maturity" in flow
    assert 'maturity: \'VALIDATED\'' not in flow
    assert "ENGINEERING DEFAULTS, NOT VALIDATED" in flow


def test_futures_chart_is_candles_and_vwap_only_without_direct_fetch():
    chart = read(CHART)
    assert "CandlestickSeries" in chart
    assert "LineSeries" in chart
    assert "VWAP" in chart
    assert "session_profile" in chart
    assert "POC" in chart
    assert "const levels = [{ title: 'POC'" in chart
    assert "current_price" in chart
    assert "LAST GOOD" not in chart
    assert "freshness === 'FRESH'" in chart
    assert "createPriceLine" in chart
    assert "priceToCoordinate" in chart
    for forbidden in ("HistogramSeries", "VOB", "FVG", "GUARDIAN", "refreshScheduler"):
        assert forbidden not in chart
    assert chart.count("fetch(") == 1
    assert "if (!hudAuditCollector" in chart


def test_visual_fixtures_cover_required_states_and_never_activate_in_production():
    fixture = read(FIXTURE)
    panel = read(PANEL)
    for name in ("'call'", "'put'", "'wait'", "'chase'", "'absorption'", "'reversal'", "'degraded'"):
        assert name in fixture
    assert "TEST FIXTURE" in read(FLOW)
    assert "process.env.NODE_ENV !== 'production'" in panel


def test_live_flow_visual_motion_responsive_and_reduced_motion_contract():
    styles = read(FLOW_CSS)
    assert "#2ff0d8" in styles
    assert "#ffc93c" in styles
    assert "#ff1447" in styles
    assert "width: 100%" in styles
    assert "font-size: 30px" in styles
    for animation in (
        "blink", "barGlow", "ringPop", "pulseRed", "particleL", "particleR",
        "invalidPulse", "entryBreatheCyan", "entryBreatheAmber", "entryBreatheGray",
        "bubbleRise", "targetPing", "liveDrift", "cometFade",
    ):
        assert f"@keyframes {animation}" in styles
    assert "--flow-call" in styles and "--flow-put" in styles
    assert "var(--font-oracle-display)" in styles
    assert "var(--font-oracle-body)" in styles
    assert "var(--font-oracle-data)" in styles
    assert "@media (max-width: 520px)" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_particle_count_speed_and_ladder_motion_match_v2_contract():
    flow = read(FLOW)
    styles = read(FLOW_CSS)
    assert "percent >= 70 ? 4 : percent >= 40 ? 3 : 2" in flow
    assert "Math.max(1.3, 3.6 - (percent / 100) * 2.3)" in flow
    assert "Math.max(0, percent - 3)" in flow
    assert '<ParticleStream percent={callPercent} side="call" />' in flow
    assert '<ParticleStream percent={putPercent} side="put" />' in flow
    assert "'--target-delay': '.9s'" in flow
    assert "NO LEVELS LOCKED" in flow
    assert "currentMarkerTone" in flow
    assert "LIVE {money(currentPremium)}" in flow
    assert "animation: invalidPulse 1.6s ease-in-out infinite" in styles
    assert "animation: bubbleRise 2.2s ease-in infinite" in styles
    assert "animation: targetPing 2.4s ease-out infinite" in styles
    assert "animation: liveDrift 1.8s ease-in-out infinite" in styles
    assert "animation: liveLinePulse 1.8s ease-in-out infinite" in styles


def test_golden_semantics_keep_confirmation_and_alarm_narrow():
    flow = read(FLOW)
    fixture = read(FIXTURE)
    assert "decision.confirmed === true" in flow
    assert "action === 'BUY CALL' || action === 'BUY PUT'" in flow
    assert "const alert = action === 'PROTECT / EXIT'" in flow
    assert "BUY 5x STACKED · ABSORBED" in fixture
    assert "action: 'NO TRADE', reason: 'BUYERS_ABSORBED'" in fixture
    assert "ENTRY_EXTENSION_EXCEEDED" in fixture


def test_futures_chart_initializes_once_then_updates_without_live_fit():
    chart = read(CHART)
    assert chart.count("candleSeries.setData(") == 1
    assert chart.count("vwapSeries.setData(") == 1
    assert "candleSeries.update(" in chart
    assert "vwapSeries.update(" in chart
    assert chart.count("fitContent()") == 2
    assert "forecastFitIdentityRef" in chart
    assert "initializedIdentityRef" in chart
    assert "lastCandleRef" in chart
    assert "Asia/Kolkata" in chart
    assert "09:15-15:30" in chart
    assert "deduplicated.set(time" in chart
    assert ".sort((left, right) => left.time - right.time)" in chart


def test_futures_chart_timeframes_and_clean_market_reference_contract():
    chart = read(CHART)
    styles = read(CHART_CSS)
    for timeframe in ("'1m'", "'3m'", "'5m'", "'15m'"):
        assert timeframe in chart
    assert "selectedTimeframe" in chart
    assert "record(root.timeframes)[selectedTimeframe]" in chart
    assert "aria-pressed={selectedTimeframe === timeframe}" in chart
    assert "currentPriceLineRef" not in chart
    assert "axisLabelVisible: false" in chart
    assert "lastValueVisible: false" in chart
    assert "background: { color: '#030508' }" in chart
    assert "upColor: '#1f7a4d'" in chart
    assert "borderUpColor: '#1f7a4d'" in chart
    assert "wickUpColor: '#1f7a4d'" in chart
    assert "downColor: '#ff3b54'" in chart
    assert "borderDownColor: '#ff3b54'" in chart
    assert "wickDownColor: '#ff3b54'" in chart
    assert "color: '#ff1447'" in chart
    assert "color: '#ffc93c'" in chart
    assert "'LAST GOOD'" not in chart
    assert "barSpacing: 8.5" in chart
    assert chart.count("series.createPriceLine(") == 1
    assert "data-profile-price={profile.poc}" in chart
    assert "data-profile-price={profile.vah}" not in chart
    assert "data-profile-price={profile.val}" not in chart
    assert "visualLiveFixture" in chart
    assert "livePriceBreathe" in styles
    assert "height: clamp(320px, 24vw, 348px)" in styles
    assert '.liveLegend[data-live="false"]' in styles
    assert "animation: none" in styles


def test_futures_chart_profile_is_canonical_and_render_only():
    chart = read(CHART)
    assert "normalizeSessionProfile" in chart
    assert "relative_volume" in chart
    assert "CANONICAL_1M_OHLCV_RANGE_DISTRIBUTION" not in chart
    for forbidden in ("calculateProfile", "computeProfile", "volume /", "valueAreaFraction"):
        assert forbidden not in chart
    assert 'data-profile-status={profile.status}' in chart
    assert 'PROFILE DEGRADED' in chart
    assert "data.status !== 'AVAILABLE' || candles.length === 0" in chart
    assert "feed.loading || feed.error" not in chart
