import ast
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api.v2_integration import V2DashboardIntegration
from src.oracle.mission import (
    MissionConflictError,
    MissionEvaluationUnavailableError,
    MissionPlanRequest,
    MissionPlanUnavailableError,
    MissionValidationError,
    OracleMissionService,
)
from src.oracle.trade_planner import OracleTradePlanner, TradePlanError


pytestmark = [pytest.mark.unit, pytest.mark.safety]
NOW = datetime(2026, 7, 26, 8, 37, 28, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


def snapshot() -> dict:
    return {
        "api_version": "2.0",
        "trace_id": "snapshot-one",
        "symbol": "NIFTY",
        "generated_at": NOW.isoformat(),
        "polling": {"snapshot_status": "FRESH"},
        "feeds": {
            "oracle": {
                "data": {
                    "market_data_as_of": (
                        NOW - timedelta(seconds=1)
                    ).isoformat(),
                    "data_status": "LIVE",
                    "regime": "TRENDING",
                    "input_features": {
                        "price_trend": "BULLISH",
                        "timeframe_bias": "BULLISH",
                    },
                },
                "meta": {"calculation_timestamp": NOW.isoformat()},
            },
            "argus": {
                "data": {
                    "data": {
                        "underlying": {
                            "segment": "IDX_I",
                            "ltp": 24000.0,
                        },
                        "tactical_edge": {
                            "freshness": "LIVE",
                            "option_chain_source_timestamp": NOW.isoformat(),
                            "decision": {
                                "market_direction": "CALL",
                                "invalidation_level": 23990.0,
                                "all_candidate_ranks": [
                                    {
                                        "rank": 1,
                                        "side": "CE",
                                        "security_id": "63935",
                                        "status": "CANDIDATE",
                                        "rejection_reason": None,
                                        "bid": 100.0,
                                        "ask": 100.2,
                                        "premium": 100.0,
                                        "delta": 0.5,
                                        "volume": 100000,
                                        "spread_abs": 0.2,
                                        "spread_pct": 0.2,
                                    }
                                ],
                            },
                            "iv_intelligence": {
                                "status": "AVAILABLE",
                                "direction": "STABLE",
                            },
                        },
                    }
                }
            },
            "strategy_lab": {
                "data": {
                    "execution": {
                        "nifty_vob": {
                            "strongest_confluence": {
                                "bullish": {
                                    "side": "BULLISH",
                                    "tier": "STRONG",
                                }
                            },
                            "source_1m_sync": {
                                "runtime_status": "LIVE",
                                "backlog_count": 0,
                            },
                        },
                        "options_structure": {
                            "status": "LIVE",
                            "source_freshness": "LIVE",
                            "duel": {"state": "CLEAR CALL ADVANTAGE"},
                            "contracts": {
                                "CE": {
                                    "premium": 100.0,
                                    "contract": {
                                        "exchange_segment": "NSE_FNO",
                                        "option_type": "CE",
                                        "security_id": "63935",
                                        "underlying": "NIFTY",
                                        "expiry": "2026-07-28",
                                        "lot_size": 65,
                                        "strike": 23900.0,
                                        "trading_symbol": "NIFTY 28 JUL 23900 CE",
                                    }
                                },
                                "PE": {
                                    "premium": 100.0,
                                    "contract": {
                                        "exchange_segment": "NSE_FNO",
                                        "option_type": "PE",
                                        "security_id": "63944",
                                        "underlying": "NIFTY",
                                        "expiry": "2026-07-28",
                                        "lot_size": 65,
                                        "strike": 24100.0,
                                        "trading_symbol": "NIFTY 28 JUL 24100 PE",
                                    }
                                },
                            },
                        },
                    }
                }
            },
            "risk_status": {
                "data": {
                    "risk_state_available": True,
                    "kill_switch_active": False,
                    "limits": {
                        "max_consecutive_losses": 2,
                        "max_daily_loss": 1000.0,
                        "max_market_data_age_seconds": 10.0,
                        "max_open_positions": 1,
                        "max_position_quantity": 100,
                        "max_risk_per_trade": 500.0,
                        "max_trades_per_day": 3,
                    },
                }
            },
            "paper_status": {
                "data": {
                    "state_health": "HEALTHY",
                    "cash_balance": 100000.0,
                    "consecutive_losses": 0,
                    "open_position_count": 0,
                    "total_daily_pnl": 0.0,
                    "trades_taken_today": 0,
                }
            },
        },
    }


def service(tmp_path, clock=None):
    return OracleMissionService(
        tmp_path / "oracle_missions",
        now_provider=clock or Clock(),
        id_provider=lambda: "mission-evaluate",
    )


def active(missions):
    return missions.start(
        idempotency_key="evaluate-one",
        instrument_scope="NIFTY",
        timeout_seconds=60,
    )


def evaluation_events(missions):
    return [
        row
        for row in missions.events.read()
        if row["event_type"] == "MISSION_EVALUATED"
    ]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluated_mission(tmp_path, supplied=None, clock=None):
    missions = service(tmp_path, clock)
    value = supplied or snapshot()
    mission = missions.start(
        idempotency_key="evaluate-one",
        instrument_scope=value["symbol"],
        timeout_seconds=60,
    )
    missions.evaluate(mission["mission_id"], value)
    return missions, mission, value


def put_snapshot():
    value = snapshot()
    oracle = value["feeds"]["oracle"]["data"]
    oracle["regime"] = "TRENDING"
    oracle["input_features"].update(
        {"price_trend": "BEARISH", "timeframe_bias": "BEARISH"}
    )
    value["feeds"]["strategy_lab"]["data"]["execution"]["nifty_vob"][
        "strongest_confluence"
    ] = {"bearish": {"side": "BEARISH", "tier": "STRONG"}}
    ose = value["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ]
    ose["duel"]["state"] = "CLEAR PUT ADVANTAGE"
    tactical = value["feeds"]["argus"]["data"]["data"]["tactical_edge"]
    tactical["decision"]["market_direction"] = "PUT"
    tactical["decision"]["invalidation_level"] = 24010.0
    tactical["decision"]["all_candidate_ranks"][0].update(
        {
            "side": "PE",
            "security_id": "63944",
            "delta": -0.5,
        }
    )
    return value


def equity_snapshot():
    value = snapshot()
    value["symbol"] = "RELIANCE"
    value["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ] = {}
    value["feeds"]["argus"]["data"]["data"]["underlying"] = {
        "segment": "NSE_EQ",
        "security_id": "2885",
        "trading_symbol": "RELIANCE",
        "lot_size": 1,
        "ltp": 3000.0,
        "top_bid_price": 2999.5,
        "top_ask_price": 3000.0,
        "fetched_at": NOW.isoformat(),
    }
    value["feeds"]["argus"]["data"]["data"]["tactical_edge"]["decision"][
        "invalidation_level"
    ] = 2980.0
    return value


def test_active_mission_persists_qualified_outcome(tmp_path):
    missions = service(tmp_path)
    mission = active(missions)

    result = missions.evaluate(mission["mission_id"], snapshot())

    assert result["decision"] == "CALL"
    assert result["probability"] is None
    assert result["contract"] is None
    assert result["entry"] is None
    assert result["stop_loss"] is None
    assert result["targets"] is None
    assert result["quantity"] is None
    assert result["execution_allowed"] is False
    persisted = missions.get(mission["mission_id"])
    assert persisted["status"] == "ACTIVE"
    assert persisted["outcome"] == "QUALIFIED"
    assert persisted["decision"] == "CALL"
    assert evaluation_events(missions)[0]["payload"]["evaluation"][
        "gate_result"
    ] == result


def test_same_snapshot_is_idempotent_and_changed_snapshot_appends(tmp_path):
    missions = service(tmp_path)
    mission = active(missions)
    supplied = snapshot()

    first = missions.evaluate(mission["mission_id"], supplied)
    duplicate = missions.evaluate(mission["mission_id"], copy.deepcopy(supplied))
    changed = copy.deepcopy(supplied)
    changed["trace_id"] = "snapshot-two"
    second = missions.evaluate(mission["mission_id"], changed)

    assert duplicate == first
    assert second == first
    assert len(evaluation_events(missions)) == 2
    assert len(
        {
            row["payload"]["evaluation"]["snapshot_hash"]
            for row in evaluation_events(missions)
        }
    ) == 2


def test_idempotency_and_evaluation_events_survive_restart(tmp_path):
    root = tmp_path / "oracle_missions"
    first = OracleMissionService(
        root,
        now_provider=Clock(),
        id_provider=lambda: "mission-restart",
    )
    mission = active(first)
    expected = first.evaluate(mission["mission_id"], snapshot())

    restarted = OracleMissionService(root, now_provider=Clock())
    actual = restarted.evaluate(mission["mission_id"], snapshot())

    assert actual == expected
    assert len(evaluation_events(restarted)) == 1
    persisted = restarted.get(mission["mission_id"])
    assert persisted["status"] == "ACTIVE"
    assert persisted["outcome"] == "QUALIFIED"
    assert persisted["decision"] == "CALL"


def test_scope_terminal_and_expired_missions_are_blocked(tmp_path):
    clock = Clock()
    missions = service(tmp_path, clock)
    mission = active(missions)
    wrong = snapshot()
    wrong["symbol"] = "BANKNIFTY"

    with pytest.raises(MissionValidationError, match="scope"):
        missions.evaluate(mission["mission_id"], wrong)
    missions.cancel(mission["mission_id"])
    with pytest.raises(MissionConflictError, match="not active"):
        missions.evaluate(mission["mission_id"], snapshot())

    expiring = OracleMissionService(
        tmp_path / "expiring",
        now_provider=clock,
        id_provider=lambda: "mission-expired",
    )
    expired = active(expiring)
    clock.value += timedelta(seconds=61)
    with pytest.raises(MissionConflictError, match="not active"):
        expiring.evaluate(expired["mission_id"], snapshot())


def test_closed_market_stale_snapshot_persists_truthful_no_trade(tmp_path):
    missions = service(tmp_path)
    mission = active(missions)
    stale = snapshot()
    stale["polling"]["snapshot_status"] = "STALE"
    stale["feeds"]["oracle"]["data"]["reason_codes"] = ["MARKET_CLOSED"]

    result = missions.evaluate(mission["mission_id"], stale)

    assert result["decision"] == "NO_TRADE"
    assert "STALE_SNAPSHOT" in result["rejection_reasons"]
    assert "MARKET_CLOSED" in result["unavailable_reasons"]
    persisted = missions.get(mission["mission_id"])
    assert persisted["status"] == "COMPLETED"
    assert persisted["outcome"] == "NO_TRADE"
    assert persisted["decision"] == "NO_TRADE"
    assert persisted["terminal_reason"] == "GATE_NO_TRADE"
    assert persisted["unavailable_reasons"] == result["unavailable_reasons"]
    assert missions.active() is None


def test_malformed_snapshot_terminalizes_failed_and_keeps_reason(tmp_path):
    missions = OracleMissionService(
        tmp_path / "oracle_missions",
        now_provider=Clock(),
        id_provider=lambda: "mission-malformed",
    )
    mission = active(missions)
    malformed = snapshot()
    del malformed["feeds"]["oracle"]
    with pytest.raises(MissionEvaluationUnavailableError) as captured:
        missions.evaluate(mission["mission_id"], malformed)
    failed = missions.get(mission["mission_id"])
    assert "feeds.oracle is missing or malformed" in str(captured.value)
    assert failed["status"] == "FAILED"
    assert failed["outcome"] == "NO_TRADE"
    assert failed["terminal_reason"] == "SNAPSHOT_EVALUATION_UNAVAILABLE"
    assert "feeds.oracle is missing or malformed" in failed["unavailable_reasons"]
    assert missions.active() is None
    assert len(evaluation_events(missions)) == 0


def test_cached_accessor_is_read_only_and_never_builds_projection():
    integration = V2DashboardIntegration(snapshot=lambda: None)
    supplied = snapshot()
    integration._last_projection = supplied
    integration._last_projection_at = 0.0

    cached = integration.cached_dashboard()
    cached["symbol"] = "MUTATED"

    assert supplied["symbol"] == "NIFTY"
    assert integration._last_projection["symbol"] == "NIFTY"
    assert integration.refresh_count == 0


def test_api_route_uses_cache_only_and_accepts_no_snapshot_body(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CITADEL_STATE_ROOT", str(tmp_path / "runtime"))
    from app import main

    missions = service(tmp_path)
    mission = active(missions)

    class Cache:
        calls = 0

        def cached_dashboard(self):
            self.calls += 1
            return snapshot()

    cache = Cache()
    monkeypatch.setattr(main, "oracle_mission_service", missions)
    monkeypatch.setattr(main, "v2_integration", cache)

    result = main.evaluate_oracle_mission(mission["mission_id"])

    assert result["decision"] == "CALL"
    assert cache.calls == 1
    assert tuple(inspect.signature(main.evaluate_oracle_mission).parameters) == (
        "mission_id",
    )
    assert any(
        route.path == "/v1/oracle/missions/{mission_id}/evaluate"
        and route.methods == {"POST"}
        for route in main.app.routes
    )


def test_api_cache_unavailable_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("CITADEL_STATE_ROOT", str(tmp_path / "runtime"))
    from app import main

    order_path = tmp_path / "order_ledger.jsonl"
    fill_path = tmp_path / "fill_ledger.jsonl"
    order_path.write_text('{"order":"existing"}\n', encoding="utf-8")
    fill_path.write_text('{"fill":"existing"}\n', encoding="utf-8")
    before = (digest(order_path), digest(fill_path))
    mission_ids = iter(("mission-cache-failed", "mission-after-failure"))
    missions = OracleMissionService(
        tmp_path / "oracle_missions",
        now_provider=Clock(),
        id_provider=lambda: next(mission_ids),
    )
    mission = active(missions)

    class MissingCache:
        @staticmethod
        def cached_dashboard():
            raise RuntimeError("V2_PROJECTION_NOT_READY")

    monkeypatch.setattr(main, "oracle_mission_service", missions)
    monkeypatch.setattr(main, "v2_integration", MissingCache())
    with pytest.raises(HTTPException) as captured:
        main.evaluate_oracle_mission(mission["mission_id"])

    assert captured.value.status_code == 503
    assert (
        captured.value.detail["code"]
        == "ORACLE_MISSION_EVALUATION_UNAVAILABLE"
    )
    assert captured.value.detail["reasons"] == ["V2_SNAPSHOT_UNAVAILABLE"]
    failed = missions.get(mission["mission_id"])
    assert failed["status"] == "FAILED"
    assert failed["outcome"] == "NO_TRADE"
    assert failed["decision"] == "NO_TRADE"
    assert failed["terminal_reason"] == "V2_SNAPSHOT_UNAVAILABLE"
    assert failed["unavailable_reasons"] == ["V2_SNAPSHOT_UNAVAILABLE"]
    assert missions.active() is None
    second = missions.start(
        idempotency_key="after-cache-failure",
        instrument_scope="NIFTY",
        mode="ADVISE",
        max_trades=1,
        timeout_seconds=60,
    )
    assert second["mission_id"] == "mission-after-failure"
    assert second["status"] == "ACTIVE"
    assert (digest(order_path), digest(fill_path)) == before


def test_mission_evaluation_has_no_forbidden_runtime_imports():
    tree = ast.parse(
        Path("src/oracle/mission.py").read_text(encoding="utf-8")
    )
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        name.startswith(
            (
                "src.api.argus",
                "src.execution",
                "src.order",
                "src.paper_trading",
                "src.risk",
                "src.strategy_lab.service",
            )
        )
        for name in imports
    )


@pytest.mark.parametrize(
    ("supplied", "decision", "option_type", "security_id"),
    [
        (snapshot(), "CALL", "CE", "63935"),
        (put_snapshot(), "PUT", "PE", "63944"),
    ],
)
def test_call_and_put_plans_lock_exact_dynamic_contract(
    tmp_path, supplied, decision, option_type, security_id
):
    missions, mission, value = evaluated_mission(tmp_path, supplied)

    plan = missions.plan(mission["mission_id"], value)

    assert plan["instrument_type"] == "OPTION"
    assert plan["option_type"] == option_type
    assert plan["security_id"] == security_id
    assert plan["expiry"] == "2026-07-28"
    assert plan["dte"] == 2
    assert plan["lot_size"] == 65
    assert plan["approved_quantity"] == 65
    assert plan["contract_locked"] is True
    assert plan["execution_allowed"] is False
    assert plan["broker_submission"] is False
    assert plan["rejection_reasons"] == []
    assert plan["evaluation_snapshot_hash"] == missions.events.read()[-2][
        "payload"
    ]["evaluation"]["snapshot_hash"]
    assert decision == missions.events.read()[-2]["payload"]["evaluation"][
        "gate_result"
    ]["decision"]


def test_equity_uses_separate_policy_and_truthful_null_option_fields(tmp_path):
    supplied = equity_snapshot()
    missions, mission, value = evaluated_mission(tmp_path, supplied)

    plan = missions.plan(mission["mission_id"], value)

    assert plan["instrument_type"] == "EQUITY"
    assert plan["policy"] == "EQUITY"
    assert plan["security_id"] == "2885"
    assert plan["expiry"] is None
    assert plan["dte"] is None
    assert plan["strike"] is None
    assert plan["option_type"] is None
    assert plan["mapped_premium_sl"] is None


def test_structural_stop_is_mapped_then_noise_adjusted_never_averaged(tmp_path):
    missions, mission, value = evaluated_mission(tmp_path)

    plan = missions.plan(mission["mission_id"], value)

    assert plan["structural_invalidation"] == 23990.0
    assert plan["mapped_premium_sl"] == 95.0
    assert plan["noise_allowance"] == 0.2
    assert plan["final_sl"] == 94.8
    assert plan["risk_cap_sl"] != plan["final_sl"]
    assert "NO_AVERAGING" in plan["stop_selection_rule"]
    assert plan["risk_per_lot"] == 351.0
    assert plan["total_maximum_risk"] == 351.0
    assert plan["target_1"] == 105.6
    assert plan["target_2"] == 111.0
    assert plan["reward_risk"] == 2.0


def test_no_trade_missing_stale_or_illiquid_quote_cannot_create_plan(tmp_path):
    cases = []
    no_trade = snapshot()
    no_trade["polling"]["snapshot_status"] = "STALE"
    cases.append((no_trade, "GATE_NO_TRADE"))

    missing = snapshot()
    del missing["feeds"]["argus"]["data"]["data"]["tactical_edge"][
        "decision"
    ]["all_candidate_ranks"][0]["ask"]
    cases.append((missing, "CONTRACT_ASK_UNAVAILABLE"))

    wide = snapshot()
    wide["feeds"]["argus"]["data"]["data"]["tactical_edge"]["decision"][
        "all_candidate_ranks"
    ][0]["spread_pct"] = 2.0
    cases.append((wide, "SPREAD_CAP_EXCEEDED"))

    stale_quote = snapshot()
    stale_quote["feeds"]["argus"]["data"]["data"]["tactical_edge"][
        "option_chain_source_timestamp"
    ] = (NOW - timedelta(seconds=11)).isoformat()
    cases.append((stale_quote, "QUOTE_STALE"))

    for index, (supplied, reason) in enumerate(cases):
        root = tmp_path / str(index)
        missions, mission, value = evaluated_mission(root, supplied)
        with pytest.raises(MissionPlanUnavailableError) as captured:
            missions.plan(mission["mission_id"], value)
        assert reason in captured.value.reasons
        assert all(
            row["event_type"] != "PLAN_CREATED"
            for row in missions.events.read()
        )


def test_risk_budget_quantity_boundaries_and_user_cannot_exceed_maximum(tmp_path):
    missions, mission, value = evaluated_mission(tmp_path / "approved")
    plan = missions.plan(
        mission["mission_id"], value, requested_quantity=130
    )
    assert plan["approved_quantity"] == plan["maximum_approved_quantity"] == 65

    invalid, invalid_mission, invalid_value = evaluated_mission(
        tmp_path / "invalid"
    )
    with pytest.raises(MissionPlanUnavailableError) as captured:
        invalid.plan(
            invalid_mission["mission_id"],
            invalid_value,
            requested_quantity=0,
        )
    assert "REQUESTED_QUANTITY_INVALID" in captured.value.reasons

    insufficient_value = snapshot()
    insufficient_value["feeds"]["risk_status"]["data"]["limits"][
        "max_risk_per_trade"
    ] = 300.0
    insufficient, insufficient_mission, insufficient_value = evaluated_mission(
        tmp_path / "insufficient", insufficient_value
    )
    with pytest.raises(MissionPlanUnavailableError) as captured:
        insufficient.plan(
            insufficient_mission["mission_id"], insufficient_value
        )
    assert "ZERO_APPROVED_QUANTITY" in captured.value.reasons


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda value: value["feeds"]["risk_status"]["data"].update(
                kill_switch_active=True
            ),
            "KILL_SWITCH_BLOCKED",
        ),
        (
            lambda value: value["feeds"]["paper_status"]["data"].update(
                total_daily_pnl=-1000.0
            ),
            "DAILY_LOSS_LIMIT_REACHED",
        ),
        (
            lambda value: value["feeds"]["paper_status"]["data"].update(
                consecutive_losses=2
            ),
            "CONSECUTIVE_LOSS_STOP",
        ),
        (
            lambda value: value["feeds"]["paper_status"]["data"].update(
                open_position_count=1
            ),
            "POSITION_ALREADY_OPEN",
        ),
        (
            lambda value: value["feeds"]["paper_status"]["data"].update(
                trades_taken_today=3
            ),
            "MAX_TRADES_PER_DAY_REACHED",
        ),
    ],
)
def test_risk_governor_blocks_authoritative_safety_states(
    tmp_path, change, reason
):
    supplied = snapshot()
    healthy = service(tmp_path / "healthy")
    healthy_mission = active(healthy)
    gate_result = healthy.evaluate(healthy_mission["mission_id"], supplied)
    change(supplied)
    with pytest.raises(TradePlanError) as captured:
        OracleTradePlanner.create(
            mission_id=healthy_mission["mission_id"],
            evaluation={
                "snapshot_hash": "a" * 64,
                "gate_result": gate_result,
            },
            snapshot=supplied,
            reserved_risk=0.0,
            reserved_capital=0.0,
            now=NOW,
        )
    assert reason in captured.value.reasons


