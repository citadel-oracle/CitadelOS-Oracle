from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.execution.paper_execution import PaperExecution
from src.execution.paper_state import (
    DuplicatePaperEvent,
    InvalidPaperEvent,
    PaperStateService,
    PaperStateUnavailable,
    UnknownPaperPosition,
)
from src.risk.authorization import (
    ReasonCode,
    RiskAuditLogger,
    RiskAuthorizationRequest,
    RiskAuthorizationService,
    RiskControlStore,
)


pytestmark = [pytest.mark.unit, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata")


class MutableNow:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


NOW = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
BASE_CONFIG = {
    "live_trading_enabled": True,
    "max_daily_loss": 1000,
    "max_trades_per_day": 3,
    "max_consecutive_losses": 2,
    "max_risk_per_trade": 500,
    "max_position_quantity": 50,
    "max_open_positions": 1,
    "max_market_data_age_seconds": 10,
    "max_volatility": None,
}


def service(tmp_path, now=None, initialize=True, **initial):
    clock = now or MutableNow(NOW)
    paper = PaperStateService(tmp_path / "paper.json", now_provider=clock)
    if initialize:
        paper.initialize(**initial)
    return paper, clock


def open_position(paper, **changes):
    values = {
        "position_id": "position-1",
        "request_id": "open-request-1",
        "event_id": "open-event-1",
        "instrument_id": "option-security-1",
        "symbol": "NIFTY",
        "option_type": "CE",
        "strike": 24200,
        "expiry": "2026-07-14",
        "side": "BUY",
        "raw_quantity": 2,
        "entry_price": 100,
        "stop_price": 90,
        "target_price": 120,
    }
    values.update(changes)
    return paper.open_position(**values)


def risk_request(request_id="risk-request", **changes):
    request = RiskAuthorizationRequest(
        operation="PLACE",
        method="POST",
        endpoint="/orders",
        request_id=request_id,
        symbol="NIFTY",
        side="BUY",
        quantity=1,
        price=100,
        stop_price=95,
        market_data_timestamp=NOW - timedelta(seconds=1),
    )
    return replace(request, **changes)


def authorizer(tmp_path, paper, **config_changes):
    config = dict(BASE_CONFIG, **config_changes)
    kill = RiskControlStore(tmp_path / "kill.json")
    kill.initialize(
        kill_switch_active=False,
        reason="offline test",
        actor="pytest",
    )
    return RiskAuthorizationService(
        config_provider=lambda: config,
        store=kill,
        paper_state=paper,
        audit_logger=RiskAuditLogger(tmp_path / "audit.jsonl"),
        now_provider=lambda: NOW,
    )


def test_initial_state_creation_is_explicit_and_complete(tmp_path):
    paper, _ = service(tmp_path)

    state = paper.load()

    assert state.trading_date == "2026-07-10"
    assert state.open_positions == ()
    assert state.closed_trades == ()
    assert state.realized_pnl == 0
    assert state.unrealized_pnl == 0
    assert state.total_daily_pnl == 0
    assert state.last_updated


def test_missing_state_fails_without_silent_creation(tmp_path):
    paper, _ = service(tmp_path, initialize=False)

    with pytest.raises(PaperStateUnavailable, match="missing"):
        paper.load()

    assert not paper.path.exists()


def test_malformed_state_fails_without_repair(tmp_path):
    paper, _ = service(tmp_path, initialize=False)
    paper.path.write_text("not-json", encoding="utf-8")

    with pytest.raises(PaperStateUnavailable):
        paper.load()

    assert paper.path.read_text(encoding="utf-8") == "not-json"


def test_open_paper_position_persists_instrument_metadata(tmp_path):
    paper, _ = service(tmp_path)

    position = open_position(paper)
    state = paper.load()

    assert state.open_positions == (position,)
    assert position.raw_quantity == 2
    assert position.instrument_id == "option-security-1"
    assert position.option_type == "CE"
    assert position.strike == 24200
    assert position.expiry == "2026-07-14"


def test_unknown_lot_size_remains_unavailable(tmp_path):
    paper, _ = service(tmp_path)

    position = open_position(paper)

    assert position.lot_size is None
    assert position.number_of_lots is None


def test_known_lot_size_derives_number_of_lots(tmp_path):
    paper, _ = service(tmp_path)

    position = open_position(paper, raw_quantity=50, lot_size=25)

    assert position.lot_size == 25
    assert position.number_of_lots == 2


@pytest.mark.parametrize("quantity", [0, -1])
def test_non_positive_open_quantity_is_rejected(tmp_path, quantity):
    paper, _ = service(tmp_path)

    with pytest.raises(InvalidPaperEvent):
        open_position(paper, raw_quantity=quantity)


def test_missing_open_price_is_rejected(tmp_path):
    paper, _ = service(tmp_path)

    with pytest.raises(InvalidPaperEvent):
        open_position(paper, entry_price=None)


def test_negative_open_price_is_rejected(tmp_path):
    paper, _ = service(tmp_path)

    with pytest.raises(InvalidPaperEvent):
        open_position(paper, entry_price=-1)


def test_mark_price_update_is_persisted(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)

    updated = paper.update_mark("position-1", 110, "mark-event-1")

    assert updated.mark_price == 110
    assert paper.load().open_positions[0].mark_price == 110


def test_long_option_unrealized_pnl_formula(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper, raw_quantity=2, entry_price=100)

    paper.update_mark("position-1", 110, "mark-event-1")
    state = paper.load()

    assert state.unrealized_pnl == (110 - 100) * 2
    assert state.total_daily_pnl == 20


def test_full_close_removes_open_position(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)

    closed = paper.close_position("position-1", 110, "close-event-1")
    state = paper.load()

    assert closed.closed_quantity == 2
    assert state.open_positions == ()
    assert len(state.closed_trades) == 1


def test_long_option_realized_pnl_formula(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper, raw_quantity=2, entry_price=100)

    closed = paper.close_position("position-1", 110, "close-event-1")

    assert closed.realized_pnl == (110 - 100) * 2
    assert paper.load().realized_pnl == 20


def test_daily_total_combines_realized_and_unrealized_pnl(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper, raw_quantity=2)
    paper.close_position(
        "position-1", 110, "partial-close", close_quantity=1
    )
    paper.update_mark("position-1", 105, "mark-remaining")

    state = paper.load()

    assert state.realized_pnl == 10
    assert state.unrealized_pnl == 5
    assert state.total_daily_pnl == 15


def test_open_increments_trades_taken_once(tmp_path):
    paper, _ = service(tmp_path)

    open_position(paper)

    assert paper.load().trades_taken == 1


def test_loss_increments_consecutive_losses(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)

    paper.close_position("position-1", 90, "loss-close")

    assert paper.load().consecutive_losses == 1


def test_winner_resets_consecutive_losses(tmp_path):
    paper, _ = service(tmp_path, consecutive_losses=2)
    open_position(paper)

    paper.close_position("position-1", 110, "win-close")

    assert paper.load().consecutive_losses == 0


def test_duplicate_request_is_rejected(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)

    with pytest.raises(DuplicatePaperEvent):
        open_position(
            paper,
            position_id="position-2",
            event_id="open-event-2",
        )


def test_duplicate_close_event_is_rejected(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper, raw_quantity=2)
    paper.close_position(
        "position-1", 110, "partial-close", close_quantity=1
    )

    with pytest.raises(DuplicatePaperEvent):
        paper.close_position(
            "position-1", 110, "partial-close", close_quantity=1
        )


def test_unknown_position_is_rejected(tmp_path):
    paper, _ = service(tmp_path)

    with pytest.raises(UnknownPaperPosition):
        paper.update_mark("unknown", 100, "unknown-mark")


def test_over_close_is_rejected(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper, raw_quantity=2)

    with pytest.raises(InvalidPaperEvent, match="exceeds"):
        paper.close_position(
            "position-1", 110, "over-close", close_quantity=3
        )


def test_restart_loads_identical_persisted_position(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)
    paper.update_mark("position-1", 111, "mark-event")

    restarted = PaperStateService(paper.path, now_provider=lambda: NOW)

    assert restarted.load() == paper.load()


def test_verified_new_trading_date_resets_only_daily_counters(tmp_path):
    clock = MutableNow(datetime(2026, 7, 10, 15, 0, tzinfo=IST))
    paper, _ = service(tmp_path, now=clock)
    open_position(paper)
    paper.update_mark("position-1", 110, "mark-day-one")
    clock.value = datetime(2026, 7, 11, 9, 20, tzinfo=IST)

    rolled = paper.load()

    assert rolled.trading_date == "2026-07-11"
    assert rolled.trades_taken == 0
    assert rolled.realized_pnl == 0
    assert rolled.accepted_request_ids == ()
    assert len(rolled.open_positions) == 1
    assert rolled.unrealized_pnl == 20


def test_open_positions_feed_risk_authorization(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)

    decision = authorizer(tmp_path, paper).authorize(risk_request())

    assert decision.reason_code == ReasonCode.MAX_OPEN_POSITIONS_REACHED.value


def test_daily_pnl_feeds_risk_authorization(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper, raw_quantity=2)
    paper.close_position("position-1", 90, "loss-close")

    decision = authorizer(tmp_path, paper, max_daily_loss=20).authorize(
        risk_request()
    )

    assert decision.reason_code == ReasonCode.DAILY_LOSS_LIMIT_REACHED.value


def test_trade_count_feeds_risk_authorization(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)
    paper.close_position("position-1", 100, "flat-close")

    decision = authorizer(tmp_path, paper, max_trades_per_day=1).authorize(
        risk_request()
    )

    assert decision.reason_code == ReasonCode.MAX_TRADES_REACHED.value


def test_consecutive_losses_feed_risk_authorization(tmp_path):
    paper, _ = service(tmp_path)
    open_position(paper)
    paper.close_position("position-1", 90, "loss-close")

    decision = authorizer(tmp_path, paper, max_consecutive_losses=1).authorize(
        risk_request()
    )

    assert decision.reason_code == ReasonCode.MAX_CONSECUTIVE_LOSSES_REACHED.value


def test_accepted_request_ids_feed_risk_authorization(tmp_path):
    paper, _ = service(tmp_path)
    paper.reserve_request("risk-request", NOW.date())

    decision = authorizer(tmp_path, paper).authorize(risk_request())

    assert decision.reason_code == ReasonCode.DUPLICATE_REQUEST.value


def test_unavailable_paper_state_denies_risk_authorization(tmp_path):
    paper, _ = service(tmp_path, initialize=False)

    decision = authorizer(tmp_path, paper).authorize(risk_request())

    assert decision.reason_code == ReasonCode.STATE_UNAVAILABLE.value


def test_paper_execution_uses_authoritative_state_for_lifecycle(tmp_path):
    paper, _ = service(tmp_path)
    journal = RecordingJournal()
    execution = PaperExecution(
        paper_state=paper,
        journal=journal,
        oracle=RecordingOracle(),
        personal_oracle=RecordingPersonalOracle(),
    )
    signal = {
        "signal": "BUY",
        "entry": 100,
        "sl": 90,
        "target": 120,
        "confidence": 80,
        "reason": "offline test",
        "quantity": 2,
    }

    opened = execution.process_signal(signal, symbol="NIFTY")
    updated = execution.update_trade(110)
    closed = execution.update_trade(121)

    assert opened["executed"] is True
    assert updated["trade"]["unrealized_pnl"] == 20
    assert closed["status"] == "CLOSED"
    assert paper.load().realized_pnl == 42
    assert [event for event, _ in journal.events] == ["OPEN", "CLOSE"]


class RecordingJournal:
    def __init__(self):
        self.events = []

    def log_trade(self, event, trade):
        self.events.append((event, dict(trade)))


class RecordingOracle:
    def log_trade(self, trade, context):
        raise AssertionError("Oracle should not be called without explicit context")


class RecordingPersonalOracle:
    def capture_closed_trade(self, raw, *, entry_context=None):
        assert raw["closed_at"]
        return True
