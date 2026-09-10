"""Focused Phase-6B constitution, memory, discipline, learning and Obsidian tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import pytest

from src.oracle_personal.capture import PersonalOracleCapture
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.second_brain import (
    CONSTITUTION_VERSION, DisciplineEngine, LocalObsidianVault,
    OracleSecondBrainService, SecondBrainError, SecondBrainStore,
)
from src.oracle_personal.service import PersonalOracleService
from src.oracle.tradingview_sync import TradingViewAutoSyncService


pytestmark = pytest.mark.unit


def closed_trade(index=1, pnl=10.0):
    opened = datetime.fromisoformat("2026-08-01T09:30:00+05:30") + timedelta(minutes=index)
    return {
        "close_event_id": f"phase6b-close-{index}", "position_id": f"position-{index}",
        "instrument_id": "NIFTY", "symbol": "NIFTY", "option_type": "CE", "strike": 24400,
        "expiry": "2026-08-04", "side": "BUY", "closed_quantity": 75, "raw_quantity": 75,
        "lot_size": 75, "number_of_lots": 1, "entry_price": 100.0,
        "exit_price": 100.0 + pnl, "realized_pnl": pnl, "opened_at": opened.isoformat(),
        "closed_at": (opened + timedelta(minutes=5)).isoformat(), "exit_reason": "TARGET" if pnl > 0 else "STOP",
    }


def captured_event(tmp_path: Path, index=1, pnl=10.0):
    ledger = PersonalOracleLedger(tmp_path / f"personal-{index}.json")
    raw = closed_trade(index, pnl)
    context = {
        "captured_at": raw["opened_at"], "strategy_name": "ORACLE_FIXTURE",
        "strategy_version": "fixture-v1", "market_regime": "TRENDING",
        "technical_bias": "BULLISH", "argus_bias": "BULLISH",
        "planned_stop_price": 92.0, "planned_target_price": 112.0,
        "setup_tag": "BREAKOUT_RETEST",
    }
    assert PersonalOracleCapture(ledger).capture_closed_trade(raw, entry_context=context)
    return ledger.events()[0]


def service(tmp_path: Path, events=()):
    return OracleSecondBrainService(
        SecondBrainStore(tmp_path / "second-brain.json"),
        vault=LocalObsidianVault(tmp_path / "vault"), event_provider=lambda: tuple(events),
    )


def base_decision(**changes):
    value = {
        "decision_id": "decision-6b", "action": "WAIT", "why": "Trigger incomplete",
        "setup_quality": 70, "freshness": "FRESH", "missing_evidence": ["TRIGGER_INCOMPLETE"],
        "reason_codes": ["TRIGGER_INCOMPLETE"], "trigger": "close above level",
        "structural_invalidation": "swing-low", "targets": [120, 130],
        "execution_authority": False,
    }
    value.update(changes)
    return value


def test_constitution_is_immutable_versioned_and_referenced_by_every_projection(tmp_path):
    brain = service(tmp_path)
    constitution = brain.constitution()
    projection = brain.project(base_decision(), knowledge={"references": ["card-1"]})
    assert constitution["version"] == CONSTITUTION_VERSION and constitution["immutable"] is True
    assert len(constitution["principles"]) == 11 and len(constitution["content_hash"]) == 64
    assert projection["explainability"]["constitution_refs"] == [row["principle_id"] for row in constitution["principles"]]
    assert projection["safety"]["execution_influence"] == "ZERO"
    assert projection["safety"]["execution_authority"] is False


def test_trading_memory_is_append_only_idempotent_hash_chained_and_corrected_by_append(tmp_path):
    brain = service(tmp_path)
    fact = {"fact_type": "REPEATED_MISTAKE", "fact": "Late entry repeated",
            "evidence_references": ["trade-1", "trade-2"], "setup": "BREAKOUT"}
    first = brain.append_memory(fact, idempotency_key="memory-1", actor_id="user", correlation_id="corr")
    duplicate = brain.append_memory(fact, idempotency_key="memory-1", actor_id="user", correlation_id="corr")
    correction = brain.correct_memory(first["event_id"], {
        "correction": "Late entry occurred only once", "reason": "Source review",
        "expected_prior_hash": first["content_hash"],
    }, idempotency_key="correction-1", actor_id="user", correlation_id="corr")
    rows = brain.store.events()
    assert first["added"] is True and duplicate["added"] is False and correction["added"] is True
    assert [row.event_type for row in rows] == ["TRADING_MEMORY_APPENDED", "TRADING_MEMORY_CORRECTION_APPENDED"]
    assert rows[0].payload["fact"] == "Late entry repeated"
    assert rows[1].previous_hash == rows[0].content_hash


def test_memory_rejects_non_trading_fact_and_prior_hash_conflict(tmp_path):
    brain = service(tmp_path)
    with pytest.raises(ValueError):
        brain.append_memory({"fact_type": "PRIVATE_PROFILE", "fact": "irrelevant", "evidence_references": ["x"]},
                            idempotency_key="bad", actor_id="user", correlation_id="corr")
    memory = brain.append_memory({"fact_type": "JOURNAL_REFERENCE", "fact": "Trade journal link",
                                  "evidence_references": ["trade-1"]},
                                 idempotency_key="good", actor_id="user", correlation_id="corr")
    with pytest.raises(SecondBrainError):
        brain.correct_memory(memory["event_id"], {"correction": "x", "reason": "y",
                             "expected_prior_hash": "0" * 64}, idempotency_key="c", actor_id="u", correlation_id="x")


def test_discipline_detects_only_objective_revenge_duplicate_fomo_and_overtrade_evidence(tmp_path):
    first = captured_event(tmp_path, 1, -10)
    second = captured_event(tmp_path, 2, 5)
    observed = datetime.fromisoformat(second.exit_at).astimezone(timezone.utc) + timedelta(minutes=5)
    result = DisciplineEngine().assess(
        base_decision(action="BUY", freshness="STALE", setup_quality=40,
                      reason_codes=["ENTRY_EXTENDED"], missing_evidence=["STALE_ASK"]),
        [first, second], context={"symbol": "NIFTY", "setup": "BREAKOUT_RETEST",
                                  "unsupported_attempts_last_10m": 3}, now=observed,
    )
    codes = {row["code"] for row in result["warnings"]}
    assert {"MISSING_EVIDENCE_CONFLICT", "STALE_EVIDENCE_CONFLICT", "LOW_QUALITY_TRADE",
            "FOMO_RISK", "OVERTRADING", "DUPLICATE_THESIS", "UNSUPPORTED_REPEATED_ATTEMPTS"} <= codes
    assert result["recommendation"] == "NO_TRADE"
    assert result["emotion_only_blocking"] is False and result["subjective_emotion_inference"] == "NOT_PERFORMED"


def test_emotion_label_alone_never_creates_a_warning_or_execution_block(tmp_path):
    result = DisciplineEngine().assess(
        base_decision(action="BUY", missing_evidence=[]), [], context={"emotion": "fear", "user_insists": True},
    )
    assert result["warnings"] == []
    assert result["execution_authority"] is False and result["execution_influence"] == "ZERO"


def test_post_loss_rapid_reentry_warning_has_exact_time_safe_evidence(tmp_path):
    loss = captured_event(tmp_path, 1, -10)
    observed = datetime.fromisoformat(loss.exit_at).astimezone(timezone.utc) + timedelta(minutes=4)
    result = DisciplineEngine().assess(base_decision(action="BUY", missing_evidence=[]), [loss], now=observed)
    warning = next(row for row in result["warnings"] if row["code"] == "POST_LOSS_RAPID_REENTRY")
    assert warning["recommendation"] == "COOLDOWN"
    assert any(item.startswith("seconds_since_loss=") for item in warning["objective_evidence"])
    assert "OC-004" in warning["constitution_refs"]


def test_post_trade_learning_and_obsidian_are_complete_append_only_and_idempotent(tmp_path):
    event = replace(captured_event(tmp_path, 1, 12), mistake_tags=("LATE_ENTRY",))
    brain = service(tmp_path, [event])
    first = brain.record_completed_trade(event)
    before = {path.relative_to(tmp_path / "vault"): path.read_text(encoding="utf-8")
              for path in (tmp_path / "vault").rglob("*.md")}
    second = brain.record_completed_trade(event)
    after = {path.relative_to(tmp_path / "vault"): path.read_text(encoding="utf-8")
             for path in (tmp_path / "vault").rglob("*.md")}
    learning = first["learning"]["payload"]
    assert first["added"] is True and second["added"] is False and before == after
    assert {"setup", "market_context", "decision", "entry", "stop", "targets", "management",
            "exit", "mistakes", "what_worked", "what_failed", "lessons"} <= set(learning)
    expected = {"Playbook.md", "Learning Notes.md", "Research Notes.md", "Knowledge Links.md",
                "Winning Setups.md", "Mistake Log.md"}
    assert expected <= {str(path) for path in before}
    assert len(list((tmp_path / "vault" / "Trade Journal").glob("*.md"))) == 1

    correction = brain.correct_learning(first["learning"]["event_id"], {
        "expected_prior_hash": first["learning"]["content_hash"],
        "correction": "The late-entry tag was user-reviewed.", "reason": "Journal review",
        "evidence_references": ["review-1"],
    }, idempotency_key="learning-correction-1", actor_id="user", correlation_id="review")
    correction_duplicate = brain.correct_learning(first["learning"]["event_id"], {
        "expected_prior_hash": first["learning"]["content_hash"],
        "correction": "The late-entry tag was user-reviewed.", "reason": "Journal review",
        "evidence_references": ["review-1"],
    }, idempotency_key="learning-correction-1", actor_id="user", correlation_id="review")
    original = brain.store.events("POST_TRADE_LEARNING_APPENDED")[0]
    assert correction["added"] is True and correction_duplicate["added"] is False
    assert original.payload["outcome"] == "WIN" and original.payload["mistakes"] == ["LATE_ENTRY"]
    assert brain.store.events("POST_TRADE_LEARNING_CORRECTION_APPENDED")[0].payload["revision"] == 1
    journal = next((tmp_path / "vault" / "Trade Journal").glob("*.md")).read_text(encoding="utf-8")
    assert "Immutable trade facts and outcome were not changed" in journal


def test_personal_oracle_completion_hook_automatically_records_learning(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "personal.json")
    personal = PersonalOracleService(paper_state=object(), ledger=ledger)
    raw = closed_trade(3, -8)
    context = {"captured_at": raw["opened_at"], "setup_tag": "FAILED_BREAKOUT",
               "planned_stop_price": 92, "planned_target_price": 115}
    assert personal.capture_closed_trade(raw, entry_context=context) is True
    assert len(personal.second_brain.store.events("POST_TRADE_LEARNING_APPENDED")) == 1
    assert (tmp_path / "obsidian_vault" / "Failed Setups.md").exists()
    assert personal.capture_closed_trade(raw, entry_context=context) is False
    assert len(personal.second_brain.store.events("POST_TRADE_LEARNING_APPENDED")) == 1


def test_why_why_not_and_all_explainability_fields_are_truthful(tmp_path):
    event = captured_event(tmp_path)
    projection = service(tmp_path, [event]).project(
        base_decision(), knowledge={"references": ["card-1"], "conflicts": ["card-2"]},
    )
    proof = projection["explainability"]
    assert proof["why"] and proof["why_not"] and proof["missing_evidence"]
    assert proof["conflicting_evidence"] == ["card-2"]
    assert proof["alternative_scenarios"] and proof["invalidation"] == "swing-low"
    assert proof["natural_targets"] == [120, 130]
    assert proof["related_journal_links"] and proof["related_historical_trades"]
    assert proof["knowledge_cards_used"] == ["card-1"]
    assert proof["confidence_boundary"] == "NOT_A_PROBABILITY"


def test_warm_projection_has_minimal_latency_and_no_network_or_llm_dependency(tmp_path):
    events = [captured_event(tmp_path, index, 5 if index % 2 else -5) for index in range(1, 8)]
    brain = service(tmp_path, events)
    durations = []
    for _ in range(50):
        started = perf_counter(); projection = brain.project(base_decision()); durations.append((perf_counter() - started) * 1000)
    durations.sort()
    assert durations[int(len(durations) * .95) - 1] < 10
    assert projection["latency_ms"] < 10 and projection["safety"]["execution_authority"] is False


def test_corrupt_history_fails_closed_without_overwrite(tmp_path):
    path = tmp_path / "brain.json"
    path.write_text(json.dumps({"schema_version": "6B.1.0", "events": [{"event_id": "tampered"}]}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(SecondBrainError):
        SecondBrainStore(path).events()
    assert path.read_bytes() == before


def test_live_workspace_binds_second_brain_without_changing_safety_or_execution(tmp_path):
    class Reader:
        def read(self):
            return {"success": True, "layout": "fixture", "chart_count": 1, "active_index": 0,
                    "panes": [{"index": 0, "symbol": "NSE:NIFTY", "resolution": "5"}]}

    phase6b = service(tmp_path).project(base_decision())
    sync = TradingViewAutoSyncService(
        tmp_path / "sync", reader=Reader(), debounce_seconds=0,
        analysis_provider=lambda chart: {"decision": base_decision(), "knowledge": {}, "second_brain": phase6b},
        personal_oracle_provider=lambda: {}, clock=lambda: datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    value = sync.poll_once(force_debounce=True)
    assert value["personal_oracle"]["second_brain"]["constitution"]["version"] == CONSTITUTION_VERSION
    assert value["personal_oracle"]["cooldown_status"] == phase6b["discipline"]["recommendation"]
    assert value["safety"] == {"paper_only": True, "live_trading_enabled": False,
                               "broker_submission": False, "advisory_only": True,
                               "execution_influence": "ZERO", "execution_authority": False}


def test_frozen_oracle_frontend_exposes_compact_phase6b_rows_without_new_stylesheet():
    root = Path(__file__).resolve().parents[1]
    panel = (root / "citadel-dashboard/src/components/institutional/OracleWorkspacePanel.tsx").read_text(encoding="utf-8")
    assert "Why not" in panel and "DISCIPLINE" in panel and "OBSIDIAN" in panel and "Journal links" in panel
    assert "secondBrain" in panel and "oracle.module.css" in panel
