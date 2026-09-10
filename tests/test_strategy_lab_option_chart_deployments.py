from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.strategy_lab import StrategyLabService
from src.strategy_lab.completed_candle import CompletedCandleContextProvider
from src.strategy_lab.option_charts import OptionChartCandleFeed
from src.strategy_lab.state_truth import HistoryRequirement
from src.strategy_lab.option_deployments import (
    OPTION_CHART_DEPLOYMENTS,
    build_option_chart_deployments,
)
from src.strategy_lab.strategies.breakout_main.adapters import BreakoutMainSignalEngine
from src.strategy_lab.strategies.breakout_main.deployment import build_deployment_request as base_breakout
from src.strategy_lab.strategies.pullback_master.adapter import PullbackMasterNativeAdapter
from src.strategy_lab.strategies.pullback_master.deployment import build_deployment_request as base_pullback


class _Dhan:
    def __init__(self):
        self.calls = []

    def get_intraday_candles(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "candles": []}


class _Master:
    def resolve(self, **kwargs):
        return {
            "security_id": str(kwargs["security_id"]),
            "exchange_segment": "NSE_FNO",
            "lot_size": 25,
            "source": "DHAN_INSTRUMENT_MASTER",
        }


def _snapshot(timestamp, ce, pe, volume):
    return {
        "status": "available",
        "freshness": "fresh",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "atm_strike": 24_000,
                "expiry": "2026-07-16",
                "trading_date": "2026-07-15",
                "fetched_at": timestamp,
            },
            "atm_window": [{
                "strike": 24_000,
                "ce": {"security_id": "CE-24000", "ltp": ce, "volume": volume},
                "pe": {"security_id": "PE-24000", "ltp": pe, "volume": volume},
            }],
        },
    }


def _populated_feed():
    dhan = _Dhan()
    feed = OptionChartCandleFeed(dhan=dhan, instrument_master=_Master())
    base = datetime.fromisoformat("2026-07-15T09:15:05+05:30")
    for offset, (ce, pe) in enumerate(((100, 200), (101, 199), (99, 201), (102, 198))):
        feed.ingest(_snapshot((base + timedelta(minutes=offset)).isoformat(), ce, pe, 100 + offset * 10))
    return feed, dhan, base


@pytest.mark.unit
def test_option_feed_fans_out_one_argus_stream_into_completed_1m_and_3m_candles():
    feed, dhan, base = _populated_feed()
    duplicate = _snapshot((base + timedelta(minutes=3)).isoformat(), 102, 198, 130)
    feed.ingest(duplicate)

    one_minute = feed.load_cache("CE", "1m")
    three_minute = feed.load_cache("CE", "3m")
    assert len(dhan.calls) == 2
    assert all(call["instrument"] == "OPTIDX" for call in dhan.calls)
    assert len(one_minute) == 3
    assert len(three_minute) == 1
    assert [row["close"] for row in one_minute] == [100.0, 101.0, 99.0]
    assert (three_minute[0]["open"], three_minute[0]["high"], three_minute[0]["low"], three_minute[0]["close"]) == (
        100.0, 101.0, 99.0, 99.0,
    )
    assert three_minute[0]["contract"] == "CE-24000"
    assert three_minute[0]["lot_size"] == 25
    assert feed.status()["additional_polling"] is False
    assert feed.status()["websocket_count"] == 0


