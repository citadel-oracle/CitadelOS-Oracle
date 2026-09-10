"""Focused unit tests for CanonicalStatusEngine contract rules."""

import pytest
from datetime import datetime, timedelta, timezone
from src.system_status import CanonicalStatusEngine


pytestmark = pytest.mark.unit


def test_market_closed_with_healthy_dependencies():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    weekend_dt = datetime(2026, 7, 25, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    res = CanonicalStatusEngine.evaluate(
        backend_online=True,
        now_provider=lambda: weekend_dt,
        safety_status={"risk_state_available": True, "kill_switch_active": False},
        deployments_status=[
            {"strategy_id": "BO_NIFTY_CE_1M", "state": "RUNNING", "health": "HEALTHY", "readiness": "READY"}
        ],
    )
    assert res["operating_mode"] == "MARKET_CLOSED"
    assert res["overall_status"] == "HEALTHY"
    assert res["safety_status"] == "SAFE"


def test_backend_connected_with_stale_projection():
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(seconds=700)).isoformat()
    res = CanonicalStatusEngine.evaluate(
        backend_online=True,
        session_calendar_status={"session_state": "OPEN"},
        safety_status={"risk_state_available": True, "kill_switch_active": False},
        deployments_status=[
            {
                "strategy_id": "BO_NIFTY_CE_1M",
                "state": "RUNNING",
                "health": "HEALTHY",
                "last_updated": stale_time,
            }
        ],
    )
    dep = res["deployments"][0]
    assert dep["freshness"] == "STALE"
    assert dep["connectivity"] == "STALE"


def test_safety_blocked_when_kill_switch_active():
    res = CanonicalStatusEngine.evaluate(
        backend_online=True,
        safety_status={"risk_state_available": True, "kill_switch_active": True},
    )
    assert res["safety_status"] == "BLOCKED"
    assert res["overall_status"] == "BLOCKED"
    assert len(res["action_required_issues"]) >= 1
    assert res["action_required_issues"][0]["code"] == "KILL_SWITCH_ACTIVE"


def test_zero_of_ten_healthy_wording():
    deps = [{"strategy_id": f"DEP_{i}", "state": "STOPPED"} for i in range(10)]
    res = CanonicalStatusEngine.evaluate(
        backend_online=True,
        deployments_status=deps,
    )
    assert res["deployment_counts"]["healthy_running"] == 0
    assert res["deployment_counts"]["total"] == 10
    assert res["overall_status"] == "DEGRADED"
    assert "0 of 10" in res["system"]["plain_language_reason"]
    assert res["wording_summary"] != "All systems running normally"


def test_enabled_but_disconnected_deployment():
    res = CanonicalStatusEngine.evaluate(
        backend_online=True,
        deployments_status=[
            {"strategy_id": "PB_NIFTY_CE_1M", "state": "NOT_LOADED", "health": "HEALTHY"}
        ],
    )
    dep = res["deployments"][0]
    assert dep["lifecycle"] == "STOPPED"
    assert dep["connectivity"] == "DISCONNECTED"
    assert dep["readiness"] == "NOT_READY"


def test_unavailable_optional_module():
    res = CanonicalStatusEngine.evaluate(
        backend_online=True,
        intelligence_modules={
            "hermes": {"freshness": "STALE", "advisory_only": True},
            "chronos2": {"freshness": "STALE", "advisory_only": True},
        },
        deployments_status=[
            {"strategy_id": "BO_NIFTY_CE_1M", "state": "RUNNING", "health": "HEALTHY"}
        ],
    )
    assert res["overall_status"] == "HEALTHY"


def test_no_contradictory_state_combination():
    res = CanonicalStatusEngine.evaluate(
        backend_online=False,
        session_calendar_status={"session_state": "OPEN"},
        safety_status={"kill_switch_active": True},
    )
    assert res["overall_status"] == "OFFLINE"
    assert res["system"]["state"] == "OFFLINE"
