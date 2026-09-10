from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Mapping, Optional

from src.order_flow.contracts import MarketEvent
from src.order_flow.service import OrderFlowService


class MarketCoreShadow:
    """Read-only shadow consumer of the existing canonical decoder.

    The shadow owns no broker client or socket. One raw packet is decoded once
    by the existing Order Flow decoder, and that same immutable MarketEvent is
    passed to the shadow Order Flow consumer.
    """

    def __init__(self, clock_ns: Optional[Callable[[], int]] = None):
        self.clock_ns = clock_ns or time.perf_counter_ns
        self.order_flow = OrderFlowService(clock_ns=self.clock_ns)
        self.market_events: deque[MarketEvent] = deque(maxlen=1000)
        self.events_consumed = 0

    def process_tick(self, tick: Mapping[str, Any]) -> MarketEvent | None:
        """Compatibility shadow tap: decode once, then consume one event."""
        if int(tick.get("response_code") or tick.get("feed_code") or 0) != 8:
            return None
        try:
            event = self.order_flow.decode_market_event(tick)
        except (KeyError, TypeError, ValueError):
            return None
        return self.process_event(event)

    def process_event(self, event: MarketEvent) -> MarketEvent:
        self.market_events.append(event)
        self.order_flow.ingest_market_event(event)
        self.events_consumed += 1
        return event

    def process_recorded_payload(self, payload: Mapping[str, Any]) -> MarketEvent:
        """Consume a genuine recorder frame through its canonical replay decoder."""

        event = self.order_flow.decode_recorded_market_event(payload)
        return self.process_event(event)


class BrainCoreShadow:
    def __init__(self, model_adapter=None):
        self.model = model_adapter
        self.domain_event_journal = deque(maxlen=100)

    def on_market_event(self, evt: MarketEvent):
        # The future process boundary consumes meaningful domain events, not every tick.
        if evt.ltq > 5000:
            self.domain_event_journal.append(
                {
                    "type": "LARGE_TRADE",
                    "event_id": evt.event_id,
                    "volume": evt.ltq,
                    "price": evt.ltp,
                    "timestamp_ns": evt.feed_receive_ns,
                }
            )
