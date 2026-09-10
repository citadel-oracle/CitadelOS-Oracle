import importlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.api.control_status_api import ControlStatusAPI
from src.execution.paper_state import PaperStateService
from src.risk.authorization import RiskAuditLogger, RiskControlStore


pytestmark = [pytest.mark.integration, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
SETTINGS = {
    "live_trading_enabled": False,
    "max_daily_loss": 1000,
    "max_trades_per_day": 3,
    "max_consecutive_losses": 2,
    "max_risk_per_trade": 500,
    "max_position_quantity": 1,
    "max_open_positions": 1,
    "max_market_data_age_seconds": 10,
    "max_volatility": None,
}


def make_api(tmp_path, *, kill_active=False, paper=True, settings=None):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(settings if settings is not None else SETTINGS),
        encoding="utf-8",
    )
    risk_store = RiskControlStore(tmp_path / "risk.json")
    risk_store.initialize(
        kill_switch_active=kill_active,
        reason="operator halt" if kill_active else "explicitly inactive",
        actor="pytest",
    )
    paper_state = PaperStateService(
        tmp_path / "paper.json", now_provider=lambda: NOW
    )
    if paper:
        paper_state.initialize()
    return ControlStatusAPI(
        settings_path=settings_path,
        risk_store=risk_store,
        paper_state=paper_state,
        audit_logger=RiskAuditLogger(tmp_path / "audit.jsonl"),
        now_provider=lambda: NOW,
    )


def test_risk_summary_is_sanitized_and_read_only(tmp_path):
    api = make_api(tmp_path)

    payload = api.risk_summary()

    assert payload["status"] == "healthy"
    assert payload["live_trading_enabled"] is False
    assert payload["kill_switch_active"] is False
    assert payload["risk_state_available"] is True
    assert payload["limits"] == {
        "max_daily_loss": 1000.0,
        "max_trades_per_day": 3,
        "max_consecutive_losses": 2,
        "max_risk_per_trade": 500.0,
        "max_raw_quantity": 1,
        "max_open_positions": 1,
        "max_market_data_age_seconds": 10.0,
        "max_volatility": None,
    }


def test_paper_summary_uses_authoritative_state(tmp_path):
    api = make_api(tmp_path)
    api.paper_state.open_position(
        position_id="position-1",
        request_id="paper-open-1",
        event_id="paper-event-1",
        symbol="NIFTY",
        side="BUY",
        raw_quantity=2,
        entry_price=100,
    )
    api.paper_state.update_mark("position-1", 110, "paper-mark-1")

    payload = api.paper_summary()

    assert payload["state_health"] == "HEALTHY"
    assert payload["unrealized_pnl"] == 20
    assert payload["total_daily_pnl"] == 20
    assert payload["trades_taken_today"] == 1
    assert payload["open_position_count"] == 1
    assert payload["accepted_request_count"] == 1
    assert payload["state_last_mutated_at"] == payload["last_updated"]
    assert payload["projection_observed_at"] == NOW.isoformat()
    assert "LAST_UPDATED_IS_LAST_MUTATION_NOT_POLL_TIME" in payload["freshness_semantics"]


def test_active_kill_switch_is_represented_truthfully(tmp_path):
    payload = make_api(tmp_path, kill_active=True).risk_summary()

    assert payload["kill_switch_active"] is True
    assert payload["kill_switch_reason"] == "operator halt"
    assert payload["kill_switch_activated_at"] is not None


@pytest.mark.parametrize("state_kind", ["missing", "malformed"])
def test_unavailable_paper_state_returns_null_metrics(tmp_path, state_kind):
    api = make_api(tmp_path, paper=False)
    if state_kind == "malformed":
        api.paper_state.path.write_text("not-json", encoding="utf-8")

    payload = api.paper_summary()

    assert payload["status"] == "unavailable"
    assert payload["state_health"] == "UNAVAILABLE"
    assert payload["realized_pnl"] is None
    assert payload["unrealized_pnl"] is None
    assert payload["total_daily_pnl"] is None
    assert payload["trades_taken_today"] is None
    assert payload["error"]["code"] == "PAPER_STATE_UNAVAILABLE"


def test_response_whitelist_excludes_credentials_and_paths(tmp_path):
    settings = dict(
        SETTINGS,
        DHAN_ACCESS_TOKEN="must-not-appear",
        client_secret="must-not-appear",
        internal_path="/private/runtime/path",
    )
    api = make_api(tmp_path, settings=settings)

    serialized = json.dumps(
        {"risk": api.risk_summary(), "paper": api.paper_summary()}
    )

    assert "must-not-appear" not in serialized
    assert "/private/runtime/path" not in serialized
    assert "access_token" not in serialized.lower()
    assert "client_secret" not in serialized.lower()


def test_fastapi_exposes_get_only_status_routes_without_mutation(tmp_path):
    api = make_api(tmp_path)
    main = importlib.import_module("app.main")
    original = main.control_status
    main.control_status = api
    try:
        assert main.risk_status()["live_trading_enabled"] is False
        assert main.paper_status()["state_health"] == "HEALTHY"
        methods = {
            route.path: route.methods
            for route in main.app.routes
            if route.path in {"/v1/risk/status", "/v1/paper/status"}
        }
        assert methods == {
            "/v1/risk/status": {"GET"},
            "/v1/paper/status": {"GET"},
        }
    finally:
        main.control_status = original


def test_invalid_risk_configuration_is_degraded_not_fabricated(tmp_path):
    settings = dict(SETTINGS)
    settings.pop("max_risk_per_trade")

    payload = make_api(tmp_path, settings=settings).risk_summary()

    assert payload["status"] == "degraded"
    assert payload["live_trading_enabled"] is None
    assert payload["limits"]["max_daily_loss"] is None
    assert payload["risk_state_available"] is False
    assert payload["error"]["code"] == "RISK_STATE_DEGRADED"
