from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json

import pytest

from src.execution.paper_state import PaperStateService
from src.oracle.paper_autopilot import (
    OracleExecutionBlocked,
    OracleExecutionUnavailable,
    OraclePaperAutopilot,
)
from src.strategy_lab.storage import ImmutableStream


NOW = datetime(2026, 7, 27, 9, 30, tzinfo=timezone.utc)


class Missions:
    def __init__(self, root, mode="PAPER_AUTOPILOT"):
        self.events = ImmutableStream(root / "mission_events.jsonl")
        self.mission = {
            "mission_id": "mission-1",
            "mode": mode,
            "status": "ACTIVE",
        }
        self.plan = {
            "plan_id": "plan-1",
            "mission_id": "mission-1",
            "status": "APPROVED",
            "contract": "NIFTY28JUL2623900CE",
            "underlying": "NIFTY",
            "security_id": "63935",
            "option_type": "CE",
            "strike": 23900,
            "expiry": "2026-07-28",
            "lot_size": 65,
            "approved_quantity": 65,
            "maximum_approved_quantity": 65,
            "maximum_entry": 200.0,
            "final_sl": 190.0,
            "structural_invalidation": 23900.0,
            "mapped_premium_sl": 191.0,
            "target_1": 210.0,
            "target_2": 220.0,
            "trail_start": 210.0,
            "trail_rule": "AFTER_TARGET_1_MOVE_STOP_TO_ENTRY",
            "time_exit": "15:20:00 Asia/Kolkata",
            "contract_locked": True,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "execution_allowed": False,
        }
        self.events.append(
            "PLAN_CREATED",
            {"mission": self.mission, "plan": self.plan},
            idempotency_key="plan",
        )

    def get(self, mission_id):
        assert mission_id == self.mission["mission_id"]
        return dict(self.mission)

    def reservation_status(self):
        released = {
            (row["payload"]["mission"]["mission_id"])
            for row in self.events.read()
            if row["event_type"]
            in {"EXECUTION_CLOSED", "EXECUTION_REJECTED", "EXECUTION_FAILED"}
        }
        return {"active_plan_count": 0 if "mission-1" in released else 1}


class OpenAlgo:
    def __init__(self):
        self.place_calls = []
        self.lookup_calls = []
        self.statuses = {}
        self.fail_place = False
        self.analyzer_on = True

    def analyzer(self):
        return {
            "_http_status": 200,
            "status": "success",
            "data": {"analyze_mode": self.analyzer_on, "mode": "analyze"},
        }

    def place(self, payload):
        self.place_calls.append(dict(payload))
        if self.fail_place:
            raise OracleExecutionUnavailable("timeout")
        order_id = "ENTRY-1" if payload["action"] == "BUY" else "EXIT-1"
        self.statuses[order_id] = {
            "data": {
                "order_status": "complete",
                "filled_quantity": payload["quantity"],
                "average_price": 198.5 if payload["action"] == "BUY" else 211.0,
            }
        }
        return {"_http_status": 200, "status": "success", "orderid": order_id}

    def lookup(self, client_order_id):
        self.lookup_calls.append(client_order_id)
        order_id = "EXIT-1" if "_x_" in client_order_id else "ENTRY-1"
        return {"_http_status": 200, "status": "success", "orderid": order_id}

    def order_status(self, order_id):
        return self.statuses.get(
            order_id,
            {
                "data": {
                    "order_status": "complete",
                    "filled_quantity": 65,
                    "average_price": 198.5 if order_id == "ENTRY-1" else 211.0,
                }
            },
        )


def snapshot(price=205.0, timestamp=None, underlying=24000.0):
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    return {
        "execution": {
            "argus": {
                "data": {
                    "underlying": {"ltp": underlying},
                    "tactical_edge": {
                        "all_candidate_ranks": [
                            {
                                "security_id": "63935",
                                "premium": price,
                                "source_timestamp": timestamp,
                            }
                        ]
                    }
                }
            }
        }
    }


def service(tmp_path, *, mode="PAPER_AUTOPILOT", openalgo=None, quote=205.0):
    root = tmp_path / "oracle"
    missions = Missions(root, mode)
    paper = PaperStateService(
        tmp_path / "paper_state.json", now_provider=lambda: NOW
    )
    paper.initialize(trading_date=date(2026, 7, 27), cash_balance=1_000_000)
    client = openalgo or OpenAlgo()
    instance = OraclePaperAutopilot(
        root,
        missions=missions,
        openalgo=client,
        paper_state=paper,
        snapshot_provider=lambda: snapshot(quote),
        now_provider=lambda: NOW,
    )
    return instance, missions, paper, client


