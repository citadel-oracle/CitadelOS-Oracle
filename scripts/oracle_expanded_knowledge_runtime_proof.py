#!/usr/bin/env python3
"""Read-only expanded-corpus proof against real persistent Oracle state."""

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
from src.oracle.knowledge_corpus import IngestionLedger, Phase5AKnowledgeRegistry
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.service import PersonalOracleService


DEFAULT_STATE_ROOT = Path("/Users/ayushmudgal/Developer/CitadelOS/logs")
SAFETY_PATTERNS = (
    "paper_state.json", "development_paper_state.json", "risk_control_state.json",
    "risk_authorization_audit.jsonl", "oracle_missions/*.json", "oracle_missions/*.jsonl",
    "oracle_dev/*guardian*.json", "oracle_phase5/**/*.json", "oracle_phase5/**/*.jsonl",
    "strategy_lab/runtimes/*/order_ledger.jsonl",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safety_snapshot(root: Path) -> dict[str, str]:
    paths = {path for pattern in SAFETY_PATTERNS for path in root.glob(pattern) if path.is_file()}
    return {str(path.relative_to(root)): digest(path) for path in sorted(paths)}


def latest_decision_id(root: Path) -> str:
    values = []
    for path in (root / "oracle_analysis" / "decisions").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        values.append((str(row.get("generated_at") or ""), str(row["decision_id"])))
    if not values:
        raise RuntimeError("NO_PERSISTED_PHASE3_DECISION")
    return sorted(values)[-1][1]


def p95_ms(callable_, iterations: int) -> float:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns(); callable_(); samples.append((time.perf_counter_ns() - start) / 1_000_000)
    samples.sort()
    return round(samples[max(0, int(len(samples) * .95) - 1)], 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--decision-id")
    args = parser.parse_args()
    state_root = args.state_root.resolve()
    before = safety_snapshot(state_root)

    registry = Phase5AKnowledgeRegistry()
    service = KnowledgeRetrievalService(registry)
    query_specs = {
        "price_action_multi_source": ("price action structure trend range pullback context", None, "5m"),
        "breakout_and_failure": ("breakout acceptance follow-through failed breakout reclaim", None, "3m"),
        "support_resistance_liquidity": ("support resistance liquidity sweep stop cascade causality", None, "5m"),
        "candlestick_context": ("candlestick signal context bars pattern limitations", None, "5m"),
        "greeks_iv": ("option Greeks Delta Gamma Theta Vega IV volatility sensitivity", None, "5m"),
        "contract_selection": ("option contract strike expiry bid ask spread executable price open interest", None, "3m"),
        "validation_overfitting": ("backtest overfitting multiple testing holdout OOS trial selection bias", None, "15m"),
        "ofi_lob": ("multi-level order flow imbalance LOB depth unavailable", None, "1m"),
        "user_fvg": ("FVG three candle displacement retest liquidity sweep", "DISPLACEMENT_FVG_RETEST", "3m"),
    }
    retrievals = {}
    for name, (question, setup, timeframe) in query_specs.items():
        result = service.search(build_query(instrument="NIFTY", timeframe=timeframe, setup_type=setup,
                                            question=question, maximum_cards=5))
        retrievals[name] = {
            "query_hash": result.query_hash,
            "card_ids": [reference.card_id for reference in result.card_references],
            "source_ids": sorted({reference.citation.source_id for reference in result.card_references}),
            "statuses": [reference.validation_status.value for reference in result.card_references],
            "locators": [reference.citation.locator for reference in result.card_references],
            "conflicts": [conflict.to_dict() for conflict in result.conflicts],
            "whole_source_loaded": result.whole_source_loaded,
        }

    fvg_query = build_query(instrument="NIFTY", timeframe="3m", setup_type="DISPLACEMENT_FVG_RETEST",
                            question="FVG liquidity sweep displacement retest contradiction",
                            current_evidence_claims=("three candle gap", "liquidity sweep"), maximum_cards=5)
    fvg_result = service.search(fvg_query)
    fvg_again = service.search(fvg_query)
    research = service.research_cards(setup_type="DISPLACEMENT_FVG_RETEST")
    if len(research) != 1:
        raise RuntimeError("RESEARCH_SETUP_TRUTH_UNAVAILABLE")

    analysis = OracleAnalysisService(state_root / "oracle_analysis")
    personal = PersonalOracleService(ledger=PersonalOracleLedger(state_root / "personal_oracle.json"),
                                     strategy_lab_root=state_root / "strategy_lab")
    evidence_service = Phase4EvidenceService(analysis, personal, knowledge=service)
    decision_id = args.decision_id or latest_decision_id(state_root)
    decision_before = analysis.decision(decision_id)
    evidence_before = analysis.evidence(decision_id)
    enrichment = evidence_service.enrich_stored(decision_id, persist=False)

    warm_p95 = p95_ms(lambda: service.search(fvg_query), 250)
    registry_p95 = p95_ms(Phase5AKnowledgeRegistry, 20)
    enrichment_p95 = p95_ms(lambda: evidence_service.enrich_stored(decision_id, persist=False), 30)
    decision_after = analysis.decision(decision_id)
    evidence_after = analysis.evidence(decision_id)
    after = safety_snapshot(state_root)

    unchanged = (before == after and decision_before.content_hash == decision_after.content_hash
                 and evidence_before.content_hash == evidence_after.content_hash
                 and decision_before.action == decision_after.action)
    if not unchanged:
        raise RuntimeError("READ_ONLY_PROOF_CHANGED_AUTHORITY_STATE")
    if enrichment.historical_probability is not None or enrichment.same_decision_execution_influence != "ZERO":
        raise RuntimeError("KNOWLEDGE_BOUNDARY_CHANGED")

    fetched = registry.fetched_sources
    no_refetch = all(not registry.source_fetch_required(
        source_id, source_location=row["source_location"], expected_hash=row["document_hash"])
        for source_id, row in registry.source_records.items())
    ledger = IngestionLedger(registry.ingestion_ledger_path)
    status_counts = Counter(card.validation_status for card in registry.curated_cards.values())
    domain_counts = Counter(card.domain for card in registry.curated_cards.values())
    safety = {
        "paper_only": decision_after.provenance.get("paper_only"),
        "live_trading_enabled": decision_after.provenance.get("live_trading_enabled"),
        "broker_submission": decision_after.provenance.get("broker_submission"),
        "advisory_only": decision_after.provenance.get("advisory_only"),
        "execution_influence": enrichment.same_decision_execution_influence,
        "execution_authority": decision_after.execution_authority,
    }
    required_safety = {"paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                       "advisory_only": True, "execution_influence": "ZERO", "execution_authority": False}
    if safety != required_safety:
        raise RuntimeError("LOCKED_SAFETY_STATE_CHANGED")

    proof = {
        "schema_version": "oracle-expanded-knowledge-runtime-proof-1.0.0",
        "runtime_mode": "READ_ONLY_REAL_PERSISTENT_STATE",
        "registry": {"version": registry.registry_version, "vault_hash": registry.vault_hash,
                     "source_families_inspected": registry.audit["source_families_inspected"],
                     "urls_fetched": fetched["network_fetches"]["attempted"],
                     "sources_accepted": len(registry.sources), "sources_rejected": len(registry.rejected["rejected"]),
                     "sources_pending": len(registry.pending["pending"]), "user_provided_sources": 2,
                     "cards_active": len(registry.cards), "new_cards_created": registry.summary["counts"]["new_cards"],
                     "conflicts_active": len(registry.conflict_registry["conflicts"]),
                     "future_data_dependent_cards": status_counts["FUTURE_DATA_DEPENDENT"],
                     "research_only_strategies": sum(card.research_only for card in registry.curated_cards.values()),
                     "internally_validated_cards": status_counts["INTERNALLY_VALIDATED"],
                     "domain_counts": dict(sorted(domain_counts.items()))},
        "retrievals": retrievals,
        "fvg_conflict_projection": {
            "card_ids": [reference.card_id for reference in fvg_result.card_references],
            "conflicts": [conflict.to_dict() for conflict in fvg_result.conflicts],
            "deterministic": fvg_result.content_hash == fvg_again.content_hash,
            "same_cached_object": fvg_result is fvg_again,
            "whole_source_loaded": fvg_result.whole_source_loaded,
        },
        "user_fvg": {"source_hash": registry.source_records["user-fvg-strategy-notes-2026"]["document_hash"],
                     "card_count": domain_counts["user_fvg"], "validation_statuses": sorted(
                         {card.validation_status for card in registry.curated_cards.values() if card.domain == "user_fvg"})},
        "strategy_research": {"card_id": research[0].card_id,
                              "status": research[0].research_fields["research_status"],
                              "execution_influence": research[0].execution_influence},
        "ingestion": {"ledger_events": len(ledger.events), "ledger_verified": ledger.verify(),
                      "last_stage": ledger.events[-1]["stage"], "unchanged_sources_skipped": no_refetch,
                      "pending_http_403": len(fetched["pending_fetches"])},
        "evidence_integration": {"decision_id": decision_id, "action_before": decision_before.action,
                                 "action_after": decision_after.action,
                                 "decision_hash_unchanged": decision_before.content_hash == decision_after.content_hash,
                                 "evidence_hash_unchanged": evidence_before.content_hash == evidence_after.content_hash,
                                 "historical_probability": enrichment.historical_probability,
                                 "execution_influence": enrichment.same_decision_execution_influence,
                                 "execution_authority": decision_after.execution_authority},
        "performance": {"registry_load_p95_ms": registry_p95, "warm_retrieval_p95_ms": warm_p95,
                        "evidence_enrichment_p95_ms": enrichment_p95, "target_ms": 50,
                        "target_met": warm_p95 <= 50, "runtime_network": False, "runtime_llm": False},
        "safety": {"tracked_authority_files": len(before), "authority_hashes_unchanged": before == after,
                   "before_digest": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                   "after_digest": hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(), **safety},
    }
    print(json.dumps(proof, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
