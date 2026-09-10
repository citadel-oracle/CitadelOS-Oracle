from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "citadel-dashboard"
PANEL = DASHBOARD / "src/components/institutional/OracleWorkspacePanel.tsx"
COMMAND = DASHBOARD / "src/components/institutional/VobPullbackCommand.tsx"
STYLES = DASHBOARD / "src/components/institutional/VobPullbackCommand.module.css"
STORE = DASHBOARD / "src/dashboard/store/oracleStore.ts"
PROVIDER = DASHBOARD / "src/dashboard/providers/RestDashboardProvider.ts"


def test_flow_pulse_is_restored_and_argus_shadow_panel_is_replaced():
    panel = PANEL.read_text(encoding="utf-8")
    assert "<OracleFlowPulse" in panel
    assert "ArgusFusionShadowPanel" not in panel
    assert "FlowPulsePaperLedger" in panel
    assert "<OracleLiveFlow" in panel
    assert "<VobPullbackCommand" in panel
    provider = PROVIDER.read_text(encoding="utf-8")
    assert "applyFlowPulseEvent" in provider
    assert "FLOW_PULSE_ACTION" in provider and "FLOW_PULSE_METERS" in provider


def test_zustand_store_is_canonical_revisioned_and_sliced():
    source = STORE.read_text(encoding="utf-8")
    assert "createStore<OracleStoreState>" in source
    assert "subscribeWithSelector" in source
    for name in ("MarketSlice", "VobSlice", "ReversalSlice", "TradeSlice", "RuntimeSlice", "ResearchSlice"):
        assert f"interface {name}" in source
    assert "incomingRevision <= get().runtime.revision" in source
    assert "ignoredStaleRevisions" in source
    assert "currentEpisode?.episodeId === episode.episodeId" in source
    assert "ingestOracleDashboardSnapshot(snapshot)" in PROVIDER.read_text(encoding="utf-8")


def test_command_is_leaf_selected_and_has_no_backend_decision_math():
    source = COMMAND.read_text(encoding="utf-8")
    assert "memo(function VobPullbackCommand" in source
    assert source.count("useOracleStore((state)") >= 18
    for forbidden in (
        "ResponseQualityEngine", "BookPressure", "OptionConfirmationEngine",
        "MLOFI", "score >", "score >=", "calculatePnl", "select_primary_ose_vob",
    ):
        assert forbidden not in source
    assert "P&L NOT REPORTED" in source
    assert "BACKEND SEMANTIC STATE" in source


def test_command_sections_source_lineage_and_accessibility_contract():
    source = COMMAND.read_text(encoding="utf-8")
    for label in (
        "VOB PULLBACK COMMAND", "MARKET STORY", "PRICE RAIL", "RECOVERY ENGINE",
        "FAILED AGGRESSION + OPTIONS", "ARGUS SUPPORT", "VOB LEVELS", "MATCHED COMPARISON",
        "LIFECYCLE", "EXPERIMENT SCOREBOARD",
    ):
        assert label in source
    store = STORE.read_text(encoding="utf-8")
    assert "levelShell('1M', ['PULLBACK'])" in store
    assert "levelShell('3M', ['PULLBACK', 'OSE'])" in store
    assert "levelShell('5M', ['OSE'])" in store
    css = STYLES.read_text(encoding="utf-8")
    assert "@media(max-width:680px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert "--violet:#b14cff" in css and "#3ff3e8" in css


def test_ultrawide_command_deck_preserves_leaf_components_and_collapses():
    source = COMMAND.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert "<TopCommandDeck />" in source
    assert '<div className={styles.decisionDeck}>' in source
    assert '<div className={styles.structureDeck}>' in source
    assert '<div className={styles.closureDeck}>' in source
    assert "width:min(96%,1600px)" in css
    assert "@media(min-width:1360px)" in css
    assert "grid-template-columns:repeat(12,minmax(0,1fr))" in css
    assert ".topDeck>.optionCard[data-option=CE]" in css
    assert ".topDeck>.optionCard[data-option=PE]" in css
    assert "@media(max-width:680px)" in css


