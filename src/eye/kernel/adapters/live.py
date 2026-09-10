"""Live Dhan Data Adapter for Eye Kernel."""
from typing import Dict, Any
import time

from src.eye.kernel.domain import MarketEvent, MarketEventType
from src.broker.dhan_client import DhanClient

class DhanLiveAdapter:
    """One Canonical Dhan Owner for live market data ingestion."""
    
    def __init__(self, kernel):
        self.kernel = kernel
        self.client = DhanClient()
        self.subscribed_instruments = set()
        
    def subscribe(self, sec_id: str):
        self.subscribed_instruments.add(sec_id)
        
    def start(self):
        # In a full implementation, this manages the singular Dhan WebSocket connection.
        pass
        
    def _on_message(self, message: Dict[str, Any]):
        """Callback from Dhan websocket."""
        # Here we decode and emit TICK events.
        pass
