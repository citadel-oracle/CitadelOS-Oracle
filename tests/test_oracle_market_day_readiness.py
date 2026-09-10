from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.oracle.market_day import (
    BlockerClassification, MarketDayError, MarketDayReadinessService, PayoffQuality,
    SAFETY, classify_blocker, payoff_diagnostic,
)


NOW = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)


def projection(*, action="WAIT", decision_hash="d" * 64, reason_codes=None):
    return {
        "generated_timestamp": NOW.isoformat(), "sync_state": action, "safety": dict(SAFETY),
        "chart_state": {"availability": "AVAILABLE", "timeframe": "3m",
            "instrument": {"underlying": "NIFTY", "security_id": "13"},
            "option": {"expiry": "2026-08-04", "strike": 24500, "option_side": "CE",
                       "security_id": "65001", "trading_symbol": "NIFTY26080424500CE"}},
        "decision": {
            "decision_id": "decision_market_day_fixture", "content_hash": decision_hash,
            "decision_timestamp": NOW.isoformat(), "candle_timestamp": "2026-08-03T09:18:00+05:30",
            "completed_candle": True, "action": action, "freshness": "FRESH", "market_state": "OPEN",
            "exact_contract": "NIFTY26080424500CE (65001)", "current_security_id": "65001",
            "setup_family": "BREAKOUT_RETEST", "trigger": "3m close above 24520 and retest hold",
            "entry_band": [101.0, 102.0], "premium_stop": 96.0,
            "structural_stop": {"invalidation_id": "inv-1", "level": 24488.0,
                                "mapping_status": "DELTA_APPROXIMATION_LOW_CONFIDENCE"},
            "targets": [112.0, 120.0], "natural_targets": [{"target_id": "t1", "level": 24580.0}],
            "costs": 0.5, "resulting_rr": [1.73, 3.06],
            "market_thesis": {"direction": "BULLISH", "location_quality": "FAVOURABLE"},
            "provider_lineage": {
                "ARGUS": {"state": "BULLISH", "freshness": "FRESH", "source_id": "argus-1",
                          "source_hash": "a" * 64, "timestamp": NOW.isoformat()},
                "VOB": {"state": "AVAILABLE", "freshness": "FRESH", "source_id": "vob-1",
                        "source_hash": "v" * 64, "timestamp": NOW.isoformat()},
                "OSE": {"state": "CONFIRMED", "freshness": "FRESH", "source_id": "ose-1",
                        "source_hash": "o" * 64, "timestamp": NOW.isoformat()}},
            "source_hashes": {"analysis_snapshot": "s" * 64, "evidence_bundle": "e" * 64},
            "knowledge_card_ids": ["card-1"],
            "evidence": {"supporting": ["completed breakout"], "conflicting": [], "missing": []},
            "reason_codes": reason_codes or (["TRIGGER_INCOMPLETE"] if action == "WAIT" else []),
            "risk_conflict": "Advisory only", "execution_authority": False,
        },
        "knowledge": {"status": "AVAILABLE"},
        "personal_oracle": {"available": True, "cooldown_status": "WAIT",
            "obsidian_sync_status": "NO_COMPLETED_TRADE_SYNC",
            "second_brain": {"discipline": {"recommendation": "WAIT", "warnings": []}}},
        "phase5": {"condition_id": None, "condition_state": None, "condition_version": None,
            "trigger_id": None, "revalidation_id": None, "authorization_id": None, "order": None,
            "paper_order_state": None, "position_id": None, "protection": None,
            "guardian_action": None, "guardian_health": {"cycles": 1}, "latest_event_hash": None,
            "paper_only": True, "live_trading_enabled": False, "broker_submission": False},
        "health": {"worker_alive": True, "push_transport": "SSE_PRIMARY_POLLING_FALLBACK",
                   "telemetry": {"argus_retrieval": {"latest_ms": 4.0}}},
    }


def test_complete_immutable_ledger_and_outcome_link(tmp_path):
    service = MarketDayReadinessService(tmp_path, minimum_rr=1.5, clock=lambda: NOW)
    source = projection()
    observed = service.observe(source)
    assert observed["recorded"] is True
    record = service.store.decision_rows()[0]["payload"]
    required = {"decision_id", "source_hashes", "decision_timestamp", "instrument", "candle_timestamp",
                "action", "setup_family", "trigger", "entry_band", "structural_stop", "natural_targets",
                "costs", "resulting_rr", "market_thesis", "providers", "risk_state", "discipline_state",
                "position_guardian_state", "knowledge_card_ids", "supporting_evidence", "conflicting_evidence",
                "missing_evidence", "primary_blocker", "execution_authority"}
    assert required <= record.keys()
    original = deepcopy(record)
    outcome = service.store.append_outcome(record["decision_id"], {
        "outcome_status": "TARGET_BEFORE_STOP", "mfe": 16.0, "mae": 3.0,
        "exit_timestamp": "2026-08-03T10:06:00+05:30", "exit_reason": "NATURAL_TARGET",
        "gross_premium_points": 10.0, "net_premium_points": 9.5, "r_multiple": 1.73,
        "holding_time_seconds": 2880, "capture_efficiency": 0.625,
    }, idempotency_key="outcome-1")
    assert outcome["payload"]["original_decision_unchanged"] is True
    assert service.store.append_outcome(record["decision_id"], {
        "outcome_status": "TARGET_BEFORE_STOP", "mfe": 16.0, "mae": 3.0,
        "exit_timestamp": "2026-08-03T10:06:00+05:30", "exit_reason": "NATURAL_TARGET",
        "gross_premium_points": 10.0, "net_premium_points": 9.5, "r_multiple": 1.73,
        "holding_time_seconds": 2880, "capture_efficiency": 0.625,
    }, idempotency_key="outcome-1")["record_hash"] == outcome["record_hash"]
    with pytest.raises(MarketDayError, match="IDEMPOTENCY_CONFLICT"):
        service.store.append_outcome(record["decision_id"], {"outcome_status": "STOP_BEFORE_TARGET"},
                                     idempotency_key="outcome-1")
    assert service.store.decision(record["decision_id"]) == original
    assert all(value["valid"] for value in service.store.verify().values())
    with pytest.raises(MarketDayError, match="PRIOR_HASH_CONFLICT"):
        service.store.append_outcome(record["decision_id"], {"outcome_status": "STOP_BEFORE_TARGET"},
                                     idempotency_key="outcome-2")


