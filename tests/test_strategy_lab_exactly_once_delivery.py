import json
from datetime import datetime, timedelta, timezone
from time import perf_counter

import pytest

from src.strategy_lab import DeploymentRequest, StrategyInputType, StrategyLabService, StrategyMetadata


class RecordingStrategy:
    def __init__(self, seen=None, fail_timestamp=None):
        self.seen = list(seen or [])
        self.fail_timestamp = fail_timestamp

    def evaluate(self, context):
        timestamp = context["bar"]["timestamp"]
        if timestamp == self.fail_timestamp:
            raise RuntimeError("planned evaluation failure")
        self.seen.append(timestamp)
        signal = context["bar"].get("test_signal", "WAIT")
        return {
            "evaluation_id": f"eval:{timestamp}",
            "signal": signal,
            "position_effect": "OPEN" if signal == "BUY" else None,
            "reason": signal,
        }

    def serialize(self):
        return json.dumps({"seen": self.seen, "fail_timestamp": self.fail_timestamp})

    @classmethod
    def deserialize(cls, payload):
        value = json.loads(payload)
        return cls(value["seen"], value["fail_timestamp"])


class MutableProvider:
    def __init__(self, timeframe="1m"):
        self.timeframe = timeframe
        self.rows = []
        self.calls = 0

    def __call__(self):
        self.calls += 1
        latest = self.rows[-1]
        contract = latest.get("contract")
        return {
            "candle_id": f"NIFTY_CE:{self.timeframe}:{latest['timestamp']}",
            "symbol": "NIFTY_CE",
            "underlying": "NIFTY",
            "timeframe": self.timeframe,
            "timestamp": latest["timestamp"],
            "closed": True,
            "is_closed": True,
            "contract": contract,
            "chart_contract": {"security_id": contract} if contract else None,
            "bar": dict(latest),
            "completed_candles": [dict(row) for row in self.rows],
            "data_readiness": {"DATA_READY": True, "not_ready_reason": None},
            "argus": {"data": {"underlying": {"symbol": "NIFTY"}, "atm_window": []}},
        }


def bar(minute, *, timeframe="1m", signal="WAIT", contract="A"):
    timestamp = f"2026-07-18T09:{minute:02d}:00+05:30"
    return {
        "index": minute,
        "timestamp": timestamp,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 10.0,
        "confirmed": True,
        "is_closed": True,
        "timeframe": timeframe,
        "test_signal": signal,
        "contract": contract,
        "chart_contract": {"security_id": contract},
        "lot_size": 65,
    }


def request(provider, adapter=None, strategy_id="exactly-once"):
    metadata = StrategyMetadata(
        strategy_id=strategy_id,
        name=strategy_id,
        version="RULE-V1",
        author="Test",
        input_type=StrategyInputType.PYTHON,
        supported_markets=["NIFTY"],
        supported_timeframes=[provider.timeframe],
        rr=None,
        risk_model="TEST",
        deployment_date="2026-07-18T00:00:00+00:00",
    )
    return DeploymentRequest(
        metadata=metadata,
        adapter=adapter or RecordingStrategy(),
        context_provider=provider,
        scheduler_interval_seconds=60,
    )


def evaluation_checkpoint(runtime):
    return runtime.workspace.read("evaluation_checkpoint")


@pytest.mark.parametrize("timeframe,minutes", [("1m", [15, 16, 17, 18]), ("3m", [15, 18, 21, 24]), ("5m", [15, 20, 25, 30])])
def test_all_eligible_candles_are_evaluated_once_in_chronological_order(tmp_path, timeframe, minutes):
    provider = MutableProvider(timeframe)
    provider.rows = [bar(minutes[0], timeframe=timeframe)]
    runtime = StrategyLabService(str(tmp_path / timeframe)).deploy(request(provider, strategy_id=f"exact-{timeframe}"))
    runtime.tick_once()
    provider.rows = [bar(value, timeframe=timeframe) for value in minutes]
    for _ in minutes[1:]:
        runtime.tick_once()
    assert runtime.strategy.seen == [row["timestamp"] for row in provider.rows]
    assert runtime.tick_once()["reason"] == "CANDLE_ALREADY_PROCESSED"
    assert runtime.workspace.journal.read() == []
    cursor = evaluation_checkpoint(runtime)["cursor"]
    assert cursor["last_completed_candle_id"].endswith(provider.rows[-1]["timestamp"])
    assert cursor["last_evaluated_candle_id"] == cursor["last_completed_candle_id"]


