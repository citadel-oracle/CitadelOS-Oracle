import time
from threading import Lock

from src.strategy_lab.models import (
    DeploymentRequest,
    StrategyInputType,
    StrategyMetadata,
)
from src.strategy_lab.runtime import StrategyRuntime
from src.strategy_lab.storage import StrategyWorkspace


class _RevisionProvider:
    def __init__(self, *, ready=True):
        self._lock = Lock()
        self.revision = "r1"
        self.ready = ready
        self.calls = 0

    def current_revision(self):
        with self._lock:
            return self.revision

    def __call__(self):
        with self._lock:
            self.calls += 1
            revision = self.revision
            ready = self.ready
        return {
            "candle_id": revision,
            "symbol": "NIFTY",
            "timeframe": "1m",
            "closed": True,
            "data_readiness": {
                "DATA_READY": ready,
                "not_ready_reason": None if ready else "HISTORY_LOADING",
            },
        }


class _WaitAdapter:
    def evaluate(self, context):
        return {
            "evaluation_id": f"wait:{context['candle_id']}",
            "signal": "WAIT",
            "reason": "NO_SETUP",
        }


def _runtime(tmp_path, provider):
    metadata = StrategyMetadata(
        strategy_id="revision-coalescing",
        name="revision-coalescing",
        version="test",
        author="test",
        input_type=StrategyInputType.PYTHON,
        supported_markets=["NIFTY"],
        supported_timeframes=["1m"],
        rr=None,
        risk_model="TEST",
    )
    request = DeploymentRequest(
        metadata=metadata,
        adapter=_WaitAdapter(),
        context_provider=provider,
        scheduler_interval_seconds=1.0,
    )
    runtime = StrategyRuntime(
        request=request,
        workspace=StrategyWorkspace(tmp_path, "revision-coalescing"),
    )
    runtime.interval = 0.02
    return runtime


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_scheduler_coalesces_unchanged_finalized_candle_before_context_build(tmp_path):
    provider = _RevisionProvider()
    runtime = _runtime(tmp_path, provider)
    runtime.start()
    try:
        _wait_for(lambda: provider.calls == 1 and runtime._unchanged_context_coalesces >= 2)
        first_call_count = provider.calls
        time.sleep(0.08)
        assert provider.calls == first_call_count

        provider.revision = "r2"
        _wait_for(
            lambda: runtime.workspace.read("evaluation_checkpoint")[
                "processed_candles"
            ].keys()
            >= {"r1", "r2"}
        )
        assert provider.calls == 2
    finally:
        runtime.stop()


def test_scheduler_does_not_coalesce_unready_input(tmp_path):
    provider = _RevisionProvider(ready=False)
    runtime = _runtime(tmp_path, provider)
    runtime.start()
    try:
        _wait_for(lambda: provider.calls >= 3)
        assert runtime._last_scheduled_context_revision is None
        assert runtime._unchanged_context_coalesces == 0
    finally:
        runtime.stop()
