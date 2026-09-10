"""Tests for E9 Unified Kernel."""
import pytest
from src.eye.kernel.core import EyeKernel
from src.eye.kernel.domain import MarketEvent, MarketEventType
from src.eye.kernel.services import BarService

def test_kernel_deterministic_dispatch():
    kernel = EyeKernel()
    dispatched = []
    
    def handler(event):
        dispatched.append(event.source_timestamp)
        
    kernel.bus.subscribe(MarketEventType.TICK, handler)
    
    # Publish out of order
    kernel.bus.publish(MarketEvent("e2", MarketEventType.TICK, 1002.0, 1002.0, "NIFTY", "test", {}))
    kernel.bus.publish(MarketEvent("e1", MarketEventType.TICK, 1001.0, 1001.0, "NIFTY", "test", {}))
    kernel.bus.publish(MarketEvent("e3", MarketEventType.TICK, 1003.0, 1003.0, "NIFTY", "test", {}))
    
    kernel.process_cycle()
    
    assert dispatched == [1001.0, 1002.0, 1003.0]

def test_bar_service_aggregation():
    kernel = EyeKernel()
    bar_service = BarService(kernel.bus)
    
    emitted = []
    def handler(event):
        emitted.append(event)
        
    kernel.bus.subscribe(MarketEventType.BAR_CLOSED, handler)
    
    # 03:45 UTC is 09:15 IST
    ts = 1786074300 # 2026-08-07 03:45:00 UTC (9:15 IST)
    
    # Push 3 1m bars
    for i in range(3):
        bar = {"time": ts + i*60, "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0}
        kernel.bus.publish(MarketEvent(f"t{i}", MarketEventType.TICK, ts + i*60, ts + i*60, "NIFTY", "test", {"bar": bar}))
        
    kernel.process_cycle()
    
    assert len(emitted) == 1
    assert emitted[0].payload["timeframe"] == 3
    assert emitted[0].payload["bar"]["time"] == ts + 120
