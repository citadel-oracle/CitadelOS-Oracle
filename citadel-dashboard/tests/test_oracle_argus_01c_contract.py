from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "src/components/institutional/OracleWorkspacePanel.tsx"
ARGUS_01C = ROOT / "src/components/institutional/OracleArgusPrime01C.tsx"
FIXTURE = ROOT / "src/components/institutional/OracleArgusPrime01C.fixture.ts"
STYLES = ROOT / "src/components/institutional/OracleArgusPrime01C.module.css"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_argus_01c_is_mounted_once_below_existing_oracle_content():
    panel = read(PANEL)
    assert panel.count("<OracleArgusPrime01C") == 1
    assert panel.index("<OracleAlertOverlay") < panel.index("<OracleArgusPrime01C")
    assert panel.index("<OracleArgusPrime01C") < panel.index("<footer className={styles.oracleFooter}")


def test_argus_01c_consumes_shared_projection_without_fetch_or_business_engine():
    source = read(ARGUS_01C)
    panel = read(PANEL)
    assert "tactical={tactical}" in panel
    assert "optionsStructure={optionsStructure}" in panel
    assert "provider={argusProvider}" in panel
    assert "optionsStructure={optionsStructure}" in panel
    for forbidden in (
        "fetch(",
        "axios",
        "setInterval(",
        "WebSocket(",
        "EventSource(",
        "Dhan",
        "computeArgus",
        "calculateArgus",
    ):
        assert forbidden not in source


def test_decision_rails_use_their_own_canonical_freshness_and_closed_market_truth():
    source = read(ARGUS_01C)
    panel = read(PANEL)
    page = read(ROOT / "src/app/oracle/page.tsx")
    types = read(ROOT / "src/dashboard/types/index.ts")
    selectors = read(ROOT / "src/dashboard/selectors/index.ts")
    assert "participation_baseline" in source
    assert "const istTimeText" in source
    assert "MARKET CLOSED · LAST VALID ${flowLastValid" in source
    assert "MARKET CLOSED · LAST VALID ${baselineLastValid" in source
    assert "const marketClosed = upper(marketState) === 'CLOSED'" in source
    assert "const officialMarketClosed = upper(structureData.market_state ?? marketState) === 'CLOSED'" in source
    assert "const flowPresentationLabel = officialMarketClosed && hasFlowSnapshot" in source
    assert "marketClosed ? flowStatusLabel : text(edge.label ?? edge.state)" in source
    assert "const flowState: RailState = marketClosed" in source
    assert "const baselineState: RailState = marketClosed" in source
    assert "feedSelectors.optionsStructure" in page
    assert "'options_structure'" in types
    assert "selectFeed<unknown>('options_structure')" in selectors
    assert "optionsStructure: optionsStructureFeed" in panel
    assert "marketState={argusUnderlying.market_state}" in panel
    assert "marketClosedAt={argusUnderlying.source_event_time}" in panel


def test_original_and_copied_01c_layers_share_exact_canonical_sources():
    source = read(ARGUS_01C)
    panel = read(PANEL)
    original = read(ROOT / "src/components/institutional/OptionsStructurePanel.tsx")
    original_flow = read(ROOT / "src/components/institutional/OseFlagshipComponents.tsx")
    legacy_workspace = read(ROOT / "src/app/page.tsx")

    # Structure: both surfaces consume the backend-owned OSE duel verbatim.
    assert "const duel = data?.duel" in original
    assert "const duel = record(structureData.duel)" in source
    assert "{upper(duel.state)}" in source
    assert "{text(duel.label)}" in source

    # Live Flow: both surfaces consume option_flow.edge; no copied classifier.
    assert "flow.edge?.label" in original_flow
    assert "const edge = record(flow.edge)" in source
    assert "text(edge.label ?? edge.state)" in source
    assert "const flowDelta = finite(edge.delta)" in source

    # Participation: retain the original ARGUS dominance and verdict regime.
    assert "snapshot.dominance.writer_dominance_percentage" in legacy_workspace
    assert "snapshot.verdict.regime" in legacy_workspace
    assert "dominance={argusData.dominance}" in panel
    assert "participationVerdict={record(argusData.verdict).regime}" in panel
    assert "writer_dominance_percentage" in source
    assert "buyer_dominance_percentage" in source
    assert "upper(participationVerdict" in source

    for forbidden in ("FLOW_EDGE_THRESHOLDS", "writerShare >=", "buyerShare >="):
        assert forbidden not in source


