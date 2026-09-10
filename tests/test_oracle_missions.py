import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from src.oracle.mission import (
    MissionConflictError,
    MissionStartRequest,
    MissionStateUnavailableError,
    MissionValidationError,
    OracleMissionService,
)


pytestmark = [pytest.mark.unit, pytest.mark.safety]
NOW = datetime(2026, 7, 26, 7, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


def service(tmp_path, clock=None):
    sequence = iter(("oracle_mission_one", "oracle_mission_two"))
    return OracleMissionService(
        tmp_path / "oracle_missions",
        now_provider=clock or Clock(),
        id_provider=lambda: next(sequence),
    )


def start(missions, **changes):
    request = {
        "idempotency_key": "request-one",
        "instrument_scope": "NIFTY",
        "mode": "ADVISE",
        "max_trades": 1,
        "timeout_seconds": 60,
    }
    request.update(changes)
    return missions.start(**request)


def test_empty_service_creates_no_mission_or_snapshot(tmp_path):
    missions = service(tmp_path)

    assert missions.active() is None
    assert missions.events.path.read_bytes() == b""
    assert not missions.state_path.exists()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_duplicate_start_is_idempotent_and_second_active_is_blocked(tmp_path):
    missions = service(tmp_path)

    first = start(missions)
    duplicate = start(missions)

    assert duplicate == first
    assert len(missions.recent()) == 1
    with pytest.raises(MissionConflictError):
        start(missions, idempotency_key="request-two")


def test_concurrent_starts_create_exactly_one_active_mission(tmp_path):
    missions = service(tmp_path)

    def attempt(index):
        try:
            return start(missions, idempotency_key=f"concurrent-{index}")
        except MissionConflictError:
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(100)))

    accepted = [result for result in results if result is not None]
    assert len(accepted) == 1
    assert missions.active() == accepted[0]
    assert len(missions.recent()) == 1
    assert len(missions.events.read()) == 1


@pytest.mark.parametrize("value", [0, 2, 10])
def test_max_trades_is_locked_to_one(tmp_path, value):
    with pytest.raises(MissionValidationError, match="locked to 1"):
        start(service(tmp_path), max_trades=value)


def test_live_mode_is_always_rejected(tmp_path):
    with pytest.raises(MissionValidationError, match="LIVE mode is forbidden"):
        start(service(tmp_path), mode="LIVE")


@pytest.mark.parametrize("mode", ["ADVISE", "CONFIRM", "PAPER_AUTOPILOT"])
def test_advisory_modes_are_accepted_without_execution_authority(tmp_path, mode):
    created = start(service(tmp_path), mode=mode)

    assert created["mode"] == mode
    assert created["max_trades"] == 1
    assert created["execution_allowed"] is False


def test_timeout_expires_as_no_trade_without_decision_or_contract(tmp_path):
    clock = Clock()
    missions = service(tmp_path, clock)
    created = start(missions)
    clock.value += timedelta(seconds=61)

    assert missions.active() is None
    expired = missions.get(created["mission_id"])

    assert expired["status"] == "EXPIRED"
    assert expired["outcome"] == "NO_TRADE"
    assert expired["terminal_reason"] == "TIMEOUT"
    assert expired["decision"] is None
    assert expired["contract"] is None
    assert expired["trades_used"] == 0
    assert expired["execution_allowed"] is False
    assert expired["forced_trade"] is False


def test_cancel_is_idempotent_and_records_one_terminal_event(tmp_path):
    missions = service(tmp_path)
    created = start(missions)

    first = missions.cancel(created["mission_id"])
    second = missions.cancel(created["mission_id"])

    assert second == first
    assert first["status"] == "CANCELLED"
    assert first["outcome"] == "NO_TRADE"
    events = missions.events.read()
    assert [event["event_type"] for event in events] == [
        "MISSION_STARTED",
        "MISSION_CANCELLED",
    ]
    assert missions.events.verify()["valid"] is True
    assert start(missions) == first
    assert missions.active() is None


def test_restart_terminalizes_active_mission_without_outcome(tmp_path):
    root = tmp_path / "oracle_missions"
    clock = Clock()
    first = OracleMissionService(
        root,
        now_provider=clock,
        id_provider=lambda: "oracle_mission_restart",
    )
    created = start(first)

    restarted = OracleMissionService(root, now_provider=clock)

    assert restarted.active() is None
    recovered = restarted.get(created["mission_id"])
    assert recovered["status"] == "FAILED"
    assert recovered["outcome"] == "NO_TRADE"
    assert recovered["terminal_reason"] == "RESTART_RECOVERY_NO_OUTCOME"
    assert restarted.state_status()["status"] == "AVAILABLE"
    assert restarted.events.verify() == {
        "valid": True,
        "records": 2,
        "failure_index": None,
    }


def test_corrupt_state_fails_safe_without_overwrite(tmp_path):
    root = tmp_path / "oracle_missions"
    root.mkdir()
    state_path = root / "mission_state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    before = state_path.read_bytes()

    missions = OracleMissionService(root)

    assert missions.state_status() == {
        "status": "UNAVAILABLE",
        "reason": "MISSION_STATE_CORRUPT",
        "execution_allowed": False,
        "execution_influence": "ZERO",
    }
    with pytest.raises(MissionStateUnavailableError):
        missions.active()
    assert state_path.read_bytes() == before


