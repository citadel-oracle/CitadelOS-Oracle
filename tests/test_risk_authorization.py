import json
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from src.broker.dhan_client import BrokerMutationBlockedError, DhanClient
from src.execution.paper_state import PaperStateService
from src.risk.authorization import (
    ReasonCode,
    RiskAuditLogger,
    RiskAuthorizationRequest,
    RiskAuthorizationService,
    RiskControlStore,
    RiskStateUnavailable,
)


pytestmark = [pytest.mark.unit, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
BASE_CONFIG = {
    "live_trading_enabled": True,
    "max_daily_loss": 1000,
    "max_trades_per_day": 3,
    "max_consecutive_losses": 2,
    "max_risk_per_trade": 500,
    "max_position_quantity": 5,
    "max_open_positions": 1,
    "max_market_data_age_seconds": 10,
    "max_volatility": None,
}


def valid_request(request_id="risk-request-1", **changes):
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
        volatility=15,
    )
    return replace(request, **changes)


def daily_state(**changes):
    values = {
        "trading_date": NOW.date().isoformat(),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "trades_taken": 0,
        "consecutive_losses": 0,
        "accepted_request_ids": (),
    }
    values.update(changes)
    return values


def make_service(
    tmp_path,
    *,
    config=None,
    state=None,
    kill_active=False,
    initialize=True,
    config_provider=None,
):
    store = RiskControlStore(tmp_path / "risk_state.json")
    paper = PaperStateService(
        tmp_path / "paper_state.json", now_provider=lambda: NOW
    )
    if initialize:
        store.initialize(
            kill_switch_active=kill_active,
            reason="test setup",
            actor="pytest",
        )
        initial = state or daily_state()
        paper.initialize(
            trading_date=datetime.fromisoformat(initial["trading_date"]).date(),
            realized_pnl=initial["realized_pnl"] + initial["unrealized_pnl"],
            trades_taken=initial["trades_taken"],
            consecutive_losses=initial["consecutive_losses"],
            accepted_request_ids=initial["accepted_request_ids"],
        )
    audit = RiskAuditLogger(tmp_path / "risk_audit.jsonl")
    provider = config_provider or (lambda: dict(config or BASE_CONFIG))
    return (
        RiskAuthorizationService(
            config_provider=provider,
            store=store,
            paper_state=paper,
            audit_logger=audit,
            now_provider=lambda: NOW,
        ),
        store,
        paper,
        audit,
    )


def assert_denied(decision, code):
    assert decision.decision == "DENY"
    assert decision.allowed is False
    assert decision.reason_code == code.value


def test_default_configuration_denies_live_mutation(tmp_path):
    config = dict(BASE_CONFIG, live_trading_enabled=False)
    service, _, _, _ = make_service(tmp_path, config=config, initialize=False)

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.LIVE_TRADING_DISABLED)


def test_active_kill_switch_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path, kill_active=True)

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.KILL_SWITCH_ACTIVE)
    assert decision.kill_switch_active is True


def test_kill_switch_persists_across_store_reload(tmp_path):
    _, store, _, _ = make_service(tmp_path)
    store.activate("operator halt", "pytest")

    reloaded = RiskControlStore(store.path)
    state = reloaded.current_kill_switch()

    assert state.active is True
    assert state.reason == "operator halt"
    assert state.actor == "pytest"


def test_explicit_kill_switch_deactivation_works(tmp_path):
    _, store, _, _ = make_service(tmp_path, kill_active=True)

    deactivated = store.deactivate("review complete", "risk-operator")

    assert deactivated.active is False
    assert RiskControlStore(store.path).current_kill_switch().active is False


def test_missing_kill_switch_state_fails_closed(tmp_path):
    service, _, _, _ = make_service(tmp_path, initialize=False)

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.KILL_SWITCH_UNKNOWN)


def test_malformed_kill_switch_state_fails_closed_without_reset(tmp_path):
    path = tmp_path / "risk_state.json"
    path.write_text("not-json", encoding="utf-8")
    service, store, _, _ = make_service(tmp_path, initialize=False)

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.KILL_SWITCH_CORRUPT)
    assert path.read_text(encoding="utf-8") == "not-json"
    with pytest.raises(RiskStateUnavailable):
        store.deactivate("must not reset", "pytest")


def test_invalid_request_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(valid_request(operation="UNKNOWN"))

    assert_denied(decision, ReasonCode.INVALID_REQUEST)


@pytest.mark.parametrize("quantity", [0, -1])
def test_zero_or_negative_quantity_denies(tmp_path, quantity):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(valid_request(quantity=quantity))

    assert_denied(decision, ReasonCode.INVALID_QUANTITY)


def test_invalid_price_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(valid_request(price=0))

    assert_denied(decision, ReasonCode.INVALID_PRICE)


def test_invalid_stop_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(valid_request(stop_price=101))

    assert_denied(decision, ReasonCode.INVALID_STOP)


def test_stale_market_data_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(
        valid_request(market_data_timestamp=NOW - timedelta(seconds=11))
    )

    assert_denied(decision, ReasonCode.STALE_MARKET_DATA)


def test_daily_loss_limit_denies(tmp_path):
    service, _, _, _ = make_service(
        tmp_path,
        state=daily_state(realized_pnl=-900, unrealized_pnl=-100),
    )

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.DAILY_LOSS_LIMIT_REACHED)


def test_maximum_trades_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path, state=daily_state(trades_taken=3))

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.MAX_TRADES_REACHED)


