"""E5A Test for Structural Stop & Invalidation Reference Derivation."""

import pytest
from src.eye.oracle_projection.structural_stop import StructuralStopBuilder
from src.eye.oracle_projection.contracts import StructuralStopStatus


def test_structural_stop_derived_from_sweep_extreme():
    builder = StructuralStopBuilder()

    setup_event = {
        "family": "LIQUIDITY_SWEEP_RECLAIM",
        "direction": "BULLISH",
        "sweep_extreme": 24520.0,
        "event_key": "EVT:SWEEP:202",
        "entry_reference": 24580.0,
    }

    stop = builder.build_structural_stop(setup_event)
    assert stop.status == StructuralStopStatus.ACTIVE
    assert stop.sl_price == 24520.0
    assert stop.sl_type == "SWEEP_EXTREME_INVALIDATION"
    assert stop.distance_from_entry == 60.0
    assert stop.source_event_key == "EVT:SWEEP:202"


def test_no_structural_stop_abstains():
    builder = StructuralStopBuilder()
    stop = builder.build_structural_stop(None)

    assert stop.status == StructuralStopStatus.STRUCTURAL_SL_NOT_ESTABLISHED
    assert stop.sl_price is None
    assert stop.distance_from_entry is None
