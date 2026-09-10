"""Frozen Replay Adapter for Eye Kernel."""
import json
from pathlib import Path
from typing import List, Dict, Any
from src.eye.kernel.domain import MarketEvent, MarketEventType

class FrozenReplayAdapter:
    """Feeds historical data into the kernel deterministically."""
    
    def __init__(self, kernel):
        self.kernel = kernel
        
    def inject_bars(self, sec_id: str, bars: List[Dict[str, Any]]):
        for bar in bars:
            event = MarketEvent(
                event_id=f"REPLAY_{sec_id}_{bar['time']}",
                event_type=MarketEventType.TICK,
                source_timestamp=float(bar['time']),
                ingest_timestamp=float(bar['time']),
                security_id=sec_id,
                source="Replay",
                payload={"bar": bar}
            )
            self.kernel.bus.publish(event)
