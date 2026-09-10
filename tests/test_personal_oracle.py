from dataclasses import replace
from datetime import datetime, timedelta
import json

import pytest

from src.oracle_personal.analytics import PersonalOracleAnalytics
from src.oracle_personal.capture import PersonalOracleCapture
from src.oracle_personal.ledger import OracleLedgerError, PersonalOracleLedger
from src.oracle_personal.models import OracleEvent, ManualJournalRecord, canonical_hash, event_id
from src.oracle_personal.service import PersonalOracleService


pytestmark = [pytest.mark.unit]


def closed_trade(index=1, pnl=10.0):
    opened = datetime.fromisoformat("2026-07-10T09:30:00+05:30") + timedelta(minutes=index)
    return {
        "close_event_id": f"close-{index}", "request_id": None, "position_id": str(index),
        "instrument_id": None, "symbol": "NIFTY", "option_type": None, "strike": None,
        "expiry": None, "side": "BUY", "closed_quantity": 1, "raw_quantity": 1,
        "lot_size": None, "number_of_lots": None, "entry_price": 100.0,
        "exit_price": 100.0 + pnl, "realized_pnl": pnl, "opened_at": opened.isoformat(),
        "closed_at": (opened + timedelta(minutes=5)).isoformat(), "exit_reason": "TEST",
    }


def event(tmp_path, index=1, pnl=10.0, **context):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    capture = PersonalOracleCapture(ledger)
    raw = closed_trade(index, pnl)
    entry_context = None
    if context:
        entry_context = {"captured_at": raw["opened_at"], **context}
    assert capture.capture_closed_trade(raw, entry_context=entry_context)
    return ledger.events()[0]


def test_ids_and_hashes_are_deterministic():
    assert event_id("PAPER_STATE", "x") == event_id("PAPER_STATE", "x")
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_capture_is_idempotent_and_restart_safe(tmp_path):
    path = tmp_path / "oracle.json"
    capture = PersonalOracleCapture(PersonalOracleLedger(path))
    assert capture.capture_closed_trade(closed_trade()) is True
    assert PersonalOracleCapture(PersonalOracleLedger(path)).capture_closed_trade(closed_trade()) is False
    assert len(PersonalOracleLedger(path).events()) == 1


@pytest.mark.parametrize("missing", ["close_event_id", "closed_at"])
def test_only_complete_authoritative_trades_are_accepted(tmp_path, missing):
    raw = closed_trade(); raw[missing] = None
    with pytest.raises(ValueError):
        PersonalOracleCapture(PersonalOracleLedger(tmp_path / "x.json")).capture_closed_trade(raw)