def test_verified_analyzer_fill_opens_exact_plan_and_retry_is_idempotent(tmp_path):
    autopilot, _, paper, client = service(tmp_path)
    first = autopilot.execute("mission-1")
    retry = autopilot.execute("mission-1")

    assert first["state"] == retry["state"] == "OPEN"
    assert first["execution_allowed"] is False
    assert first["direct_dhan_fallback"] is False
    assert first["remote_order_reference_present"] is True
    assert len(client.place_calls) == 1
    assert client.place_calls[0] == {
        "client_order_id": client.place_calls[0]["client_order_id"],
        "strategy": "ORACLE",
        "exchange": "NFO",
        "symbol": "NIFTY28JUL2623900CE",
        "action": "BUY",
        "quantity": 65,
        "pricetype": "LIMIT",
        "product": "MIS",
        "price": 200.0,
        "trigger_price": 0,
        "disclosed_quantity": 0,
    }
    assert len(paper.load(date(2026, 7, 27)).open_positions) == 1


def test_one_hundred_concurrent_execute_calls_place_one_order(tmp_path):
    autopilot, _, _, client = service(tmp_path)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: autopilot.execute("mission-1"), range(100)))
    assert {row["state"] for row in results} == {"OPEN"}
    assert len(client.place_calls) == 1


def test_advise_live_and_analyzer_off_are_blocked(tmp_path):
    advise, _, _, _ = service(tmp_path / "advise", mode="ADVISE")
    with pytest.raises(OracleExecutionBlocked, match="ADVISE"):
        advise.execute("mission-1")

    off = OpenAlgo()
    off.analyzer_on = False
    autopilot, _, paper, _ = service(tmp_path / "off", openalgo=off)
    with pytest.raises(OracleExecutionBlocked, match="ANALYZER"):
        autopilot.execute("mission-1")
    assert paper.load(date(2026, 7, 27)).trades_taken == 0


def test_timeout_never_assumes_fill_and_restart_reconciles_by_client_id(tmp_path):
    remote = OpenAlgo()
    remote.fail_place = True
    autopilot, missions, paper, _ = service(tmp_path, openalgo=remote)
    result = autopilot.execute("mission-1")
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert paper.load(date(2026, 7, 27)).trades_taken == 0

    remote.fail_place = False
    restarted = OraclePaperAutopilot(
        tmp_path / "oracle",
        missions=missions,
        openalgo=remote,
        paper_state=paper,
        snapshot_provider=snapshot,
        now_provider=lambda: NOW,
    )
    recovered = restarted.recover()
    assert recovered["status"] == "AVAILABLE"
    assert restarted.guardian("mission-1")["state"] == "OPEN"
    assert len(remote.place_calls) == 1
    assert len(remote.lookup_calls) >= 1


def test_manual_exit_is_exactly_once_and_closes_paper_position(tmp_path):
    autopilot, missions, paper, client = service(tmp_path)
    autopilot.execute("mission-1")
    first = autopilot.exit("mission-1")
    second = autopilot.exit("mission-1")
    assert first["state"] == second["state"] == "CLOSED"
    assert len(client.place_calls) == 2
    assert client.place_calls[1]["action"] == "SELL"
    assert client.place_calls[1]["quantity"] == 65
    state = paper.load(date(2026, 7, 27))
    assert not state.open_positions
    assert len(state.closed_trades) == 1
    assert missions.reservation_status()["active_plan_count"] == 0


def test_stop_target_trailing_stale_and_disconnect_behaviour(tmp_path):
    autopilot, _, paper, client = service(tmp_path, quote=215.0)
    autopilot.execute("mission-1")
    heartbeat = autopilot.guardian("mission-1")
    assert heartbeat["state"] == "OPEN"
    assert heartbeat["break_even_done"] is True
    assert heartbeat["trailing_active"] is True
    assert heartbeat["current_stop"] >= heartbeat["entry_fill_price"]

    stale = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    autopilot.snapshot_provider = lambda: snapshot(180.0, stale)
    frozen = autopilot.guardian("mission-1")
    assert frozen["state"] == "OPEN"
    assert frozen["health"] == "STALE"
    assert len(client.place_calls) == 1

    autopilot.snapshot_provider = lambda: snapshot(180.0)
    closed = autopilot.guardian("mission-1")
    assert closed["state"] == "CLOSED"
    assert len(paper.load(date(2026, 7, 27)).closed_trades) == 1


