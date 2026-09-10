import importlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.api.control_status_api import ControlStatusAPI
from src.athena.athena_service import AthenaService
from src.execution.paper_state import PaperStateService
from src.risk.authorization import RiskAuditLogger, RiskControlStore


pytestmark = [pytest.mark.unit, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 11, 10, 0, tzinfo=IST)


def risk_source(*, kill=False, available=True, latest=None, **limit_changes):
    limits = {
        "max_daily_loss": 1000.0,
        "max_trades_per_day": 4,
        "max_consecutive_losses": 3,
        "max_risk_per_trade": 500.0,
        "max_raw_quantity": 1,
        "max_open_positions": 2,
        "max_market_data_age_seconds": 10.0,
        "max_volatility": None,
    }
    limits.update(limit_changes)
    return {
        "status": "healthy" if available else "degraded",
        "state_health": "HEALTHY" if available else "DEGRADED",
        "live_trading_enabled": False,
        "kill_switch_active": kill,
        "risk_state_available": available,
        "limits": limits,
        "latest_authorization": latest,
        "last_updated": NOW.isoformat(),
    }


def paper_source(
    *,
    realized=0.0,
    unrealized=0.0,
    trades=0,
    losses=0,
    positions=0,
    capital=None,
    blocked=None,
    equity=None,
):
    return {
        "status": "healthy",
        "state_health": "HEALTHY",
        "trading_date": NOW.date().isoformat(),
        "cash_balance": capital,
        "blocked_capital": blocked,
        "current_equity": equity,
        "realized_pnl": float(realized),
        "unrealized_pnl": float(unrealized),
        "total_daily_pnl": float(realized + unrealized),
        "trades_taken_today": trades,
        "consecutive_losses": losses,
        "open_position_count": positions,
        "last_updated": NOW.isoformat(),
    }


def assess(risk=None, paper=None):
    service = AthenaService(
        risk_provider=lambda: risk if risk is not None else risk_source(),
        paper_provider=lambda: paper if paper is not None else paper_source(),
        now_provider=lambda: NOW,
    )
    return service.assess()


def test_safe_continue_state_is_deterministic():
    result = assess()

    assert result.risk_state == "SAFE"
    assert result.recommendation == "CONTINUE"
    assert result.recommended_size_multiplier == 1.0
    assert "ATHENA_SAFE" in result.reason_codes


def test_caution_reduce_state_is_deterministic():
    result = assess(paper=paper_source(trades=2))

    assert result.risk_state == "CAUTION"
    assert result.recommendation == "REDUCE"
    assert result.recommended_size_multiplier == 0.75
    assert "TRADE_USAGE_HIGH" in result.reason_codes


def test_high_risk_pause_state_is_deterministic():
    result = assess(paper=paper_source(realized=-850))

    assert result.risk_state == "HIGH_RISK"
    assert result.recommendation == "PAUSE"
    assert result.recommended_size_multiplier == 0.25
    assert "ATHENA_HIGH_RISK" in result.reason_codes


def test_active_kill_switch_is_blocked_stop():
    result = assess(risk=risk_source(kill=True))

    assert result.athena_status == "BLOCKED"
    assert result.risk_state == "STOP"
    assert result.recommendation == "STOP"
    assert result.recommended_size_multiplier == 0.0
    assert "KILL_SWITCH_ACTIVE" in result.reason_codes


@pytest.mark.parametrize(
    ("paper", "code"),
    [
        (paper_source(realized=-1000), "DAILY_LOSS_LIMIT_REACHED"),
        (paper_source(trades=4), "MAX_TRADES_REACHED"),
        (paper_source(losses=3), "MAX_CONSECUTIVE_LOSSES_REACHED"),
        (paper_source(positions=2), "OPEN_POSITION_LIMIT_REACHED"),
    ],
)
def test_hard_limits_map_to_stop(paper, code):
    result = assess(paper=paper)

    assert result.athena_status == "BLOCKED"
    assert result.recommendation == "STOP"
    assert code in result.reason_codes


def test_missing_risk_state_fails_safely():
    result = assess(risk=risk_source(available=False))

    assert result.athena_status == "UNAVAILABLE"
    assert result.risk_state == "STOP"
    assert result.recommended_size_multiplier == 0.0
    assert result.daily_loss_used_percentage is None
    assert "RISK_STATE_UNAVAILABLE" in result.reason_codes


def test_malformed_paper_state_fails_safely():
    malformed = paper_source()
    malformed["total_daily_pnl"] = "not-a-number"

    result = assess(paper=malformed)

    assert result.athena_status == "UNAVAILABLE"
    assert result.recommendation == "STOP"
    assert result.current_drawdown is None


