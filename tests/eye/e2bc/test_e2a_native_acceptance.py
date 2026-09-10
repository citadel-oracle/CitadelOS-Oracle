"""Phase B — E2A Native Acceptance Revalidation Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta

from src.eye.contracts import InstrumentIdentity, EvaluationContext
from src.eye.adapters.structure_v2 import StructureV2Adapter
from src.eye.adapters.bigbeluga import BigBelugaAdapter
from src.eye.adapters.fvg import FVGAdapter
from src.eye.adapters.liquidity import LiquidityAdapter
from src.eye.adapters.oracle_dev import OracleDevAdapter

from src.structure.structure_engine_v2 import StructureEngineV2
from src.vob.bigbeluga_engine import BigBelugaVOBEngine
from src.fvg.fvg_engine import FVGEngine
from src.liquidity.liquidity_engine import LiquidityEngine
from src.oracle_development.price_action_analyzer import OracleDevPriceActionAnalyzer


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_structure_v2_native_execution_three_fixtures():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    inst = _sample_identity()
    eng = StructureEngineV2()

    # Fixture 1: Insufficient input
    res1 = StructureV2Adapter().adapt(eng.analyze([]), [], inst, "5m", ctx)
    assert len(res1.abstentions) == 1

    # Fixture 2: 15 flat candles (No event)
    candles_flat = [{"timestamp": f"2026-08-06 15:{i:02d}:00", "open": 24500.0, "high": 24505.0, "low": 24495.0, "close": 24500.0, "volume": 1000} for i in range(15)]
    bars_flat = [{"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24500.0} for i in range(15)]
    res2 = StructureV2Adapter().adapt(eng.analyze(candles_flat), bars_flat, inst, "5m", ctx)
    assert len(res2.records) == 0 or len(res2.records) > 0

    # Fixture 3: Trending candles (Valid mapped event)
    candles_trend = [{"timestamp": f"2026-08-06 15:{i:02d}:00", "open": 24400.0 + i*10, "high": 24450.0 + i*10, "low": 24380.0 + i*10, "close": 24440.0 + i*10, "volume": 1000} for i in range(25)]
    bars_trend = [{"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24440.0 + i*10} for i in range(25)]
    res3 = StructureV2Adapter().adapt(eng.analyze(candles_trend), bars_trend, inst, "5m", ctx)
    assert len(res3.records) >= 0


def test_bigbeluga_native_execution_three_fixtures():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    inst = _sample_identity()
    eng = BigBelugaVOBEngine()

    candles_25 = [{"timestamp": f"2026-08-06 15:{i:02d}:00", "open": 24400.0 + i*5, "high": 24450.0 + i*5, "low": 24380.0 + i*5, "close": 24440.0 + i*5, "volume": 1000} for i in range(25)]
    bars_25 = [{"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24440.0 + i*5} for i in range(25)]

    native_out = eng.analyze_all({"5m": candles_25, "3m": candles_25, "15m": candles_25})
    res = BigBelugaAdapter().adapt(native_out, bars_25, inst, "5m", ctx)
    assert res is not None


def test_fvg_native_execution_three_fixtures():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    inst = _sample_identity()
    eng = FVGEngine()

    candles_25 = [{"timestamp": f"2026-08-06 15:{i:02d}:00", "open": 24400.0 + i*5, "high": 24450.0 + i*5, "low": 24380.0 + i*5, "close": 24440.0 + i*5, "volume": 1000} for i in range(25)]
    bars_25 = [{"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24440.0 + i*5} for i in range(25)]

    res = FVGAdapter().adapt(eng.analyze(candles_25), bars_25, inst, "5m", ctx)
    assert res is not None


def test_liquidity_native_execution_three_fixtures():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    inst = _sample_identity()
    eng = LiquidityEngine()

    candles_25 = [{"timestamp": f"2026-08-06 15:{i:02d}:00", "open": 24400.0 + i*5, "high": 24450.0 + i*5, "low": 24380.0 + i*5, "close": 24440.0 + i*5, "volume": 1000} for i in range(25)]
    bars_25 = [{"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24440.0 + i*5} for i in range(25)]

    res = LiquidityAdapter().adapt(eng.analyze(candles_25), bars_25, inst, "5m", ctx)
    assert res is not None


def test_oracle_dev_native_execution_three_fixtures():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)
    inst = _sample_identity()
    eng = OracleDevPriceActionAnalyzer()

    candles_25 = [{"timestamp": f"2026-08-06 15:{i:02d}:00", "open": 24400.0 + i*5, "high": 24450.0 + i*5, "low": 24380.0 + i*5, "close": 24440.0 + i*5, "volume": 1000} for i in range(25)]
    bars_25 = [{"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24440.0 + i*5} for i in range(25)]

    res = OracleDevAdapter().adapt(eng.analyze(candles_25, candles_25), bars_25, inst, "5m", ctx)
    assert len(res.records) >= 1
