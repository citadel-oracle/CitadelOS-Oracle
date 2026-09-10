import json
from dataclasses import dataclass
from datetime import datetime

import pytest

from src.forensics import DecisionEvidenceRecorder, EvidenceJournal, OpportunityReplayEngine
from src.paper_trading.orchestrator import RealMarketPaperOrchestrator


pytestmark = [pytest.mark.unit, pytest.mark.safety]


def test_evidence_journal_is_hash_chained_append_only_and_idempotent(tmp_path):
    journal = EvidenceJournal(tmp_path / "evidence.jsonl", clock=lambda: datetime(2026, 7, 13, 10, 0))
    first, created = journal.append("ONE", {"value": 1}, idempotency_key="one")
    duplicate, duplicate_created = journal.append("ONE", {"value": 999}, idempotency_key="one")
    second, _ = journal.append("TWO", {"value": 2}, idempotency_key="two")
    assert created is True and duplicate_created is False and duplicate == first
    assert second["previous_hash"] == first["record_hash"]
    assert journal.verify()["valid"] is True


def test_evidence_verification_detects_tampering(tmp_path):
    path = tmp_path / "evidence.jsonl"
    journal = EvidenceJournal(path)
    journal.append("ONE", {"value": 1})
    row = json.loads(path.read_text(encoding="utf-8"))
    row["payload"]["value"] = 2
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = journal.verify()
    assert result == {"valid": False, "records": 1, "failed_index": 0, "reason": "RECORD_HASH_MISMATCH"}


@dataclass
class Context:
    symbol: str = "NIFTY"
    indicators: dict = None
    kronos: dict = None
    structure_v1: dict = None
    structure_v2: dict = None
    liquidity: dict = None
    fvg: dict = None
    order_block: dict = None
    timeframe: dict = None
    features: dict = None
    regime: str = "TRENDING"

    def __post_init__(self):
        self.indicators = {"close": 101.0, "ema_21": 100.0, "ema_38": 99.0, "vwap": 100.5}
        self.kronos = {"bias": "BULLISH", "regime": "TRENDING", "confidence": 80}
        self.structure_v1 = {}; self.structure_v2 = {}; self.liquidity = {}; self.fvg = {}
        self.order_block = {}; self.timeframe = {}; self.features = {}


def test_decision_envelope_preserves_why_no_trade_and_observed_candidates(tmp_path):
    journal = EvidenceJournal(tmp_path / "evidence.jsonl")
    recorder = DecisionEvidenceRecorder(journal)
    candle = {"timestamp": "2026-07-13T10:00:00+05:30", "candle_closed_at": "2026-07-13T10:05:00+05:30", "open": 100, "high": 102, "low": 99, "close": 101, "closed": True, "source": "TEST"}
    signal = {"signal": "BUY", "confidence": 80, "entry": 101, "sl": 100, "target": 103, "reason": "production rule", "strategy": "Simple Pullback"}
    snapshot = {"kronos_alpha": {"status": "READY"}, "argus": {"status": "AVAILABLE"}, "athena": {"status": "READY"}, "personal_oracle": {"status": "STABLE"}, "hermes": {"status": "NOT_CONFIGURED"}, "source_timestamps": {}}
    decision = {"decision": "WAIT", "hard_gate_reasons": ["MARKET_POLICY_WAIT"], "dominant_reasons": ["MARKET_POLICY_WAIT"], "generated_at": "2026-07-13T10:05:01+05:30", "missing_inputs": [], "component_scores": {"technical": 80}, "weighted_contributions": {"technical": 24}, "conflicts": [], "data_coverage_percentage": 80, "input_fingerprint": "abc"}
    argus = {"data": {"underlying": {"atm_strike": 100, "expiry": "2026-07-16"}, "atm_window": [{"strike": 50, "ce": {"security_id": "1"}, "pe": {"security_id": "2"}}, {"strike": 100, "ce": {"security_id": "3"}, "pe": {"security_id": "4"}}, {"strike": 150, "ce": {"security_id": "5"}, "pe": {"security_id": "6"}}]}}
    recorder.decision_envelope(candle=candle, context=Context(), signal=signal, final_state="WAITING", final_reason="AEGIS_WAIT", aegis_snapshot=snapshot, aegis_decision=decision, argus=argus)
    envelope = journal.latest(event_type="CANDLE_DECISION_ENVELOPE")["payload"]
    assert envelope["why_no_trade"]["first_rejecting_module"] == "AEGIS"
    assert envelope["pullback_conditions"]["bullish_ema_alignment"] is True
    assert [row["classification"] for row in envelope["contract_candidates"]["candidates"]] == ["ATM", "ATM_PLUS_1", "ITM_CALL_OR_OTM_PUT"]
    assert envelope["risk_readiness"]["status"] == "NOT_EVALUATED"


def test_replay_never_invokes_production_and_calculates_underlying_outcome_only(tmp_path):
    journal = EvidenceJournal(tmp_path / "evidence.jsonl")
    recorder = DecisionEvidenceRecorder(journal)
    candle = {"timestamp": "2026-07-13T10:00:00+05:30", "candle_closed_at": "2026-07-13T10:05:00+05:30", "open": 100, "high": 102, "low": 99, "close": 101, "closed": True}
    signal = {"signal": "BUY", "confidence": 80, "entry": 101, "sl": 100, "target": 103, "reason": "production rule", "strategy": "Simple Pullback"}
    recorder.decision_envelope(candle=candle, context=Context(), signal=signal, final_state="WAITING", final_reason="AEGIS_WAIT")
    candle_path = tmp_path / "candles.json"
    candle_path.write_text(json.dumps({"candles": [candle, {"timestamp": "2026-07-13T10:05:00+05:30", "high": 104, "low": 98, "close": 103}]}), encoding="utf-8")
    replay = OpportunityReplayEngine(journal, candle_path=candle_path, kronos_alpha_history=tmp_path / "ka.json", chronos_2_history=tmp_path / "c2.json")
    result = replay.replay(candle["timestamp"], outcome_until="2026-07-13T10:05:00+05:30")
    assert result["status"] == "RECONSTRUCTED" and result["production_recalculation_performed"] is False
    assert result["actual_market_outcome"]["mfe_points"] == 3
    assert result["actual_market_outcome"]["mae_points"] == 3
    assert result["actual_market_outcome"]["option_pnl"] is None


def test_replay_requires_explicit_horizon_and_existing_envelope(tmp_path):
    replay = OpportunityReplayEngine(EvidenceJournal(tmp_path / "none.jsonl"), candle_path=tmp_path / "none.json")
    assert replay.replay("missing")["reason"] == "IMMUTABLE_DECISION_ENVELOPE_NOT_FOUND"


def test_diagnostic_failure_cannot_change_or_raise_into_production_path():
    class BrokenRecorder:
        def decision_envelope(self, **kwargs):
            raise RuntimeError("diagnostic storage failed")

    orchestrator = object.__new__(RealMarketPaperOrchestrator)
    orchestrator.evidence = BrokenRecorder()
    assert orchestrator._persist_envelope({}, None, {}, "WAITING", "STRATEGY_WAIT") is None
