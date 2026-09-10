"""Typed Event Contracts and Data Schemas for Citadel Live Island."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class ArchetypeType(str, Enum):
    SCALAR = "scalar"
    POLARITY = "polarity"
    DUAL_SIDED = "dual_sided"
    LEVEL = "level"
    IMPULSE = "impulse"


class NumericTrend(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class EventBias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    RISK = "RISK"
    UNCLASSIFIED = "UNCLASSIFIED"


class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PresentationPhase(str, Enum):
    IMPACT = "IMPACT"
    SETTLED = "SETTLED"
    MEMORY = "MEMORY"


@dataclass
class LiveIslandTimestamps:
    feed_ts: Optional[float] = None
    ingest_ts: float = field(default_factory=time.time)
    computed_ts: float = field(default_factory=time.time)
    event_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LiveIslandEvent:
    id: str  # e.g. "vix", "pcr", "gex", "oi_shift", "max_pain", "gamma_blast", "buyers_writers", "buildup"
    family: str  # e.g. "vix", "pcr", "gex", "oi", "option", "regime"
    title: str  # e.g. "India VIX Shock"
    short_title: str  # e.g. "VIX ↑ 17.8"
    archetype: str = ArchetypeType.SCALAR.value
    numeric_trend: str = NumericTrend.FLAT.value
    event_bias: str = EventBias.NEUTRAL.value
    severity: str = SeverityLevel.MEDIUM.value
    phase: str = PresentationPhase.IMPACT.value
    current_value: str = ""
    previous_value: str = ""
    change_percent: float = 0.0
    change_pp: Optional[float] = None  # Percentage points for Buyers/Writers
    velocity: float = 0.0
    acceleration: float = 0.0
    confidence: float = 1.0
    shorthand: str = ""
    secondary_value: str = ""
    reference_window: str = "1m"
    priority_weight: float = 1.0
    timestamps: LiveIslandTimestamps = field(default_factory=LiveIslandTimestamps)
    provenance: str = "ORACLE_LIVE_ISLAND"
    feed_epoch: int = 1
    universe_version: str = "v1"
    archetype_data: Dict[str, Any] = field(default_factory=dict)
    age: int = 0
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_frontend_dict(self) -> Dict[str, Any]:
        """Maps to exact camelCase/snakeCase expected by final-island-engine.js and index.html."""
        return {
            "id": self.id,
            "family": self.family,
            "title": self.title,
            "shortTitle": self.short_title,
            "archetype": self.archetype,
            "numericTrend": self.numeric_trend,
            "eventBias": self.event_bias,
            "severity": self.severity,
            "phase": self.phase,
            "currentValue": self.current_value,
            "previousValue": self.previous_value,
            "changePercent": self.change_percent,
            "changePp": self.change_pp,
            "velocity": self.velocity,
            "acceleration": self.acceleration,
            "confidence": self.confidence,
            "shorthand": self.shorthand or self.short_title,
            "secondaryValue": self.secondary_value,
            "referenceWindow": self.reference_window,
            "priorityWeight": self.priority_weight,
            "archetypeData": self.archetype_data,
            "timestamp": self.created_at_ms,
            "age": self.age,
            "feedEpoch": self.feed_epoch,
            "universeVersion": self.universe_version,
            "provenance": self.provenance,
        }


@dataclass
class LiveIslandPillState:
    spine_bias: Literal["bear", "bull"] = "bear"
    active_events: List[LiveIslandEvent] = field(default_factory=list)  # 0 is Hero, 1..3 are companions
    memory_events: List[LiveIslandEvent] = field(default_factory=list)  # max 3
    burst_count: int = 0
    sequence_id: int = 0
    state_version: int = 1
    updated_at: float = field(default_factory=time.time)

    def to_frontend_payload(self) -> Dict[str, Any]:
        return {
            "spineBias": self.spine_bias,
            "activeEvents": [e.to_frontend_dict() for e in self.active_events[:4]],
            "memoryEvents": [e.to_frontend_dict() for e in self.memory_events[:3]],
            "burstCount": self.burst_count,
            "sequenceId": self.sequence_id,
            "stateVersion": self.state_version,
            "updatedAt": self.updated_at,
        }
