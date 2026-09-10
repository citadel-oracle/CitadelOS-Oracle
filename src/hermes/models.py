"""Typed provider-agnostic HERMES news and event contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class InputKind(str, Enum):
    SCHEDULED_ECONOMIC = "SCHEDULED_ECONOMIC"
    MARKET_NEWS = "MARKET_NEWS"
    SOCIAL_MEDIA_CATALYST = "SOCIAL_MEDIA_CATALYST"
    OFFICIAL_ANNOUNCEMENT = "OFFICIAL_ANNOUNCEMENT"


class EventType(str, Enum):
    ECONOMIC = "ECONOMIC"
    CENTRAL_BANK = "CENTRAL_BANK"
    POLITICAL = "POLITICAL"
    GEOPOLITICAL = "GEOPOLITICAL"
    EARNINGS = "EARNINGS"
    REGULATORY = "REGULATORY"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    BREAKING_NEWS = "BREAKING_NEWS"
    OTHER = "OTHER"


class Impact(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class TimingState(str, Enum):
    UPCOMING = "UPCOMING"
    IMMINENT = "IMMINENT"
    LIVE = "LIVE"
    RECENT = "RECENT"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class SourceConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    OFFICIAL_GOVERNMENT = "OFFICIAL_GOVERNMENT"
    OFFICIAL_CENTRAL_BANK = "OFFICIAL_CENTRAL_BANK"
    OFFICIAL_EXCHANGE = "OFFICIAL_EXCHANGE"
    OFFICIAL_REGULATOR = "OFFICIAL_REGULATOR"
    AUTHENTICATED_OFFICIAL = "AUTHENTICATED_OFFICIAL"
    NEWSWIRE = "NEWSWIRE"
    APPROVED_NEWS_PROVIDER = "APPROVED_NEWS_PROVIDER"
    SECONDARY_AGGREGATOR = "SECONDARY_AGGREGATOR"
    UNVERIFIED_SOCIAL = "UNVERIFIED_SOCIAL"
    UNKNOWN_PUBLISHER = "UNKNOWN_PUBLISHER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AffectedScope:
    country: Optional[str] = None
    market: Optional[str] = None
    indices: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    currency: Optional[str] = None
    commodity: Optional[str] = None
    global_scope: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "market": self.market,
            "indices": list(self.indices),
            "sectors": list(self.sectors),
            "symbols": list(self.symbols),
            "currency": self.currency,
            "commodity": self.commodity,
            "global": self.global_scope,
        }


@dataclass(frozen=True)
class HermesInput:
    input_kind: InputKind
    headline: str
    summary: str = ""
    event_id: Optional[str] = None
    taxonomy_key: Optional[str] = None
    event_type: EventType = EventType.OTHER
    impact: Impact = Impact.UNKNOWN
    sentiment: Sentiment = Sentiment.UNKNOWN
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    source_name: Optional[str] = None
    source_type: SourceType = SourceType.UNKNOWN
    source_url: Optional[str] = None
    provider_name: Optional[str] = None
    raw_provider_id: Optional[str] = None
    is_scheduled: bool = False
    is_confirmed: bool = False
    is_verified_source: Optional[bool] = None
    account_identity: Optional[str] = None
    affected_scope: AffectedScope = AffectedScope()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedHermesEvent:
    event_id: str
    headline: str
    summary: str
    event_type: EventType
    impact: Impact
    sentiment: Sentiment
    timing_state: TimingState
    scheduled_at: Optional[str]
    published_at: Optional[str]
    received_at: Optional[str]
    age_seconds: Optional[float]
    event_countdown_seconds: Optional[float]
    source_name: Optional[str]
    source_type: SourceType
    source_confidence: SourceConfidence
    source_url: Optional[str]
    country: Optional[str]
    market: Optional[str]
    affected_indices: tuple[str, ...]
    affected_sectors: tuple[str, ...]
    affected_symbols: tuple[str, ...]
    currency: Optional[str]
    commodity: Optional[str]
    affects_global: bool
    tags: tuple[str, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    raw_provider_id: Optional[str]
    provider_name: Optional[str]
    is_scheduled: bool
    is_confirmed: bool
    is_conflicting: bool
    duplicate_group_id: Optional[str]
    source_names: tuple[str, ...]
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for field in (
            "event_type",
            "impact",
            "sentiment",
            "timing_state",
            "source_type",
            "source_confidence",
        ):
            value[field] = getattr(self, field).value
        for field in (
            "affected_indices",
            "affected_sectors",
            "affected_symbols",
            "tags",
            "reason_codes",
            "warnings",
            "source_names",
        ):
            value[field] = list(value[field])
        return value


@dataclass(frozen=True)
class HermesSourceMetadata:
    provider_mode: str
    provider_name: Optional[str]
    provider_configured: bool
    advisory_only: bool
    external_refresh_on_read: bool
    fixture_data: bool
    normalized_input_count: int
    rejected_input_count: int
    last_refresh_at: Optional[str]


@dataclass(frozen=True)
class HermesFreshnessMetadata:
    snapshot_age_seconds: Optional[float]
    stale_after_seconds: float
    freshest_event_age_seconds: Optional[float]
    oldest_event_age_seconds: Optional[float]
    timestamp_semantics: str


@dataclass(frozen=True)
class HermesAssessment:
    generated_at: str
    hermes_status: str
    market_session_context: Optional[str]
    overall_event_risk: str
    recommendation: str
    dominant_sentiment: str
    imminent_event_count: Optional[int]
    high_impact_event_count: Optional[int]
    critical_event_count: Optional[int]
    conflicting_event_count: Optional[int]
    stale_event_count: Optional[int]
    next_major_event: Optional[NormalizedHermesEvent]
    top_events: tuple[NormalizedHermesEvent, ...]
    affected_markets: tuple[str, ...]
    affected_indices: tuple[str, ...]
    affected_sectors: tuple[str, ...]
    affected_symbols: tuple[str, ...]
    reason_codes: tuple[str, ...]
    human_readable_summary: str
    warnings: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    maturity_label: str
    source_metadata: HermesSourceMetadata
    freshness_metadata: HermesFreshnessMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "hermes_status": self.hermes_status,
            "market_session_context": self.market_session_context,
            "overall_event_risk": self.overall_event_risk,
            "recommendation": self.recommendation,
            "dominant_sentiment": self.dominant_sentiment,
            "imminent_event_count": self.imminent_event_count,
            "high_impact_event_count": self.high_impact_event_count,
            "critical_event_count": self.critical_event_count,
            "conflicting_event_count": self.conflicting_event_count,
            "stale_event_count": self.stale_event_count,
            "next_major_event": (
                self.next_major_event.to_dict() if self.next_major_event else None
            ),
            "top_events": [event.to_dict() for event in self.top_events],
            "affected_markets": list(self.affected_markets),
            "affected_indices": list(self.affected_indices),
            "affected_sectors": list(self.affected_sectors),
            "affected_symbols": list(self.affected_symbols),
            "reason_codes": list(self.reason_codes),
            "human_readable_summary": self.human_readable_summary,
            "warnings": list(self.warnings),
            "missing_inputs": list(self.missing_inputs),
            "maturity_label": self.maturity_label,
            "source_metadata": asdict(self.source_metadata),
            "freshness_metadata": asdict(self.freshness_metadata),
        }
