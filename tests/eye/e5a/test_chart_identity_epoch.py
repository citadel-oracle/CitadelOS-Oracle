"""E5A Test for Chart Identity Epoch & Symbol Switching Isolation."""

import pytest
from src.eye.oracle_projection.chart_context import ChartContextManager
from src.eye.oracle_projection.contracts import EyeChartContext, ChartIdentityStatus
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
from src.eye.oracle_projection.runtime_state import EyeRuntimeState


def test_chart_identity_epoch_increment_on_symbol_switch():
    mgr = ChartContextManager()

    ctx1 = mgr.resolve_context(symbol="NIFTY", timeframe="5m")
    assert ctx1.normalized_symbol == "NIFTY"
    assert ctx1.chart_timeframe == "5m"
    assert ctx1.identity_epoch == 1
    assert ctx1.status == ChartIdentityStatus.ACTIVE

    # Switch symbol to BANKNIFTY -> Epoch must increment to 2
    ctx2 = mgr.resolve_context(symbol="BANKNIFTY", timeframe="5m")
    assert ctx2.normalized_symbol == "BANKNIFTY"
    assert ctx2.identity_epoch == 2
    assert ctx2.status == ChartIdentityStatus.ACTIVE

    # Switch timeframe to 15m -> Epoch must increment to 3
    ctx3 = mgr.resolve_context(symbol="BANKNIFTY", timeframe="15m")
    assert ctx3.identity_epoch == 3


def test_unsupported_symbol_returns_unsupported_status():
    mgr = ChartContextManager()
    ctx = mgr.resolve_context(symbol="INVALID_XYZ", timeframe="5m")
    assert ctx.status == ChartIdentityStatus.UNSUPPORTED_INSTRUMENT


def test_exact_option_chart_uses_exact_canonical_security_identity():
    mgr = ChartContextManager()
    ctx = mgr.resolve_tradingview_context({
        "symbol": {"normalized_symbol": "NIFTY260811C24500", "route": "EXACT_OPTION"},
        "instrument": {"route": "EXACT_OPTION"},
        "option": {"underlying": "NIFTY", "expiry": "2026-08-11", "strike": 24500.0, "option_side": "CE", "security_id": "42"},
        "timeframe": "5m",
    })
    assert ctx.status == ChartIdentityStatus.ACTIVE
    assert ctx.underlying == "NIFTY"
    assert ctx.resolved_market_data_identity == "DHAN:OPTION:42"

    unresolved = mgr.resolve_tradingview_context({
        "symbol": {"normalized_symbol": "NIFTY260811C24500", "route": "EXACT_OPTION"},
        "instrument": {"route": "EXACT_OPTION"}, "option": {"underlying": "NIFTY"}, "timeframe": "5m",
    })
    assert unresolved.status == ChartIdentityStatus.IDENTITY_UNRESOLVED


def test_exact_option_identity_survives_a_read_only_oracle_projection():
    runtime = EyeRuntimeState()
    runtime.update_tradingview_context(
        "NIFTY",
        "5m",
        chart_state={
            "symbol": {"normalized_symbol": "NIFTY260811C24500", "route": "EXACT_OPTION"},
            "instrument": {"route": "EXACT_OPTION"},
            "option": {
                "underlying": "NIFTY",
                "expiry": "2026-08-11",
                "strike": 24500.0,
                "option_side": "CE",
                "security_id": "42",
            },
            "timeframe": "5m",
        },
    )

    projection = EyeOracleProjectionService(runtime_state=runtime).get_projection(
        symbol="NIFTY",
        timeframe="5m",
    )

    assert projection.identity.resolved_market_data_identity == "DHAN:OPTION:42"
    assert projection.identity.status == ChartIdentityStatus.ACTIVE
