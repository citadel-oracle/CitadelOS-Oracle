"""Expanded free-source and user-provided knowledge corpus tests."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
from time import perf_counter

import pytest

from src.oracle.contracts.learning import ValidationStatus
from src.oracle.knowledge_corpus import (
    CORPUS_SCHEMA_VERSION, CorpusError, IngestionLedger, IngestionStage,
    KNOWLEDGE_POLICY_VERSION, Phase5AKnowledgeRegistry,
)
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query


ROOT = Path("oracle_knowledge")
REGISTRY = ROOT / "registry" / "expanded_registry.json"


def copied_registry(tmp_path: Path) -> Path:
    root = tmp_path / "oracle_knowledge"
    shutil.copytree(ROOT, root)
    return root / "registry" / "expanded_registry.json"


@pytest.mark.unit
def test_expanded_counts_sources_user_hashes_and_status_truth():
    registry = Phase5AKnowledgeRegistry()
    assert registry.schema_version == CORPUS_SCHEMA_VERSION == "5a.2.0"
    assert registry.registry_version == "oracle-knowledge-corpus-5a.2.0"
    assert len(registry.sources) == 27 and len(registry.cards) == 105
    assert sum(card.research_only for card in registry.curated_cards.values()) == 10
    assert registry.summary["counts"]["user_fvg_cards"] == 25
    assert registry.summary["truth"]["internally_validated_cards"] == 0
    assert registry.summary["truth"]["historical_probabilities_created"] == 0
    assert registry.summary["truth"]["strategies_promoted"] == 0
    assert registry.summary["truth"]["same_trade_execution_influence"] == "ZERO"
    expected = {
        "user_sources/fvg_strategy_notes.txt": "c51f68b10a8d0947f576ba49ad4520a5213edad17de645adfa2bb4c79be59269",
        "user_sources/strategy_knowledge_base.txt": "dccf62ee374392d9c0fd5d722b9a65d98f41ebae5ab2862d1d9e421bd957c525",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    assert registry.sources["user-fvg-strategy-notes-2026"].validation_status is ValidationStatus.USER_PROVIDED_UNVALIDATED
    assert all(card.execution_influence == "ZERO" for card in registry.curated_cards.values())


@pytest.mark.unit
def test_source_manifest_url_hash_locator_rights_and_duplicate_integrity():
    registry = Phase5AKnowledgeRegistry()
    assert len({row["source_location"] for row in registry.source_records.values()}) == 27
    assert len({row["document_hash"] for row in registry.source_records.values()}) == 27
    for card in registry.curated_cards.values():
        source = registry.source_records[card.source_id]
        assert card.exact_locator in source["stable_locators"]
        assert card.source_hash_version == source["document_hash"]
        assert source["rights_status"]
        assert source["excerpt_policy"]["full_text_runtime_allowed"] is False
        assert card.knowledge_policy_version in {"oracle-knowledge-advisory-5a.1.0", KNOWLEDGE_POLICY_VERSION}


@pytest.mark.unit
def test_duplicate_url_duplicate_hash_and_user_file_tamper_are_rejected(tmp_path):
    path = copied_registry(tmp_path / "url")
    source_path = path.parents[1] / "source_manifests" / "expanded_sources.json"
    doc = json.loads(source_path.read_text())
    doc["sources"][1]["source_location"] = doc["sources"][0]["source_location"]
    source_path.write_text(json.dumps(doc))
    with pytest.raises(CorpusError, match="duplicate source URL"):
        Phase5AKnowledgeRegistry(path, legacy_root=ROOT)


@pytest.mark.unit
def test_fake_locator_and_forbidden_excerpt_are_rejected_in_expanded_snapshot(tmp_path):
    path = copied_registry(tmp_path / "locator")
    card_path = path.parents[1] / "cards" / "options" / "expanded.json"
    doc = json.loads(card_path.read_text())
    doc["cards"][0]["exact_locator"] = "fabricated page 999"
    card_path.write_text(json.dumps(doc))
    with pytest.raises(CorpusError, match="locator"):
        Phase5AKnowledgeRegistry(path, legacy_root=ROOT)

    path = copied_registry(tmp_path / "excerpt")
    card_path = path.parents[1] / "cards" / "options" / "expanded.json"
    doc = json.loads(card_path.read_text())
    doc["cards"][0]["short_excerpt"] = "not licensed for an excerpt"
    card_path.write_text(json.dumps(doc))
    with pytest.raises(CorpusError, match="excerpt"):
        Phase5AKnowledgeRegistry(path, legacy_root=ROOT)

    path = copied_registry(tmp_path / "hash")
    source_path = path.parents[1] / "source_manifests" / "expanded_sources.json"
    doc = json.loads(source_path.read_text())
    doc["sources"][1]["document_hash"] = doc["sources"][0]["document_hash"]
    source_path.write_text(json.dumps(doc))
    with pytest.raises(CorpusError, match="duplicate source content hash"):
        Phase5AKnowledgeRegistry(path, legacy_root=ROOT)

    path = copied_registry(tmp_path / "user")
    user_path = path.parents[1] / "user_sources" / "fvg_strategy_notes.txt"
    user_path.write_text(user_path.read_text() + "\ntamper\n")
    with pytest.raises(CorpusError, match="user-provided source hash mismatch"):
        Phase5AKnowledgeRegistry(path, legacy_root=ROOT)


@pytest.mark.unit
def test_fetch_metadata_skips_same_url_hash_and_rejects_mismatch(tmp_path):
    registry = Phase5AKnowledgeRegistry()
    source = registry.source_records["oic-bid-ask-options-2024"]
    assert registry.source_fetch_required(source["source_id"], source_location=source["source_location"],
                                          expected_hash=source["document_hash"]) is False
    assert registry.source_fetch_required(source["source_id"], source_location=source["source_location"],
                                          expected_hash="0" * 64) is True
    assert registry.fetched_sources["network_fetches"] == {"attempted": 18, "accepted": 16, "pending": 2}

    path = copied_registry(tmp_path)
    fetched_path = path.parents[1] / "fetched_sources" / "expanded_fetched.json"
    doc = json.loads(fetched_path.read_text())
    next(row for row in doc["sources"] if row["source_id"] == "oic-bid-ask-options-2024")["sha256"] = "0" * 64
    fetched_path.write_text(json.dumps(doc))
    with pytest.raises(CorpusError, match="fetched source hash mismatch"):
        Phase5AKnowledgeRegistry(path, legacy_root=ROOT)


@pytest.mark.unit
def test_eleven_stage_ledger_is_hash_chained_complete_idempotent_and_restart_safe():
    registry = Phase5AKnowledgeRegistry()
    assert [stage.value for stage in IngestionStage] == [
        "DISCOVERED", "SOURCE_VERIFIED", "RIGHTS/ACCESS_CHECKED", "DUPLICATE_CHECKED", "FETCHED",
        "HASHED", "EXTRACTED", "REVIEWED", "CARD_VALIDATED", "REGISTERED", "RETRIEVAL_TESTED",
    ]
    ledger = IngestionLedger(registry.ingestion_ledger_path)
    assert len(ledger.events) == 27 * 11 and ledger.verify()
    source_ids = {row["source_id"] for row in registry.fetched_sources["sources"]}
    assert len(source_ids) == 27
    assert all(ledger.state(source_id) is IngestionStage.RETRIEVAL_TESTED for source_id in source_ids)
    last = ledger.events[-1]
    assert ledger.advance(candidate_id=last["candidate_id"], stage=IngestionStage.RETRIEVAL_TESTED,
                          idempotency_key=last["idempotency_key"], actor_id="different",
                          correlation_id="different", details={}) == last


@pytest.mark.unit
def test_pending_youtube_and_blocked_academic_sources_never_become_cards():
    registry = Phase5AKnowledgeRegistry()
    pending = registry.pending["pending"]
    youtube = [row for row in pending if row["candidate_id"].startswith("youtube-")]
    assert len(youtube) == 21 and all("not independently reviewed" in row["reason"] for row in youtube)
    assert {row["candidate_id"] for row in pending} >= {
        "original-candlestick-pattern-research", "white-reality-check-original-paper"
    }
    assert not any(card.source_id.startswith("youtube-") for card in registry.curated_cards.values())
    assert registry.audit["youtube_transcripts_verified"] == 0 and registry.audit["books_ingested"] == 0


@pytest.mark.unit
def test_user_fvg_cards_are_granular_unvalidated_and_fixed_rr_is_hypothesis():
    registry = Phase5AKnowledgeRegistry()
    cards = [card for card in registry.curated_cards.values() if card.domain == "user_fvg"]
    assert len(cards) == 25
    assert {card.validation_status for card in cards} == {"USER_PROVIDED_UNVALIDATED", "HYPOTHESIS"}
    fixed = registry.raw("user-fvg-fixed-rr-hypothesis")
    assert fixed.validation_status == "HYPOTHESIS"
    assert "natural" in fixed.definition_principle.lower()
    assert "construction-no-fixed-rr-targets" in fixed.contradicts_card_ids
    assert not any(card.validation_status == "INTERNALLY_VALIDATED" for card in cards)


@pytest.mark.unit
def test_context_displacement_liquidity_options_transfer_and_data_boundaries_are_preserved():
    registry = Phase5AKnowledgeRegistry()
    assert "context" in registry.raw("brooks-context-over-candle-name").concept.lower()
    assert "trend/range" in registry.raw("grimes-structure-before-pattern").definition_principle.lower()
    assert "not a setup" in registry.raw("brooks-context-over-candle-name").definition_principle.lower()
    assert "strong middle displacement" in registry.raw("user-fvg-displacement-filter").definition_principle.lower()
    assert "not a standalone" in registry.raw("user-fvg-not-standalone-entry").concept.lower()
    sweep = registry.raw("liquidity-sweep-no-causality")
    assert any("Only a wick" in failure for failure in sweep.failure_conditions)
    ob = registry.raw("smc-order-block-bos-choch-boundary")
    assert {"versioned", "completed close", "immutable"} <= {
        term for term in ("versioned", "completed close", "immutable")
        if term in " ".join(ob.measurable_predicates).lower()
    }
    assert "theoretical" in registry.raw("occ-greeks-sensitivities").definition_principle.lower()
    assert "indian index options" in registry.raw("frbny-stop-cascade-transfer-limit").definition_principle.lower()
    assert registry.raw("mlofi-multiple-depth-levels").validation_status == "FUTURE_DATA_DEPENDENT"
    assert registry.raw("micro-ofi-price-impact").validation_status == "FUTURE_DATA_DEPENDENT"


@pytest.mark.unit
def test_exactly_ten_research_only_setups_and_none_are_retrievable_live():
    service = KnowledgeRetrievalService()
    research = service.research_cards()
    expected = {
        "LIQUIDITY_SWEEP_RECLAIM", "BREAKOUT_ACCEPTANCE_RETEST", "FAILED_BREAKOUT_REVERSAL",
        "TREND_PULLBACK", "COMPRESSION_DISPLACEMENT", "DISPLACEMENT_FVG_RETEST",
        "BREAKAWAY_FVG_CONTINUATION", "DEMAND_VOB_FVG_CONFLUENCE",
        "PREMIUM_CONFIRMED_CONTINUATION", "PREMIUM_CONFIRMED_REVERSAL",
    }
    assert len(research) == 10
    assert {card.setup_types[0] for card in research} == expected
    assert all(card.research_fields["research_status"] == "RESEARCH_ONLY" for card in research)
    result = service.search(build_query(instrument="NIFTY", timeframe="3m", setup_type="DISPLACEMENT_FVG_RETEST",
                                        question="FVG displacement retest entry target"))
    assert result.card_references
    assert all(not service.registry.raw(ref.card_id).research_only for ref in result.card_references)


@pytest.mark.unit
def test_fvg_retrieval_is_deterministic_bounded_and_returns_material_counterprinciple():
    service = KnowledgeRetrievalService()
    query = build_query(instrument="NIFTY", timeframe="3m", setup_type="DISPLACEMENT_FVG_RETEST", maximum_cards=5,
                        question="FVG liquidity sweep displacement retest contradiction",
                        current_evidence_claims=("three candle gap", "liquidity sweep"))
    first = service.search(query); second = service.search(query)
    ids = {ref.card_id for ref in first.card_references}
    assert first.content_hash == second.content_hash and 1 <= len(ids) <= 5
    assert "user-fvg-liquidity-sweep-filter" in ids
    assert "liquidity-sweep-no-causality" in ids
    assert any("hidden liquidity" in conflict.explanation for conflict in first.conflicts)
    assert first.whole_source_loaded is False
    unsupported = service.search(build_query(instrument="AAPL", timeframe="3m", question="FVG displacement"))
    assert unsupported.card_references == ()


@pytest.mark.unit
def test_official_and_primary_domains_have_multiple_independent_sources():
    registry = Phase5AKnowledgeRegistry()
    domain_sources: dict[str, set[str]] = {}
    for card in registry.curated_cards.values():
        if card.research_only or card.validation_status == "USER_PROVIDED_UNVALIDATED":
            continue
        domain_sources.setdefault(card.domain, set()).add(card.source_id)
    assert len(domain_sources["price_action"] | domain_sources["market_structure"] | domain_sources["candlesticks"]) >= 5
    assert len(domain_sources["options"] | domain_sources["volatility"]) >= 4
    assert len(domain_sources["microstructure"] | domain_sources["order_flow"]) >= 4
    assert len(domain_sources["systematic_validation"]) >= 4


@pytest.mark.safety
def test_no_probability_promotion_runtime_web_or_forbidden_authority_dependency():
    registry = Phase5AKnowledgeRegistry()
    for card in registry.curated_cards.values():
        payload = card.to_dict()
        assert payload["execution_influence"] == "ZERO"
        assert "historical_probability" not in payload and "execution_authority" not in payload
    files = [Path("src/oracle/knowledge_corpus.py"), Path("src/oracle/knowledge_engine.py"),
             Path("scripts/build_expanded_knowledge_corpus.py")]
    forbidden_imports = ("requests", "httpx", "urllib", "risk", "guardian", "paper", "dhan", "openalgo", "mission", "condition")
    for path in files:
        tree = ast.parse(path.read_text(), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.lower() for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.append((node.module or "").lower())
        assert not any(any(token in name for token in forbidden_imports) for name in imports)


@pytest.mark.unit
def test_warm_expanded_retrieval_p95_under_50ms():
    service = KnowledgeRetrievalService()
    query = build_query(instrument="NIFTY", timeframe="3m", maximum_cards=5,
                        question="FVG displacement retest liquidity sweep contradiction")
    service.search(query)
    samples = []
    for _ in range(250):
        start = perf_counter(); service.search(query); samples.append((perf_counter() - start) * 1000)
    samples.sort()
    assert samples[int(len(samples) * .95) - 1] <= 50
