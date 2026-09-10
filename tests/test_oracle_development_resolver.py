"""Focused unit tests for the Oracle Development Instrument Resolver."""

import json
import tempfile
from pathlib import Path
import pytest

from src.oracle_development.instrument_resolver import (
    OracleDevInstrumentResolver,
    InstrumentResolutionError,
)


class MockDhanClient:
    def get_option_expiries(self, segment, security_id):
        return {"data": ["2026-07-29", "2026-08-05"]}


def test_dynamic_strike_interval_parsing():
    """Asserts that strike intervals are parsed dynamically from the option master instead of being hardcoded."""
    dhan = MockDhanClient()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        master_path = Path(tmpdir) / "dhan_master.json"
        
        # 1. Create a dummy option master with strike intervals of 50 for NIFTY
        mock_master_data = {
            "rows": [
                {"UNDERLYING_SYMBOL": "NIFTY", "STRIKE_PRICE": 24000.0},
                {"UNDERLYING_SYMBOL": "NIFTY", "STRIKE_PRICE": 24050.0},
                {"UNDERLYING_SYMBOL": "NIFTY", "STRIKE_PRICE": 24100.0}
            ]
        }
        with open(master_path, "w") as f:
            json.dump(mock_master_data, f)
            
        resolver = OracleDevInstrumentResolver(dhan, option_master_path=master_path)
        
        # Interval must resolve dynamically to 50
        assert resolver.get_strike_interval("NIFTY") == 50.0
        
        # 2. Check fallback for non-existent symbol
        assert resolver.get_strike_interval("UNKNOWN_SYM") == 50.0


def test_atm_and_itm_strike_bounds():
    """Asserts strike boundaries are locked strictly to ATM and maximum 1 strike ITM."""
    dhan = MockDhanClient()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        master_path = Path(tmpdir) / "dhan_master.json"
        
        # Instantiate resolver to get dynamic weekly expiry
        resolver = OracleDevInstrumentResolver(dhan, option_master_path=master_path)
        weekly_expiry = resolver.active_expiries("NSE_FNO", "13")[0]
        
        # Create option master rows for strikes around 24000
        mock_master_data = {
            "rows": [
                {"UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": weekly_expiry, "OPTION_TYPE": "CE", "STRIKE_PRICE": 24000.0, "SECURITY_ID": "CE_24000", "SYMBOL_NAME": "NIFTY-CE-24000"},
                {"UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": weekly_expiry, "OPTION_TYPE": "CE", "STRIKE_PRICE": 24050.0, "SECURITY_ID": "CE_24050", "SYMBOL_NAME": "NIFTY-CE-24050"},
                {"UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": weekly_expiry, "OPTION_TYPE": "CE", "STRIKE_PRICE": 23950.0, "SECURITY_ID": "CE_23950", "SYMBOL_NAME": "NIFTY-CE-23950"},
                {"UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": weekly_expiry, "OPTION_TYPE": "PE", "STRIKE_PRICE": 24000.0, "SECURITY_ID": "PE_24000", "SYMBOL_NAME": "NIFTY-PE-24000"},
                {"UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": weekly_expiry, "OPTION_TYPE": "PE", "STRIKE_PRICE": 24050.0, "SECURITY_ID": "PE_24050", "SYMBOL_NAME": "NIFTY-PE-24050"},
                {"UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": weekly_expiry, "OPTION_TYPE": "PE", "STRIKE_PRICE": 24100.0, "SECURITY_ID": "PE_24100", "SYMBOL_NAME": "NIFTY-PE-24100"}
            ]
        }
        with open(master_path, "w") as f:
            json.dump(mock_master_data, f)
            
        # Re-initialize with master path populated
        resolver = OracleDevInstrumentResolver(dhan, option_master_path=master_path)
        
        # Under Spot 24020, with strike interval 50:
        # ATM strike = 24000
        # ITM CE (1 ITM) = 23950
        # ITM PE (1 ITM) = 24050
        resolved = resolver.resolve_options(spot_price=24020.0, underlying="NIFTY")
        
        assert resolved["ATM_CE"]["strike"] == 24000.0
        assert resolved["ATM_PE"]["strike"] == 24000.0
        assert resolved["ITM_CE_CE"]["strike"] == 23950.0
        assert resolved["ITM_PE_PE"]["strike"] == 24050.0
        
        # Verify no OTM option (e.g. CE 24050, PE 23950) is ever returned in ATM/ITM resolutions
        assert "OTM" not in resolved
        for k, contract in resolved.items():
            if contract["option_type"] == "CE":
                assert contract["strike"] <= 24000.0
            if contract["option_type"] == "PE":
                assert contract["strike"] >= 24000.0


def test_live_subscription_window_resolves_exact_atm_plus_minus_two_without_fabrication():
    dhan = MockDhanClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        master_path = Path(tmpdir) / "dhan_master.json"
        resolver = OracleDevInstrumentResolver(dhan, option_master_path=master_path)
        expiry = resolver.active_expiries("NSE_FNO", "13")[0]
        rows = []
        for strike in (23900, 23950, 24000, 24050, 24100):
            for side in ("CE", "PE"):
                rows.append({
                    "UNDERLYING_SYMBOL": "NIFTY",
                    "SM_EXPIRY_DATE": expiry,
                    "OPTION_TYPE": side,
                    "STRIKE_PRICE": strike,
                    "SECURITY_ID": f"{strike}-{side}",
                })
        master_path.write_text(json.dumps({"rows": rows}))

        window = resolver.resolve_option_window(24020.0, "NIFTY", radius=2)

        assert len(window) == 10
        assert set(window) == {
            f"{label}_{side}"
            for label in ("ATM-2", "ATM-1", "ATM", "ATM+1", "ATM+2")
            for side in ("CE", "PE")
        }
        assert len({item["security_id"] for item in window.values()}) == 10


def test_setup_instrument_locking():
    """Asserts that once a trade setup is active, resolved contracts are locked and rollover is blocked."""
    dhan = MockDhanClient()
    resolver = OracleDevInstrumentResolver(dhan)
    
    setup_id = "test_setup_123"
    instruments = {
        "FUT": {"security_id": "61093", "symbol": "NIFTY-FUT-NEAR"},
        "ATM_CE": {"security_id": "12345", "symbol": "NIFTY-CE-24000"}
    }
    
    # Lock instruments
    resolver.lock_instruments(setup_id, instruments)
    
    # Retrieve locked instruments
    locked = resolver.get_locked_instruments(setup_id)
    assert locked == instruments
    
    # Retrieve locked instruments for non-existent setup
    assert resolver.get_locked_instruments("other_setup") is None
    
    # Clear / Unlock
    resolver.unlock_instruments(setup_id)
    assert resolver.get_locked_instruments(setup_id) is None