def test_event_tamper_and_truncation_fail_safe(tmp_path):
    root = tmp_path / "oracle_missions"
    missions = OracleMissionService(
        root,
        id_provider=lambda: "oracle_mission_tamper",
    )
    created = start(missions)
    missions.cancel(created["mission_id"])
    rows = missions.events.read()

    tampered = json.loads(json.dumps(rows))
    tampered[0]["payload"]["mission"]["instrument_scope"] = "BANKNIFTY"
    missions.events.path.write_text(
        "\n".join(json.dumps(row) for row in tampered) + "\n",
        encoding="utf-8",
    )
    assert OracleMissionService(root).state_status()["status"] == "UNAVAILABLE"

    missions.events.path.write_text(
        json.dumps(rows[0]) + "\n",
        encoding="utf-8",
    )
    truncated = OracleMissionService(root)
    assert truncated.state_status() == {
        "status": "UNAVAILABLE",
        "reason": "MISSION_STATE_CORRUPT",
        "execution_allowed": False,
        "execution_influence": "ZERO",
    }

    missions.events.path.unlink()
    missing = OracleMissionService(root)
    assert missing.state_status()["status"] == "UNAVAILABLE"


def test_event_ahead_of_snapshot_recovers_idempotently(tmp_path):
    root = tmp_path / "oracle_missions"
    missions = OracleMissionService(
        root,
        id_provider=lambda: "oracle_mission_event_recovery",
    )
    created = start(missions)
    state = missions._empty_state()
    state_path = root / "mission_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    restarted = OracleMissionService(root)

    assert restarted.active() is None
    recovered_mission = restarted.get(created["mission_id"])
    assert recovered_mission["status"] == "FAILED"
    assert recovered_mission["outcome"] == "NO_TRADE"
    assert recovered_mission["terminal_reason"] == "RESTART_RECOVERY_NO_OUTCOME"
    assert restarted.start(
        idempotency_key="request-one",
        instrument_scope="NIFTY",
        mode="ADVISE",
        max_trades=1,
        timeout_seconds=60,
    ) == recovered_mission
    recovered = json.loads(state_path.read_text(encoding="utf-8"))
    assert recovered["event_records"] == 2
    assert recovered["event_head"] == restarted.events.read()[-1]["record_hash"]


def test_missions_never_mutate_order_or_fill_ledgers(tmp_path):
    order_path = tmp_path / "order_ledger.jsonl"
    fill_path = tmp_path / "fill_ledger.jsonl"
    order_path.write_text('{"order":"existing"}\n', encoding="utf-8")
    fill_path.write_text('{"fill":"existing"}\n', encoding="utf-8")
    before = (digest(order_path), digest(fill_path))
    missions = service(tmp_path)

    created = start(missions, mode="PAPER_AUTOPILOT")
    missions.cancel(created["mission_id"])

    assert (digest(order_path), digest(fill_path)) == before
    assert created["safety"] == {
        "execution_allowed": False,
        "execution_influence": "ZERO",
        "strategy_influence": "ZERO",
        "order_influence": "ZERO",
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
        "forced_trade": False,
    }


def test_mission_api_contract_and_live_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv("CITADEL_STATE_ROOT", str(tmp_path / "runtime"))
    from app import main

    missions = service(tmp_path)
    monkeypatch.setattr(main, "oracle_mission_service", missions)
    payload = {
        "idempotency_key": "api-one",
        "instrument_scope": "NIFTY",
        "mode": "CONFIRM",
        "max_trades": 1,
        "timeout_seconds": 60,
    }

    created = main.start_oracle_mission(MissionStartRequest(**payload))
    duplicate = main.start_oracle_mission(MissionStartRequest(**payload))
    active = main.active_oracle_mission()
    fetched = main.get_oracle_mission(created["mission_id"])
    recent = main.recent_oracle_missions()
    cancelled = main.cancel_oracle_mission(created["mission_id"])
    with pytest.raises(HTTPException) as captured:
        main.start_oracle_mission(
            MissionStartRequest(
                **{**payload, "idempotency_key": "api-live", "mode": "LIVE"}
            )
        )

    route_methods = {
        (route.path, tuple(sorted(route.methods or ())))
        for route in main.app.routes
    }
    assert ("/v1/oracle/missions", ("POST",)) in route_methods
    assert ("/v1/oracle/missions", ("GET",)) in route_methods
    assert ("/v1/oracle/missions/active", ("GET",)) in route_methods
    assert ("/v1/oracle/missions/{mission_id}", ("GET",)) in route_methods
    assert (
        "/v1/oracle/missions/{mission_id}/cancel",
        ("POST",),
    ) in route_methods
    assert duplicate == created
    assert active["mission"] == created
    assert fetched == created
    assert recent["missions"] == [created]
    assert cancelled["status"] == "CANCELLED"
    assert captured.value.status_code == 422
    assert captured.value.detail["code"] == "ORACLE_MISSION_INVALID"