def test_restart_and_failed_evaluation_resume_without_advancing_cursor(tmp_path):
    provider = MutableProvider()
    provider.rows = [bar(15)]
    root = str(tmp_path / "restart")
    first = StrategyLabService(root).deploy(request(provider))
    first.tick_once()
    provider.rows = [bar(15), bar(16), bar(17)]

    restarted = StrategyLabService(root).deploy(request(provider))
    restarted.strategy.fail_timestamp = provider.rows[1]["timestamp"]
    assert restarted.tick_once()["status"] == "ERROR"
    cursor = evaluation_checkpoint(restarted)["cursor"]
    assert cursor["last_evaluated_candle_id"].endswith(provider.rows[0]["timestamp"])
    restarted.strategy.fail_timestamp = None
    restarted.tick_once()
    restarted.tick_once()
    processed = evaluation_checkpoint(restarted)["processed_candles"]
    assert all(f"NIFTY_CE:1m:{row['timestamp']}" in processed for row in provider.rows)
    assert evaluation_checkpoint(restarted)["interruption"]["status"] == "RECOVERED"


def test_historical_entry_is_audit_only_and_interruption_is_durable(tmp_path):
    provider = MutableProvider()
    provider.rows = [bar(15)]
    runtime = StrategyLabService(str(tmp_path / "missed")).deploy(request(provider))
    runtime.tick_once()
    provider.rows = [bar(15), bar(16, signal="BUY"), bar(17)]
    missed = runtime.tick_once()["decision"]
    assert (missed["signal"], missed["would_signal"], missed["reason"]) == (
        "WAIT", "BUY", "MISSED_SIGNAL_DUE_TO_INFRA"
    )
    assert runtime.execution.projection()["orders"] == []
    runtime.tick_once()
    events = runtime.workspace.logs.read()
    assert [row["event_type"] for row in events].count("MISSED_SIGNAL_DUE_TO_INFRA") == 1
    assert any(row["event_type"] == "EVALUATION_INTERRUPTION_STARTED" for row in events)
    assert any(row["event_type"] == "EVALUATION_INTERRUPTION_RECOVERED" for row in events)
    assert runtime.execution.projection()["broker_submission"] is False


def test_wait_hot_path_is_compact_and_500_candles_clear_under_15_seconds(tmp_path):
    provider = MutableProvider()
    provider.rows = [bar(15)]
    runtime = StrategyLabService(str(tmp_path / "throughput")).deploy(request(provider))
    strategy_state_path = runtime.workspace.paths["strategy_state"]
    before = strategy_state_path.read_bytes()
    started = perf_counter()
    origin = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
    for index in range(500):
        row = {**bar(15), "index": index, "timestamp": (origin + timedelta(seconds=index)).isoformat()}
        context = provider()
        context.update({
            "candle_id": f"NIFTY_CE:1m:{row['timestamp']}",
            "timestamp": row["timestamp"],
            "bar": row,
            "completed_candles": [row],
        })
        assert runtime.tick_once(context_override=context)["status"] == "EVALUATED"
    elapsed = perf_counter() - started
    assert elapsed < 15.0
    assert strategy_state_path.read_bytes() == before
    checkpoint = evaluation_checkpoint(runtime)
    assert len(checkpoint["processed_candles"]) == 500
    assert checkpoint["cursor"]["last_evaluated_candle_id"].endswith(
        (origin + timedelta(seconds=499)).isoformat()
    )


