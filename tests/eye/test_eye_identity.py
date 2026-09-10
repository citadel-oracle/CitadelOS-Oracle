"""Tests for Instrument Identity and Identity Epoch Isolation."""

import pytest
from src.eye.contracts import InstrumentIdentity, EyeContractError


def test_underlying_identity_key():
    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
    )
    assert inst.instrument_key == "UNDERLYING_INDEX:NIFTY"


def test_option_identity_key():
    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY260811P24600",
        normalized_symbol="NIFTY260811P24600",
        exchange="NSE",
        instrument_type="EXACT_OPTION",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        expiry="2026-08-11",
        strike=24600.0,
        option_type="PUT",
        security_id="41016",
    )
    assert inst.instrument_key == "EXACT_OPTION:NIFTY:2026-08-11:24600.0:PUT"


def test_call_put_is_not_market_direction():
    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY260811C24500",
        normalized_symbol="NIFTY260811C24500",
        exchange="NSE",
        instrument_type="EXACT_OPTION",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        expiry="2026-08-11",
        strike=24500.0,
        option_type="CALL",
    )
    # Option type is CALL, but instrument identity carries NO market direction
    assert inst.option_type == "CALL"
    assert not hasattr(inst, "direction")


def test_epoch_isolation_between_live_and_replay():
    # Live identity carries identity_epoch
    live_inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        identity_epoch="epoch-20260806-001",
    )
    assert live_inst.identity_epoch == "epoch-20260806-001"

    # Replay context carries replay_run_id without identity_epoch
    replay_inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        replay_run_id="replay-run-20260806-alpha",
    )
    assert replay_inst.replay_run_id == "replay-run-20260806-alpha"
    assert replay_inst.identity_epoch is None
