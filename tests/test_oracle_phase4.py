"""Phase-4 knowledge, similarity, calibration and Visual Edge acceptance tests."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.oracle.contracts.learning import (
    CalibrationReport, CalibrationState, CitationLocator, ExcerptPolicy,
    HistoricalCaseReference, HistoricalOutcomeRecord, KnowledgeCard,
    KnowledgeSourceManifest, LearningContractError, SampleSufficiencyPolicy,
    SimilarityFeatureVector, ValidationStatus, seal,
)
from src.oracle.evidence import Phase4EvidenceService
from src.oracle.knowledge_engine import (
    KnowledgeRegistryError, KnowledgeRetrievalService, Phase4KnowledgeRegistry,
    build_query,
)
from src.oracle.similarity import DEFAULT_SAMPLE_POLICY, HistoricalDataset, SimilarityEngine
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.service import PersonalOracleService
from src.oracle_personal.visual_edge import VisualEdgeError, VisualEdgeRecorder, VisualEdgeStore


NOW = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def vector(identifier="query", *, numerical=None, symbol="NIFTY", expiry="DTE_1_7",
           iv="NORMAL", time_bucket="HOUR_10", spread="TIGHT"):
    return seal(SimilarityFeatureVector(
        record_id=f"feature-{identifier}", version="features-1.0.0", created_at=NOW.isoformat(),
        provenance={"fixture": True, "production_registry": False}, symbol=symbol,
        setup_version="setup-1", timeframe_alignment=("1H", "15m", "5m"), regime="TRENDING",
        location_class="BREAKOUT_RETEST", structural_claims=("ACCEPTANCE",), vob_state="BULLISH",
        ose_state="CLEAR CALL ADVANTAGE", argus_state="BULLISH", option_type="CE",
        strike_relation="ATM", expiry_bucket=expiry, iv_regime=iv, delta_bucket="MID",
        time_of_day_bucket=time_bucket, spread_liquidity_bucket=spread,
        trigger_definition_id="trigger-1", invalidation_definition_id="stop-1",
        target_definition_ids=("target-1",), feature_versions={"vob": "existing", "similarity": "1"},
        numerical_features=numerical if numerical is not None else {
            "spot_distance_atr": .2, "delta_abs": .5, "iv_percentile": .4,
            "spread_pct": .02, "minutes_to_close_norm": .5,
        }, observed_at=NOW.isoformat(),
    ))


def fixture_dataset(count=30, *, costs=True, production=False):
    cases, outcomes = [], {}
    for index in range(count):
        feature = vector(f"case-{index}")
        source_hash = h(f"source-{index}")
        outcome_id = f"outcome-{index}"
        # Same 60% rate on train/OOS makes the constant train baseline calibrated.
        within_split = index if index < count // 2 else index - count // 2
        classification = "TARGET_BEFORE_STOP" if within_split < round((count // 2) * .6) else "STOP_BEFORE_TARGET"
        outcome = seal(HistoricalOutcomeRecord(
            record_id=outcome_id, outcome_id=outcome_id, version="1.0.0",
            created_at=(NOW + timedelta(hours=1)).isoformat(),
            provenance={"fixture": True, "production_registry": False},
            source_record_id=f"trade-{index}", source_record_hash=source_hash,
            decision_id=f"decision-{index}", decision_hash=h(f"decision-{index}"),
            outcome_definition_id="oracle-outcome-target-stop-1",
            target_definition_from_decision="target-1", stop_definition_from_decision="stop-1",
            classification=classification, mfe=2.0, mae=-.5,
            time_to_target_seconds=300.0 if classification == "TARGET_BEFORE_STOP" else None,
            time_to_stop_seconds=240.0 if classification == "STOP_BEFORE_TARGET" else None,
            after_cost_return=1.0 if classification == "TARGET_BEFORE_STOP" else -.5,
            slippage=.05, invalidation_timing_seconds=240.0, premium_response=.2,
            costs_included=costs, completed_at=(NOW + timedelta(hours=1)).isoformat(),
        ))
        case = seal(HistoricalCaseReference(
            record_id=f"case-{index}", case_id=f"case-{index}", version="1.0.0", created_at=NOW.isoformat(),
            provenance={"fixture": True, "production_registry": False}, source_record_id=f"trade-{index}",
            source_record_hash=source_hash, feature_vector=feature,
            split="TRAIN" if index < count // 2 else "OOS", data_completeness=1.0,
            outcome_record_id=outcome_id, outcome_record_hash=outcome.content_hash,
            production_eligible=production,
        ))
        cases.append(case); outcomes[outcome_id] = outcome
    return HistoricalDataset(version="synthetic-test-fixture-1", cases=tuple(cases), outcomes=outcomes,
                             exclusions={}, source="SYNTHETIC_TEST_FIXTURE_ONLY", production=production)


@pytest.mark.unit
def test_knowledge_registry_is_hash_pinned_bounded_and_preserves_legacy_hypotheses():
    registry = Phase4KnowledgeRegistry()
    assert registry.vault_hash and all(card.verify_hash() for card in registry.cards.values())
    assert len(registry.legacy_vault.items) == 12
    assert {row.status for row in registry.legacy_vault.items} == {"HYPOTHESIS"}
    assert not any(card.validation_status is ValidationStatus.HYPOTHESIS for card in registry.cards.values())


@pytest.mark.unit
def test_missing_nonexistent_and_hash_mismatched_citations_are_rejected(tmp_path):
    with pytest.raises(LearningContractError, match="locator"):
        CitationLocator(source_id="s", source_version="1", document_hash=h("doc"), locator="")
    source = json.loads(Path("oracle_knowledge/phase4_registry.json").read_text(encoding="utf-8"))
    source["cards"][0]["locator"] = "Chapter 99, fabricated page 999"
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(KnowledgeRegistryError, match="INVALID"):
        Phase4KnowledgeRegistry(bad)
    source = json.loads(Path("oracle_knowledge/phase4_registry.json").read_text(encoding="utf-8"))
    source["sources"][0]["document_hash"] = "0" * 64
    bad.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(KnowledgeRegistryError, match="HASH_MISMATCH"):
        Phase4KnowledgeRegistry(bad)


@pytest.mark.unit
def test_excerpt_policy_and_edition_identity_are_explicit():
    with pytest.raises(LearningContractError, match="zero"):
        ExcerptPolicy(policy_id="none", excerpt_allowed=False, maximum_words=1)
    common = dict(record_id="source:s", created_at=NOW.isoformat(), provenance={"locator": "x"}, source_id="s",
                  title="Title", author_organisation="Authority", publication_date="2026-01-01",
                  source_type="OFFICIAL_DOCUMENTATION", document_hash=h("document"), source_location="https://example.invalid/pinned",
                  ingestion_status="VERIFIED", excerpt_policy=ExcerptPolicy(policy_id="short", excerpt_allowed=True, maximum_words=5),
                  validation_status=ValidationStatus.SOURCE_VERIFIED, stable_locators=("Section X",))
    first = seal(KnowledgeSourceManifest(version="1", edition_version="Edition 1", **common))
    second = seal(KnowledgeSourceManifest(version="2", edition_version="Edition 2", **common))
    assert first.content_hash != second.content_hash


@pytest.mark.unit
def test_retrieval_is_deterministic_small_and_returns_material_counterprinciple():
    service = KnowledgeRetrievalService()
    query = build_query(instrument="NIFTY", question="premium expiry volatility loss", timeframe="5m", maximum_cards=3)
    first, second = service.search(query), service.search(query)
    assert first.content_hash == second.content_hash and first.query_hash == second.query_hash
    assert 1 <= len(first.card_references) <= 3
    assert first.conflicts and first.whole_source_loaded is False
    assert all(ref.citation.locator and ref.citation.document_hash for ref in first.card_references)


@pytest.mark.unit
def test_unsupported_timeframe_is_omitted_and_book_principle_cannot_create_probability():
    service = KnowledgeRetrievalService()
    result = service.search(build_query(instrument="NIFTY", question="premium", timeframe="2m"))
    assert result.card_references == ()
    with pytest.raises(LearningContractError, match="OOS calibration"):
        CalibrationReport(
            record_id="c", version="1", created_at=NOW.isoformat(), provenance={"book": True},
            cohort_id="x", cohort_statistics_hash=h("s"), policy_id="p",
            state=CalibrationState.NOT_AVAILABLE, historical_probability=.8, numerator=8,
            denominator=10, confidence_interval=(.4, .9), oos_status="NONE", costs_included=False,
            cohort_version="1", brier_score=None, calibration_error=None, cohort_drift=None, caveats=(),
        )


@pytest.mark.unit
def test_similarity_rejects_future_outcome_fields_and_cross_bucket_cases():
    with pytest.raises(LearningContractError, match="future"):
        vector("future", numerical={"mfe": 2.0})
    dataset = fixture_dataset()
    engine = SimilarityEngine(dataset)
    _, cross_symbol, _, _ = engine.query(vector("bank", symbol="BANKNIFTY"))
    assert not cross_symbol.matches and cross_symbol.excluded_counts["REQUIRED_EXACT_FILTER"] == 30
    _, cross_expiry, _, _ = engine.query(vector("expiry", expiry="DTE_8_PLUS"))
    assert not cross_expiry.matches
    _, cross_iv, _, _ = engine.query(vector("iv", iv="HIGH"))
    assert not cross_iv.matches
    _, cross_time, _, _ = engine.query(vector("time", time_bucket="HOUR_14"))
    assert not cross_time.matches


@pytest.mark.unit
def test_similarity_exact_relaxed_distance_and_train_oos_are_transparent():
    engine = SimilarityEngine(fixture_dataset())
    _, exact, _, calibrated = engine.query(vector())
    assert {row.tier for row in exact.matches} == {"EXACT"}
    assert {row.split for row in exact.matches} == {"TRAIN", "OOS"}
    relaxed_vector = vector("relaxed", numerical={
        "spot_distance_atr": .3, "delta_abs": .5, "iv_percentile": .4,
        "spread_pct": .02, "minutes_to_close_norm": .5,
    })
    _, relaxed, _, _ = engine.query(relaxed_vector)
    assert {row.tier for row in relaxed.matches} == {"RELAXED"}
    assert all(row.distance == .03 and "spot_distance_atr" in row.differing_features for row in relaxed.matches)
    assert calibrated.state is CalibrationState.OOS_CALIBRATED
    assert calibrated.historical_probability == pytest.approx(.6)


@pytest.mark.unit
def test_statistics_reconcile_costs_intervals_and_sample_policy():
    _, _, stats, calibration = SimilarityEngine(fixture_dataset()).query(vector())
    assert (stats.target_before_stop, stats.stop_before_target, stats.neither) == (18, 12, 0)
    assert stats.mean_mfe == 2 and stats.mean_mae == -.5 and stats.mean_slippage == .05
    assert stats.mean_after_cost_return is not None and stats.confidence_interval[0] < .6 < stats.confidence_interval[1]
    assert calibration.numerator == 18 and calibration.denominator == 30 and calibration.costs_included
    _, _, small_stats, small = SimilarityEngine(fixture_dataset(10)).query(vector())
    assert small_stats.total_sample == 10 and small.state is CalibrationState.INSUFFICIENT_SAMPLE
    assert small.historical_probability is None


@pytest.mark.unit
def test_cost_exclusion_degrades_and_explicit_coverage_policy_blocks_probability():
    _, _, _, degraded = SimilarityEngine(fixture_dataset(costs=False)).query(vector())
    assert degraded.state is CalibrationState.DEGRADED and degraded.historical_probability is None
    stricter = seal(replace(DEFAULT_SAMPLE_POLICY, record_id="coverage-policy", content_hash="",
                            minimum_regime_coverage=2))
    _, _, _, insufficient = SimilarityEngine(fixture_dataset(), policy=stricter).query(vector())
    assert insufficient.state is CalibrationState.INSUFFICIENT_SAMPLE
    assert any("Coverage failed" in caveat for caveat in insufficient.caveats)


@pytest.mark.unit
def test_production_dataset_cannot_admit_fixture_or_scaffold_cases():
    with pytest.raises(ValueError, match="NON_PRODUCTION"):
        SimilarityEngine(fixture_dataset(production=True))

    @dataclass
    class Event:
        source_type: str = "SYNTHETIC_FIXTURE"
        oracle_event_id: str = "fixture-1"
        source_record_id: str = "placeholder-fold"
        entry_context: dict = None
    dataset = HistoricalDataset.from_personal_oracle((Event(),), version="runtime")
    assert not dataset.cases and dataset.exclusions == {"RESEARCH_FIXTURE_OR_SCAFFOLD": 1}


@dataclass
class CompletedEvent:
    oracle_event_id: str = "event-1"
    source_record_id: str = "trade-1"
    immutable_source_hash: str = h("immutable-trade")
    exit_at: str = (NOW + timedelta(hours=1)).isoformat()
    outcome: str = "WIN"
    mfe: float = 2.0
    mae: float = -.5

    def to_dict(self):
        return dict(self.__dict__)


def visual_recorder(tmp_path, event=None):
    event = event or CompletedEvent()
    return VisualEdgeRecorder(VisualEdgeStore(tmp_path / "visual"),
                              completed_record_resolver=lambda source: event if source in {event.source_record_id, event.oracle_event_id} else None)


def visual_payload(**extra):
    value = {
        "label": "USER_EDGE", "original_user_wording": "I see premium non-confirmation",
        "reason_tags": ["PREMIUM_NON_CONFIRMATION"],
        "chart_artifacts": [{"timeframe": timeframe, "availability": "UNAVAILABLE"}
                            for timeframe in ("1D", "4H", "1H", "15m", "5m", "3m", "1m")],
        "permission": "PRIVATE_RESEARCH", "retention_status": "ACTIVE", "source_licensed": True,
        "observed_at": NOW.isoformat(),
    }
    value.update(extra); return value


@pytest.mark.unit
def test_visual_edge_partial_capture_is_truthful_idempotent_and_preserves_original_wording(tmp_path):
    recorder = visual_recorder(tmp_path)
    first = recorder.observe(visual_payload(), idempotency_key="observe-1", actor_id="user", correlation_id="corr")
    again = recorder.observe(visual_payload(), idempotency_key="observe-1", actor_id="user", correlation_id="corr")
    assert first == again and first["label"]["original_user_wording"] == "I see premium non-confirmation"
    assert first["completeness"]["state"] == "PARTIAL" and first["completeness"]["training_eligible"] is False
    assert all(row["artifact_id"] is None for row in first["chart_artifacts"])
    assert recorder.store.verify_chain()


@pytest.mark.unit
def test_visual_label_revision_is_append_only_and_prior_version_is_required(tmp_path):
    recorder = visual_recorder(tmp_path)
    original = recorder.observe(visual_payload(), idempotency_key="o", actor_id="user", correlation_id="c")
    revision = recorder.revise(original["observation_id"], {
        "label": "CORRECTED", "original_user_wording": "Correction", "reason": "Typo",
    }, idempotency_key="r", actor_id="user", correlation_id="c2", expected_prior_version=1)
    projection = recorder.store.observation(original["observation_id"])
    assert revision["revision_version"] == 2 and projection["observation"]["label"] == original["label"]
    assert projection["revisions"][0]["revised_label"]["label"] == "CORRECTED"
    with pytest.raises(VisualEdgeError, match="PRIOR_VERSION"):
        recorder.revise(original["observation_id"], {
            "label": "X", "original_user_wording": "X", "reason": "X",
        }, idempotency_key="r2", actor_id="user", correlation_id="c3", expected_prior_version=1)


@pytest.mark.unit
def test_visual_outcome_links_later_and_never_influences_current_decision(tmp_path):
    event = CompletedEvent()
    recorder = visual_recorder(tmp_path, event)
    original = recorder.observe(visual_payload(), idempotency_key="o", actor_id="user", correlation_id="c")
    link = recorder.link_outcome(original["observation_id"], {
        "source_record_id": event.source_record_id, "source_record_hash": event.immutable_source_hash,
        "correctness_label": "CORRECT",
    }, idempotency_key="outcome", actor_id="user", correlation_id="c2")
    assert link["time_safe_validated"] is True and link["model_training_eligible"] is False
    assert original["current_decision_influence"] == "ZERO"
    with pytest.raises(VisualEdgeError, match="ALREADY"):
        recorder.link_outcome(original["observation_id"], {
            "source_record_id": event.source_record_id, "source_record_hash": event.immutable_source_hash,
        }, idempotency_key="outcome-2", actor_id="user", correlation_id="c3")


@pytest.mark.unit
def test_visual_hindsight_permissions_hashes_and_idempotency_fail_closed(tmp_path):
    recorder = visual_recorder(tmp_path)
    with pytest.raises(VisualEdgeError, match="HINDSIGHT"):
        recorder.observe(visual_payload(mfe=5), idempotency_key="h", actor_id="u", correlation_id="c")
    with pytest.raises(VisualEdgeError, match="PERMISSION"):
        recorder.observe(visual_payload(permission="DENIED"), idempotency_key="d", actor_id="u", correlation_id="c")
    original = recorder.observe(visual_payload(), idempotency_key="same", actor_id="u", correlation_id="c")
    with pytest.raises(VisualEdgeError, match="IDEMPOTENCY_CONFLICT"):
        recorder.observe(visual_payload(label="DIFFERENT"), idempotency_key="same", actor_id="u", correlation_id="c")
    with pytest.raises(VisualEdgeError, match="HASH_MISMATCH"):
        recorder.link_outcome(original["observation_id"], {
            "source_record_id": "trade-1", "source_record_hash": h("wrong"),
        }, idempotency_key="bad-outcome", actor_id="u", correlation_id="c")


def phase3_result(tmp_path):
    path = Path("tests/test_oracle_phase3.py").resolve()
    spec = importlib.util.spec_from_file_location("phase3_fixture_module", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.result(tmp_path)


@pytest.mark.unit
def test_evidence_enrichment_has_exact_citations_caveats_and_cannot_change_action(tmp_path):
    result, analysis = phase3_result(tmp_path / "phase3")
    personal = PersonalOracleService(
        ledger=PersonalOracleLedger(tmp_path / "personal.json"), strategy_lab_root=tmp_path / "lab",
    )
    phase4 = Phase4EvidenceService(analysis, personal)
    enriched = phase4.enrich_result(result, persist=True)
    proof = enriched.proof_projection
    assert enriched.original_action == result.decision.action == "BUY"
    assert enriched.execution_authority is False and enriched.same_decision_execution_influence == "ZERO"
    assert proof["principle"] and all(row["exact_locator"] for row in proof["principle"])
    assert any(not row["card_id"].startswith("validation-") for row in proof["principle"])
    assert proof["principle_conflicts"]
    assert proof["historical_evidence"]["calibration"]["state"] == "INSUFFICIENT_SAMPLE"
    assert proof["historical_evidence"]["historical_probability"] is None
    assert proof["policy"]["decision_action_changed"] is False
    before = {path: path.stat().st_mtime_ns for path in (tmp_path / "phase3" / "analysis").rglob("*.json")}
    assert phase4.evidence_projection(result.decision.decision_id)["content_hash"] == enriched.content_hash
    after = {path: path.stat().st_mtime_ns for path in (tmp_path / "phase3" / "analysis").rglob("*.json")}
    assert before == after


@pytest.mark.unit
def test_phase4_gets_are_side_effect_free_and_learning_post_touches_only_visual_store(tmp_path, monkeypatch):
    import app.main as main

    result, analysis = phase3_result(tmp_path / "phase3")
    personal = PersonalOracleService(
        ledger=PersonalOracleLedger(tmp_path / "personal.json"), strategy_lab_root=tmp_path / "lab",
    )
    knowledge = KnowledgeRetrievalService()
    phase4 = Phase4EvidenceService(analysis, personal, knowledge=knowledge)
    enriched = phase4.enrich_result(result, persist=True)
    monkeypatch.setattr(main, "oracle_analysis_service", analysis)
    monkeypatch.setattr(main, "personal_oracle_service", personal)
    monkeypatch.setattr(main, "oracle_knowledge_service", knowledge)
    monkeypatch.setattr(main, "oracle_phase4_evidence_service", phase4)
    files = list((tmp_path / "phase3" / "analysis").rglob("*.json"))
    before = {path: path.stat().st_mtime_ns for path in files}
    search = main.oracle_knowledge_search(question="premium volatility loss", timeframe="5m")
    assert search["card_references"]
    assert main.oracle_knowledge_card(search["card_references"][0]["card_id"])["citation"]["locator"]
    assert main.oracle_similarity(result.decision.decision_id)["similarity"]["method_version"].startswith("oracle-transparent")
    cohort_id = enriched.proof_projection["historical_evidence"]["cohort"]["cohort_id"]
    assert main.oracle_calibration(cohort_id)["calibration"]["state"] == "INSUFFICIENT_SAMPLE"
    assert main.oracle_decision_evidence(result.decision.decision_id)["phase4"]["execution_authority"] is False
    assert before == {path: path.stat().st_mtime_ns for path in files}

    created = main.create_visual_edge_observation(main.VisualEdgeWriteRequest(
        idempotency_key="api-observation", actor_id="user", correlation_id="api-correlation",
        payload=visual_payload(),
    ))
    assert main.get_visual_edge_observation(created["observation_id"])["journal_verified"]
    assert not (tmp_path / "personal.json").exists()
    visual_files = tuple((tmp_path / "personal_oracle_visual_edge").rglob("*"))
    assert visual_files and before == {path: path.stat().st_mtime_ns for path in files}


@pytest.mark.safety
def test_phase4_modules_have_no_trading_mutations_or_forbidden_dependencies():
    files = [
        Path("src/oracle/knowledge_engine.py"), Path("src/oracle/similarity/engine.py"),
        Path("src/oracle/evidence/enrichment.py"), Path("src/oracle_personal/visual_edge.py"),
    ]
    forbidden_imports = ("risk", "guardian", "paper_autopilot", "dhan", "openalgo", "mission", "condition")
    forbidden_calls = ("submit_order", "authorize", "paper_execute", "arm_condition", "create_mission",
                       "alter_position", "promote_strategy")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports, calls = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.extend(alias.name.lower() for alias in node.names)
            if isinstance(node, ast.ImportFrom): imports.append((node.module or "").lower())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute): calls.append(node.func.attr.lower())
        assert not any(any(token in name for token in forbidden_imports) for name in imports)
        assert not any(call in forbidden_calls for call in calls)


@pytest.mark.safety
def test_phase4_api_surface_and_safety_locks_are_explicit():
    source = Path("app/main.py").read_text(encoding="utf-8")
    for route in (
        '/v1/oracle/knowledge/search', '/v1/oracle/knowledge/cards/{card_id}',
        '/v1/oracle/similarity/{decision_id}', '/v1/oracle/calibration/{cohort_id}',
        '/v1/oracle/visual-edge-observations',
        '/v1/oracle/visual-edge-observations/{observation_id}',
        '/v1/oracle/visual-edge-observations/{observation_id}/revisions',
        '/v1/oracle/visual-edge-observations/{observation_id}/outcomes',
    ):
        assert route in source
    enrichment = Path("src/oracle/evidence/enrichment.py").read_text(encoding="utf-8")
    for literal in ('"same_decision_execution_influence": "ZERO"', '"execution_authority": False',
                    '"decision_action_changed": False'):
        assert literal in enrichment
