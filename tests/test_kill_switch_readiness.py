from datetime import datetime
import json
from pathlib import Path

import pytest
from app.main import app
from src.api.control_status_api import ControlStatusAPI
from src.risk.authorization import RiskControlStore, RiskStateUnavailable
from src.system_readiness import OpenMarketReadinessService


pytestmark = pytest.mark.unit
NOW = datetime.fromisoformat("2026-07-11T14:00:00+05:30")


def initialized_store(tmp_path, active=False):
    store = RiskControlStore(tmp_path / "risk_control_state.json")
    store.initialize(active, "INITIALIZED_SAFE_DEFAULT" if not active else "OPERATOR_STOP", "test")
    return store


def test_clean_initialization_is_explicit_atomic_and_restart_safe(tmp_path):
    store = initialized_store(tmp_path)
    projection = store.ensure_metadata()
    reloaded = RiskControlStore(store.path).projection()
    assert projection.state == reloaded.state == "INACTIVE"
    assert projection.reason == reloaded.reason == "INITIALIZED_SAFE_DEFAULT"
    assert projection.persistence_health == "HEALTHY"
    assert projection.last_valid_state == "INACTIVE"
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_state_cannot_be_silently_initialized_twice(tmp_path):
    store = initialized_store(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(RiskStateUnavailable, match="already exists"):
        store.initialize(False, "SECOND_STORE", "test")
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "payload,state,health,reason",
    [
        (None, "UNKNOWN", "MISSING", "KILL_SWITCH_STATE_MISSING"),
        ("not-json", "CORRUPT", "CORRUPT", "KILL_SWITCH_STATE_CORRUPT"),
        ({"version": 999, "kill_switch": {}}, "CORRUPT", "CORRUPT", "KILL_SWITCH_STATE_CORRUPT"),
        ({"version": 1, "kill_switch": {"active": "false"}}, "CORRUPT", "CORRUPT", "KILL_SWITCH_STATE_CORRUPT"),
    ],
)
def test_unavailable_or_invalid_store_fails_closed(tmp_path, payload, state, health, reason):
    path = tmp_path / "risk_control_state.json"
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    projection = RiskControlStore(path).projection()
    assert (projection.state, projection.persistence_health, projection.reason) == (state, health, reason)
    assert projection.active is None and projection.last_valid_state is None


@pytest.mark.parametrize("active,expected", [(False, "INACTIVE"), (True, "ACTIVE")])
def test_valid_active_and_inactive_state_are_projected_truthfully(tmp_path, active, expected):
    projection = initialized_store(tmp_path, active).projection()
    assert projection.state == expected
    assert projection.active is active
    assert projection.last_valid_state == expected
    assert projection.activated_at is not None if active else projection.deactivated_at is not None


def test_kill_switch_api_is_sanitized_and_get_only(tmp_path):
    api = ControlStatusAPI(risk_store=initialized_store(tmp_path))
    response = api.kill_switch_summary()
    assert set(response) == {
        "enabled", "state", "reason", "activated_at", "deactivated_at", "updated_at",
        "source", "schema_version", "persistence_health", "last_valid_state", "warnings",
        "status", "warning",
    }
    assert not any(key in json.dumps(response).lower() for key in ("credential", "token", "password", "path"))
    routes = {(route.path, tuple(route.methods or ())) for route in app.routes}
    assert any(path == "/v1/risk/kill-switch" and methods == ("GET",) for path, methods in routes)
    assert not any(path.startswith("/v1/risk/kill-switch") and set(methods) & {"POST", "PUT", "PATCH", "DELETE"} for path, methods in routes)


