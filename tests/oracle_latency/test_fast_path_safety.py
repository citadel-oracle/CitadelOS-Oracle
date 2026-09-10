import pytest
from src.oracle.tradingview_sync import TradingViewOptionIdentity
from app.main import _phase6a_fast_path

def test_fast_path_safety():
    decision = {
        "current_security_id": "12345",
        "identity_epoch": 10,
        "exact_option": {"premium": 100.0}
    }
    
    # Tick belongs to a previous chart identity (wrong security_id)
    phase5 = {
        "gateway_quotes": {
            "99999": {"ltp": 150.0}
        }
    }
    
    patched = _phase6a_fast_path(decision, phase5)
    assert patched["exact_option"]["premium"] == 100.0
    
    # Tick has wrong identity epoch (e.g. from an old websocket message before chart switched)
    phase5 = {
        "gateway_quotes": {
            "12345": {"ltp": 150.0, "identity_epoch": 9}
        }
    }
    patched = _phase6a_fast_path(decision, phase5)
    # This will fail before repair because the current logic doesn't check identity epoch!
    assert patched["exact_option"]["premium"] == 100.0