def test_argus_01c_contains_locked_information_architecture():
    source = read(ARGUS_01C)
    for label in (
        "Options Structure",
        "Options Structure Engine",
        "ARGUS Live Option Flow",
        "Tactical Summary",
        "Prime Decision Hub",
        "Outcome Intelligence",
        "Money / Wall / Gamma",
        "Live PCR",
        "Strongest Structural Strike",
        "Expiry Gamma Blast",
        "Enhanced Strike Spine",
        "VOB / Trend Lifecycle",
        "Risk Shape",
        "Why / Canonical Read",
        "Full Quant Evidence",
        "Canonical Decision Rails",
    ):
        assert label in source
    assert source.index('title="Canonical Decision Rails"') < source.index('title="Enhanced Strike Spine"')
    assert source.index('title="Enhanced Strike Spine"') < source.rindex('title="Options Structure Engine"')
    assert source.rindex('title="Options Structure Engine"') > source.index("Full Quant Evidence")


def test_argus_01c_signal_threshold_is_presentation_only_and_rearms():
    source = read(ARGUS_01C)
    assert "priorScore.current < 50 && score >= 50" in source
    assert "const canonicalDirection = upper(tacticalSummary.directional_posture ?? prime.direction, 'HOLD')" in source
    assert "const primeTone = primeToneFor(canonicalDirection, isFresh)" in source
    assert "score_is_probability" not in source
    assert "EDGE / READINESS · NOT PROBABILITY" in source
    assert 'data-signal-flip-count={flipCount}' in source
    assert "setFixtureScore(49)" in source
    assert "setFixtureScore(50)" in source
    assert "setFixtureScore(51)" in source


def test_argus_01c_truthfully_preserves_partial_and_unavailable_states():
    source = read(ARGUS_01C)
    assert "LAST_GOOD" in source
    assert "AGE UNAVAILABLE" in source
    assert "INCOMPLETE EVIDENCE · NO ZERO IMPUTATION" in source
    assert "NO STRIKE AUTHORIZED" in source
    assert "NO AUTHORIZED CONTRACT" in source
    assert "change_1m_state === 'AVAILABLE'" in source
    assert "change_5m_state === 'AVAILABLE'" in source


def test_argus_01c_visual_tokens_motion_and_responsive_contract():
    styles = read(STYLES)
    for token in (
        "--bg-0: #000",
        "--red: #ff1447",
        "--red-hi: #ff5c82",
        "--cyan: #2ff0d8",
        "--amber: #ffc93c",
        "--green: #4ade80",
        "--font-display",
        "--font-metric",
        "--font-body",
    ):
        assert token in styles
    for motion in (
        "@keyframes cardGlow",
        "@keyframes breathe",
        "@keyframes hubBreathe",
        "@keyframes ripple",
        "@keyframes pipelineDot",
        "@keyframes signalFlip",
        "@keyframes rowBreathe",
        "@keyframes tipPulse",
        "@keyframes scan",
        "@keyframes barGlow",
        "@keyframes radarReveal",
        "@keyframes refract",
        "@keyframes blobMorph",
        "@keyframes fillShift",
        "@keyframes kineticBreathe",
        "@keyframes ringPing",
    ):
        assert motion in styles
    assert "@media (max-width: 900px)" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert "animation-duration: .001ms" in styles


def test_argus_01c_locked_gauge_flow_and_risk_geometry():
    source = read(ARGUS_01C)
    assert "const ticks = [[15,70,10,60]" in source
    assert 'd="M12 70 A53 53 0 0 1 118 70"' in source
    assert 'strokeDasharray="166"' in source
    assert "Array.from({ length: 10 }" in source
    assert "segmentHazard" in source
    assert "['Pressure', bounded(pressurePrice.score)]" in source
    assert "['NO_DATA', 'HELD', 'LIVE', 'STALE']" in source


def test_argus_01c_stale_state_locks_live_motion_but_preserves_ambient_motion():
    source = read(ARGUS_01C)
    styles = read(STYLES)
    assert "const isFresh = freshnessPill === 'LIVE'" in source
    assert "if (!fresh) return 'slate'" in source
    assert 'data-freshness-active={isFresh' in source
    assert '.deck[data-freshness-active="false"]' in styles
    assert 'filter: saturate(.7)' not in styles
    assert '.panel { position: relative' in styles
    assert 'animation: cardGlow 4s ease-in-out infinite' in styles
    assert 'animation: scan 6s linear infinite' in styles
    stale_rule = styles[styles.index('.deck[data-freshness-active="false"] .pipeline i::after'):]
    assert 'animation-duration: .001ms' not in stale_rule.split('@media (prefers-reduced-motion: reduce)')[0]
    assert 'animation: none' in stale_rule
    assert '.deck[data-freshness-active="false"] .dialTip' not in styles


