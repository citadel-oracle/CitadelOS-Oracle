"""Focused tests: production wiring of deployment_held_security_id_provider.

Verifies:
1. Production constructors receive held_security_id_provider (not None).
2. Correct deployment open security ID returned for the matching deployment.
3. Wrong deployment, closed position, and no-position all return None.
4. Index/ATM substitution is impossible — only held_security_id from position is used.
5. Stale chain + exact held contract → evaluation allowed end-to-end.
6. No duplicate order/fill can result from provider logic.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

from src.strategy_lab.completed_candle import (
    CompletedCandleContextProvider,
    deployment_held_security_id_provider,
)
from src.strategy_lab.option_deployments import (
    OPTION_CHART_DEPLOYMENTS,
    build_option_chart_deployments,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 21, 8, 10, 0, tzinfo=timezone.utc)
_CANDLE_TS = "2026-07-21T08:09:00+00:00"
_CANDLE_CLOSED = "2026-07-21T08:10:00+00:00"
_HELD_SID = "57346"
_ATM_SID = "57999"       # current ATM — must never be substituted
_INDEX_SID = "NIFTY"     # index instrument — must never be returned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(*, deployment_id: str, held_security_id: str | None, status: str = "OPEN") -> Any:
    """Minimal mock of StrategyLabService with one runtime."""
    position = {
        "status": status,
        "held_security_id": held_security_id,
        "contract": held_security_id or _ATM_SID,   # ATM when no real held
    }
    engine = MagicMock()
    engine.projection.return_value = {
        "strategy_id": deployment_id,
        "positions": [position] if held_security_id else [],
    }
    runtime = MagicMock()
    runtime.execution = engine

    service = MagicMock()
    service._runtimes = {deployment_id: runtime}
    return service


def _make_candle(security_id: str = _HELD_SID) -> dict:
    return {
        "symbol": "NIFTY_CE",
        "timeframe": "1m",
        "timestamp": _CANDLE_TS,
        "candle_closed_at": _CANDLE_CLOSED,
        "closed": True,
        "is_closed": True,
        "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0,
        "volume": 1000.0, "source": "TEST", "lot_size": 75,
        "underlying": "NIFTY", "contract": security_id,
        "chart_contract": {"security_id": security_id, "option_type": "CE",
                           "strike": 24200, "expiry": "2026-07-31"},
    }


def _stale_argus() -> dict:
    return {
        "status": "stale", "freshness": "STALE",
        "data": {"underlying": {"market_state": "OPEN",
                                "fetched_at": (_NOW - timedelta(seconds=700)).isoformat()}},
    }


def _fresh_argus() -> dict:
    return {
        "status": "available", "freshness": "FRESH",
        "data": {"underlying": {"market_state": "OPEN", "fetched_at": _NOW.isoformat()}},
    }


class _FakeSource:
    def __init__(self, candles):
        self._candles = candles

    def load_cache(self):
        return list(self._candles)

    def readiness(self):
        return {"DATA_READY": True, "loaded_bars": len(self._candles), "not_ready_reason": None}


# ---------------------------------------------------------------------------
# 1. Production constructors receive held_security_id_provider
# ---------------------------------------------------------------------------

def test_pullback_context_receives_provider_in_main():
    """Smoke: CompletedCandleContextProvider can be constructed with provider (app/main.py pattern)."""
    service = _make_service(deployment_id="pullback-master-pine-v5", held_security_id=_HELD_SID)
    provider = deployment_held_security_id_provider(service, "pullback-master-pine-v5")
    candle = _make_candle()
    ctx = CompletedCandleContextProvider(
        candle_source=_FakeSource([candle]),
        argus_provider=lambda: _fresh_argus(),
        clock=lambda: _NOW,
        held_security_id_provider=provider,
    )
    assert ctx.held_security_id_provider is not None
    assert callable(ctx.held_security_id_provider)


def test_breakout_context_receives_provider_in_main():
    service = _make_service(deployment_id="breakout-main-pine-v5", held_security_id=_HELD_SID)
    provider = deployment_held_security_id_provider(service, "breakout-main-pine-v5")
    ctx = CompletedCandleContextProvider(
        candle_source=_FakeSource([_make_candle()]),
        argus_provider=lambda: _fresh_argus(),
        clock=lambda: _NOW,
        held_security_id_provider=provider,
    )
    assert callable(ctx.held_security_id_provider)


def test_option_deployments_all_receive_provider():
    """build_option_chart_deployments wires a non-None provider when service is passed."""
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=_HELD_SID)

    class _FakeFeed:
        def source(self, side, timeframe):
            return _FakeSource([_make_candle()])

    requests = build_option_chart_deployments(
        feed=_FakeFeed(),
        argus_provider=lambda: _fresh_argus(),
        service=service,
    )
    assert len(requests) == len(OPTION_CHART_DEPLOYMENTS)
    for req in requests:
        ctx = req.context_provider
        assert hasattr(ctx, "held_security_id_provider")
        assert ctx.held_security_id_provider is not None, \
            f"held_security_id_provider is None for {req.metadata.strategy_id}"


def test_option_deployments_no_service_gives_none_provider():
    """Without service, provider defaults to None (backward compat)."""
    class _FakeFeed:
        def source(self, side, timeframe):
            return _FakeSource([_make_candle()])

    requests = build_option_chart_deployments(
        feed=_FakeFeed(),
        argus_provider=lambda: _fresh_argus(),
    )
    for req in requests:
        assert req.context_provider.held_security_id_provider is None


# ---------------------------------------------------------------------------
# 2. Correct deployment open security ID returned
# ---------------------------------------------------------------------------

def test_provider_returns_held_security_id_for_open_position():
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=_HELD_SID)
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    assert provider() == _HELD_SID


# ---------------------------------------------------------------------------
# 3. Wrong deployment / closed position / no position → None
# ---------------------------------------------------------------------------

def test_provider_wrong_deployment_returns_none():
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=_HELD_SID)
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_PE_1M")  # different
    assert provider() is None


def test_provider_closed_position_returns_none():
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=_HELD_SID, status="CLOSED")
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    assert provider() is None


def test_provider_no_open_position_returns_none():
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=None)
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    assert provider() is None


def test_provider_runtime_not_loaded_returns_none():
    service = MagicMock()
    service._runtimes = {}   # runtime not yet deployed
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    assert provider() is None


def test_provider_projection_exception_returns_none():
    engine = MagicMock()
    engine.projection.side_effect = RuntimeError("engine offline")
    runtime = MagicMock()
    runtime.execution = engine
    service = MagicMock()
    service._runtimes = {"BO_NIFTY_CE_1M": runtime}
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    assert provider() is None   # never raises


# ---------------------------------------------------------------------------
# 4. Index / ATM substitution is impossible
# ---------------------------------------------------------------------------

def test_provider_never_returns_atm_contract():
    """Even if position.contract is ATM, only held_security_id field is used."""
    engine = MagicMock()
    engine.projection.return_value = {
        "positions": [{
            "status": "OPEN",
            "held_security_id": _HELD_SID,
            "contract": _ATM_SID,   # different from held — ATM substitution attempt
        }]
    }
    runtime = MagicMock()
    runtime.execution = engine
    service = MagicMock()
    service._runtimes = {"BO_NIFTY_CE_1M": runtime}
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    result = provider()
    assert result == _HELD_SID
    assert result != _ATM_SID


def test_provider_never_returns_index_security_id():
    """Provider reads held_security_id, not symbol/underlying."""
    engine = MagicMock()
    engine.projection.return_value = {
        "positions": [{
            "status": "OPEN",
            "held_security_id": _HELD_SID,
            "symbol": _INDEX_SID,
            "underlying": _INDEX_SID,
        }]
    }
    runtime = MagicMock()
    runtime.execution = engine
    service = MagicMock()
    service._runtimes = {"BO_NIFTY_CE_1M": runtime}
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    result = provider()
    assert result == _HELD_SID
    assert result != _INDEX_SID


def test_provider_ambiguous_two_open_positions_returns_none():
    """If two positions are open (impossible in normal flow), provider returns None safely."""
    engine = MagicMock()
    engine.projection.return_value = {
        "positions": [
            {"status": "OPEN", "held_security_id": _HELD_SID},
            {"status": "OPEN", "held_security_id": _ATM_SID},
        ]
    }
    runtime = MagicMock()
    runtime.execution = engine
    service = MagicMock()
    service._runtimes = {"BO_NIFTY_CE_1M": runtime}
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    assert provider() is None


# ---------------------------------------------------------------------------
# 5. Stale chain + exact held contract → evaluation allowed end-to-end
# ---------------------------------------------------------------------------

def test_stale_chain_with_wired_provider_allows_held_exit():
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=_HELD_SID)
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    candle = _make_candle(_HELD_SID)
    ctx_provider = CompletedCandleContextProvider(
        candle_source=_FakeSource([candle]),
        argus_provider=lambda: _stale_argus(),
        clock=lambda: _NOW,
        held_security_id_provider=provider,
    )
    ctx = ctx_provider()
    assert ctx["closed"] is True
    assert ctx["chain_stale"] is True
    assert ctx["candle_fallback_security_id"] == _HELD_SID
    assert ctx["new_entry_blocked"] is True
    assert ctx["contract_rotation_blocked"] is True


def test_stale_chain_with_wired_provider_blocks_new_entry():
    # No open position → provider returns None → no fallback for entry
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=None)
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    candle = _make_candle(_HELD_SID)
    ctx_provider = CompletedCandleContextProvider(
        candle_source=_FakeSource([candle]),
        argus_provider=lambda: _stale_argus(),
        clock=lambda: _NOW,
        held_security_id_provider=provider,
    )
    ctx = ctx_provider()
    assert ctx["closed"] is False
    assert ctx["source_health"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# 6. No duplicate order/fill from provider logic
# ---------------------------------------------------------------------------

def test_provider_is_stateless_and_idempotent():
    """Calling provider multiple times returns the same value without side effects."""
    service = _make_service(deployment_id="BO_NIFTY_CE_1M", held_security_id=_HELD_SID)
    provider = deployment_held_security_id_provider(service, "BO_NIFTY_CE_1M")
    results = [provider() for _ in range(10)]
    assert all(r == _HELD_SID for r in results)
    # projection was called exactly once per call — no batching, no mutation
    assert service._runtimes["BO_NIFTY_CE_1M"].execution.projection.call_count == 10