def fake_service(tmp_path, *, market_open=False, kill_state="INACTIVE", argus_status="stale", alpha_candles=64, risk_ready=True, aegis_ready=True):
    session = {
        "market_open": market_open,
        "session_state": "OPEN" if market_open else "WEEKEND",
        "reason": "MARKET_OPEN" if market_open else "WEEKEND",
        "next_valid_open": "2026-07-13T09:15:00+05:30",
    }
    return OpenMarketReadinessService(
        session=lambda: session,
        argus=lambda: {"status": argus_status},
        kronos_alpha=lambda: {"readiness_state": "READY_FOR_NEXT_OPEN", "input_candle_count": alpha_candles},
        technical=lambda: {
            "oracle_status": "READY",
            "data_status": "CACHED",
            "input_features": {
                "ema_21": 1.0,
                "ema_38": 1.0,
                "vwap": 1.0,
                "rsi_14": 50.0,
                "adx_14": 20.0,
                "atr_14": 5.0,
            },
        },
        kronos_core=lambda: {"status": "AVAILABLE"},
        athena=lambda: {"athena_status": "READY", "recommendation": "CONTINUE"},
        hermes=lambda: {"hermes_status": "UNAVAILABLE"},
        personal_oracle=lambda: {"status": "available", "maturity": "PRELIMINARY"},
        risk=lambda: {"risk_state_available": risk_ready, "state_health": "HEALTHY" if risk_ready else "UNAVAILABLE"},
        kill_switch=lambda: {"state": kill_state},
        aegis=lambda: {"status": "READY" if aegis_ready else "UNAVAILABLE"},
        now_provider=lambda: NOW,
    )


def test_closed_market_readiness_is_waiting_not_failed(tmp_path):
    value = fake_service(tmp_path).assess()
    assert value["status"] == "WAITING_FOR_MARKET"
    assert value["blocking_components"] == []
    by_name = {item["component"]: item for item in value["items"]}
    assert by_name["ARGUS"]["status"] == "READY_WITH_LIMITATIONS"
    assert by_name["KRONOS ALPHA"]["status"] == "WAITING_FOR_MARKET"
    assert by_name["HERMES"]["status"] == "READY_WITH_LIMITATIONS"
    assert by_name["Personal ORACLE"]["status"] == "READY_WITH_LIMITATIONS"
    assert by_name["Risk Authorization"]["status"] == "READY"
    assert by_name["AEGIS API"]["status"] == "READY"


@pytest.mark.parametrize("state", ["ACTIVE", "UNKNOWN", "CORRUPT"])
def test_unsafe_kill_switch_states_block_readiness(tmp_path, state):
    value = fake_service(tmp_path, kill_state=state).assess()
    assert value["status"] == "BLOCKED"
    assert "Kill Switch" in value["blocking_components"]


@pytest.mark.parametrize(
    "kwargs,component",
    [
        ({"risk_ready": False}, "Risk Authorization"),
        ({"aegis_ready": False}, "AEGIS API"),
        ({"market_open": True, "argus_status": "unavailable"}, "ARGUS"),
        ({"market_open": True, "alpha_candles": 12}, "KRONOS ALPHA"),
    ],
)
def test_missing_critical_readiness_input_is_explained(tmp_path, kwargs, component):
    value = fake_service(tmp_path, **kwargs).assess()
    item = next(item for item in value["items"] if item["component"] == component)
    assert item["status"] == "NOT_READY" and item["blocking"] is True
    assert component in value["blocking_components"]


def test_open_market_ready_with_truthful_limitations(tmp_path):
    value = fake_service(tmp_path, market_open=True, argus_status="available").assess()
    assert value["status"] == "READY_WITH_LIMITATIONS"
    assert value["blocking_components"] == []


@pytest.mark.parametrize(
    "technical_reason",
    ["INSUFFICIENT_FEATURES", "DHAN_HISTORY_UNAVAILABLE"],
)
def test_technical_readiness_reports_exact_failure_not_live_or_cached(
    tmp_path, technical_reason
):
    service = fake_service(
        tmp_path,
        market_open=True,
        argus_status="available",
    )
    service.providers["technical"] = lambda: {
        "oracle_status": "DEGRADED",
        "data_status": "LIVE",
        "reason_codes": [technical_reason],
    }

    value = service.assess()
    item = next(
        item
        for item in value["items"]
        if item["component"] == "Technical Intelligence"
    )

    assert item["status"] == "NOT_READY"
    assert item["reason"] == technical_reason
    assert item["blocking"] is True


