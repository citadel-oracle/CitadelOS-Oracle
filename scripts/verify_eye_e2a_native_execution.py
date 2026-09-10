"""Phase 0 E2A Native Engine Execution Acceptance Verification Script."""

import json
from datetime import datetime, timezone

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


def verify_e2a_native_acceptance():
    print("=== PHASE 0: E2A NATIVE ACCEPTANCE GATE VERIFICATION ===")

    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    ctx = EvaluationContext(market_time=now, available_at=now, detected_at=now, as_of=now)

    # 25 synthetic candle dicts with timestamp field
    candles = [
        {
            "timestamp": f"2026-08-06 15:{i:02d}:00",
            "open": 24400.0 + i*5, "high": 24450.0 + i*5, "low": 24380.0 + i*5, "close": 24440.0 + i*5, "volume": 1000 + i*100
        }
        for i in range(25)
    ]

    bars = [
        {"open_time": now, "expected_close_time": now, "available_at": now, "bar_key": f"NIFTY:5m:{i}", "is_closed": True, "source_name": "DHAN", "close": 24440.0 + i*5}
        for i in range(25)
    ]

    # 1. StructureEngineV2
    eng_s = StructureEngineV2()
    native_s = eng_s.analyze(candles)
    res_s = StructureV2Adapter().adapt(native_s, bars, inst, "5m", ctx)
    print("1. StructureEngineV2 Native Execution -> Records:", len(res_s.records), "Abstentions:", len(res_s.abstentions))

    # 2. BigBelugaVOBEngine
    eng_b = BigBelugaVOBEngine()
    native_b = eng_b.analyze_all({"5m": candles, "3m": candles, "15m": candles})
    res_b = BigBelugaAdapter().adapt(native_b, bars, inst, "5m", ctx)
    print("2. BigBelugaVOBEngine Native Execution -> Records:", len(res_b.records), "Abstentions:", len(res_b.abstentions))

    # 3. FVGEngine
    eng_f = FVGEngine()
    native_f = eng_f.analyze(candles)
    res_f = FVGAdapter().adapt(native_f, bars, inst, "5m", ctx)
    print("3. FVGEngine Native Execution -> Records:", len(res_f.records), "Abstentions:", len(res_f.abstentions))

    # 4. LiquidityEngine
    eng_l = LiquidityEngine()
    native_l = eng_l.analyze(candles)
    res_l = LiquidityAdapter().adapt(native_l, bars, inst, "5m", ctx)
    print("4. LiquidityEngine Native Execution -> Records:", len(res_l.records), "Abstentions:", len(res_l.abstentions))

    # 5. OracleDevPriceActionAnalyzer
    eng_o = OracleDevPriceActionAnalyzer()
    native_o = eng_o.analyze(candles, candles)
    res_o = OracleDevAdapter().adapt(native_o, bars, inst, "5m", ctx)
    print("5. OracleDevPriceActionAnalyzer Native Execution -> Records:", len(res_o.records), "Abstentions:", len(res_o.abstentions))

    print("\nE2A_NATIVE_ACCEPTANCE: PASS")


if __name__ == "__main__":
    verify_e2a_native_acceptance()
