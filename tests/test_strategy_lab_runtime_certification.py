import json
from dataclasses import replace

import pytest

from src.paper_trading.models import ResolvedOptionContract
from src.strategy_lab import StrategyLabService
from src.strategy_lab.strategies.breakout_main import build_deployment_request as breakout_request
from src.strategy_lab.strategies.pullback_master import build_deployment_request as pullback_request


DEPLOYMENTS = (
    ("pullback-master-pine-v5", "PB", "CE", None),
    ("breakout-main-pine-v5", "BO", "CE", None),
    ("PB_NIFTY_CE_1M", "PB", "CE", "1m"),
    ("PB_NIFTY_CE_3M", "PB", "CE", "3m"),
    ("PB_NIFTY_PE_1M", "PB", "PE", "1m"),
    ("PB_NIFTY_PE_3M", "PB", "PE", "3m"),
    ("BO_NIFTY_CE_1M", "BO", "CE", "1m"),
    ("BO_NIFTY_CE_3M", "BO", "CE", "3m"),
    ("BO_NIFTY_PE_1M", "BO", "PE", "1m"),
    ("BO_NIFTY_PE_3M", "BO", "PE", "3m"),
)


class _StatefulAdapter:
    def __init__(self, count=0):
        self.count = count

    def evaluate(self, context):
        self.count += 1
        signal = context.get("test_signal", "WAIT")
        result = {
            "evaluation_id": f"{context['candle_id']}:{self.count}",
            "signal": signal,
            "position_effect": "OPEN" if signal == "BUY" else "CLOSE" if signal == "SELL" else None,
            "side": "LONG",
            "stop": 95.0,
            "target": 120.0,
            "exit_reason": context.get("exit_reason"),
        }
        if signal == "SELL":
            result.update({"contract": "ATM-ROTATED", "exit": 999.0, "execution_price": 999.0})
        return result

    def serialize(self):
        return json.dumps({"count": self.count})

    @classmethod
    def deserialize(cls, payload):
        return cls(json.loads(payload)["count"])


class _Resolver:
    def __init__(self, side):
        self.side = side

    def resolve(self, *_args, **_kwargs):
        return ResolvedOptionContract(
            security_id=f"HELD-{self.side}",
            exchange_segment="NSE_FNO",
            underlying="NIFTY",
            option_type=self.side,
            strike=25_000.0,
            expiry="2026-07-23",
            lot_size=25,
            ltp=100.0,
            top_ask_price=None,
            top_ask_quantity=None,
            top_bid_price=None,
            top_bid_quantity=None,
            instrument_source="TEST_MASTER",
            quote_source="TEST_QUOTE",
        )

    def quote_existing(self, _argus, contract):
        return {"security_id": contract, "ltp": 110.0}


def _request(deployment_id, kind, side, timeframe):
    builder = pullback_request if kind == "PB" else breakout_request
    request = (
        builder()
        if timeframe is None
        else builder(
            deployment_id=deployment_id,
            deployment_name=deployment_id,
            chart_symbol=f"NIFTY_{side}",
            chart_timeframe=timeframe,
            option_type=side,
        )
    )
    return replace(
        request,
        adapter=_StatefulAdapter(),
        option_resolver=_Resolver(side),
        scheduler_interval_seconds=60.0,
    )


def _candle(deployment_id, index, signal, side, *, held_quote=110.0):
    return {
        "candle_id": f"{deployment_id}:{index}",
        "symbol": "NIFTY",
        "timeframe": "1m",
        "timestamp": f"2026-07-16T09:{15 + index:02d}:00+05:30",
        "closed": True,
        "test_signal": signal,
        "exit_reason": "TARGET" if signal == "SELL" else None,
        "argus": {
            "data": {
                "underlying": {"symbol": "NIFTY", "atm_strike": 25_100, "expiry": "2026-07-23"},
                "atm_window": [
                    {side.lower(): {"security_id": f"HELD-{side}", "ltp": held_quote}},
                    {side.lower(): {"security_id": "ATM-ROTATED", "ltp": 999.0}},
                ],
            },
        },
    }