def test_cached_technical_assessment_is_ready_when_all_indicators_are_present(tmp_path):
    service = fake_service(tmp_path, market_open=True, argus_status="available")

    item = next(
        item
        for item in service.assess()["items"]
        if item["component"] == "Technical Intelligence"
    )

    assert item["status"] == "READY"
    assert item["reason"] == "INDICATORS_READY"
    assert item["blocking"] is False


def test_cached_technical_assessment_with_null_indicator_fails_closed(tmp_path):
    service = fake_service(tmp_path, market_open=True, argus_status="available")
    technical = service.providers["technical"]()
    technical["input_features"]["adx_14"] = None
    service.providers["technical"] = lambda: technical

    item = next(
        item
        for item in service.assess()["items"]
        if item["component"] == "Technical Intelligence"
    )

    assert item["status"] == "NOT_READY"
    assert item["reason"] == "INSUFFICIENT_FEATURES"
    assert item["blocking"] is True


def test_completed_indicator_readiness_survives_transient_spot_quote_gap(tmp_path):
    service = fake_service(tmp_path, market_open=True, argus_status="available")
    technical = service.providers["technical"]()
    technical.update({
        "oracle_status": "UNAVAILABLE",
        "data_status": "UNAVAILABLE",
        "reason_codes": ["MARKET_PRICE_UNAVAILABLE"],
    })
    service.providers["technical"] = lambda: technical

    item = next(
        item
        for item in service.assess()["items"]
        if item["component"] == "Technical Intelligence"
    )

    assert item["status"] == "READY"
    assert item["reason"] == "INDICATORS_READY"
    assert item["blocking"] is False


@pytest.mark.parametrize(
    "argus_reason",
    ["ARGUS_CACHE_UNAVAILABLE", "ARGUS_SOURCE_STALE"],
)
def test_argus_readiness_preserves_exact_cache_or_source_reason(
    tmp_path, argus_reason
):
    service = fake_service(tmp_path, market_open=True)
    service.providers["argus"] = lambda: {
        "status": "stale",
        "reason": argus_reason,
    }

    value = service.assess()
    item = next(item for item in value["items"] if item["component"] == "ARGUS")

    assert item["status"] == "NOT_READY"
    assert item["reason"] == argus_reason


def test_next_session_plan_is_deterministic_bounded_and_unobserved(tmp_path):
    plan = fake_service(tmp_path).next_session_plan()
    assert plan["expected_open"] == "2026-07-13T09:15:00+05:30"
    assert plan["first_candle_close"] == "2026-07-13T09:20:00+05:30"
    assert plan["grace_complete"] == "2026-07-13T09:20:10+05:30"
    assert plan["minimum_candle_count"] == 64 and plan["grace_seconds"] == 10
    assert [step["sequence"] for step in plan["steps"]] == list(range(1, 11))
    assert all(step["observed"] is False for step in plan["steps"])


def test_readiness_calls_each_read_provider_once_and_no_mutation(tmp_path):
    service = fake_service(tmp_path)
    counts = {name: 0 for name in service.providers}
    for name, provider in tuple(service.providers.items()):
        def counted(provider=provider, name=name):
            counts[name] += 1
            return provider()
        service.providers[name] = counted
    result = service.assess()
    assert counts == {name: 1 for name in counts}
    assert result["provider_refresh_triggered"] is False
    assert result["model_inference_triggered"] is False
    assert result["broker_call_triggered"] is False


def test_readiness_routes_are_get_only_and_frontend_has_no_controls():
    routes = {(route.path, frozenset(route.methods or ())) for route in app.routes}
    for path in ("/v1/system/open-market-readiness", "/v1/system/next-session-plan"):
        assert (path, frozenset({"GET"})) in routes
    frontend = (Path(__file__).parents[1] / "citadel-dashboard/src/app/page.tsx").read_text(encoding="utf-8")
    assert "feedSelectors.readiness" in frontend
    assert "feedSelectors.nextSessionPlan" in frontend
    assert not any(label in frontend for label in ("Activate Kill Switch", "Deactivate Kill Switch"))


def test_live_trading_remains_disabled():
    settings = json.loads((Path(__file__).parents[1] / "config/settings.json").read_text(encoding="utf-8"))
    assert settings["live_trading_enabled"] is False