def test_entry_cutoff_blocks_plan(tmp_path):
    clock = Clock()
    clock.value = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)
    supplied = snapshot()
    supplied["feeds"]["oracle"]["meta"][
        "calculation_timestamp"
    ] = clock.value.isoformat()
    supplied["feeds"]["oracle"]["data"][
        "market_data_as_of"
    ] = (clock.value - timedelta(seconds=1)).isoformat()
    missions, mission, value = evaluated_mission(tmp_path, supplied, clock)

    with pytest.raises(MissionPlanUnavailableError) as captured:
        missions.plan(mission["mission_id"], value)
    assert "ENTRY_CUTOFF_REACHED" in captured.value.reasons


def test_plan_is_idempotent_concurrent_reserved_and_restart_safe(tmp_path):
    root = tmp_path / "oracle_missions"
    missions = OracleMissionService(
        root,
        now_provider=Clock(),
        id_provider=lambda: "mission-plan-restart",
    )
    mission = active(missions)
    supplied = snapshot()
    missions.evaluate(mission["mission_id"], supplied)

    with ThreadPoolExecutor(max_workers=8) as pool:
        plans = list(
            pool.map(
                lambda _: missions.plan(mission["mission_id"], supplied),
                range(20),
            )
        )

    assert all(plan == plans[0] for plan in plans)
    assert sum(
        row["event_type"] == "PLAN_CREATED"
        for row in missions.events.read()
    ) == 1
    assert missions.reservation_status() == {
        "reserved_risk": 351.0,
        "reserved_capital": 6513.0,
        "active_plan_count": 1,
        "execution_allowed": False,
    }

    restarted = OracleMissionService(root, now_provider=Clock())
    assert restarted.plan(mission["mission_id"], supplied) == plans[0]
    assert restarted.reservation_status() == missions.reservation_status()