def test_openalgo_disconnect_freezes_guardian_and_does_not_exit(tmp_path):
    autopilot, _, paper, client = service(tmp_path)
    autopilot.execute("mission-1")
    client.analyzer_on = False
    result = autopilot.guardian("mission-1")
    assert result["state"] == "OPEN"
    assert result["health"] == "DISCONNECTED"
    assert len(client.place_calls) == 1
    assert len(paper.load(date(2026, 7, 27)).open_positions) == 1


def test_structural_invalidation_exits_exactly_once(tmp_path):
    autopilot, _, paper, client = service(tmp_path)
    autopilot.execute("mission-1")
    autopilot.snapshot_provider = lambda: snapshot(205.0, underlying=23899.0)
    result = autopilot.guardian("mission-1")
    assert result["state"] == "CLOSED"
    assert result["exit_reason"] == "STRUCTURAL_INVALIDATION"
    assert len(client.place_calls) == 2
    assert len(paper.load(date(2026, 7, 27)).closed_trades) == 1


def test_active_guardian_blocks_mission_cancellation_until_verified_close(tmp_path):
    autopilot, _, _, _ = service(tmp_path)
    assert autopilot.has_active_execution("mission-1") is False
    autopilot.execute("mission-1")
    assert autopilot.has_active_execution("mission-1") is True
    autopilot.exit("mission-1")
    assert autopilot.has_active_execution("mission-1") is False


def test_partial_fill_requires_reconciliation_and_no_fake_position(tmp_path):
    remote = OpenAlgo()
    autopilot, _, paper, _ = service(tmp_path, openalgo=remote)
    original = remote.place

    def partial(payload):
        response = original(payload)
        remote.statuses["ENTRY-1"]["data"]["filled_quantity"] = 10
        return response

    remote.place = partial
    result = autopilot.execute("mission-1")
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert paper.load(date(2026, 7, 27)).trades_taken == 0


def test_corrupt_guardian_state_fails_closed(tmp_path):
    autopilot, missions, paper, remote = service(tmp_path)
    autopilot.state_path.write_text("{", encoding="utf-8")
    restarted = OraclePaperAutopilot(
        tmp_path / "oracle",
        missions=missions,
        openalgo=remote,
        paper_state=paper,
        snapshot_provider=snapshot,
    )
    with pytest.raises(OracleExecutionUnavailable, match="CORRUPT"):
        restarted.execute("mission-1")


def test_execution_journal_contains_no_credentials_or_synthetic_fills(tmp_path):
    autopilot, _, _, _ = service(tmp_path)
    autopilot.execute("mission-1")
    encoded = json.dumps(autopilot.events.read() + autopilot.journal.read())
    assert "apikey" not in encoded.lower()
    assert "access_token" not in encoded.lower()
    assert "fake" not in encoded.lower()
    assert autopilot.journal.verify()["valid"] is True


def test_api_routes_delegate_without_request_supplied_execution_fields(monkeypatch):
    import app.main as main

    class Routes:
        def execute(self, mission_id):
            return {"mission_id": mission_id, "state": "OPEN"}

        def exit(self, mission_id):
            return {"mission_id": mission_id, "state": "CLOSED"}

        def guardian(self, mission_id):
            return {"mission_id": mission_id, "state": "OPEN"}

        def has_active_execution(self, mission_id):
            return False

    monkeypatch.setattr(main, "oracle_paper_autopilot", Routes())
    assert main.execute_oracle_mission("mission-1")["state"] == "OPEN"
    assert main.exit_oracle_mission("mission-1")["state"] == "CLOSED"
    assert main.oracle_mission_guardian("mission-1")["state"] == "OPEN"
    paths = {route.path for route in main.app.routes}
    assert "/v1/oracle/missions/{mission_id}/paper-execute" in paths
    assert "/v1/oracle/missions/{mission_id}/exit" in paths
    assert "/v1/oracle/missions/{mission_id}/guardian" in paths
