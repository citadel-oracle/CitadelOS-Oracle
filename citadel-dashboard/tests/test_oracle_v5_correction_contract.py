from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "src/components/institutional/OracleWorkspacePanel.tsx").read_text(encoding="utf-8")
CSS = (ROOT / "src/app/oracle/oracle.module.css").read_text(encoding="utf-8")
NAV_CSS = (ROOT / "src/components/institutional/CitadelPrimaryNavigation.module.css").read_text(encoding="utf-8")
ARGUS = (ROOT / "src/components/institutional/oracleArgusProjection.ts").read_text(encoding="utf-8")
PROVIDER = (ROOT / "src/dashboard/providers/RestDashboardProvider.ts").read_text(encoding="utf-8")


def test_connectors_measure_real_card_and_hub_anchors_at_runtime():
    for hook in (
        'data-oracle-graph',
        'data-engine-node="${nodeId}"',
        'data-oracle-hub-core',
        "getBoundingClientRect()",
        "new ResizeObserver(measure)",
        "data-provider-anchor={id}",
        "data-hub-anchor={id}",
    ):
        assert hook in PANEL
    assert "providerPoint.x + pathDx * 0.36" in PANEL
    assert "hub.x.toFixed(2)" in PANEL
    assert 'viewBox="0 0 1200 760"' not in PANEL


def test_one_normalized_state_drives_card_connector_and_center():
    for state in ("CALL", "PUT", "MIXED", "PENDING", "HEALTHY", "BLOCKED", "STANDBY", "UNAVAILABLE"):
        assert state in PANEL
    assert PANEL.count("data-presentation-state") >= 5
    assert 'data-presentation-state={node.presentationState}' in PANEL
    assert "data-presentation-state={node?.presentationState ?? 'UNAVAILABLE'}" in PANEL
    assert 'data-stale={node.stale}' in PANEL
    assert 'data-stale={node?.stale ?? false}' in PANEL


def test_stale_status_preserves_last_valid_direction_but_dims_motion():
    assert "const oracleVote = isUnavailableState(oracleState)" in PANEL
    assert "const argusVote = isUnavailableState(argusState)" in PANEL
    assert "const vobVote = isUnavailableState(vobState)" in PANEL
    assert "state === 'STALE'\n        ? 'NO CLEAN SIDE'" not in ARGUS
    assert '.evidenceEdges g[data-stale="true"] path' in CSS
    assert '.semanticEmphasis[data-stale="true"]' in CSS


def test_all_six_cards_expose_locked_compact_contract_rows():
    required = (
        "15m / 5m / 3m", "Structure / liquidity / FVG", "Location", "Confirm", "Invalid / target",
        "Best stack", "Support / resistance", "PCR / straddle", "Highest load", "Accel @",
        "Resistance life", "Support life", "NEXT NOT REPORTED",
        "ATM / pair", "SSI / edge", "ARGUS / agreement", "Call EMA50 / Supertrend / bar", "Put EMA50 / Supertrend / bar",
        "Today / return", "Trades / W–L / 60m", "Risk used / limit / open", "Discipline",
        "Position / guardian", "Protection / feed", "Entry → live / P&L", "SL / T1 / distance", "Current R / best / giveback",
    )
    for label in required:
        assert label in PANEL
    assert "ceBuyWriteSplit: NOT_REPORTED" in ARGUS
    assert "peBuyWriteSplit: NOT_REPORTED" in ARGUS
    assert "flowType: NOT_REPORTED" in ARGUS


def test_semantic_emphasis_is_shared_and_readable_without_layout_rewrite():
    assert "function SemanticEmphasis" in PANEL
    assert "<SemanticEmphasis node={node} />" in PANEL
    assert ".semanticEmphasis" in CSS
    assert "font: 700 14px" in CSS
    assert "font-size: 10.5px" in CSS
    assert "font-size: 9.5px" in CSS
    for position in (".node_thesis", ".node_argus", ".node_vob", ".node_ose", ".node_risk", ".node_guardian"):
        assert position in CSS