@pytest.mark.unit
def test_stale_argus_snapshot_restores_persisted_completed_candles(tmp_path):
    feed = OptionChartCandleFeed(
        dhan=_Dhan(),
        instrument_master=_Master(),
        canonical_store_root=str(tmp_path),
    )
    snapshot = _snapshot("2026-07-15T15:30:00+05:30", 100, 200, 100)
    for side, security_id in (("CE", "CE-24000"), ("PE", "PE-24000")):
        contract = {
            "security_id": security_id,
            "exchange_segment": "NSE_FNO",
            "underlying": "NIFTY",
            "option_type": side,
            "strike": 24_000,
            "expiry": "2026-07-16",
            "lot_size": 25,
            "instrument_source": "DHAN_INSTRUMENT_MASTER",
            "quote_source": "DHAN_OPTION_CHAIN",
        }
        feed._store(contract, "1m").merge([{
            "symbol": f"NIFTY_{side}",
            "underlying": "NIFTY",
            "timeframe": "1m",
            "timestamp": "2026-07-15T15:28:00+05:30",
            "candle_closed_at": "2026-07-15T15:29:00+05:30",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 65.0,
            "source": "DHAN_DATA_API",
            "received_at": "2026-07-15T15:29:01+05:30",
            "closed": True,
            "is_closed": True,
            "contract": security_id,
            "chart_contract": contract,
            "lot_size": 25,
        }], fetch_timestamp="2026-07-15T15:29:01+05:30")

    snapshot["status"] = "stale"
    snapshot["freshness"] = "stale"
    feed.ingest(snapshot)

    assert len(feed.load_cache("CE", "1m")) == 1
    assert len(feed.load_cache("PE", "1m")) == 1
    assert feed.status()["last_error"] is None


@pytest.mark.unit
def test_stale_context_preserves_loaded_history_but_blocks_live_readiness():
    context = CompletedCandleContextProvider._unavailable(
        "CANDLE_STALE",
        timestamp="2026-07-24T15:29:00+05:30",
        readiness={
            "DATA_READY": True,
            "loaded_bars": 12000,
            "latest_completed_candle": "2026-07-24T15:29:00+05:30",
        },
    )

    assert context["data_readiness"]["DATA_READY"] is False
    assert context["data_readiness"]["not_ready_reason"] == "CANDLE_STALE"
    assert context["data_readiness"]["loaded_bars"] == 12000


@pytest.mark.unit
def test_locked_contract_outside_atm_window_uses_exact_read_only_quote():
    class QuoteDhan(_Dhan):
        def get_quote(self, segment, security_id):
            assert segment == "NSE_FNO"
            assert security_id == "LOCKED-CE"
            return {"ltp": 123.45, "raw": {"volume": 500}}

    feed = OptionChartCandleFeed(dhan=QuoteDhan(), instrument_master=_Master())
    state = feed._states["CE"]
    state.update({
        "contract": {
            "security_id": "LOCKED-CE",
            "exchange_segment": "NSE_FNO",
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 23_900,
            "expiry": "2026-07-16",
            "lot_size": 65,
        },
        "trading_date": "2026-07-15",
    })

    feed.ingest(_snapshot("2026-07-15T09:15:05+05:30", 100, 200, 100))

    assert feed._states["CE"]["contract"]["security_id"] == "LOCKED-CE"
    assert feed._states["CE"]["live"]["close"] == 123.45


@pytest.mark.unit
def test_option_context_and_native_adapters_preserve_chart_contract_for_paper_execution():
    feed, _, base = _populated_feed()
    argus = _snapshot((base + timedelta(minutes=3)).isoformat(), 102, 198, 130)
    context = CompletedCandleContextProvider(
        candle_source=feed.source("CE", "3m"),
        argus_provider=lambda: argus,
        clock=lambda: base + timedelta(minutes=3, seconds=1),
    )()

    assert context["symbol"] == "NIFTY_CE"
    assert context["timeframe"] == "3m"
    assert context["contract"] == "CE-24000"
    assert context["option_contract"] == "CE-24000"
    assert context["chart_contract"]["instrument_source"] == "DHAN_INSTRUMENT_MASTER"
    assert context["paper_price"] == 99.0
    assert context["lot_size"] == 25

    for adapter in (PullbackMasterNativeAdapter(), BreakoutMainSignalEngine()):
        result = adapter.evaluate(context)
        assert result["option_contract"]["security_id"] == "CE-24000"
        assert result["lot_size"] == 25
        assert result["paper_only"] is True
        assert result["live_trading_enabled"] is False


