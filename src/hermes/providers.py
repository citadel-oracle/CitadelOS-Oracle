"""Offline provider interfaces for future HERMES adapters."""

from __future__ import annotations

from typing import Protocol, Sequence

from src.hermes.models import HermesInput


class HermesProvider(Protocol):
    name: str
    mode: str

    def fetch_events(self) -> Sequence[HermesInput]: ...


class InMemoryHermesProvider:
    """Deterministic provider for local callers and offline tests."""

    mode = "IN_MEMORY"

    def __init__(self, events=(), *, name="in-memory"):
        self.name = str(name)
        self.events = tuple(events)
        self.fetch_count = 0

    def fetch_events(self):
        self.fetch_count += 1
        return self.events


class FixtureHermesProvider(InMemoryHermesProvider):
    """Explicit fixture mode; never represented as live data."""

    mode = "FIXTURE"

    def __init__(self, events=(), *, name="offline-fixture"):
        super().__init__(events, name=name)
