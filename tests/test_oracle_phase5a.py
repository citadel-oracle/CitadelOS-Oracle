"""Phase-5A curated knowledge corpus, ingestion, retrieval, and safety tests."""

from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path
import shutil
from time import perf_counter

import pytest

from src.oracle.knowledge_corpus import (
    ACCEPTED_STATUSES, CORPUS_SCHEMA_VERSION, CorpusError, IngestionLedger,
    IngestionStage, LEGACY_PHASE5A_REGISTRY, Phase5AKnowledgeRegistry,
)
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query


CORPUS_ROOT = Path("oracle_knowledge")


def copied_registry(tmp_path: Path) -> Path:
    root = tmp_path / "oracle_knowledge"
    shutil.copytree(CORPUS_ROOT, root)
    return root / "registry" / "phase5a_registry.json"


@pytest.mark.unit
def test_registry_counts_hashes_domains_statuses_and_legacy_hypotheses():
    registry = Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY)
    assert len(registry.sources) == 9 and len(registry.cards) == 37
    assert len(registry.curated_cards) == 37 and registry.vault_hash
    assert sum(card.research_only for card in registry.curated_cards.values()) == 8
    assert {card.domain for card in registry.curated_cards.values()} == {
        "price_action", "market_structure", "liquidity_smc", "options",
        "microstructure", "trade_construction", "systematic_validation", "strategy_research",
    }
    assert all(card.validation_status in ACCEPTED_STATUSES for card in registry.curated_cards.values())
    assert all(card.execution_influence == "ZERO" for card in registry.curated_cards.values())
    assert {item.status for item in registry.legacy_vault.items} == {"HYPOTHESIS"}
    assert registry.summary["truth"]["internally_validated_cards"] == 0
    assert registry.summary["truth"]["historical_probabilities_created"] == 0


@pytest.mark.unit
def test_every_card_has_exact_contract_and_canonical_citadel_mapping():
    registry = Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY)
    for card in registry.curated_cards.values():
        raw = card.to_dict()
        for field in (
            "card_id", "concept", "domain", "definition_principle", "measurable_predicates",
            "required_evidence", "optional_confirmations", "failure_conditions", "contradictions",
            "when_not_to_use", "timeframes", "instruments", "option_buying_relevance",
            "relevant_citadel_fields", "data_availability", "source_id", "exact_locator",
            "paraphrase", "source_quality", "source_hash_version", "validation_status",
            "empirical_status", "execution_influence", "knowledge_policy_version",
        ):
            assert field in raw
        assert raw["exact_locator"] in registry.source_records[card.source_id]["stable_locators"]
        assert raw["source_hash_version"] == registry.source_records[card.source_id]["document_hash"]
        assert raw["relevant_citadel_fields"] and raw["data_availability"]
        assert raw["knowledge_policy_version"] == "oracle-knowledge-advisory-5a.1.0"


@pytest.mark.unit
def test_missing_locator_source_hash_mismatch_and_duplicate_card_rejected(tmp_path):
    path = copied_registry(tmp_path)
    card_path = path.parents[1] / "cards" / "options" / "phase5a.json"
    document = json.loads(card_path.read_text(encoding="utf-8"))
    document["cards"][0]["exact_locator"] = "fabricated chapter 99 page 999"
    card_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="locator"):
        Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT)

    path = copied_registry(tmp_path / "hash")
    card_path = path.parents[1] / "cards" / "options" / "phase5a.json"
    document = json.loads(card_path.read_text(encoding="utf-8"))
    document["cards"][0]["source_hash_version"] = "0" * 64
    card_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="source hash"):
        Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT)

    path = copied_registry(tmp_path / "duplicate")
    card_path = path.parents[1] / "cards" / "options" / "phase5a.json"
    document = json.loads(card_path.read_text(encoding="utf-8"))
    document["cards"].append(document["cards"][0])
    card_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="duplicate card"):
        Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT)


