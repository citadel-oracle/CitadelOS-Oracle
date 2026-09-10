"""E5A Test for Entry Band Geometry Derivation & Abstention."""

import pytest
from src.eye.oracle_projection.entry_geometry import EntryGeometryBuilder
from src.eye.oracle_projection.contracts import EntryGeometryStatus


def test_entry_band_derived_from_fvg_retest_geometry():
    builder = EntryGeometryBuilder()

    # Bullish FVG retest setup
    setup_event = {
        "family": "DISPLACEMENT_FVG_RETEST",
        "direction": "BULLISH",
        "fvg_low": 24580.0,
        "fvg_high": 24595.0,
        "event_key": "EVT:FVG:101",
    }

    geom = builder.build_entry_geometry(setup_event)
    assert geom.entry_status == EntryGeometryStatus.ACTIVE
    assert geom.entry_low == 24580.0
    assert geom.entry_high == 24595.0
    assert geom.entry_reference == 24587.5
    assert geom.entry_geometry_type == "FVG_RETEST_BAND"
    assert "EVT:FVG:101" in geom.source_event_keys


def test_no_entry_geometry_abstains():
    builder = EntryGeometryBuilder()
    geom = builder.build_entry_geometry(None)

    assert geom.entry_status == EntryGeometryStatus.ENTRY_BAND_NOT_ESTABLISHED
    assert geom.entry_low is None
    assert geom.entry_high is None
    assert geom.entry_reference is None
