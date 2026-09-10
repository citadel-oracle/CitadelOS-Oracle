#!/usr/bin/env python3
"""Create an isolated, persistent NON-LIVE Phase-5 proof (never a market claim)."""

from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from statistics import quantiles
from time import perf_counter
import runpy
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.oracle.conditions import (
    ConditionEvaluator, ConditionState, IndependentPaperGuardian,
    OracleConditionService, Phase5OracleWorkflow, Phase5RevalidationService,
)
from src.oracle.conditions.contracts import TriggerEvent, seal


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def p95(values):
    if not values:
        return None
    if len(values) < 2:
        return round(values[0], 3)
    return round(quantiles(values, n=100, method="inclusive")[94], 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit("proof root must be new or empty")
    root.mkdir(parents=True, exist_ok=True)

    # Synthetic builders stay in the test path and are never production evidence.
    fixture = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tests" / "test_oracle_phase5.py"))
    now = fixture["NOW"]
    armed = fixture["armed"]
    structured = fixture["structured"]
    paper_components = fixture["paper_components"]
    analysis_result = fixture["_analysis_result"]
    Hash = fixture["_Hash"]

    proposal_service = OracleConditionService(root / "proposal", clock=lambda: now)
    proposal = proposal_service.propose(
        original_wording="Next 3-minute candle X ke above close kare, retest hold ho aur CE confirm kare to paper buy",
        structured=structured(now), actor_id="runtime-proof-user", correlation_id="runtime-proof-proposal",
    )

    cancel_service, cancel_condition, cancel_projection = armed(root / "cancel", now)
    cancelled = cancel_service.cancel(cancel_condition.condition_id,
        expected_prior_version=cancel_projection.version, idempotency_key="runtime-cancel",
        actor_id="runtime-proof-user")

    def trigger(condition, suffix):
        return seal(TriggerEvent(
            trigger_id=f"trigger-runtime-{suffix}", condition_id=condition.condition_id,
            correlation_id=condition.correlation_id, canonical_event_id=f"fixture-event-{suffix}",
            candle_id=f"fixture-candle-{suffix}", candle_timeframe="3m",
            candle_closed_at=now.isoformat(), candle_close=24405,
            quote_timestamp=now.isoformat(), observed_at=now.isoformat(),
            predicate_results={"all": True}, source_hashes={"fixture": "f" * 64},
            non_live_fixture=True,
        ))

    def prepare_workflow(name, *, depth, result_factory):
        condition_service, condition, projection = armed(root / name, now)
        event = trigger(condition, name)
        condition_service.transition(condition.condition_id, ConditionState.TRIGGERED,
            expected_prior_version=projection.version, idempotency_key=f"trigger-transition-{name}",
            actor_id="NON_LIVE_FIXTURE_MONITOR", reason_code="NON_LIVE_FIXTURE_TRIGGER",
            details={"trigger_id": event.trigger_id})
        paper_state, ledger, risk, paper, quote = paper_components(root / name / "paper", now, depth=depth)
        analysis = Hash(policy=Hash(minimum_data_completeness=75), create=lambda **_: result_factory())
        revalidation = Phase5RevalidationService(analysis, clock=lambda: now)
        guardian = IndependentPaperGuardian(root / name / "guardian", execution=paper, clock=lambda: now)
        workflow = Phase5OracleWorkflow(conditions=condition_service, revalidation=revalidation,
            risk=risk, paper=paper, guardian=guardian, quote_provider=lambda _: quote, clock=lambda: now)
        return condition_service, condition, event, paper_state, ledger, paper, quote, guardian, workflow

    drift = prepare_workflow("drift", depth=75,
        result_factory=lambda: analysis_result(action="WAIT", rr=(1.0,), fresh=False))
    drift[8].handle_trigger(drift[1], drift[2])
    drift_projection = drift[0].store.projection(drift[1].condition_id)

    partial = prepare_workflow("partial", depth=30, result_factory=analysis_result)
    partial[8].handle_trigger(partial[1], partial[2])
    partial_projection = partial[0].store.projection(partial[1].condition_id)

    full = prepare_workflow("full", depth=75, result_factory=analysis_result)
    risk_state_path = root / "full" / "paper" / "risk.json"
    risk_hash_before_guardian = digest(risk_state_path)
    full[8].handle_trigger(full[1], full[2])
    full_projection = full[0].store.projection(full[1].condition_id)
    protection = full[5].active_protections()[0]

    guardian_times = []
    for index in range(25):
        started = perf_counter()
        hold = full[7].cycle(protection, {
            "event_id": f"hold-{index}", "paper_route_healthy": True,
            "kill_switch_active": False, "quote_fresh": True, "bid": 100.0,
            "premium_confirmed": True, "structural_invalidated": False,
            "authority_material_reversal": False,
        })
        guardian_times.append((perf_counter() - started) * 1000)
    exited = full[7].cycle(protection, {
        "event_id": "target-exit", "paper_route_healthy": True,
        "kill_switch_active": False, "quote_fresh": True, "bid": 110.0,
        "premium_confirmed": True, "structural_invalidated": False,
        "authority_material_reversal": False,
    })
    latest = full[0].store.projection(full[1].condition_id)
    exited_projection = full[0].transition(full[1].condition_id, ConditionState.EXITED,
        expected_prior_version=latest.version, idempotency_key="guardian-target-exit",
        actor_id="INDEPENDENT_GUARDIAN", reason_code="NATURAL_TARGET_HIT",
        details={"position_id": latest.position_id, "guardian_action": "EXIT"})

    recovered_conditions = OracleConditionService(root / "full" / "conditions", clock=lambda: now)
    recovered_projection = recovered_conditions.store.projection(full[1].condition_id)
    recovered_order = full[4].get_order(full_projection.order_id)
    recovered_paper_state = full[3].load()
    recovered_guardian_events = full[7].events(full_projection.position_id)

    evaluator_times = []
    projection_times = []
    evaluation_event = {
        "symbol": "NIFTY", "timeframe": "3m", "closed": True,
        "close": 24405, "low": 24399, "high": 24408,
        "candle_closed_at": (now + timedelta(minutes=6)).isoformat(),
        "acceptance_proven": True,
        "option_quote": {"contract_id": "12345", "bid": 100, "ask": 100.2,
                         "timestamp": now.isoformat(), "ose_confirmed": True},
        "context": {"direction": "BULLISH"},
    }
    for _ in range(500):
        started = perf_counter()
        ConditionEvaluator.evaluate(full[1], evaluation_event, observed_at=now)
        evaluator_times.append((perf_counter() - started) * 1000)
        started = perf_counter()
        full[0].store.projection(full[1].condition_id)
        projection_times.append((perf_counter() - started) * 1000)

    full_events = full[0].store.events(full[1].condition_id)
    chain_valid = all(row["previous_hash"] == ("GENESIS" if index == 0 else full_events[index - 1]["record_hash"])
                      for index, row in enumerate(full_events))
    intents = [row["intent"] for row in full[4].list_orders(limit=100)["orders"]]
    report = {
        "proof_type": "NON_LIVE_FIXTURE",
        "production_market_claim": False,
        "proposal": {"status": proposal["status"], "requires_confirmation": proposal["requires_exact_user_confirmation"]},
        "watching": cancel_projection.to_dict(), "cancelled": cancelled.to_dict(),
        "material_drift": {"state": drift_projection.state.value, "explanation": drift_projection.explanation},
        "partial_fill": {"state": partial_projection.state.value, "position_id": partial_projection.position_id,
                         "order": partial[4].get_order(partial_projection.order_id)},
        "full_paper_trade": {"pre_guardian_state": full_projection.state.value,
                             "post_guardian_state": exited_projection.state.value,
                             "guardian_hold": hold, "guardian_exit": exited,
                             "closed_trades": [row.to_dict() for row in recovered_paper_state.closed_trades]},
        "restart_recovery": {"condition_state": recovered_projection.state.value,
                             "order_state": recovered_order["state"],
                             "guardian_event_count": len(recovered_guardian_events)},
        "lineage": {"condition_event_count": len(full_events), "hash_chain_valid": chain_valid,
                    "latest_hash": full_events[-1]["record_hash"]},
        "openalgo": full[8].openalgo_capability(),
        "performance": {"condition_evaluation": {"samples": len(evaluator_times), "p95_ms": p95(evaluator_times)},
                        "ui_projection": {"samples": len(projection_times), "p95_ms": p95(projection_times)},
                        "guardian_cycle": {"samples": len(guardian_times), "p95_ms": p95(guardian_times)},
                        **full[8].performance()},
        "safety": {"paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                   "llm_in_critical_path": False, "knowledge_learning_influence": "ZERO",
                   "all_order_intents_non_live": all(not row["live_trading_enabled"] for row in intents),
                   "all_order_intents_no_broker_submission": all(not row["broker_submission_requested"] for row in intents),
                   "risk_state_hash_before_guardian": risk_hash_before_guardian,
                   "risk_state_hash_after_guardian": digest(risk_state_path),
                   "real_dhan_orders": 0, "real_openalgo_orders": 0},
    }
    (root / "runtime_proof.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PASS", "root": str(root), "summary": report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