@pytest.mark.unit
def test_unsupported_status_excerpt_breach_and_whole_source_policy_rejected(tmp_path):
    path = copied_registry(tmp_path)
    card_path = path.parents[1] / "cards" / "options" / "phase5a.json"
    document = json.loads(card_path.read_text(encoding="utf-8"))
    document["cards"][0]["validation_status"] = "PENDING_SOURCE"
    card_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="unavailable status"):
        Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT)

    path = copied_registry(tmp_path / "excerpt")
    card_path = path.parents[1] / "cards" / "options" / "phase5a.json"
    document = json.loads(card_path.read_text(encoding="utf-8"))
    document["cards"][0]["short_excerpt"] = "word " * 30
    card_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="excerpt"):
        Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT)

    path = copied_registry(tmp_path / "whole")
    source_path = path.parents[1] / "source_manifests" / "phase5a_sources.json"
    document = json.loads(source_path.read_text(encoding="utf-8"))
    document["sources"][0]["excerpt_policy"]["full_text_runtime_allowed"] = True
    source_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="whole-source"):
        Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT)


@pytest.mark.unit
def test_pending_rejected_and_promotional_claims_are_excluded():
    registry = Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY)
    unavailable = {row["candidate_id"] for row in registry.pending["pending"] + registry.rejected["rejected"]}
    assert "white-reality-check-2000" in unavailable
    assert "awesome-institutional-trading-as-authority" in unavailable
    assert "gex-dealer-positioning-glossary" in unavailable
    assert not unavailable.intersection(registry.cards)
    assert registry.audit["repositories"][0]["role"] == "DISCOVERY_INDEX_ONLY"
    assert registry.audit["repositories"][1]["role"] == "DISCOVERY_INDEX_ONLY"
    assert registry.audit["repositories_cloned"] == 0 and registry.audit["frameworks_installed"] == 0


@pytest.mark.unit
def test_ingestion_pipeline_is_ordered_idempotent_hash_chained_and_restart_safe(tmp_path):
    path = tmp_path / "ingestion.jsonl"
    ledger = IngestionLedger(path)
    events = []
    for index, stage in enumerate(IngestionStage):
        events.append(ledger.advance(candidate_id="candidate-1", stage=stage,
            idempotency_key=f"idem-{index}", actor_id="curator", correlation_id="corr-1",
            details={"stage_index": index}))
    assert ledger.state("candidate-1") is IngestionStage.RETRIEVAL_TESTED
    assert ledger.verify() and IngestionLedger(path).events == events
    assert ledger.advance(candidate_id="candidate-1", stage=IngestionStage.RETRIEVAL_TESTED,
        idempotency_key=f"idem-{len(events) - 1}", actor_id="curator", correlation_id="corr-1", details={}) == events[-1]
    with pytest.raises(CorpusError, match="transition"):
        IngestionLedger(tmp_path / "invalid.jsonl").advance(candidate_id="candidate-2",
            stage=IngestionStage.EXTRACTED, idempotency_key="bad", actor_id="curator",
            correlation_id="corr-2", details={})


@pytest.mark.unit
def test_deterministic_retrieval_is_bounded_filtered_and_returns_counterprinciples():
    service = KnowledgeRetrievalService(Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY))
    query = build_query(instrument="NIFTY", timeframe="5m", maximum_cards=5,
        question="option premium expiry volatility loss theta vega",
        current_evidence_claims=("premium response and spread",))
    first, second = service.search(query), service.search(query)
    identifiers = [ref.card_id for ref in first.card_references]
    assert first.content_hash == second.content_hash and first.query_hash == second.query_hash
    assert 1 <= len(identifiers) <= 5 and first.conflicts
    assert "options-premium-multiple-drivers" in identifiers
    assert all(service.registry.raw(card_id).research_only is False for card_id in identifiers)
    assert all(ref.citation.locator for ref in first.card_references)
    assert service.search(build_query(instrument="NIFTY", timeframe="2m", question="premium")).card_references == ()
    assert service.search(build_query(instrument="AAPL", timeframe="5m", question="premium")).card_references == ()


