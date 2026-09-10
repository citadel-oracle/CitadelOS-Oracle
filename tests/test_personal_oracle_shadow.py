from datetime import datetime, timedelta, timezone

import pytest

from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.models import OracleEvent
from src.oracle_personal.shadow import POLICY_VERSION, PersonalOracleShadow
from src.oracle_personal.service import PersonalOracleService


pytestmark = pytest.mark.unit


def event(index: int, pnl: float, *, exit_at: str, strategy="shadow", setup="PULLBACK", option_side="CE"):
    entered = datetime.fromisoformat(exit_at) - timedelta(minutes=5)
    return OracleEvent(
        oracle_event_id=f"event-{index}", source_type="TEST", source_record_id=f"trade-{index}",
        immutable_source_hash=f"hash-{index}", captured_at=exit_at, entry_at=entered.isoformat(),
        exit_at=exit_at, trading_date=entered.date().isoformat(), symbol="NIFTY", instrument_id="63942",
        option_side=option_side, strike=24000, expiry="2026-07-28", side="LONG", quantity=65,
        raw_quantity=65, lot_size=65, number_of_lots=1, entry_price=100, exit_price=101,
        realized_pnl=pnl, realized_points=1, holding_seconds=300,
        outcome="WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT", exit_reason="TARGET",
        r_multiple=None, brokerage=None, slippage=None, strategy_name=strategy, strategy_version="1",
        trade_number_of_day=index, weekday=entered.strftime("%A"), time_bucket="OPENING",
        strategy_id=strategy, setup_tag=setup, timeframe="1m", ingestion_mode="LEGACY",
    )


def candidate(identity="sig-1", timestamp="2026-07-22T09:30:00+05:30"):
    return {
        "candidate_signal_id": identity, "entry_timestamp": timestamp, "instrument": "NIFTY 24000 CE",
        "underlying": "NIFTY", "option_side": "CE", "strike": 24000.0, "expiry": "2026-07-28",
        "strategy": "shadow", "setup": "PULLBACK", "timeframe": "1m", "quantity": 65,
        "signal_price": 100.0, "reference_price": None, "stop_loss": 95.0, "target": 110.0,
        "market_regime": None, "context_completeness_percentage": 85.0,
        "missing_context_fields": ["reference_price", "market_regime"],
        "provenance": {"source": "TEST"},
    }


def test_advisory_is_exactly_once_pretrade_only_and_truthfully_missing(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    shadow = PersonalOracleShadow(ledger)
    assert shadow.advise(candidate(), source_event_id="evt-1") is True
    assert shadow.advise(candidate(), source_event_id="evt-1") is False
    advisory = ledger.advisories()[0]
    assert advisory.classification == "INSUFFICIENT_DATA"
    assert advisory.confidence_band == "UNCALIBRATED"
    assert advisory.reference_price is None and advisory.market_regime is None
    assert not any(key in advisory.to_dict() for key in ("realized_pnl", "outcome", "exit_price"))
    assert advisory.execution_influence == "ZERO"


def test_timestamp_filter_prevents_lookahead_and_minimum_sample_policy(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    before = datetime(2026, 7, 22, 3, 30, tzinfo=timezone.utc)
    for index in range(6):
        ledger.append(event(index, 10, exit_at=(before - timedelta(minutes=index + 1)).isoformat()))
    ledger.append(event(99, -1000, exit_at=(before + timedelta(minutes=1)).isoformat()))
    shadow = PersonalOracleShadow(ledger)
    proposal = candidate(timestamp=before.isoformat())
    shadow.advise(proposal, source_event_id="evt-filter")
    advisory = ledger.advisories()[0]
    assert advisory.sample_sizes["overall"] == 6
    assert advisory.personal_metrics["overall"]["expectancy"] == 10
    assert advisory.classification == "POSITIVE_PERSONAL_FIT"
    assert advisory.confidence_band == "UNCALIBRATED"
    assert advisory.policy_version == POLICY_VERSION and advisory.policy_source == "POLICY_DEFAULT"
    assert advisory.policy_parameters["minimum_cohort_size"] == 5


def test_outcome_link_is_exactly_once_and_original_advice_is_immutable(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    shadow = PersonalOracleShadow(ledger)
    shadow.advise(candidate(), source_event_id="evt-1")
    original = ledger.advisories()[0].to_dict()
    trade = {
        "trade_id": "trade-1", "realized_pnl": -25.0, "duration_seconds": 120,
        "mae": -2.0, "mfe": 1.0, "oracle_entry_context": {"candidate_signal_id": "sig-1"},
    }
    assert shadow.link_outcome(trade) is True
    assert shadow.link_outcome(trade) is False
    assert ledger.advisories()[0].to_dict() == original
    assert len(ledger.outcomes()) == 1 and ledger.outcomes()[0].source_trade_id == "trade-1"


def test_restart_reconciliation_repairs_only_missing_links(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    PersonalOracleShadow(ledger).advise(candidate(), source_event_id="evt-1")
    restarted = PersonalOracleShadow(PersonalOracleLedger(ledger.path))
    trade = {"trade_id": "trade-1", "realized_pnl": 10, "oracle_entry_context": {"candidate_signal_id": "sig-1"}}
    records = [({}, {}, trade)]
    assert restarted.reconcile_outcomes(records) == {"linked": 1, "duplicate": 0, "unlinked": 0}
    assert restarted.reconcile_outcomes(records) == {"linked": 0, "duplicate": 1, "unlinked": 0}


def test_scorecard_uses_only_prospective_records_and_exposes_denominators(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    for index in range(20):
        ledger.append(event(index, 10, exit_at=f"2026-07-21T09:{index:02d}:00+05:30"))
    shadow = PersonalOracleShadow(ledger)
    shadow.advise(candidate(), source_event_id="evt-1")
    scorecard = shadow.projection()["prospective_scorecard"]
    assert scorecard["total_prospective_advisories"] == 1
    assert scorecard["completed_outcomes"] == 0 and scorecard["pending_advisories"] == 1
    assert scorecard["positive_fit_precision"] == {
        "state": "INSUFFICIENT_SAMPLE", "numerator": 0, "denominator": 0, "value": None,
    }


def test_legacy_events_are_descriptive_not_prospective_accuracy(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    ledger.append(event(1, 20, exit_at="2026-07-21T09:20:00+05:30"))
    projection = PersonalOracleShadow(ledger).projection()
    assert projection["prospective_scorecard"]["total_prospective_advisories"] == 0
    assert projection["prospective_scorecard"]["completed_outcomes"] == 0


def test_service_api_projection_and_failure_status_remain_advisory(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    service = PersonalOracleService(ledger=ledger, strategy_lab_root=tmp_path / "strategy_lab")
    assert service.capture_shadow_advisory(candidate(), source_event_id="evt-api") is True
    shadow = service.summary()["shadow"]
    assert shadow["latest_advisory"]["candidate_signal_id"] == "sig-1"
    assert shadow["latest_outcome_status"] == "PENDING"
    assert shadow["execution_influence"] == "ZERO" and shadow["advisory_only"] is True
    assert service.capture_shadow_advisory({}, source_event_id="evt-bad") is False
    assert service.summary()["shadow"]["status"] == "DEGRADED"
