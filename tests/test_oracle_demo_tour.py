from datetime import datetime, timezone

import pytest

from src.oracle.mission import MissionMode, OracleMissionService
from src.oracle.trade_planner import OracleTradePlanner, TradePlanError


NOW = datetime(2026, 7, 27, 5, 0, tzinfo=timezone.utc)


def _patch_planner(monkeypatch):
    monkeypatch.setattr(OracleTradePlanner, "_require_fresh", lambda snapshot: None)
    monkeypatch.setattr(
        OracleTradePlanner,
        "_risk_context",
        lambda snapshot: (
            {"risk_state_available": True, "kill_switch_active": False},
            {"max_market_data_age_seconds": 30},
            {"state_health": "HEALTHY", "open_position_count": 0},
        ),
    )
    monkeypatch.setattr(
        OracleTradePlanner,
        "_option_instrument",
        lambda snapshot, decision, today: {
            "instrument_type": "OPTION",
            "underlying": "NIFTY",
            "contract": f"NIFTY28JUL2624000{'CE' if decision == 'CALL' else 'PE'}",
            "security_id": "1001" if decision == "CALL" else "1002",
            "expiry": "2026-07-28",
            "dte": 1,
            "strike": 24000.0,
            "option_type": "CE" if decision == "CALL" else "PE",
            "lot_size": 65,
            "ltp": 200.0,
            "bid": 199.5,
            "ask": 200.0,
            "spread": 0.5,
            "delta": 0.5 if decision == "CALL" else -0.5,
            "quote_timestamp": NOW.isoformat(),
        },
    )
    monkeypatch.setattr(OracleTradePlanner, "_validate_quote_age", lambda *args: None)
    monkeypatch.setattr(
        OracleTradePlanner,
        "_structural_risk",
        lambda **kwargs: {
            "maximum_entry": 200.0,
            "structural_invalidation": 23950.0,
            "mapped_premium_stop": 190.0,
            "noise_allowance": 0.5,
            "final_stop": 189.5,
        },
    )


def test_demo_mode_is_paper_only_and_one_trade(tmp_path):
    service = OracleMissionService(tmp_path, now_provider=lambda: NOW)
    mission = service.start(
        idempotency_key="tour-1",
        instrument_scope="NIFTY",
        mode=MissionMode.DEMO_PAPER.value,
    )
    assert mission["mode"] == "DEMO_PAPER"
    assert mission["max_trades"] == 1
    assert mission["execution_allowed"] is False
    assert mission["safety"]["live_trading_enabled"] is False
    assert mission["safety"]["broker_submission"] is False


@pytest.mark.parametrize(("side", "lots"), [("CE", 4), ("PE", 4), ("CE", 5), ("PE", 5)])
def test_demo_plan_quantity_and_statistics_exclusion(monkeypatch, side, lots):
    _patch_planner(monkeypatch)
    plan = OracleTradePlanner.create_demo(
        mission_id=f"demo-{side}-{lots}",
        snapshot={},
        option_type=side,
        lots=lots,
        now=NOW,
    )
    assert plan["approved_quantity"] == 65 * lots
    assert plan["approved_lots"] == lots
    assert plan["execution_origin"] == "DEMO_PAPER"
    assert plan["directional_edge"] == "NOT_CLAIMED"
    assert plan["capital_reserved"] == 0
    assert plan["exclude_from_strategy_stats"] is True
    assert plan["exclude_from_backtests"] is True
    assert plan["exclude_from_performance_metrics"] is True
    assert plan["live_trading_enabled"] is False
    assert plan["broker_submission"] is False


def test_demo_six_lots_rejected_and_production_limit_unchanged(monkeypatch):
    _patch_planner(monkeypatch)
    with pytest.raises(TradePlanError, match="DEMO_LOTS_INVALID"):
        OracleTradePlanner.create_demo(
            mission_id="too-many",
            snapshot={},
            option_type="CE",
            lots=6,
            now=NOW,
        )
    assert OracleTradePlanner.OPTION_MAX_LOTS == 1
    assert OracleTradePlanner.DEMO_MAX_LOTS == 5