def test_argus_01c_reference_red_chrome_hub_and_animation_semantics():
    source = read(ARGUS_01C)
    styles = read(STYLES)
    for token in (
        '--bg-0: #000', '--bg-1: #050505', '--panel: #0a0507',
        '--panel-hi: #100609', '--line: #3a181e', '--line-soft: #2a0c15',
        '--red: #ff1447', '--red-hi: #ff5c82', '--red-dim: #5c0d22',
    ):
        assert token in styles
    assert 'width: 184px' in styles
    assert '0 0 48px' in styles
    assert '<i /><i /><i />' in source
    assert 'orbitMetric' not in source
    assert '@keyframes scan' in styles
    assert '@keyframes tipPulse' in styles
    assert '@keyframes breathe' in styles
    assert '@keyframes rowBreathe' in styles
    assert '@keyframes barGlow' in styles
    assert '@keyframes heatArrival' in styles
    assert 'className={styles.deckBackdrop}' in source
    assert '<LiquidGlassRail position={finite(pcr.oi_pcr)' in source
    assert '.signalFlourishLarge' in styles
    assert '.deckSignal' in styles


def test_argus_01c_premium_flow_pills_halos_rails_and_hover_chrome():
    source = read(ARGUS_01C)
    styles = read(STYLES)
    assert 'function canonicalOiState' in source
    assert 'function canonicalOiTone' in source
    assert 'function StrikeFlowPill' in source
    assert 'function ProbableFlowHelper' in source
    assert 'PROBABLE FLOW:' in source
    assert '<StrikeFlowPill state={ceOiState} side="CE" />' in source
    assert '<StrikeFlowPill state={peOiState} side="PE" />' in source
    assert '<ProbableFlowHelper arrow={ce.velocity_arrow} value={ce.probable_flow} />' in source
    assert '<ProbableFlowHelper arrow={pe.velocity_arrow} value={pe.probable_flow} />' in source
    for token in ('.flowPill', '.flow_green', '.flow_red', '.flow_amber', '.flow_slate'):
        assert token in styles
    assert 'function PrimeGlowRing' in source
    assert 'data-prime-glow-ring={variant}' in source
    assert '.primeGlowMain' in styles
    assert '.primeGlowMini' in styles
    assert source.count('<PrimeGlowRing') == 2
    assert 'function LiquidGlassRail' in source
    assert 'function DecisionRails' in source
    assert '.decisionRails' in styles
    assert 'state={structureState}' in source
    assert 'state={flowState}' in source
    assert 'position={buyerShare}' in source
    assert 'CANONICAL ATM±5 DOMINANCE' in source
    assert "const primeTone = primeToneFor(canonicalDirection, isFresh)" in source
    assert "if (/PUT|BEAR/.test(state)) return 'red'" in source
    assert "return 'amber'" in source
    assert 'data-prime-direction={canonicalDirection}' in source
    assert 'data-prime-tone={primeTone}' in source
    assert 'score !== null && score >= 50' not in source
    for token in ('.glassTrack', '.railFill', '.refractSweep', '.liquidThumb', '.kineticValue', '.frozenNode', '.pingRing'):
        assert token in styles
    assert '.railFill' in styles
    assert '.panel:hover' in styles
    assert '.panel:focus-visible' in styles
    assert 'animation: none' in styles


def test_argus_01c_outcome_semantic_colors_and_strike_oi_mapping():
    source = read(ARGUS_01C)
    styles = read(STYLES)
    for token in (
        '.outcomeCall { --ring-core: #2eff7d',
        '.outcomePut { --ring-core: #ff1447',
        '.outcomeHold { --ring-core: #ffc93c',
        '.outcomeDecay { --ring-core: #2ff0d8',
        '.outcomeBigMove { --ring-core: #ff9f43',
        '.outcomeGamma { --ring-core: #a970ff',
        '.outcomeReversal { --ring-core: #ff5c82',
    ):
        assert token in styles
    assert 'caption=""' in source
    assert "['CALL', 'call_edge']" in source
    assert "['PUT', 'put_edge']" in source
    assert "['HOLD', 'hold_edge']" in source
    assert "state === 'LONG BUILDUP' || state === 'SHORT COVERING'" in source
    assert "state === 'LONG UNWINDING' || state === 'SHORT BUILDUP'" in source
    assert '.flowMetaLine' in styles
    assert 'min-height: 27px' in styles
    assert 'background: #ff3b54' in styles
    assert 'border-color: #ff5c6c' in styles
    assert 'background: #1f7a4d' in styles
    assert 'border-color: #319864' in styles
    assert '.probableFlowHelper > span { overflow: hidden; color: #7a7376' in styles
    assert '.probableFlowHelper > b[data-unavailable="true"] { color: #b8b3b6; }' in styles
    assert '.probableFlowHelper' in styles
    assert 'translate3d(0,-50%,0)' in styles
    assert 'translate3d(0,50%,0)' in styles
    assert 'styles.flowCall' in source
    assert 'styles.flowPut' in source
    assert '.flowCall' in styles
    assert '.flowPut' in styles
    assert 'height: 13px' in styles
    assert 'height: 10px' in styles
    assert '.primeGlowCore::after' in styles


