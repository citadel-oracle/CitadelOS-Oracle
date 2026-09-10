"""Comprehensive E2A Adapter, Characterization, Temporal Parity & Determinism Tests."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import (
    InstrumentIdentity,
    EvaluationContext,
    EventType,
    EventDirection,
    EventFamily,
    DetectionState,
    LifecycleState,
    EyeContractError,
)
from src.eye.adapters.base import quantize_price
from src.eye.adapters.structure_v2 import StructureV2Adapter
from src.eye.adapters.bigbeluga import BigBelugaAdapter
from src.eye.adapters.fvg import FVGAdapter
from src.eye.adapters.liquidity import LiquidityAdapter
from src.eye.adapters.oracle_dev import OracleDevAdapter
from src.eye.adapter_result import AdapterAbstentionReason, AdapterResult
from src.eye.offline_replay import OfflineReplayHarness, ReplayMode, PrefixInvarianceStatus
from src.eye.registry import RuleRegistry, RuleStatus, ProvenanceType


def _sample_bars():
    t = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    return [
        {
            "open_time": t - timedelta(minutes=10),
            "expected_close_time": t - timedelta(minutes=5),
            "available_at": t - timedelta(minutes=5),
            "bar_key": "NIFTY:5m:1525",
            "is_closed": True,
            "source_name": "DHAN",
            "open": 24400.0, "high": 24500.0, "low": 24380.0, "close": 24490.0,
        },
        {
            "open_time": t - timedelta(minutes=5),
            "expected_close_time": t,
            "available_at": t,
            "bar_key": "NIFTY:5m:1530",
            "is_closed": True,
            "source_name": "DHAN",
            "open": 24490.0, "high": 24550.0, "low": 24480.0, "close": 24540.0,
        },
    ]


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
    )


def _sample_ctx():
    t = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    return EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)


# ----------------------------------------------------
# 1. StructureEngineV2 Adapter Tests
# ----------------------------------------------------

def test_structure_v2_bos_bullish_adaptation():
    adapter = StructureV2Adapter()
    native_out = {"bos": "BULLISH_BOS", "last_high": {"price": 24500.0}}
    res = adapter.adapt(
        native_output=native_out, source_bars=_sample_bars(),
        instrument_identity=_sample_identity(), timeframe="5m",
        evaluation_context=_sample_ctx(),
    )
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.BOS_BULLISH
    assert rec.payload.primary_level.value == 24500.0
    assert rec.producer.engine_name == "StructureEngineV2"
    assert rec.producer.rule_id == "STRUCTURE_V2_BOS_CLOSE_V1"


def test_structure_v2_no_signal_abstention():
    adapter = StructureV2Adapter()
    native_out = {"bos": "NONE", "choch": "NONE"}
    res = adapter.adapt(
        native_output=native_out, source_bars=_sample_bars(),
        instrument_identity=_sample_identity(), timeframe="5m",
        evaluation_context=_sample_ctx(),
    )
    assert len(res.records) == 0
    assert len(res.abstentions) == 1
    assert res.abstentions[0].code == AdapterAbstentionReason.UNSUPPORTED_NATIVE_EVENT


# ----------------------------------------------------
# 2. BigBelugaVOBEngine Adapter Tests
# ----------------------------------------------------

def test_bigbeluga_order_block_adaptation():
    adapter = BigBelugaAdapter()
    native_out = [{"top": 24500.0, "bottom": 24450.0, "is_bullish": True, "mitigated": False}]
    res = adapter.adapt(
        native_output=native_out, source_bars=_sample_bars(),
        instrument_identity=_sample_identity(), timeframe="5m",
        evaluation_context=_sample_ctx(),
    )
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.ORDER_BLOCK_BULLISH
    assert rec.payload.lower.value == 24450.0
    assert rec.payload.upper.value == 24500.0
    assert rec.lifecycle_state == LifecycleState.ACTIVE


# ----------------------------------------------------
# 3. FVGEngine Adapter Tests
# ----------------------------------------------------

def test_fvg_imbalance_adaptation():
    adapter = FVGAdapter()
    native_out = [{"top": 24520.0, "bottom": 24500.0, "is_bullish": True, "mitigated": False}]
    res = adapter.adapt(
        native_output=native_out, source_bars=_sample_bars(),
        instrument_identity=_sample_identity(), timeframe="5m",
        evaluation_context=_sample_ctx(),
    )
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.FVG_BULLISH
    assert rec.family == EventFamily.IMBALANCE
    assert rec.payload.lower.value == 24500.0


# ----------------------------------------------------
# 4. LiquidityEngine Adapter Tests
# ----------------------------------------------------

def test_liquidity_pool_adaptation():
    adapter = LiquidityAdapter()
    native_out = {"eqh": [{"price": 24550.0}]}
    res = adapter.adapt(
        native_output=native_out, source_bars=_sample_bars(),
        instrument_identity=_sample_identity(), timeframe="5m",
        evaluation_context=_sample_ctx(),
    )
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.LIQUIDITY_POOL_HIGH
    assert rec.payload.primary_level.value == 24550.0


# ----------------------------------------------------
# 5. OracleDev Adapter Tests
# ----------------------------------------------------

def test_oracle_dev_regime_adaptation():
    adapter = OracleDevAdapter()
    native_out = {"trend": "BULLISH_TREND"}
    res = adapter.adapt(
        native_output=native_out, source_bars=_sample_bars(),
        instrument_identity=_sample_identity(), timeframe="5m",
        evaluation_context=_sample_ctx(),
    )
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.TREND_BULLISH
    assert rec.payload.state_code == "BULLISH_TREND"


# ----------------------------------------------------
# 6. Exact Price Quantization Tests
# ----------------------------------------------------

def test_exact_price_quantization():
    atom, diag = quantize_price(24500.000000000004, quantum="0.01")
    assert atom.ticks == 2450000
    assert atom.value == 24500.0
    assert diag.rounding_delta < 1e-10

    # Float string vs direct
    atom_str, _ = quantize_price("24500.00", quantum="0.01")
    assert atom_str.ticks == 2450000

    # Boolean rejected
    with pytest.raises(EyeContractError, match="Boolean input rejected"):
        quantize_price(True, quantum="0.01")


# ----------------------------------------------------
# 7. Cross-Producer Conflict Preservation Tests
# ----------------------------------------------------

def test_cross_producer_bos_isolation():
    struct_adapter = StructureV2Adapter()
    beluga_adapter = BigBelugaAdapter()

    res_s = struct_adapter.adapt(
        native_output={"bos": "BULLISH_BOS", "last_high": {"price": 24500.0}},
        source_bars=_sample_bars(), instrument_identity=_sample_identity(),
        timeframe="5m", evaluation_context=_sample_ctx(),
    )
    res_b = beluga_adapter.adapt(
        native_output=[{"top": 24500.0, "bottom": 24450.0, "is_bullish": True}],
        source_bars=_sample_bars(), instrument_identity=_sample_identity(),
        timeframe="5m", evaluation_context=_sample_ctx(),
    )

    rec_s = res_s.records[0]
    rec_b = res_b.records[0]

    # Different rule IDs and rule versions keep events isolated!
    assert rec_s.producer.rule_id == "STRUCTURE_V2_BOS_CLOSE_V1"
    assert rec_b.producer.rule_id == "BIGBELUGA_OB_CLOSE_MITIGATION_V1"
    assert rec_s.event_key != rec_b.event_key


# ----------------------------------------------------
# 8. Replay Harness & Incremental Parity Tests
# ----------------------------------------------------

def test_offline_replay_parity():
    harness = OfflineReplayHarness()
    bars = _sample_bars()
    inst = _sample_identity()

    def dummy_eval(sub_bars):
        if len(sub_bars) >= 2:
            return {"bos": "BULLISH_BOS", "last_high": {"price": 24500.0}}
        return {"bos": "NONE"}

    parity_res = harness.compare_parity(
        producer_name="structure_v2",
        fixture_bars=bars,
        instrument_identity=inst,
        timeframe="5m",
        native_evaluator=dummy_eval,
    )
    assert parity_res.producer == "structure_v2"
    assert parity_res.is_parity is True
    assert parity_res.prefix_invariance_status == PrefixInvarianceStatus.PREFIX_STABLE


# ----------------------------------------------------
# 9. Rule Registry Provenance Verification
# ----------------------------------------------------

def test_default_native_rule_registry():
    registry = RuleRegistry()
    rules = registry.list_all()
    assert len(rules) >= 5

    r_struct = registry.get("STRUCTURE_V2_BOS_CLOSE_V1", "1.0.0")
    assert r_struct is not None
    assert r_struct.status == RuleStatus.ACTIVE
    assert r_struct.provenance == ProvenanceType.EXISTING_CITADEL_RULE
    assert r_struct.source_file == "src/structure/structure_engine_v2.py"