@pytest.mark.integration
def test_twelve_option_chart_deployments_are_unique_isolated_and_paper_only(tmp_path):
    feed, _, base = _populated_feed()
    argus = _snapshot((base + timedelta(minutes=3)).isoformat(), 102, 198, 130)
    requests = build_option_chart_deployments(feed=feed, argus_provider=lambda: argus)
    expected = [
        "PB_NIFTY_CE_1M", "PB_NIFTY_CE_3M", "PB_NIFTY_PE_1M", "PB_NIFTY_PE_3M",
        "BO_NIFTY_CE_1M", "BO_NIFTY_CE_3M", "BO_NIFTY_PE_1M", "BO_NIFTY_PE_3M",
        "TC_NIFTY_PE_1M", "TC_NIFTY_PE_3M", "BP_NIFTY_CE_1M", "BP_NIFTY_CE_3M",
    ]
    assert [row[0] for row in OPTION_CHART_DEPLOYMENTS] == expected
    assert [request.metadata.strategy_id for request in requests] == expected
    assert len({id(request.adapter) for request in requests}) == 12
    assert all(request.activation_enabled for request in requests)
    assert all(request.metadata.parameters["runtime_mode"] == "PAPER" for request in requests)

    service = StrategyLabService(str(tmp_path / "lab"))
    runtimes = [service.deploy(request) for request in requests]
    assert len({str(runtime.workspace.root) for runtime in runtimes}) == 12
    assert service.status()["loaded_runtime_count"] == 12
    assert service.status()["paper_only"] is True
    assert service.status()["live_trading_enabled"] is False
    assert service.status()["broker_submission"] is False
    assert all(runtime.execution is not runtimes[0].execution for runtime in runtimes[1:])


@pytest.mark.unit
def test_parameterized_builders_preserve_existing_base_deployment_identity():
    pullback = base_pullback().metadata.to_dict()
    breakout = base_breakout().metadata.to_dict()
    assert "chart_input" not in pullback["parameters"]
    assert "chart_input" not in breakout["parameters"]
    assert pullback["supported_markets"] == ["TRADINGVIEW_CHART_SYMBOL"]
    assert pullback["supported_timeframes"] == ["CHART_TIMEFRAME"]
    assert breakout["supported_markets"] == ["NIFTY"]
    assert breakout["supported_timeframes"] == ["5m"]


def _session_rows(start_date, contract, missing=()):
    rows = []
    day = start_date
    sessions = 0
    missing = set(missing)
    while sessions < 7:
        if day.weekday() < 5:
            start = datetime.combine(day, datetime.min.time(), ZoneInfo("Asia/Kolkata")).replace(hour=9, minute=15)
            for offset in range(375):
                timestamp = start + timedelta(minutes=offset)
                if timestamp.isoformat() in missing:
                    continue
                rows.append({
                    "symbol": "NIFTY_CE", "underlying": "NIFTY", "timeframe": "1m",
                    "timestamp": timestamp.isoformat(), "candle_closed_at": (timestamp + timedelta(minutes=1)).isoformat(),
                    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0,
                    "source": "DHAN_DATA_API", "received_at": (timestamp + timedelta(minutes=1)).isoformat(),
                    "closed": True, "is_closed": True, "contract": contract,
                    "chart_contract": {"security_id": contract, "option_type": "CE", "expiry": "2026-07-21", "lot_size": 65},
                    "lot_size": 65,
                })
            sessions += 1
        day += timedelta(days=1)
    return rows