def test_blocker_classification_is_explicit_and_primary():
    stale = projection(reason_codes=["NO_ELIGIBLE_OPTION_CONTRACT", "STALE_CRITICAL_SOURCE"])
    stale["decision"]["freshness"] = "STALE"
    assert classify_blocker(stale["decision"], stale) == BlockerClassification.STALE_CRITICAL_SOURCE.value
    contract = projection(reason_codes=["NO_ELIGIBLE_OPTION_CONTRACT"])
    assert classify_blocker(contract["decision"], contract) == BlockerClassification.CONTRACT_REJECTED.value
    position = projection()
    position["phase5"]["position_id"] = "paper-position-1"
    assert classify_blocker(position["decision"], position) == BlockerClassification.POSITION_ALREADY_OPEN.value


def test_payoff_diagnostic_uses_existing_boundary_and_never_changes_action():
    value = projection()["decision"]
    assert payoff_diagnostic(value, minimum_rr=1.5)["quality"] == PayoffQuality.GOOD.value
    value["resulting_rr"] = [1.2]
    assert payoff_diagnostic(value, minimum_rr=1.5)["quality"] == PayoffQuality.MARGINAL.value
    value["costs"] = None
    missing = payoff_diagnostic(value, minimum_rr=1.5)
    assert missing["quality"] == PayoffQuality.NOT_REPORTED.value
    assert "COST_ESTIMATE_UNAVAILABLE" in missing["reason"]
    assert projection()["decision"]["action"] == "WAIT"


def test_compact_scan_contains_only_market_desk_truth(tmp_path):
    service = MarketDayReadinessService(tmp_path, minimum_rr=1.5, clock=lambda: NOW)
    output = service.command(".", projection(), idempotency_key="read")["output"]
    assert output["decision"] == "WAIT" and output["contract"] == "NIFTY26080424500CE (65001)"
    assert output["entry"] == 102.0 and output["sl"] == 96.0
    assert output["t1"] == 112.0 and output["t2"] == 120.0 and output["rr_after_costs"] == 3.06
    assert set(output["states"]) == {"PA", "ARGUS", "VOB", "OSE", "Risk", "Discipline"}
    assert len(output["blockers"]) <= 3 and output["expand"] == ["WHY", "DETAILS", "PROOF"]


def test_soak_deduplicates_recovers_and_never_mutates_trading_state(tmp_path):
    service = MarketDayReadinessService(tmp_path, minimum_rr=1.5, clock=lambda: NOW)
    source = projection()
    started = service.start_soak(source, idempotency_key="soak-start")
    assert started["status"] == "ACTIVE"
    assert service.observe(source)["recorded"] is True
    assert service.observe(source)["reason"] == BlockerClassification.DUPLICATE_SUPPRESSED.value
    source["phase5"]["guardian_health"]["cycles"] = 99
    recovered = MarketDayReadinessService(tmp_path, minimum_rr=1.5, clock=lambda: NOW)
    assert recovered.soak_status()["restart_recovered"] is True
    stopped = recovered.stop_soak(source, idempotency_key="soak-stop")
    proof = stopped["report"]["safety_no_mutation"]
    assert proof["unchanged"] is True
    assert proof["risk_authorization_calls"] == proof["order_submission_calls"] == 0
    assert stopped["report"]["blocked_decisions_by_reason"] == {"MARKET_REJECTED": 1}


def test_incomplete_or_unsafe_projection_is_not_recorded(tmp_path):
    service = MarketDayReadinessService(tmp_path, minimum_rr=1.5, clock=lambda: NOW)
    incomplete = projection()
    incomplete["decision"]["completed_candle"] = False
    assert service.observe(incomplete)["reason"] == "COMPLETED_CANDLE_DECISION_UNAVAILABLE"
    unsafe = projection()
    unsafe["safety"]["live_trading_enabled"] = True
    with pytest.raises(MarketDayError, match="SAFETY_STATE_CONFLICT"):
        service.observe(unsafe)