def test_historical_backfill_never_uses_current_context(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    PersonalOracleCapture(ledger).capture_closed_trade(
        closed_trade(), historical=True,
        entry_context={"captured_at": "2020-01-01T00:00:00+05:30", "market_regime": "CURRENT"},
    )
    row = ledger.events()[0]
    assert row.market_regime is None
    assert "HISTORICAL_CONTEXT_UNAVAILABLE" in row.warnings


def test_future_context_is_rejected(tmp_path):
    raw = closed_trade()
    row = event(tmp_path, market_regime="TRENDING")
    future = {"captured_at": raw["closed_at"], "market_regime": "FUTURE"}
    ledger = PersonalOracleLedger(tmp_path / "future.json")
    PersonalOracleCapture(ledger).capture_closed_trade(raw, entry_context=future)
    assert ledger.events()[0].market_regime is None
    assert "FUTURE_CONTEXT_REJECTED" in ledger.events()[0].warnings
    assert row.market_regime == "TRENDING"


def test_source_fields_and_truthful_missing_values(tmp_path):
    row = event(tmp_path, 1, 15)
    assert row.realized_points == 15 and row.realized_pnl == 15
    assert row.option_side == "UNKNOWN" and row.r_multiple is None
    assert row.brokerage is None and row.slippage is None and row.strategy_version is None


def test_atomic_ledger_recovers_without_overwriting_corruption(tmp_path):
    path = tmp_path / "oracle.json"; path.write_text("{broken", encoding="utf-8")
    with pytest.raises(OracleLedgerError): PersonalOracleLedger(path).events()
    assert path.read_text(encoding="utf-8") == "{broken"


def test_ledger_bound_and_enrichment_idempotency(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json", max_events=1)
    capture = PersonalOracleCapture(ledger); capture.capture_closed_trade(closed_trade(1))
    with pytest.raises(OracleLedgerError): capture.capture_closed_trade(closed_trade(2))
    enrichment = {"enrichment_id": "e1", "oracle_event_id": ledger.events()[0].oracle_event_id,
                  "reviewed_at": "2026-07-10T12:00:00+05:30", "reviewed_by_user": True}
    assert ledger.append_enrichment(enrichment) is True
    assert ledger.append_enrichment(enrichment) is False


@pytest.mark.parametrize("count,expected", [(0,"COLLECTING"),(19,"COLLECTING"),(20,"PRELIMINARY"),(50,"STABLE"),(100,"MATURE")])
def test_maturity_thresholds(count, expected):
    assert PersonalOracleAnalytics().maturity(count) == expected


def test_summary_math_streaks_and_coverage(tmp_path):
    events = [event(tmp_path / str(i), i, pnl) for i, pnl in enumerate([10, 20, -5, -5, 0], 1)]
    summary = PersonalOracleAnalytics().summary(events)
    assert summary["sample_size"] == 5 and summary["performance"]["net_pnl"] == 20
    assert summary["performance"]["profit_factor"] == 3
    assert summary["performance"]["max_win_streak"] == 2
    assert summary["performance"]["max_loss_streak"] == 2


def test_segments_are_threshold_gated(tmp_path):
    events = [event(tmp_path / str(i), i, 1 if i % 2 else -1) for i in range(1, 11)]
    rows = PersonalOracleAnalytics().segments(events)["segments"]["instrument"]
    assert rows[0]["sample_size"] == 10 and rows[0]["meaningful"] is True


def test_findings_require_two_eligible_comparative_segments(tmp_path):
    rows = []
    for i in range(1, 21):
        row = event(tmp_path / str(i), i, 10 if i <= 10 else -2)
        rows.append(replace(row, symbol="NIFTY" if i <= 10 else "BANKNIFTY"))
    findings = PersonalOracleAnalytics().findings(rows)["findings"]
    assert findings and findings[0]["type"] == "OBSERVED_SEGMENT_DIFFERENCE"
    assert "no causal claim" in findings[0]["limitations"][0].lower()


def test_recommendation_is_truthful_when_evidence_is_insufficient(tmp_path):
    result = PersonalOracleAnalytics().recommendations([event(tmp_path)])["recommendations"][0]
    assert result["state"] == "INSUFFICIENT_EVIDENCE"


def test_manual_journal_contract_is_typed_but_has_no_write_api():
    record = ManualJournalRecord("x", "2026-01-01T10:00:00+05:30", "2026-01-01T10:05:00+05:30", "NIFTY", "BUY", 1, 10, 11, 1)
    assert record.external_id == "x"


def test_service_get_payloads_and_bounded_events(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    capture = PersonalOracleCapture(ledger)
    for i in range(1, 4): capture.capture_closed_trade(closed_trade(i))
    service = PersonalOracleService(ledger=ledger)
    assert service.status()["event_count"] == 3
    assert service.summary()["sample_size"] == 3
    assert len(service.events(2)["events"]) == 2
    assert service.events(999)["limit"] == 100


def test_event_schema_rejects_bad_side_and_notes(tmp_path):
    row = event(tmp_path)
    with pytest.raises(ValueError): replace(row, side="BAD")
    with pytest.raises(ValueError): replace(row, notes_reference="x" * 161)


def test_serialized_ledger_contains_no_raw_note_field(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    PersonalOracleCapture(ledger).capture_closed_trade(closed_trade())
    raw = json.loads((tmp_path / "oracle.json").read_text())
    assert "notes" not in raw["events"][0]