def test_visible_cards_are_bounded_summaries_with_non_overlapping_regions():
    assert "node.metrics.slice(0, 2)" in PANEL
    assert "node.metrics.slice(2, 5)" in PANEL
    assert "node.metrics.slice(2, 6)" not in PANEL
    assert ".engineNode {" in CSS and "display: flex;" in CSS and "flex-direction: column;" in CSS
    assert ".nodeEvidence { min-height: 16px; margin-top: auto;" in CSS
    assert ".nodeEvidence { position: absolute" not in CSS
    assert ".semanticEmphasis span { overflow-wrap: anywhere; }" in CSS


def test_center_cells_and_neutral_palette_do_not_repeat_provider_text_or_use_amber():
    assert "<em>{compactPresentation(node)}</em>" in PANEL
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in CSS
    assert "grid-template-rows: auto auto;" in CSS
    assert "--amber" not in CSS
    assert "#d99b45" not in CSS.lower()
    assert "#ff3b54" in CSS.lower() and "#ff7285" in CSS.lower() and "#6e2530" in CSS.lower()
    assert "#4ade80" in CSS.lower() and "#245c3d" in CSS.lower()


def test_hub_moves_down_without_changing_orbital_positions_or_connector_measurement():
    assert "top: 53%;" in CSS
    assert "const centerY = viewport.height * 0.53" in PANEL
    for position in (".node_thesis", ".node_argus", ".node_vob", ".node_ose", ".node_risk", ".node_guardian"):
        assert position in CSS
    assert "getBoundingClientRect()" in PANEL


def test_transient_toast_has_ten_second_lifecycle_and_persistent_history():
    assert "const ALERT_TOAST_DURATION_MS = 10_000" in PANEL
    assert "const ALERT_TOAST_EXIT_MS = 180" in PANEL
    assert "function DismissibleAlertToast" in PANEL
    assert "onMouseEnter={pause}" in PANEL and "onFocus={pause}" in PANEL
    assert 'aria-label="Dismiss alert"' in PANEL
    assert "window.clearTimeout" in PANEL
    assert "persistedKeys.current.has(alert.deduplication_key)" in PANEL
    assert "data-alert-history" in PANEL
    assert 'data-phase="leaving"' in CSS


def test_sse_remains_primary_and_polling_is_recovery_only():
    assert "new EventSource" in PROVIDER
    assert "/v1/oracle/live-workspace/stream" in PROVIDER
    assert "event_receipt_ms" in PROVIDER
    assert "fetch(" not in PANEL


def test_micro_patch_uses_one_strong_semantic_result_per_provider():
    assert PANEL.count("<SemanticEmphasis node={node} />") == 1
    assert "node.metrics.slice(2, 5)" in PANEL
    assert "background: linear-gradient(180deg, rgba(110, 37, 48, 0.64)" in CSS
    assert "background: linear-gradient(180deg, rgba(36, 92, 61, 0.62)" in CSS


def test_micro_patch_uses_brand_red_and_two_layer_connector_contrast():
    assert "--red: #ff3b54;" in CSS
    assert "--red-hi: #ff7285;" in CSS
    assert "rgba(255, 114, 133" not in CSS
    assert "className={styles.edgeCore}" in PANEL
    assert "className={styles.edgeHighlight}" in PANEL
    assert "data-edge-highlight={id}" in PANEL
    assert '.edgeCore[data-vote="BLOCKS"] { stroke: var(--red-dim);' in CSS
    assert '.edgeHighlight[data-vote="BLOCKS"] { stroke: var(--red-hi);' in CSS
    assert '.edgeCore[data-vote="SUPPORTIVE"] { stroke: var(--green-dim);' in CSS
    assert '.edgeHighlight[data-vote="SUPPORTIVE"] { stroke: var(--green);' in CSS
    assert ".oracleShell .mark" in NAV_CSS
    assert "#ff7285" not in NAV_CSS.lower()