def test_argus_01c_black_dominant_surfaces_restrain_red_wash():
    styles = read(STYLES)
    assert 'var(--red) 3%' in styles
    assert 'linear-gradient(180deg, #020101, var(--bg-0) 28%)' in styles
    assert 'background: linear-gradient(180deg, #100609, #0a0507)' in styles
    assert 'border: 1px solid var(--line-soft)' in styles
    assert '.deck[data-freshness-active="true"] .panel' not in styles


def test_argus_01c_full_ose_contract_coverage_uses_supplied_projection():
    source = read(ARGUS_01C)
    for field in (
        "{side} CONTRACT", "{timeframe.toUpperCase()} STRUCTURE", 'DECISION WINDOW', 'ENGINE AGREEMENT',
        'EMA50', 'SUPERTREND 10 / 3.4',
        'LATEST STATE CHANGE', 'SSI contribution lineage',
    ):
        assert field in source
    assert '<OseContractDetail side="CE" contract={ce}' in source
    assert '<OseContractDetail side="PE" contract={pe}' in source


def test_argus_01c_holographic_rails_are_canonical_presentation_only():
    source = read(ARGUS_01C)
    panel = read(PANEL)
    styles = read(STYLES)
    assert 'function LiquidGlassRail' in source
    assert 'Presentation-only geometry for canonical values' in source
    assert 'marketSentiment={record(argusData.verdict).bias}' in panel
    assert 'marketBias={record(tactical.contract_selection).directional_bias}' in panel
    assert 'fetch(' not in source
    assert 'setInterval(' not in source
    assert 'width: 72%; background:' not in styles
    for token in (
        '--holo-violet: #b14cff', '--holo-violet-hi: #d9a3ff', '--holo-violet-dim: #4a1373',
        '--holo-cyan: #3ff3e8', '--flow-stale: #ff3d8b', '--flow-stale-dim: #7a0d33',
        '--glass-fill: rgba(255,255,255,.02)', '--glass-border: rgba(255,255,255,.08)',
    ):
        assert token in styles


def test_argus_01c_stale_rail_freezes_data_motion_but_keeps_search_signal():
    source = read(ARGUS_01C)
    styles = read(STYLES)
    assert "const searching = state === 'STALE' || state === 'HELD'" in source
    assert 'animationMode="frozen"' in source
    assert "state !== 'UNAVAILABLE' && <i className={styles.refractSweep}" in source
    assert '<span className={styles.frozenNode}' in source
    assert '<i className={styles.pingRing} /><i className={styles.pingRing} /><i className={styles.pingRing} />' in source
    assert 'staleMotion="ping"' in source
    assert '.railAccent_magenta[data-rail-state="STALE"] .refractSweep' in styles
    assert '.deck .refractSweep, .deck .liquidThumb, .deck .kineticValue, .deck .railFill, .deck .pingRing' in styles


def test_argus_01c_intraday_baseline_keeps_sentiment_and_canonical_bias_separate():
    source = read(ARGUS_01C)
    assert 'MARKET SENTIMENT' in source
    assert 'MARKET BIAS' in source
    assert 'const sentiment = upper(marketSentiment)' in source
    assert 'const bias = upper(marketBias)' in source
    assert 'baseline provenance, not an authoritative baseline score' in source


def test_argus_01c_test_fixtures_cannot_enter_production():
    source = read(ARGUS_01C)
    panel = read(PANEL)
    fixture = read(FIXTURE)
    assert "process.env.NODE_ENV !== 'production'" in source
    assert "process.env.NODE_ENV !== 'production'" in panel
    assert "TEST FIXTURE" in source
    assert "fetch(" not in fixture
    assert "execution influence remains zero" in fixture.lower()