@pytest.mark.unit
def test_setup_regime_timeframe_and_research_catalog_behavior():
    service = KnowledgeRetrievalService(Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY))
    breakout = service.search(build_query(instrument="NIFTY", timeframe="3m",
        setup_type="BREAKOUT_CONTINUATION", question="breakout momentum continuation"))
    assert breakout.card_references
    assert all(
        not service.registry.raw(ref.card_id).setup_types
        or "BREAKOUT_CONTINUATION" in service.registry.raw(ref.card_id).setup_types
        for ref in breakout.card_references
    )
    research = service.research_cards()
    assert len(research) == 8 and all(card.research_only for card in research)
    assert len(service.research_cards(setup_type="ORDER_FLOW_IMBALANCE")) == 1
    assert service.research_cards(setup_type="ORDER_FLOW_IMBALANCE")[0].validation_status == "FUTURE_DATA_DEPENDENT"


@pytest.mark.unit
def test_vault_hash_participates_in_query_and_updated_card_requires_new_registry(tmp_path):
    old = KnowledgeRetrievalService(Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY))
    query = build_query(instrument="NIFTY", timeframe="5m", question="premium volatility")
    old_result = old.search(query)
    path = copied_registry(tmp_path)
    registry_doc = json.loads(path.read_text(encoding="utf-8"))
    registry_doc["registry_version"] = "oracle-knowledge-corpus-5a.1.1-test"
    path.write_text(json.dumps(registry_doc), encoding="utf-8")
    card_path = path.parents[1] / "cards" / "options" / "phase5a.json"
    document = json.loads(card_path.read_text(encoding="utf-8"))
    document["cards"][0]["paraphrase"] += " Updated test version."
    card_path.write_text(json.dumps(document), encoding="utf-8")
    new = KnowledgeRetrievalService(Phase5AKnowledgeRegistry(path, legacy_root=CORPUS_ROOT))
    new_result = new.search(query)
    assert new.registry.vault_hash != old.registry.vault_hash
    assert new_result.query_hash != old_result.query_hash
    assert old.registry.raw("options-greeks-theoretical-not-guarantee").paraphrase.endswith("quotes.")
    assert new.registry.raw("options-greeks-theoretical-not-guarantee").paraphrase.endswith("version.")


@pytest.mark.unit
def test_no_card_creates_probability_or_strategy_promotion():
    registry = Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY)
    for card in registry.curated_cards.values():
        payload = card.to_dict()
        assert "historical_probability" not in payload and "confidence" not in payload
        assert payload["execution_influence"] == "ZERO"
        if card.research_only:
            assert card.research_fields["research_status"] == "RESEARCH_ONLY"
    assert registry.summary["truth"]["strategies_promoted"] == 0


@pytest.mark.safety
def test_corpus_and_retrieval_have_no_forbidden_dependencies_or_runtime_web():
    files = [Path("src/oracle/knowledge_corpus.py"), Path("src/oracle/knowledge_engine.py")]
    forbidden_imports = ("risk", "guardian", "paper", "dhan", "openalgo", "mission", "condition", "requests", "httpx", "urllib")
    forbidden_calls = ("submit_order", "authorize", "paper_execute", "arm", "create_mission", "promote_strategy")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports, calls = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.extend(alias.name.lower() for alias in node.names)
            if isinstance(node, ast.ImportFrom): imports.append((node.module or "").lower())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute): calls.append(node.func.attr.lower())
        assert not any(any(token in name for token in forbidden_imports) for name in imports)
        assert not any(call in forbidden_calls for call in calls)


@pytest.mark.unit
def test_warm_retrieval_p95_under_50ms():
    service = KnowledgeRetrievalService()
    query = build_query(instrument="NIFTY", timeframe="3m", maximum_cards=5,
        question="liquidity sweep option premium confirmation contradiction")
    service.search(query)
    samples = []
    for _ in range(200):
        start = perf_counter(); service.search(query); samples.append((perf_counter() - start) * 1000)
    samples.sort()
    assert samples[int(len(samples) * .95) - 1] <= 50