def test_material_signal_persists_full_state_and_failed_checkpoint_does_not_advance(tmp_path, monkeypatch):
    provider = MutableProvider()
    provider.rows = [bar(15)]
    runtime = StrategyLabService(str(tmp_path / "material")).deploy(request(provider))
    state_path = runtime.workspace.paths["strategy_state"]
    before = state_path.read_bytes()
    runtime._persist_runtime_state({
        "signal": "BUY",
        "reason": "TEST_ENTRY",
        "evaluated_at": "2026-07-20T03:45:00+00:00",
        "bar_timestamp": "2026-07-20T03:45:00+00:00",
        "timeframe": "1m",
        "input_security_id": "A",
        "paper_execution": {"status": "FILLED", "paper_state_mutated": True},
    }, "NIFTY_CE:1m:material", "2026-07-20T03:45:00+00:00")
    assert state_path.read_bytes() != before
    prior_cursor = dict(evaluation_checkpoint(runtime)["cursor"])
    original_write = runtime.workspace.write

    def fail_checkpoint(name, value):
        if name == "evaluation_checkpoint":
            raise OSError("planned checkpoint failure")
        return original_write(name, value)

    monkeypatch.setattr(runtime.workspace, "write", fail_checkpoint)
    with pytest.raises(OSError):
        runtime._persist_runtime_state({
            "signal": "WAIT", "reason": "WAIT", "evaluated_at": "2026-07-20T03:46:00+00:00",
            "bar_timestamp": "2026-07-20T03:46:00+00:00", "timeframe": "1m",
            "input_security_id": "A", "paper_execution": {"status": "NO_ACTION"},
        }, "NIFTY_CE:1m:failed", "2026-07-20T03:46:00+00:00")
    monkeypatch.setattr(runtime.workspace, "write", original_write)
    assert evaluation_checkpoint(runtime)["cursor"] == prior_cursor


def test_backlog_drain_is_bounded_refreshes_first_and_continues_without_overlap(tmp_path):
    provider = MutableProvider()
    origin = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
    first_row = {**bar(15), "index": 0, "timestamp": origin.isoformat()}
    provider.rows = [first_row]
    runtime = StrategyLabService(str(tmp_path / "batch")).deploy(request(provider))
    runtime.tick_once()
    provider.rows = [
        {**bar(15), "index": index, "timestamp": (origin + timedelta(seconds=index)).isoformat()}
        for index in range(100)
    ]
    runtime._queue_completed_contexts(provider(), reason="CANDLE_GAP")
    runtime._set_scheduler_started_runtime()
    assert runtime.workspace.read("runtime")["state"] == "CATCHING_UP"
    assert runtime.workspace.read("runtime")["reason"] == "CANDLE_BACKLOG"
    before_calls = provider.calls
    first = runtime._drain_backlog_pass()
    assert provider.calls == before_calls + 1
    assert 1 <= first["processed"] <= 25
    assert first["elapsed_ms"] <= 450
    assert first["remaining"] > 0
    assert runtime.workspace.read("runtime")["state"] == "CATCHING_UP"
    assert runtime.workspace.read("runtime")["readiness"] == "BLOCKED"
    assert runtime.workspace.read("runtime")["reason"] == "CANDLE_BACKLOG"
    while runtime._pending_evaluation_contexts:
        result = runtime._drain_backlog_pass()
        assert result["processed"] <= 25
    checkpoint = evaluation_checkpoint(runtime)
    assert len(checkpoint["processed_candles"]) == 100
    assert checkpoint["cursor"]["last_evaluated_candle_id"].endswith(provider.rows[-1]["timestamp"])
    assert checkpoint["interruption"]["status"] == "RECOVERED"
    assert runtime.execution.projection()["orders"] == []
    assert runtime.workspace.read("runtime")["state"] == "RUNNING"
    assert runtime.workspace.read("runtime")["readiness"] == "READY"