def test_consecutive_loss_limit_denies(tmp_path):
    service, _, _, _ = make_service(
        tmp_path, state=daily_state(consecutive_losses=2)
    )

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.MAX_CONSECUTIVE_LOSSES_REACHED)


def test_per_trade_risk_limit_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(valid_request(quantity=5, price=200, stop_price=95))

    assert_denied(decision, ReasonCode.PER_TRADE_RISK_EXCEEDED)


def test_position_size_limit_denies(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    decision = service.authorize(valid_request(quantity=6, stop_price=99))

    assert_denied(decision, ReasonCode.MAX_POSITION_SIZE_EXCEEDED)


def test_open_position_limit_denies(tmp_path):
    service, _, paper, _ = make_service(tmp_path)
    paper.open_position(
        position_id="paper-open-1",
        request_id="paper-request-1",
        event_id="paper-event-1",
        symbol="NIFTY",
        side="BUY",
        raw_quantity=1,
        entry_price=100,
    )

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.MAX_OPEN_POSITIONS_REACHED)


def test_duplicate_request_denies(tmp_path):
    service, _, _, _ = make_service(
        tmp_path,
        state=daily_state(accepted_request_ids=("risk-request-1",)),
    )

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.DUPLICATE_REQUEST)


def test_volatility_limit_denies_when_configured(tmp_path):
    service, _, _, _ = make_service(
        tmp_path,
        config=dict(BASE_CONFIG, max_volatility=20),
    )

    decision = service.authorize(valid_request(volatility=21))

    assert_denied(decision, ReasonCode.VOLATILITY_LIMIT_EXCEEDED)


def test_invalid_configuration_denies(tmp_path):
    config = dict(BASE_CONFIG)
    config.pop("max_risk_per_trade")
    service, _, _, _ = make_service(tmp_path, config=config)

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.CONFIGURATION_ERROR)


def test_unexpected_internal_exception_denies(tmp_path):
    def broken_config():
        raise RuntimeError("unexpected")

    service, _, _, _ = make_service(tmp_path, config_provider=broken_config)

    decision = service.authorize(valid_request())

    assert_denied(decision, ReasonCode.INTERNAL_ERROR)
    assert "unexpected" not in decision.reason.lower()


def test_valid_controlled_request_returns_allow_and_is_reserved(tmp_path):
    service, _, paper, _ = make_service(tmp_path)

    decision = service.authorize(valid_request())

    assert decision.allowed is True
    assert decision.reason_code == ReasonCode.ALLOWED.value
    assert decision.calculated_risk["per_trade_risk"] == 5
    state = paper.risk_snapshot(NOW.date())
    assert state.accepted_request_ids == ("risk-request-1",)


def test_deny_never_invokes_broker_mutation(tmp_path, monkeypatch):
    service, _, _, _ = make_service(tmp_path, kill_active=True)
    post = Mock()
    monkeypatch.setattr("src.broker.dhan_client.requests.post", post)
    client = DhanClient(
        access_token="offline-token",
        client_id="offline-client",
        risk_authorizer=service,
    )

    with pytest.raises(BrokerMutationBlockedError) as captured:
        client.place_order(*broker_request("deny-request"))

    assert captured.value.decision.reason_code == "KILL_SWITCH_ACTIVE"
    post.assert_not_called()


def test_allow_invokes_only_mocked_broker_mutation(tmp_path, monkeypatch):
    service, _, _, _ = make_service(tmp_path)
    response = Mock()
    response.json.return_value = {"status": "mocked"}
    post = Mock(return_value=response)
    monkeypatch.setattr("src.broker.dhan_client.requests.post", post)
    client = DhanClient(
        access_token="offline-token",
        client_id="offline-client",
        risk_authorizer=service,
    )

    result = client.place_order(*broker_request("allow-request"))

    assert result == {"status": "mocked"}
    assert client.last_risk_decision.allowed is True
    post.assert_called_once()


def test_new_verified_trading_date_resets_daily_state_only_once(tmp_path):
    _, _, paper, _ = make_service(
        tmp_path,
        state=daily_state(
            trading_date="2026-07-09",
            realized_pnl=-100,
            trades_taken=2,
            accepted_request_ids=("old",),
        ),
    )

    reset = paper.risk_snapshot(NOW.date())
    reloaded = PaperStateService(
        paper.path, now_provider=lambda: NOW
    ).risk_snapshot(NOW.date())

    assert reset.realized_pnl == 0
    assert reset.trades_taken == 0
    assert reset.accepted_request_ids == ()
    assert reloaded == reset


def test_audit_record_contains_only_non_secret_request_metadata(tmp_path):
    service, _, _, audit = make_service(tmp_path)

    decision = service.authorize(valid_request())
    record = json.loads(audit.path.read_text(encoding="utf-8").splitlines()[-1])
    serialized = json.dumps(record).lower()

    assert decision.allowed is True
    assert record["request"]["request_id"] == "risk-request-1"
    assert "access-token" not in serialized
    assert "client-secret" not in serialized
    assert "offline-token" not in serialized


def broker_request(request_id):
    payload = {
        "securityId": "13",
        "transactionType": "BUY",
        "quantity": 1,
        "price": 100,
        "triggerPrice": 95,
    }
    context = {
        "request_id": request_id,
        "symbol": "NIFTY",
        "market_data_timestamp": NOW.isoformat(),
        "volatility": 15,
    }
    return payload, context
