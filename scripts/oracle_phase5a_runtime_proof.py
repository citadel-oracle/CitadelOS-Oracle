#!/usr/bin/env python3
"""Read-only Phase-5A corpus, retrieval, and evidence-enrichment proof.

The proof reads an existing persistent Phase-3 decision but does not persist
knowledge output.  It also hashes every trading-authority artifact in scope
before and after execution and fails if any hash changes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.oracle.decision import OracleAnalysisService
from src.oracle.evidence import Phase4EvidenceService
from src.oracle.knowledge_corpus import LEGACY_PHASE5A_REGISTRY, Phase5AKnowledgeRegistry
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.service import PersonalOracleService


DEFAULT_STATE_ROOT = Path("/Users/ayushmudgal/Developer/CitadelOS/logs")
SAFETY_PATTERNS = (
    "paper_state.json",
    "development_paper_state.json",
    "risk_control_state.json",
    "risk_authorization_audit.jsonl",
    "oracle_missions/*.json",
    "oracle_missions/*.jsonl",
    "oracle_dev/*guardian*.json",
    "oracle_phase5/**/*.json",
    "oracle_phase5/**/*.jsonl",
    "strategy_lab/runtimes/*/order_ledger.jsonl",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safety_snapshot(root: Path) -> dict[str, str]:
    paths = {
        path
        for pattern in SAFETY_PATTERNS
        for path in root.glob(pattern)
        if path.is_file()
    }
    return {str(path.relative_to(root)): digest(path) for path in sorted(paths)}


def latest_decision_id(root: Path) -> str:
    rows = []
    for path in (root / "oracle_analysis" / "decisions").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows.append((str(value.get("generated_at") or ""), str(value["decision_id"])))
    if not rows:
        raise RuntimeError("NO_PERSISTED_PHASE3_DECISION")
    return sorted(rows)[-1][1]


def p95_ms(callable_, iterations: int) -> float:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        callable_()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    samples.sort()
    return round(samples[max(0, int(len(samples) * 0.95) - 1)], 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--decision-id")
    args = parser.parse_args()
    state_root = args.state_root.resolve()
    before = safety_snapshot(state_root)

    analysis = OracleAnalysisService(state_root / "oracle_analysis")
    personal = PersonalOracleService(
        ledger=PersonalOracleLedger(state_root / "personal_oracle.json"),
        strategy_lab_root=state_root / "strategy_lab",
    )
    registry = Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY)
    knowledge = KnowledgeRetrievalService(registry)
    phase4 = Phase4EvidenceService(analysis, personal, knowledge=knowledge)
    decision_id = args.decision_id or latest_decision_id(state_root)
    decision_before = analysis.decision(decision_id)
    evidence_before = analysis.evidence(decision_id)

    query = build_query(
        instrument=decision_before.symbol,
        timeframe="5m",
        question="option premium volatility expiry loss theta vega",
        current_evidence_claims=("premium response and spread",),
        maximum_cards=5,
    )
    retrieval = knowledge.search(query)
    retrieval_again = knowledge.search(query)
    enrichment = phase4.enrich_stored(decision_id, persist=False)

    accepted_id = "options-greeks-theoretical-not-guarantee"
    accepted = registry.raw(accepted_id)
    if accepted is None:
        raise RuntimeError("ACCEPTED_CARD_UNAVAILABLE")
    research = knowledge.research_cards(setup_type="ORDER_FLOW_IMBALANCE")
    if len(research) != 1:
        raise RuntimeError("RESEARCH_CARD_UNAVAILABLE")

    warm_retrieval_p95 = p95_ms(lambda: knowledge.search(query), 200)
    registry_load_p95 = p95_ms(lambda: Phase5AKnowledgeRegistry(LEGACY_PHASE5A_REGISTRY), 30)
    enrichment_p95 = p95_ms(lambda: phase4.enrich_stored(decision_id, persist=False), 30)

    decision_after = analysis.decision(decision_id)
    evidence_after = analysis.evidence(decision_id)
    after = safety_snapshot(state_root)
    if before != after:
        raise RuntimeError("TRADING_AUTHORITY_STATE_CHANGED")
    if (
        decision_before.content_hash != decision_after.content_hash
        or decision_before.action != decision_after.action
        or evidence_before.content_hash != evidence_after.content_hash
        or decision_after.execution_authority is not False
    ):
        raise RuntimeError("IMMUTABLE_PHASE3_DECISION_CHANGED")
    safety_values = {
        "paper_only": decision_after.provenance.get("paper_only"),
        "live_trading_enabled": decision_after.provenance.get("live_trading_enabled"),
        "broker_submission": decision_after.provenance.get("broker_submission"),
        "advisory_only": decision_after.provenance.get("advisory_only"),
        "learning_execution_influence": registry.summary["truth"]["execution_influence"],
        "execution_authority": decision_after.execution_authority,
    }
    if safety_values != {
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
        "advisory_only": True,
        "learning_execution_influence": "ZERO",
        "execution_authority": False,
    }:
        raise RuntimeError("LOCKED_SAFETY_STATE_CHANGED")

    status_counts = Counter(card.validation_status for card in registry.curated_cards.values())
    proof = {
        "schema_version": "oracle-phase5a-runtime-proof-1.0.0",
        "runtime_mode": "READ_ONLY_REAL_PERSISTENT_STATE",
        "corpus": {
            "registry_version": registry.registry_version,
            "vault_hash": registry.vault_hash,
            "accepted_sources": len(registry.sources),
            "accepted_cards": len(registry.curated_cards),
            "principle_cards": sum(not card.research_only for card in registry.curated_cards.values()),
            "strategy_research_cards": sum(card.research_only for card in registry.curated_cards.values()),
            "domain_counts": registry.summary["domain_counts"],
            "status_counts": dict(sorted(status_counts.items())),
            "pending_sources": len(registry.pending["pending"]),
            "rejected_candidates": len(registry.rejected["rejected"]),
            "internally_validated_cards": registry.summary["truth"]["internally_validated_cards"],
            "historical_probabilities_created": registry.summary["truth"]["historical_probabilities_created"],
            "strategies_promoted": registry.summary["truth"]["strategies_promoted"],
        },
        "accepted_card": {
            "card_id": accepted.card_id,
            "source_id": accepted.source_id,
            "source_title": registry.sources[accepted.source_id].title,
            "exact_locator": accepted.exact_locator,
            "source_hash_version": accepted.source_hash_version,
            "validation_status": accepted.validation_status,
            "execution_influence": accepted.execution_influence,
        },
        "retrieval": {
            "query_hash": retrieval.query_hash,
            "card_ids": [reference.card_id for reference in retrieval.card_references],
            "conflicts": [conflict.to_dict() for conflict in retrieval.conflicts],
            "bounded_to_five": len(retrieval.card_references) <= 5,
            "whole_source_loaded": retrieval.whole_source_loaded,
            "deterministic": retrieval.content_hash == retrieval_again.content_hash,
            "cache_hit_same_object": retrieval is retrieval_again,
        },
        "strategy_research": {
            "card_id": research[0].card_id,
            "research_status": research[0].research_fields["research_status"],
            "validation_status": research[0].validation_status,
            "execution_influence": research[0].execution_influence,
        },
        "excluded": {
            "pending_example": registry.pending["pending"][0],
            "rejected_example": registry.rejected["rejected"][0],
            "discovery_indexes_used_as_authority": False,
        },
        "evidence_integration": {
            "decision_id": decision_id,
            "non_live_fixture": "non-live-fixture" in decision_before.correlation_id.lower(),
            "knowledge_reference_ids": [reference.card_id for reference in enrichment.knowledge_references],
            "knowledge_conflicts": [conflict.to_dict() for conflict in enrichment.knowledge_conflicts],
            "historical_probability": enrichment.historical_probability,
            "calibration_state": enrichment.calibration_state.value,
            "original_action_before": decision_before.action,
            "original_action_after": decision_after.action,
            "decision_hash_unchanged": decision_before.content_hash == decision_after.content_hash,
            "evidence_hash_unchanged": evidence_before.content_hash == evidence_after.content_hash,
            "execution_authority_before": decision_before.execution_authority,
            "execution_authority_after": decision_after.execution_authority,
            "same_decision_execution_influence": enrichment.same_decision_execution_influence,
        },
        "performance": {
            "registry_load_p95_ms": registry_load_p95,
            "warm_retrieval_p95_ms": warm_retrieval_p95,
            "evidence_enrichment_p95_ms": enrichment_p95,
            "warm_retrieval_target_ms": 50,
            "warm_retrieval_target_met": warm_retrieval_p95 <= 50,
            "llm_required": False,
            "network_required_at_runtime": False,
        },
        "safety": {
            "tracked_authority_files": len(before),
            "authority_hashes_unchanged": before == after,
            **safety_values,
        },
    }
    print(json.dumps(proof, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