@pytest.mark.parametrize("deployment_id,kind,side,timeframe", DEPLOYMENTS)
@pytest.mark.integration
def test_all_deployments_are_exactly_once_restart_safe_and_exit_the_held_contract(
    tmp_path, deployment_id, kind, side, timeframe
):
    root = str(tmp_path / deployment_id)
    request = _request(deployment_id, kind, side, timeframe)
    first_service = StrategyLabService(root)
    runtime = first_service.deploy(request)

    wait = runtime.tick_once(_candle(deployment_id, 0, "WAIT", side))
    assert wait["decision"]["paper_execution"]["status"] == "NO_ACTION"
    assert runtime.execution.projection()["orders"] == []

    entry = runtime.tick_once(_candle(deployment_id, 1, "BUY", side))
    assert entry["decision"]["paper_execution"]["status"] == "FILLED"
    opened = runtime.execution.projection()
    position = next(row for row in opened["positions"] if row["status"] == "OPEN")
    assert (position["contract"], position["quantity"]) == (f"HELD-{side}", 25)
    assert position["option_contract"]["security_id"] == f"HELD-{side}"
    counts = tuple(len(opened[key]) for key in ("orders", "fills", "positions", "closed_trades"))
    journal_count = len(runtime.workspace.journal.read())

    duplicate = runtime.tick_once(_candle(deployment_id, 1, "BUY", side))
    assert duplicate["reason"] == "CANDLE_ALREADY_PROCESSED"
    unchanged = runtime.execution.projection()
    assert tuple(len(unchanged[key]) for key in ("orders", "fills", "positions", "closed_trades")) == counts
    assert len(runtime.workspace.journal.read()) == journal_count

    first_service.start()
    running = runtime.status()
    assert running["state"] == "RUNNING"
    assert running["scheduler"]["state"] == "RUNNING"
    assert running["scheduler"]["activation_enabled"] is True
    assert running["scheduler"]["thread_alive"] is True
    runtime.workspace.write("runtime", {**runtime.workspace.read("runtime"), "state": "STOPPED"})
    runtime.workspace.write(
        "scheduler_state",
        {**runtime.workspace.read("scheduler_state"), "state": "STOPPED"},
    )
    corrected = runtime.status()
    assert corrected["state"] == "RUNNING"
    assert corrected["scheduler"]["state"] == "RUNNING"

    restarted_service = StrategyLabService(root)
    restarted = restarted_service.deploy(_request(deployment_id, kind, side, timeframe))
    stopped = restarted.status()
    assert stopped["state"] == "STOPPED"
    assert stopped["scheduler"]["state"] == "STOPPED"
    assert stopped["scheduler"]["thread_alive"] is False
    restored = restarted.execution.projection()
    assert len(restored["orders"]) == 1
    assert len(restored["fills"]) == 1
    assert next(row for row in restored["positions"] if row["status"] == "OPEN")["position_id"] == position["position_id"]
    assert restarted.strategy.count == runtime.strategy.count
    assert restarted.tick_once(_candle(deployment_id, 1, "BUY", side))["reason"] == "CANDLE_ALREADY_PROCESSED"

    restarted_service.start()
    exit_result = restarted.tick_once(_candle(deployment_id, 2, "SELL", side))
    assert exit_result["decision"]["paper_execution"]["status"] == "FILLED"
    closed = restarted.execution.projection()
    close_order = closed["orders"][-1]
    close_fill = closed["fills"][-1]
    trade = closed["closed_trades"][-1]
    assert close_order["position_id"] == position["position_id"]
    assert close_order["contract"] == f"HELD-{side}"
    assert close_order["requested_quantity"] == 25
    assert close_order["option_contract"] == position["option_contract"]
    assert close_fill["contract"] == f"HELD-{side}"
    assert close_fill["price"] == 110.0
    assert trade["realized_pnl"] == 250.0
    assert all(row["paper_only"] for row in closed["orders"] + closed["fills"])
    assert closed["live_trading_enabled"] is False
    assert closed["broker_submission"] is False

    restarted_service.stop()
    first_service.stop()


@pytest.mark.integration
def test_position_and_daily_trade_limits_are_isolated_per_deployment(tmp_path):
    service = StrategyLabService(str(tmp_path / "isolated"))
    left = service.deploy(_request("PB_NIFTY_CE_1M", "PB", "CE", "1m"))
    right = service.deploy(_request("BO_NIFTY_CE_1M", "BO", "CE", "1m"))
    assert left.tick_once(_candle("PB_NIFTY_CE_1M", 1, "BUY", "CE"))["decision"]["paper_execution"]["status"] == "FILLED"
    assert right.tick_once(_candle("BO_NIFTY_CE_1M", 1, "BUY", "CE"))["decision"]["paper_execution"]["status"] == "FILLED"
    assert len(left.execution.projection()["positions"]) == 1
    assert len(right.execution.projection()["positions"]) == 1