def test_cancel_and_expiry_release_reservation_without_ledger_mutation(tmp_path):
    order = tmp_path / "orders.jsonl"
    fill = tmp_path / "fills.jsonl"
    order.write_text('{"order":"existing"}\n', encoding="utf-8")
    fill.write_text('{"fill":"existing"}\n', encoding="utf-8")
    before = (digest(order), digest(fill))

    missions, mission, value = evaluated_mission(tmp_path / "cancel")
    missions.plan(mission["mission_id"], value)
    missions.cancel(mission["mission_id"])
    assert missions.reservation_status()["active_plan_count"] == 0

    clock = Clock()
    expiring, expiring_mission, expiring_value = evaluated_mission(
        tmp_path / "expire", clock=clock
    )
    expiring.plan(expiring_mission["mission_id"], expiring_value)
    clock.value += timedelta(seconds=61)
    assert expiring.active() is None
    assert expiring.reservation_status()["active_plan_count"] == 0
    assert (digest(order), digest(fill)) == before


def test_plan_api_uses_cache_and_rejects_snapshot_body(tmp_path, monkeypatch):
    monkeypatch.setenv("CITADEL_STATE_ROOT", str(tmp_path / "runtime"))
    from app import main

    missions, mission, supplied = evaluated_mission(tmp_path)

    class Cache:
        @staticmethod
        def cached_dashboard():
            return supplied

    monkeypatch.setattr(main, "oracle_mission_service", missions)
    monkeypatch.setattr(main, "v2_integration", Cache())
    plan = main.plan_oracle_mission(
        mission["mission_id"], MissionPlanRequest()
    )

    assert plan["status"] == "APPROVED"
    with pytest.raises(Exception):
        MissionPlanRequest(snapshot=supplied)
    assert any(
        route.path == "/v1/oracle/missions/{mission_id}/plan"
        and route.methods == {"POST"}
        for route in main.app.routes
    )
