"""Single-Writer Pill Reducer Enforcing 1 Hero + 3 Active + 3 Memory Capacity."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Literal, Optional

from src.oracle.live_island.contracts import (
    LiveIslandEvent,
    LiveIslandPillState,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.registry import DEFAULT_REGISTRY, LiveIslandRegistry

logger = logging.getLogger(__name__)


class LiveIslandReducer:
    """State reducer enforcing layout capacity, hysteresis, coalescing, and memory rules."""

    def __init__(
        self,
        registry: LiveIslandRegistry = DEFAULT_REGISTRY,
        on_state_change: Optional[Callable[[LiveIslandPillState], None]] = None,
    ) -> None:
        self.registry = registry
        self.on_state_change = on_state_change
        self._lock = threading.RLock()

        self._spine_bias: Literal["bear", "bull"] = "bear"
        self._active_events: List[LiveIslandEvent] = []  # Index 0 is Hero, 1..3 are companions
        self._memory_events: List[LiveIslandEvent] = []  # Max 3
        self._hero_locked_until: float = 0.0
        self._sequence_id: int = 0
        self._state_version: int = 1
        self._current_burst_count: int = 0

        # Burst coalescing state
        self._pending_burst: List[LiveIslandEvent] = []
        self._burst_timer: Optional[threading.Timer] = None

    @property
    def current_state(self) -> LiveIslandPillState:
        with self._lock:
            return LiveIslandPillState(
                spine_bias=self._spine_bias,
                active_events=list(self._active_events),
                memory_events=list(self._memory_events),
                burst_count=self._current_burst_count,
                sequence_id=self._sequence_id,
                state_version=self._state_version,
                updated_at=time.time(),
            )

    def set_spine_bias(self, bias: Literal["bear", "bull"]) -> None:
        with self._lock:
            if self._spine_bias != bias:
                self._spine_bias = bias
                self._state_version += 1
                self._dispatch_state()

    def dispatch_event(self, event: LiveIslandEvent) -> None:
        """Entry point for detector events. Handles burst coalescing and critical bypass."""
        with self._lock:
            # Critical bypass or disabled burst window: Immediate processing
            if event.severity == SeverityLevel.CRITICAL.value or self.registry.burst_window_ms <= 0:
                self._process_single_event(event)
                self._dispatch_state()
                return

            # Otherwise coalesce within burst_window_ms
            self._pending_burst.append(event)
            if self._burst_timer is None:
                delay = self.registry.burst_window_ms / 1000.0
                self._burst_timer = threading.Timer(delay, self._flush_burst)
                self._burst_timer.daemon = True
                self._burst_timer.start()

    def _flush_burst(self) -> None:
        with self._lock:
            self._burst_timer = None
            if not self._pending_burst:
                return

            self._current_burst_count = len(self._pending_burst)
            # Sort pending events by priority weight descending
            sorted_events = sorted(self._pending_burst, key=lambda e: e.priority_weight, reverse=True)
            self._pending_burst.clear()

            for ev in sorted_events:
                self._process_single_event(ev)

            self._dispatch_state()

    def _process_single_event(self, event: LiveIslandEvent) -> None:
        now = time.time()
        event.created_at_ms = int(now * 1000)
        event.updated_at_ms = int(now * 1000)
        event.phase = PresentationPhase.IMPACT.value

        # 1. In-place Update Check
        existing_idx = None
        for idx, existing in enumerate(self._active_events):
            if existing.id == event.id or existing.family == event.family:
                existing_idx = idx
                break

        if existing_idx is not None:
            # Update existing event in-place
            incumbent = self._active_events[existing_idx]
            event.previous_value = incumbent.current_value
            self._active_events[existing_idx] = event

            # If updated event is incumbent Hero, refresh tenure only if state actually changed
            if existing_idx == 0 and event.current_value != incumbent.current_value:
                self._hero_locked_until = now + (self.registry.hero_min_tenure_ms / 1000.0)
            return

        # 2. Check Memory Eviction / Contradiction
        # If an opposing directional event arrives for same family, remove contradictory memory
        self._memory_events = [
            m for m in self._memory_events
            if not (m.family == event.family and m.numeric_trend != event.numeric_trend)
        ]

        # 3. Hero Takeover Evaluation
        if not self._active_events:
            self._active_events.append(event)
            self._hero_locked_until = now + (self.registry.hero_min_tenure_ms / 1000.0)
            return

        incumbent_hero = self._active_events[0]
        can_take_hero = False

        if event.severity == SeverityLevel.CRITICAL.value and incumbent_hero.severity != SeverityLevel.CRITICAL.value:
            can_take_hero = True
        elif now >= self._hero_locked_until:
            if incumbent_hero.phase == PresentationPhase.SETTLED.value:
                if event.priority_weight >= incumbent_hero.priority_weight:
                    can_take_hero = True
            elif event.priority_weight > (incumbent_hero.priority_weight * self.registry.hero_takeover_margin):
                can_take_hero = True

        if can_take_hero:
            # Demote current Hero to Companion
            self._active_events.insert(0, event)
            self._hero_locked_until = now + (self.registry.hero_min_tenure_ms / 1000.0)
        else:
            # Append as Companion
            self._active_events.append(event)

        # 4. Enforce Active Capacity (Max 4: 1 Hero + 3 Companions)
        while len(self._active_events) > self.registry.max_active_events:
            # Hero (index 0) is protected by hysteresis; evict the lowest priority companion
            lowest_idx = 1
            lowest_weight = self._active_events[1].priority_weight
            for i in range(2, len(self._active_events)):
                if self._active_events[i].priority_weight < lowest_weight:
                    lowest_weight = self._active_events[i].priority_weight
                    lowest_idx = i
            evicted = self._active_events.pop(lowest_idx)
            evicted.phase = PresentationPhase.MEMORY.value
            self._add_to_memory(evicted)

    def _add_to_memory(self, event: LiveIslandEvent) -> None:
        """Adds an event to memory plane, enforcing max capacity of 3 items."""
        # Check if same family already exists in memory; replace if so
        self._memory_events = [m for m in self._memory_events if m.id != event.id and m.family != event.family]
        self._memory_events.insert(0, event)

        # Enforce max memory capacity
        while len(self._memory_events) > self.registry.max_memory_events:
            self._memory_events.pop()

    def tick_phases(self) -> None:
        """Called periodically (e.g. 1s) to advance IMPACT -> SETTLED and evict expired memory."""
        with self._lock:
            now = time.time()
            changed = False
            impact_sec = self.registry.impact_duration_ms / 1000.0

            for ev in self._active_events:
                ev.age = int(now - (ev.created_at_ms / 1000.0))
                if ev.phase == PresentationPhase.IMPACT.value and (now - (ev.created_at_ms / 1000.0)) >= impact_sec:
                    ev.phase = PresentationPhase.SETTLED.value
                    changed = True

            # Evict memory items older than memory_ttl_seconds
            initial_mem_count = len(self._memory_events)
            self._memory_events = [
                m for m in self._memory_events
                if (now - (m.created_at_ms / 1000.0)) < self.registry.memory_ttl_seconds
            ]
            if len(self._memory_events) != initial_mem_count:
                changed = True

            if changed:
                self._dispatch_state()

    def invalidate_event(self, family: str) -> None:
        """Manually or rule-driven invalidation moving an active family event to memory."""
        with self._lock:
            idx_to_remove = None
            for idx, ev in enumerate(self._active_events):
                if ev.family == family:
                    idx_to_remove = idx
                    break
            if idx_to_remove is not None:
                ev = self._active_events.pop(idx_to_remove)
                ev.phase = PresentationPhase.MEMORY.value
                self._add_to_memory(ev)
                self._dispatch_state()

    def _dispatch_state(self) -> None:
        self._sequence_id += 1
        self._state_version += 1
        if self.on_state_change:
            state = self.current_state
            self.on_state_change(state)
