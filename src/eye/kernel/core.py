"""Core orchestration for the unified Eye Kernel."""
import threading
import heapq
from datetime import datetime
from time import perf_counter
from typing import Dict, List, Callable
from collections import defaultdict
from zoneinfo import ZoneInfo

from src.eye.kernel.domain import MarketEvent, MarketEventType

class MarketEventBus:
    """Event bus ensuring deterministic, ordered dispatch of market events."""
    
    def __init__(self):
        self._subscribers: Dict[MarketEventType, List[Callable[[MarketEvent], None]]] = defaultdict(list)
        self._event_queue = [] # Priority queue for deterministic ordering
        self._counter = 0 # Tie-breaker for identical timestamps
        self._lock = threading.Lock()
        self._seen_event_ids: set[str] = set()
        self.duplicate_event_rejects = 0
        self.max_queue_depth = 0
        self.dispatched_events = 0
        self.handler_errors = 0
        self.event_latency_ms: list[float] = []

    def subscribe(self, event_type: MarketEventType, handler: Callable[[MarketEvent], None]):
        self._subscribers[event_type].append(handler)
        
    def publish(self, event: MarketEvent):
        """Enqueues an event for deterministic dispatch."""
        with self._lock:
            if event.event_id in self._seen_event_ids:
                self.duplicate_event_rejects += 1
                return False
            self._seen_event_ids.add(event.event_id)
            # Ordering: source_timestamp -> insertion sequence
            heapq.heappush(self._event_queue, (event.source_timestamp, self._counter, event))
            self._counter += 1
            self.max_queue_depth = max(self.max_queue_depth, len(self._event_queue))
        return True

    def dispatch_all(self):
        """Drains the queue and dispatches deterministically."""
        while True:
            with self._lock:
                if not self._event_queue:
                    break
                _, _, event = heapq.heappop(self._event_queue)
                
            event_started = perf_counter()
            for handler in self._subscribers[event.event_type]:
                try:
                    handler(event)
                except Exception as e:
                    self.handler_errors += 1
            self.dispatched_events += 1
            self.event_latency_ms.append((perf_counter() - event_started) * 1000.0)
            if len(self.event_latency_ms) > 256:
                del self.event_latency_ms[:-256]

    def telemetry(self) -> dict:
        values = sorted(self.event_latency_ms)
        def percentile(percent: float):
            if not values:
                return None
            return round(values[min(len(values) - 1, int((len(values) - 1) * percent))], 3)
        return {
            "events": self.dispatched_events, "duplicate_event_rejects": self.duplicate_event_rejects,
            "handler_errors": self.handler_errors, "max_queue_depth": self.max_queue_depth,
            "p50_ms": percentile(0.50), "p95_ms": percentile(0.95), "p99_ms": percentile(0.99),
        }

class MarketClock:
    """Deterministic market clock."""
    
    def __init__(self, bus):
        self.bus = bus
        self.milestones = {
            "09:15": "SESSION_OPEN",
            "09:35": "09:35",
            "09:45": "09:45",
            "10:30": "10:30",
            "15:00": "15:00",
            "15:05": "15:05",
            "15:15": "15:15",
            "15:25": "15:25",
            "15:30": "SESSION_END"
        }
        self.triggered = set()
        self.bus.subscribe(MarketEventType.TICK, self._on_tick)
        
    def reset(self):
        self.triggered.clear()
        
    def _on_tick(self, event: MarketEvent):
        self.tick(event.source_timestamp)
        
    def tick(self, ts: float):
        time_str = datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
        
        if time_str in self.milestones and time_str not in self.triggered:
            self.triggered.add(time_str)
            self.bus.publish(MarketEvent(
                event_id=f"CLOCK_{time_str}_{ts}",
                event_type=MarketEventType.SCHEDULED_CLOCK,
                source_timestamp=ts,
                ingest_timestamp=ts,
                security_id="CLOCK",
                source="MarketClock",
                payload={"milestone": self.milestones[time_str]}
            ))

class EyeKernel:
    """Central orchestration component for the unified Eye Kernel."""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self.bus = MarketEventBus()
        self.dependency_router = None
        self.bar_service = None
        self.feature_store = None
        self.option_universe = None
        self.strategy_registry = None
        self.is_running = False
        self.clock = MarketClock(self.bus)
        
    def register_components(self, router, bar_service, feature_store, option_universe, registry):
        self.dependency_router = router
        self.bar_service = bar_service
        self.feature_store = feature_store
        self.option_universe = option_universe
        self.strategy_registry = registry
        
    def start(self):
        self.is_running = True
        
    def stop(self):
        self.is_running = False
        
    def process_cycle(self):
        """Process one deterministic cycle of the kernel (drains the bus)."""
        self.bus.dispatch_all()
