"""EYE consumes the existing option-chart cache through one shared kernel."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.eye.kernel.runtime import EyeRuntime


IST = ZoneInfo("Asia/Kolkata")


def _candle(index: int, *, price: float = 100.0) -> dict:
    opened = datetime(2026, 8, 10, 9, 15, tzinfo=IST) + timedelta(minutes=index)
    return {
        "timestamp": opened.isoformat(),
        "candle_closed_at": (opened + timedelta(minutes=1)).isoformat(),
        "received_at": (opened + timedelta(minutes=1)).isoformat(),
        "open": price, "high": price + 1.0, "low": price - 1.0,
        "close": price + 0.1, "volume": 100.0,
        "closed": True, "is_closed": True, "contract": "41015",
        "chart_contract": {"security_id": "41015", "option_type": "CE"},
    }


def test_option_history_primes_one_bar_service_without_historical_signal(tmp_path):
    runtime = EyeRuntime(state_path=tmp_path / "state.json")
    history = [_candle(index, price=100.0 + index * 0.1) for index in range(66)]
    assert runtime.hydrate_option_history(history) == 66
    assert len(runtime.bar_service.get_bars("41015", 3, limit=100)) >= 21
    assert runtime.dependency_router.evaluation_count == 0

    # A new completed source candle reaches the same service exactly once; two
    # more are needed to close the 3m bar and release a live evaluation.
    assert runtime.ingest_option_candle(_candle(66, price=107.0))
    runtime.kernel.process_cycle()
    assert runtime.ingest_option_candle(_candle(67, price=107.2))
    runtime.kernel.process_cycle()
    assert runtime.ingest_option_candle(_candle(68, price=107.4))
    runtime.kernel.process_cycle()
    snapshot = runtime.dependency_router.state_store.get_state("S01")
    assert snapshot["locked_contract"] in {None, "41015"}
    assert runtime.dependency_router.evaluation_count == 1

    assert not runtime.ingest_option_candle(_candle(68, price=107.4))
    runtime.kernel.process_cycle()
    assert runtime.dependency_router.evaluation_count == 1