def test_development_capital_is_explicit_and_does_not_invent_equity():
    result = assess(paper=paper_source(realized=-100))

    assert result.available_capital == 50_000.0
    assert result.blocked_capital is None
    assert result.current_equity is None
    assert result.maximum_allowed_drawdown is None
    assert result.current_drawdown == 100.0
    assert "DEVELOPMENT_CAPITAL_APPLIED" in result.reason_codes
    assert "DEVELOPMENT_CAPITAL_SIMULATION_ONLY" in result.warnings
    assert result.source_metadata.capital_basis == "DEVELOPMENT_CAPITAL_SIMULATION_ONLY"


def test_authoritative_cash_balance_is_exposed_without_inventing_equity():
    result = assess(paper=paper_source(capital=100000))

    assert result.available_capital == 100000.0
    assert result.blocked_capital is None
    assert result.current_equity is None
    assert result.source_metadata.capital_basis == "PAPER_CASH_BALANCE"


@pytest.mark.parametrize(
    "paper",
    [
        paper_source(),
        paper_source(trades=2),
        paper_source(realized=-850),
        paper_source(realized=-5000),
    ],
)
def test_size_multiplier_is_always_bounded(paper):
    multiplier = assess(paper=paper).recommended_size_multiplier

    assert 0.0 <= multiplier <= 1.0


def test_risk_authorization_deny_cannot_be_overridden():
    deny = {
        "decision": "DENY",
        "reason_code": "STALE_MARKET_DATA",
        "reason": "Market data is stale",
        "timestamp": NOW.isoformat(),
    }
    result = assess(risk=risk_source(latest=deny))

    assert result.athena_status == "BLOCKED"
    assert result.recommendation == "STOP"
    assert "RISK_AUTHORIZATION_DENY" in result.reason_codes
    assert "STALE_MARKET_DATA" in result.reason_codes


def test_reason_codes_and_advisory_metadata_are_always_present():
    result = assess()

    assert result.reason_codes
    assert result.explanation
    assert result.advisory_only is True
    assert result.source_metadata.risk_authorization_final_veto is True
    assert result.source_metadata.exposure_basis == "OPEN_POSITION_CAPACITY"


def test_api_response_is_sanitized_and_get_only(monkeypatch):
    service = AthenaService(
        risk_provider=lambda: risk_source(),
        paper_provider=lambda: paper_source(),
        now_provider=lambda: NOW,
    )
    main = importlib.import_module("app.main")
    original = main.athena_service
    main.athena_service = service
    try:
        payload = main.athena_status()
        legacy = main.athena_wheel()
        methods = {
            route.path: route.methods
            for route in main.app.routes
            if route.path.startswith("/v1/athena/")
        }
        assert payload["recommendation"] == "CONTINUE"
        assert legacy["risk_state"] == "SAFE"
        assert methods == {
            "/v1/athena/wheel": {"GET"},
            "/v1/athena/status": {"GET"},
        }
    finally:
        main.athena_service = original


def test_api_response_contains_no_secret_source_fields():
    risk = risk_source()
    risk["access_token"] = "must-not-appear"
    paper = paper_source()
    paper["credential"] = "must-not-appear"

    serialized = json.dumps(assess(risk=risk, paper=paper).to_dict()).lower()

    assert "must-not-appear" not in serialized
    assert "access_token" not in serialized
    assert "credential" not in serialized


def test_service_has_no_broker_or_mutation_dependency():
    module_path = Path(
        importlib.import_module("src.athena.athena_service").__file__
    )
    source = module_path.read_text(encoding="utf-8")

    for forbidden in (
        "DhanClient",
        "place_order",
        "cancel_order",
        ".open_position(",
        ".close_position(",
        "activate(",
        "deactivate(",
    ):
        assert forbidden not in source


def test_assessment_does_not_mutate_authoritative_files(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "live_trading_enabled": False,
                "max_daily_loss": 1000,
                "max_trades_per_day": 4,
                "max_consecutive_losses": 3,
                "max_risk_per_trade": 500,
                "max_position_quantity": 1,
                "max_open_positions": 2,
                "max_market_data_age_seconds": 10,
                "max_volatility": None,
            }
        ),
        encoding="utf-8",
    )
    risk_store = RiskControlStore(tmp_path / "risk.json")
    risk_store.initialize(False, "test inactive", "pytest")
    paper_state = PaperStateService(
        tmp_path / "paper.json", now_provider=lambda: NOW
    )
    paper_state.initialize(cash_balance=100000)
    control = ControlStatusAPI(
        settings_path=settings_path,
        risk_store=risk_store,
        paper_state=paper_state,
        audit_logger=RiskAuditLogger(tmp_path / "audit.jsonl"),
        now_provider=lambda: NOW,
    )
    service = AthenaService(
        risk_provider=control.risk_summary,
        paper_provider=control.paper_summary,
        now_provider=lambda: NOW,
    )
    before_risk = risk_store.path.read_bytes()
    before_paper = paper_state.path.read_bytes()

    result = service.assess()

    assert result.available_capital == 100000.0
    assert risk_store.path.read_bytes() == before_risk
    assert paper_state.path.read_bytes() == before_paper
