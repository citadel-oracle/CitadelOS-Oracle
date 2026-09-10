"""Synchronous internal event bus for one isolated Strategy Lab runtime."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    entity_id: str
    parent_id: Optional[str]
    lineage: Sequence[str]
    payload: Mapping[str, Any]
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_type or not self.entity_id:
            raise ValueError("domain event type and entity ID are required")
        if not self.event_id:
            canonical = "|".join((self.event_type, self.entity_id, self.parent_id or "ROOT"))
            object.__setattr__(self, "event_id", f"evt_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}")

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["lineage"] = list(self.lineage)
        value["payload"] = dict(self.payload)
        return value


EventHandler = Callable[[DomainEvent], None]


class InternalEventBus:
    """In-process publish/subscribe; a recorder subscriber supplies durability."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._all: List[EventHandler] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self._all.append(handler)

    def publish(self, event: DomainEvent) -> DomainEvent:
        for handler in tuple(self._all):
            handler(event)
        for handler in tuple(self._subscribers.get(event.event_type, ())):
            handler(event)
        return event