@pytest.mark.integration
def test_exact_range_reconciliation_restores_1m_and_derived_3m_readiness(tmp_path):
    contract = {"security_id": "57350", "option_type": "CE", "expiry": "2026-07-21", "lot_size": 65}
    gap = "2026-07-17T11:28:00+05:30"
    rows = _session_rows(datetime(2026, 7, 9).date(), "57350", missing={gap})
    provider_row = {
        "time": int(datetime.fromisoformat(gap).timestamp()), "open": 107.15, "high": 107.75,
        "low": 105.7, "close": 107.15, "volume": 196235,
    }

    class GapDhan(_Dhan):
        def get_intraday_candles(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "candles": [provider_row]}

    dhan = GapDhan()
    feed = OptionChartCandleFeed(
        dhan=dhan, instrument_master=_Master(), canonical_store_root=str(tmp_path), max_candles=5000,
    )
    store = feed._store(contract, "1m")
    store.merge(rows, fetch_timestamp="2026-07-17T15:30:00+05:30")
    state = feed._states["CE"]
    state.update({
        "contract": contract, "trading_date": "2026-07-17", "completed_1m": store.load(),
        "readiness": store.readiness(HistoryRequirement.strategy_lab_default("1m"), now=datetime.fromisoformat("2026-07-17T15:30:00+05:30")),
    })
    three_store = feed._store(contract, "3m")
    three_store.merge(feed._aggregate_three_minute(state["completed_1m"]), fetch_timestamp="2026-07-17T15:30:00+05:30")
    assert state["readiness"]["not_ready_reason"] == "CANDLE_GAP"
    assert three_store.readiness(HistoryRequirement.strategy_lab_default("3m"), now=datetime.fromisoformat("2026-07-17T15:30:00+05:30"))["not_ready_reason"] == "CANDLE_GAP"

    feed._reconcile_missing_history(state, datetime.fromisoformat("2026-07-17T15:30:00+05:30"))
    one = feed.readiness("CE", "1m")
    three = feed.readiness("CE", "3m")

    assert one["DATA_READY"] is True
    assert one["missing_candle_count"] == 0
    assert any(row["timestamp"] == gap and row["classification"] == "FETCH_RANGE_MISSING" and row["repaired"] for row in one["gap_classifications"])
    assert three["DATA_READY"] is True
    assert three["missing_candle_count"] == 0
    assert any(row["classification"] == "MERGE_DROPPED" and row["repaired"] for row in three["gap_classifications"])
    assert dhan.calls[-1]["from_date"] == dhan.calls[-1]["to_date"] == "2026-07-17"


@pytest.mark.unit
def test_provider_missing_interval_remains_truthfully_blocked(tmp_path):
    contract = {"security_id": "57350", "option_type": "CE", "expiry": "2026-07-21", "lot_size": 65}
    gap = "2026-07-17T11:28:00+05:30"
    feed = OptionChartCandleFeed(dhan=_Dhan(), instrument_master=_Master(), canonical_store_root=str(tmp_path))
    store = feed._store(contract, "1m")
    store.merge(_session_rows(datetime(2026, 7, 9).date(), "57350", missing={gap}), fetch_timestamp="2026-07-17T15:30:00+05:30")
    state = feed._states["CE"]
    state.update({"contract": contract, "completed_1m": store.load(), "readiness": store.readiness(HistoryRequirement.strategy_lab_default("1m"), now=datetime.fromisoformat("2026-07-17T15:30:00+05:30"))})

    feed._reconcile_missing_history(state, datetime.fromisoformat("2026-07-17T15:30:00+05:30"))

    assert state["readiness"]["DATA_READY"] is False
    assert state["readiness"]["not_ready_reason"] == "CANDLE_GAP"
    assert any(row["timestamp"] == gap and row["classification"] == "PROVIDER_MISSING" and not row["repaired"] for row in state["readiness"]["gap_classifications"])


@pytest.mark.unit
def test_feed_restores_exact_held_contract_instead_of_rotated_atm():
    held = {
        "security_id": "57351", "exchange_segment": "NSE_FNO", "underlying": "NIFTY",
        "option_type": "PE", "strike": 24250.0, "expiry": "2026-07-21", "lot_size": 65,
        "instrument_source": "DHAN_INSTRUMENT_MASTER", "quote_source": "DHAN_OPTION_CHAIN",
    }
    feed = OptionChartCandleFeed(
        dhan=_Dhan(), instrument_master=_Master(), held_contract_provider=lambda side: held if side == "PE" else None,
    )
    snapshot = _snapshot("2026-07-17T12:00:05+05:30", 100, 200, 100)
    snapshot["data"]["underlying"].update({"expiry": "2026-07-21", "trading_date": "2026-07-17", "atm_strike": 24300})
    snapshot["data"]["atm_window"] = [
        {"strike": 24250, "pe": {"security_id": "57351", "ltp": 138.65, "volume": 100}},
        {"strike": 24300, "ce": {"security_id": "57352", "ltp": 110.0, "volume": 100}, "pe": {"security_id": "57353", "ltp": 145.0, "volume": 100}},
    ]

    feed.ingest(snapshot)

    assert feed.status()["sides"]["PE"]["contract"]["security_id"] == "57351"
    assert feed._states["PE"]["live"]["close"] == 138.65
