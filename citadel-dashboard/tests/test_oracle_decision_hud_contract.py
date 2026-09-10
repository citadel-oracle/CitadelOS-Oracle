from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHART = (ROOT / "src/components/institutional/OracleFuturesVwapChart.tsx").read_text()
PROVIDER = (ROOT / "src/dashboard/providers/RestDashboardProvider.ts").read_text()


def test_browser_explicitly_prefers_canonical_display_states():
    assert "source.display_edge_state" in CHART
    assert "source.display_structure_state" in CHART
    assert "? source.display_edge_state" in CHART
    assert "? source.display_structure_state" in CHART


def test_semantic_snapshot_is_keyed_by_display_revision_not_raw_revision():
    assert "displayRevision: number(source.display_revision) ?? revision" in CHART
    assert "const decisionHudSemantic = useMemo<DecisionHudSemanticProjection>" in CHART
    assert "decisionHud.displayRevision" in CHART
    assert "data-hud-display-revision" in CHART
    assert "data-hud-raw-revision" in CHART


def test_semantic_labels_are_memoized_while_live_rail_positions_remain_separate():
    assert "const DecisionHeader = memo" in CHART
    assert "const DecisionRailLabel = memo" in CHART
    assert "flowStrength={decisionHud.call.flowStrength}" in CHART
    assert "oiStrength={decisionHud.put.oiStrength}" in CHART
    assert "animationMode=\"frozen\"" in CHART


def test_cards_are_universal_flow_and_oi_controls_not_reversal_trade_gates():
    assert 'label: \'FLOW\' | \'OI\'' in CHART
    assert 'label="CE"' in CHART
    assert 'label="PE"' in CHART
    assert "relationshipState" in CHART
    assert "controlEventId" in CHART
    assert "FOCUS {label}" in CHART
    assert 'DecisionRailLabel label="FLOW"' in CHART
    assert 'DecisionRailLabel label="OI"' in CHART
    assert "REVERSAL COMING" not in CHART
    assert "const oiDisplayState" in CHART
    assert "SHORT COVERING" in CHART
    assert "LONG UNWINDING" in CHART
    assert "SHORT BUILDUP" in CHART
    assert "LONG BUILDUP" in CHART


def test_live_certification_beacon_is_opt_in_and_event_driven():
    assert "hudAuditCollector" in CHART
    assert "hudAuditCollectorPort" in CHART
    assert "fetch(`http://127.0.0.1:${hudAuditCollectorPort}/dom-transition`" in CHART
    assert "decisionHudSemantic.displayRevision" in CHART
    assert "setInterval(" not in CHART


def test_existing_fast_lane_sse_attaches_browser_receipt_to_futures_chart():
    assert "new EventSource(streamPath)" in PROVIDER
    assert "key === 'futures_chart'" in PROVIDER
    assert "browser_receive_epoch_ms: receivedAt" in PROVIDER
    assert "published_at: event.published_at" in PROVIDER
