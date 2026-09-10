"""Unit tests for Upstox Option Chain fallback and provenance in ARGUS."""

import pytest
from unittest.mock import MagicMock
from src.argus.option_chain_engine import (
    OptionChainEngine,
    OptionChainDataError,
    OptionChainSnapshot,
)


def test_upstox_chain_conversion_and_provenance():
    mock_upstox = MagicMock()
    mock_dhan = MagicMock()
    # Dhan fails with auth error
    mock_dhan.get_option_expiries.return_value = {
        "status": "failed",
        "data": {"808": "Authentication Failed"},
    }
    mock_dhan.get_option_chain.return_value = {
        "status": "failed",
        "data": {"808": "Authentication Failed"},
    }

    mock_upstox.get_option_contracts.return_value = [
        {"expiry": "2026-09-08", "strike_price": 24000.0, "instrument_key": "NSE_FO|1"},
        {"expiry": "2026-09-15", "strike_price": 24000.0, "instrument_key": "NSE_FO|2"},
    ]
    mock_upstox.get_option_chain.return_value = [
        {
            "expiry": "2026-09-08",
            "strike_price": 24000.0,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_spot_price": 24050.0,
            "call_options": {
                "instrument_key": "NSE_FO|101",
                "market_data": {
                    "ltp": 120.5,
                    "close_price": 115.0,
                    "oi": 50000,
                    "prev_oi": 48000,
                    "volume": 25000,
                    "ask_price": 121.0,
                    "ask_qty": 50,
                    "bid_price": 120.0,
                    "bid_qty": 50,
                },
                "option_greeks": {
                    "delta": 0.52,
                    "gamma": 0.001,
                    "theta": -15.2,
                    "vega": 8.5,
                    "iv": 14.5,
                },
            },
            "put_options": {
                "instrument_key": "NSE_FO|102",
                "market_data": {
                    "ltp": 85.0,
                    "close_price": 90.0,
                    "oi": 60000,
                    "prev_oi": 55000,
                    "volume": 30000,
                    "ask_price": 85.5,
                    "ask_qty": 100,
                    "bid_price": 84.5,
                    "bid_qty": 100,
                },
                "option_greeks": {
                    "delta": -0.48,
                    "gamma": 0.001,
                    "theta": -14.8,
                    "vega": 8.3,
                    "iv": 15.0,
                },
            },
        }
    ]

    engine = OptionChainEngine(dhan=mock_dhan, upstox=mock_upstox)

    # Expiries should fall back to Upstox
    expiries = engine.active_expiries("IDX_I", 13)
    assert "2026-09-08" in expiries

    # Snapshot should fall back to Upstox
    snap = engine.fetch_current_snapshot("NIFTY", "IDX_I", 13, expiry="2026-09-08")
    assert isinstance(snap, OptionChainSnapshot)
    assert snap.source == "UPSTOX"
    assert snap.provider == "UPSTOX"
    assert snap.underlying_ltp == 24050.0
    assert snap.atm_strike == 24000.0
    assert len(snap.strikes) == 1
    assert snap.totals.ce_oi == 50000
    assert snap.totals.pe_oi == 60000