def test_contract_rotation_preserves_order_and_updates_cursor_identity(tmp_path):
    provider = MutableProvider()
    provider.rows = [bar(15, contract="OLD")]
    runtime = StrategyLabService(str(tmp_path / "rotation")).deploy(request(provider))
    runtime.tick_once()
    provider.rows = [bar(15, contract="OLD"), bar(16, contract="NEW"), bar(17, contract="NEW")]
    runtime.tick_once()
    runtime.tick_once()
    cursor = evaluation_checkpoint(runtime)["cursor"]
    assert cursor["instrument_security_id"] == "NEW"
    starts = [row["payload"] for row in runtime.workspace.logs.read() if row["event_type"] == "EVALUATION_INTERRUPTION_STARTED"]
    assert any(row["reason"] == "CONTRACT_ROTATION" for row in starts)
    assert runtime.strategy.seen == [row["timestamp"] for row in provider.rows]


def test_null_cursor_bootstraps_and_replays_only_missing_candles(tmp_path):
    provider = MutableProvider()
    root = str(tmp_path / "bootstrap")
    provider.rows = [bar(15)]
    first = StrategyLabService(root).deploy(request(provider))
    first.tick_once()
    first.tick_once(context_override={
        **provider(),
        "candle_id": f"NIFTY_CE:1m:{bar(17)['timestamp']}",
        "timestamp": bar(17)["timestamp"],
        "bar": bar(17),
        "completed_candles": [bar(17)],
    })
    state = evaluation_checkpoint(first)
    state["cursor"] = None
    state["interruption"] = {
        "deployment_id": "exactly-once", "status": "ACTIVE", "reason": "FEED_RECONNECT",
        "started_at": "2026-07-18T09:18:00+05:30", "ended_at": None,
        "affected_candle_ids": [], "recovery_result": None,
    }
    first.workspace.write("evaluation_checkpoint", state)

    provider.rows = [bar(15), bar(16, signal="BUY"), bar(17), bar(18)]
    restarted = StrategyLabService(root).deploy(request(provider))
    cursor = evaluation_checkpoint(restarted)["cursor"]
    assert cursor is not None
    assert cursor["last_evaluated_candle_id"].endswith(bar(17)["timestamp"])
    restarted.bootstrap_data()
    restarted.tick_once()
    restarted.tick_once()
    final = evaluation_checkpoint(restarted)
    assert final["cursor"]["last_evaluated_candle_id"].endswith(bar(18)["timestamp"])
    assert final["interruption"]["status"] == "RECOVERED"
    assert restarted.execution.projection()["orders"] == []


def test_obsolete_contract_backlog_does_not_starve_live_session(tmp_path):
    provider = MutableProvider()
    old = {**bar(14, contract="OLD"), "timestamp": "2026-07-17T09:14:00+05:30"}
    obsolete = {**bar(15, signal="BUY", contract="OLD"), "timestamp": "2026-07-17T09:15:00+05:30"}
    provider.rows = [old]
    runtime = StrategyLabService(str(tmp_path / "lanes")).deploy(request(provider))
    runtime.tick_once()

    provider.rows = [
        old,
        obsolete,
        bar(15, signal="BUY", contract="NEW"),
        bar(16, signal="BUY", contract="NEW"),
        bar(17, signal="BUY", contract="NEW"),
    ]
    before = provider.calls
    stale = runtime.tick_once()["decision"]
    assert provider.calls > before
    assert stale["signal"] == "WAIT"
    assert stale["would_signal"] == "BUY"
    assert stale["reason"] == "MISSED_SIGNAL_DUE_TO_INFRA"
    second_stale = runtime.tick_once()["decision"]
    assert second_stale["signal"] == "WAIT"
    assert second_stale["would_signal"] == "BUY"
    assert second_stale["reason"] == "MISSED_SIGNAL_DUE_TO_INFRA"
    fresh = runtime.tick_once()["decision"]
    assert fresh["reason"] != "MISSED_SIGNAL_DUE_TO_INFRA"
    assert fresh.get("would_signal") is None
    assert runtime.tick_once()["reason"] == "CANDLE_ALREADY_PROCESSED"

    state = evaluation_checkpoint(runtime)
    assert state["cursor"]["instrument_security_id"] == "NEW"
    assert state["cursor"]["last_evaluated_candle_id"].endswith(bar(17)["timestamp"])
    assert state["historical_audit_backlog"]["count"] == 1
    assert state["interruption"]["status"] == "RECOVERED"
    assert runtime.execution.projection()["orders"] == []
