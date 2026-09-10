from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/app/page.tsx").read_text(encoding="utf-8")
ADAPTER = (ROOT / "src/dashboard/adapters/DashboardDataAdapter.ts").read_text(encoding="utf-8")
ACKNOWLEDGEMENTS = (ROOT / "src/dashboard/utils/oracleAcknowledgements.ts").read_text(encoding="utf-8")


def test_existing_06c_panel_is_upgraded_once_and_remains_advisory():
    assert PAGE.count("function PersonalOraclePanel") == 1
    assert PAGE.count("Personal Trading Intelligence") >= 1
    assert PAGE.count('aria-label="Personal Trading Intelligence"') == 1
    assert "EXECUTION INFLUENCE 0%" in PAGE
    assert "No execution, risk, strategy, or AEGIS authority" in PAGE


def test_compact_panel_bounds_observations_and_handles_collecting_state():
    assert "data.observations.slice(0, 3)" in PAGE
    assert "Collecting evidence. No threshold-qualified observation yet." in PAGE
    assert "'Insufficient evidence'" in PAGE


def test_exact_six_hero_capabilities_map_from_backend_fields():
    start = PAGE.index('<div className="personal-oracle-overview personal-oracle-lite-overview">')
    end = PAGE.index('<div className="personal-oracle-block" aria-label="Personal Shadow Advisory">', start)
    hero = PAGE[start:end]
    titles = (
        "STRATEGY INTELLIGENCE",
        "EXECUTION AUDIT",
        "PATTERN DETECTION",
        "PERFORMANCE LEAKS",
        "DISCIPLINE ANALYSIS",
        "TODAY'S FOCUS",
    )
    assert hero.count("<PersonalOracleMetric") == 6
    assert all(f'label="{title}"' in hero for title in titles)
    assert "data.hero.discoveredStrategyCount" in hero
    assert "data.hero.needsAttentionCount" in hero
    assert "data.hero.activeObservationCount" in hero
    assert "data.hero.newObservationCount" in hero
    assert "data.hero.highestPriorityExecutionIssue" in hero
    assert "data.hero.highestImpactPerformanceLeak" in hero
    assert "data.hero.disciplineMetric" in hero
    assert "data.hero.todayFocus.text" in hero
    assert "10 strategies · 3 need attention" not in PAGE
    assert "Rapid re-entry" not in PAGE


def test_acknowledgements_are_versioned_and_persisted_locally():
    assert "observationId}:${version" in ACKNOWLEDGEMENTS
    assert "localStorage.getItem" in ACKNOWLEDGEMENTS
    assert "localStorage.setItem" in ACKNOWLEDGEMENTS
    assert "acknowledged.has(oracleAcknowledgementKey" in PAGE
    assert "observation.status === 'NEW' && !isAcknowledged" in PAGE


def test_existing_evidence_drawer_and_dynamic_strategy_scale_are_preserved():
    assert 'aria-label="Personal Oracle evidence"' in PAGE
    assert "Existing 06C evidence" in PAGE
    assert "data.strategyScope.filter" in PAGE
    assert "const pageSize = 20" in PAGE
    assert "data.tradeEvidence.map" in PAGE


def test_oracle_moves_after_active_positions_once_without_changing_hero_or_drawer():
    workspace = PAGE[PAGE.index("function TradingWorkspace"):PAGE.index("function PersonalOraclePanel")]
    positions = workspace.index('aria-label="Active Positions"')
    oracle = workspace.index('aria-label="Personal Trading Intelligence"')
    timeline = workspace.index('aria-label="Execution Timeline"', oracle)
    oracle_section = workspace[oracle:timeline]
    assert positions < oracle < timeline
    assert workspace.count('aria-label="Personal Trading Intelligence"') == 1
    assert 'personal-oracle-panel ${workspaceStyles.panel} ${workspaceStyles.oraclePanel}' in workspace
    assert "personalOracle.error" in oracle_section
    assert "athena.error" not in oracle_section
    assert "hermes.error" not in oracle_section
    assert 'aria-label="Personal Oracle evidence"' in PAGE


def test_rest_data_is_mapped_once_without_direct_component_fetch_or_strategy_ids():
    assert "const adaptPersonalOracle" in ADAPTER
    assert "key === 'personal_oracle' ? adaptPersonalOracle" in ADAPTER
    assert "const hero = object(source.hero)" in ADAPTER
    assert "fetch(" not in PAGE
    for hardcoded_id in ("PB_NIFTY_CE_1M", "PB_NIFTY_PE_3M", "BO_NIFTY_CE_1M", "BO_NIFTY_PE_3M"):
        assert hardcoded_id not in PAGE
        assert hardcoded_id not in ADAPTER


def test_stage_a_ingestion_and_context_contract_is_visible_without_new_fetches():
    assert "const ingestion = object(source.ingestion)" in ADAPTER
    assert "latestOracleIngestTimestamp" in ADAPTER
    assert "contextCompletenessPercentage" in ADAPTER
    assert "missingContextFields" in ADAPTER
    assert "data.ingestion.label" in PAGE
    assert "Oracle ingest" in PAGE
    assert "Context {formatPercent(data.ingestion.contextCompletenessPercentage)}" in PAGE
    assert "Missing {data.ingestion.missingContextFields.length" in PAGE
    assert "fetch(" not in PAGE


def test_stage_b_shadow_advisory_and_prospective_validation_are_compact_and_advisory():
    assert PAGE.count('aria-label="Personal Shadow Advisory"') == 1
    assert PAGE.count('aria-label="Prospective Validation"') == 1
    assert "data.shadow.latest.classification" in PAGE
    assert "data.shadow.latest.confidenceBand" in PAGE
    assert "data.shadow.latest.reasonCodes" in PAGE
    assert "data.shadow.latest.contextCompletenessPercentage" in PAGE
    assert "data.shadow.scorecard.prospectiveAdvisories" in PAGE
    assert "INSUFFICIENT SAMPLE" in PAGE
    assert "Execution influence ZERO" in PAGE
    assert "const shadow = object(source.shadow)" in ADAPTER
    assert "fetch(" not in PAGE