def test_itm1_labels_bind_only_to_canonical_current_pair():
    source = COMMAND.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    assert "canonicalAtmStrike" in store
    assert "current_itm1_contracts" in store
    assert '<CurrentItmQuote optionType="CE" side="CALL" />' in source
    assert '<CurrentItmQuote optionType="PE" side="PUT" />' in source
    assert "<ContractTruthStrip />" in source
    assert 'label="REF PRICE"' in source
    assert 'label="STRIKE STEP"' in source
    assert "const roleLabel = frozen ? `FROZEN EPISODE ${optionType}`" in source
    assert "<span>ITM-1 {side}</span>" not in source
    assert "CURRENT ITM-1 {optionType}" in source
    assert "CURRENT != FROZEN" in source
    assert "QUOTE · VOB · DISTANCE →" in source
    assert "Frozen = contract selected" not in source
    assert "FROZEN EPISODE CONTRACT" in source


def test_current_and_frozen_contract_truth_have_distinct_visual_authority():
    source = COMMAND.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert 'aria-label="Current canonical ITM-1 contract authority"' in source
    assert "CURRENT ITM-1</b> = live resolver pair right now" in source
    assert "FROZEN</span> = contracts captured when this VOB episode was created" in source
    assert "data-current-itm1-authority" in source
    assert "data-contract-binding={frozen ? 'frozen' : 'current'}" in source
    assert ".currentItmQuote>strong" in css
    assert ".currentItmReference[data-mismatch=true]" in css


def test_current_itm1_live_quotes_are_distinct_from_frozen_episode_quotes():
    source = COMMAND.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    assert "currentItmCall: OracleOptionDisplay" in store
    assert "currentItmPut: OracleOptionDisplay" in store
    assert "parseOptionDisplay(currentCe, activeCe, 'CURRENT_ITM1')" in store
    assert "parseOptionDisplay(currentPe, activePe, 'CURRENT_ITM1')" in store
    assert '<CurrentItmQuote optionType="CE" side="CALL" />' in source
    assert '<CurrentItmQuote optionType="PE" side="PUT" />' in source
    assert "state.market.currentItmCall" in source
    assert "state.market.currentItmPut" in source
    assert "CURRENT CONTRACT VOB ·" in source
    assert "FROZEN CONTRACT LIVE PREMIUM" in source
    assert "data-quote-security-id" in source
    assert "data-vob-security-id" in source


def test_current_itm1_labels_never_describe_frozen_quote_values():
    source = COMMAND.read_text(encoding="utf-8")
    assert "CURRENT ITM-1 CALL" not in source or 'side="CALL"' in source
    assert "CURRENT ITM-1 PUT" not in source or 'side="PUT"' in source
    assert "FROZEN EPISODE CONTRACT" in source
    assert "FROZEN CONTRACT LIVE PREMIUM" in source
    assert "CURRENT != FROZEN" in source
    assert "ITM-1 CALL" not in source.replace("CURRENT ITM-1 CALL", "")
    assert "ITM-1 PUT" not in source.replace("CURRENT ITM-1 PUT", "")


def test_current_itm1_live_price_has_exactly_two_visual_authorities():
    source = COMMAND.read_text(encoding="utf-8")
    assert source.count('data-price-role="current-itm1"') == 1
    assert source.count('data-price-role="frozen-episode"') == 1
    assert "state.market.currentItmCall : state.market.currentItmPut" in source
    live_card = source[source.index("const LiveOptionCard"):source.index("function MagnetRail")]
    assert "currentItm1.premium" not in live_card
    assert "currentItm1.bid" not in live_card
    assert "currentItm1.ask" not in live_card
    assert "CURRENT != FROZEN" in live_card
    assert "option.contractStatus === 'FROZEN_EPISODE' ? 'FROZEN LIVE PREMIUM' : 'CURRENT LIVE PREMIUM'" in source


def test_historical_replay_reuses_command_store_and_suppresses_live_semantics():
    source = COMMAND.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    assert "<HistoricalReplayBanner />" in source
    assert "data-historical-replay" in source
    assert "DATE" in source and "CONTRACT" in source and "TIMEFRAME" in source and "EPISODE ID" in source
    assert "historical ? 'HISTORICAL' : market.dataFreshness" in source
    assert "if (!prior || historical) return" in source
    assert "loadHistoricalReplay" in store and "stepHistoricalReplay" in store and "exitHistoricalReplay" in store
    assert "source !== 'REPLAY'" in store
