import pytest
import time
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta

from src.api.v2_integration import V2DashboardIntegration
from src.oracle.tradingview_sync import TradingViewAutoSyncService
from src.kronos_alpha.candle_source import RealNiftyCandleSource

def test_strategies_blocks_projection():
    integration = V2DashboardIntegration(providers={})
    
    def slow_strategies():
        time.sleep(0.5)
        return {"ok": True, "data": {}}
        
    integration.providers = {
        "snapshot": lambda: {"ok": True, "data": {}},
        "kronos_alpha": lambda: {"ok": True, "data": {}},
        "chronos2": lambda: {"ok": True, "data": {}},
        "oracle": lambda sym: {"ok": True, "data": {}},
        "athena": lambda: {"ok": True, "data": {}},
        "hermes": lambda: {"ok": True, "data": {}},
        "argus": lambda sym: {"ok": True, "data": {}},
        "risk_status": lambda: {"ok": True, "data": {}},
        "kill_switch": lambda: {"ok": True, "data": {}},
        "paper_status": lambda: {"ok": True, "data": {}},
        "personal_oracle": lambda: {"ok": True, "data": {}},
        "readiness": lambda: {"ok": True, "data": {}},
        "next_session_plan": lambda: {"ok": True, "data": {}},
        "order_ledger": lambda: {"ok": True, "data": {}},
        "paper_trading": lambda: {"ok": True, "data": {}},
        "strategies_command": slow_strategies,
    }
    
    start = time.perf_counter()
    res = integration._build_dashboard("NIFTY")
    duration = time.perf_counter() - start
    
    assert duration < 0.1, f"Expected strategies NOT to block, took {duration:.3f}s"

from src.oracle.contracts.tradingview import TradingViewInstrumentIdentity, TradingViewSymbolIdentity, TradingViewRoute

@patch('src.oracle.tradingview_sync.route_tradingview_symbol')
def test_deterministic_analysis_blocks_sse(mock_route):
    # Use real identities to avoid serialization errors during seal()
    mock_instrument = TradingViewInstrumentIdentity(
        route=TradingViewRoute.UNDERLYING_INDEX,
        instrument_id=None,
        security_id=None,
        underlying="NIFTY",
        analysis_supported=True,
        mapping_status="CANONICAL_ANALYSIS_AVAILABLE"
    )
    mock_symbol = TradingViewSymbolIdentity(
        raw_symbol="NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        route=TradingViewRoute.UNDERLYING_INDEX,
        ambiguity_status="RESOLVED"
    )
    mock_route.return_value = (mock_symbol, mock_instrument, None)

    def slow_analysis(chart):
        time.sleep(0.5)
        return {}
        
    service = TradingViewAutoSyncService(
        root="/tmp",
        analysis_provider=slow_analysis
    )
    # the thread starts automatically in start(), but _accept is direct
    
    start = time.perf_counter()
    # Simulate accepting a chart state change
    service._accept({"active_index": 0, "panes": [{"index": 0, "symbol": "NIFTY", "resolution": "5"}]}, datetime.now(timezone.utc))
    duration = time.perf_counter() - start
    
    assert duration < 0.1, f"Expected analysis to NOT block SSE emission, took {duration:.3f}s"

def test_final_5m_candle_systematically_missed():
    source = RealNiftyCandleSource()
    reference = datetime(2026, 8, 5, 15, 30, 0, tzinfo=timezone.utc)
    
    # Mock dhan API response for a candle at 15:25, closing at 15:30
    fetched_candles = [{
        "time": int(reference.timestamp() - 300),
        "open": 100, "high": 105, "low": 95, "close": 102
    }]
    
    mock_result = {"success": True, "candles": fetched_candles, "raw": {"volume": [1000]}}
    
    with patch.object(source.provider, 'get_intraday_candles', return_value=mock_result):
        with patch.object(source.calendar, 'session_for_date', return_value={"session_state": "OPEN"}):
            # Try backfill with reference = 15:30:00
            # By mocking canonical_store = None and the internal fetch, we bypass the db and get just 1 item back (but it enforces 64 usually so we mock that out)
            source.canonical_store = Mock()
            source.canonical_store.load.return_value = fetched_candles # Just to bypass the < 64 check
            # wait, if we mock load to return fetched_candles, the dropping logic is completely bypassed?
            # Let's mock canonical_store to None and patch the 64 check
            pass


