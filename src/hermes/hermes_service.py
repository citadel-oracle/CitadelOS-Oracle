"""Deterministic, provider-agnostic, read-only HERMES intelligence."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace
from datetime import datetime
from threading import Lock
from typing import Any, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from src.hermes.models import (
    AffectedScope,
    EventType,
    HermesAssessment,
    HermesFreshnessMetadata,
    HermesInput,
    HermesSourceMetadata,
    Impact,
    InputKind,
    NormalizedHermesEvent,
    Sentiment,
    SourceConfidence,
    SourceType,
    TimingState,
)
from src.hermes.providers import HermesProvider
from src.hermes.taxonomy import taxonomy_for


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class HermesConfig:
    imminent_window_seconds: float = 30 * 60
    live_after_seconds: float = 15 * 60
    recent_window_seconds: float = 120 * 60
    relevance_horizon_seconds: float = 6 * 60 * 60
    stale_after_seconds: float = 5 * 60
    top_event_limit: int = 5
    events_api_limit: int = 20

    def __post_init__(self):
        values = (
            self.imminent_window_seconds,
            self.live_after_seconds,
            self.recent_window_seconds,
            self.relevance_horizon_seconds,
            self.stale_after_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("HERMES timing windows must be positive and finite")
        if self.top_event_limit <= 0 or self.events_api_limit <= 0:
            raise ValueError("HERMES output limits must be positive")


class HermesService:
    """Explicit refresh ingestion plus side-effect-free cached read methods."""

    MATURITY_LABEL = "PROVIDER_AGNOSTIC_FOUNDATION_V1"

    def __init__(
        self,
        provider: Optional[HermesProvider] = None,
        *,
        config: Optional[HermesConfig] = None,
        now_provider=None,
    ):
        self.provider = provider
        self.config = config or HermesConfig()
        self.now_provider = now_provider or (lambda: datetime.now(IST))
        self._events: tuple[NormalizedHermesEvent, ...] = ()
        self._last_refresh_at: Optional[datetime] = None
        self._normalized_input_count = 0
        self._rejected_input_count = 0
        self._lock = Lock()

    def refresh_from_provider(self) -> HermesAssessment:
        """Explicit internal ingestion; never called by GET routes or frontend polls."""
        now = self._now()
        if self.provider is None:
            return self.assessment()
        try:
            raw_events = tuple(self.provider.fetch_events())
        except Exception:
            with self._lock:
                self._last_refresh_at = now
                self._events = ()
                self._normalized_input_count = 0
                self._rejected_input_count = 1
            return self.assessment()

        normalized = []
        rejected = 0
        for item in raw_events:
            try:
                normalized.append(self._normalize(item, now))
            except (TypeError, ValueError):
                rejected += 1
        merged = self._merge_duplicates(normalized)
        ordered = tuple(sorted(merged, key=_event_sort_key))
        with self._lock:
            self._events = ordered
            self._last_refresh_at = now
            self._normalized_input_count = len(normalized)
            self._rejected_input_count = rejected
        return self.assessment()

    def assessment(self) -> HermesAssessment:
        """Return current cached state without provider refresh or network activity."""
        now = self._now()
        with self._lock:
            events = self._events
            refreshed_at = self._last_refresh_at
            normalized_count = self._normalized_input_count
            rejected_count = self._rejected_input_count
        current_events = tuple(
            sorted(
                (self._retime_event(event, now) for event in events),
                key=_event_sort_key,
            )
        )
        return self._build_assessment(
            now,
            current_events,
            refreshed_at,
            normalized_count,
            rejected_count,
        )

    def events_payload(self) -> dict[str, Any]:
        assessment = self.assessment()
        now = self._now()
        current = tuple(
            sorted(
                (
                    self._retime_event(event, now)
                    for event in self._current_events()
                ),
                key=_event_sort_key,
            )
        )[: self.config.events_api_limit]
        return {
            "generated_at": assessment.generated_at,
            "hermes_status": assessment.hermes_status,
            "provider_mode": assessment.source_metadata.provider_mode,
            "count": len(current),
            "events": [event.to_dict() for event in current],
            "advisory_only": True,
            "external_refresh_on_read": False,
        }

    def _current_events(self) -> tuple[NormalizedHermesEvent, ...]:
        with self._lock:
            return self._events

    def _normalize(
        self, item: HermesInput, now: datetime
    ) -> NormalizedHermesEvent:
        if not isinstance(item, HermesInput):
            raise TypeError("HERMES providers must return HermesInput values")
        headline = _safe_text(item.headline, 240)
        if not headline:
            raise ValueError("Event headline is required")
        summary = _safe_text(item.summary, 600) or ""
        scheduled_at = _aware(item.scheduled_at)
        published_at = _aware(item.published_at)
        received_at = _aware(item.received_at)
        taxonomy_key = _safe_text(item.taxonomy_key, 80)
        taxonomy = taxonomy_for(taxonomy_key)

        event_type = (
            taxonomy.event_type
            if taxonomy and item.event_type == EventType.OTHER
            else item.event_type
        )
        impact = (
            taxonomy.impact
            if taxonomy and item.impact == Impact.UNKNOWN
            else item.impact
        )
        scope = _merge_scope(
            taxonomy.scope if taxonomy else AffectedScope(),
            item.affected_scope,
        )
        tags = list(taxonomy.tags if taxonomy else ()) + list(item.tags)
        if taxonomy_key:
            tags.append(f"TAXONOMY_{taxonomy_key.upper()}")

        source_type = item.source_type
        if (
            item.input_kind == InputKind.SOCIAL_MEDIA_CATALYST
            and item.is_verified_source is not True
        ):
            source_type = SourceType.UNVERIFIED_SOCIAL
        source_confidence = _source_confidence(
            source_type, item.is_verified_source
        )

        reasons = []
        warnings = []
        if source_confidence == SourceConfidence.HIGH:
            reasons.append("OFFICIAL_SOURCE")
        elif source_confidence == SourceConfidence.LOW:
            reasons.append("SOURCE_CONFIDENCE_LOW")
        elif source_confidence == SourceConfidence.UNKNOWN:
            reasons.append("SOURCE_CONFIDENCE_UNKNOWN")

        if impact == Impact.CRITICAL and source_confidence in {
            SourceConfidence.LOW,
            SourceConfidence.UNKNOWN,
        }:
            impact = Impact.HIGH
            warnings.append("LOW_CONFIDENCE_CRITICAL_IMPACT_CAPPED")

        is_scheduled = (
            item.is_scheduled
            or item.input_kind == InputKind.SCHEDULED_ECONOMIC
        )
        if is_scheduled and scheduled_at is None:
            warnings.append("SCHEDULED_TIME_UNAVAILABLE")
        if item.is_confirmed and is_scheduled:
            reasons.append("SCHEDULED_EVENT_CONFIRMED")
        if item.input_kind == InputKind.MARKET_NEWS and event_type == EventType.BREAKING_NEWS:
            reasons.append("UNSCHEDULED_BREAKING_NEWS")

        timing_state, countdown = self._timing_state(
            event_type,
            is_scheduled,
            scheduled_at,
            published_at,
            received_at,
            now,
        )
        reasons.append(f"EVENT_{timing_state.value}")
        reasons.append(f"{impact.value}_IMPACT_EVENT")
        reasons.extend(_sentiment_reasons(item.sentiment))
        reasons.extend(_scope_reasons(scope))

        observed_at = published_at or received_at
        age = None
        if observed_at is not None:
            age = max(0.0, (now - observed_at).total_seconds())
        elif scheduled_at is not None and scheduled_at <= now:
            age = max(0.0, (now - scheduled_at).total_seconds())

        if scheduled_at is None and published_at is None and received_at is None:
            warnings.append("EVENT_TIME_UNAVAILABLE")
        if not item.source_name:
            warnings.append("SOURCE_NAME_UNAVAILABLE")

        event_id = _safe_text(item.event_id, 120) or _stable_id(
            "event",
            item.provider_name,
            item.raw_provider_id,
            headline,
            scheduled_at.isoformat() if scheduled_at else None,
            published_at.isoformat() if published_at else None,
        )
        source_name = _safe_text(item.source_name, 120)
        return NormalizedHermesEvent(
            event_id=event_id,
            headline=headline,
            summary=summary,
            event_type=event_type,
            impact=impact,
            sentiment=item.sentiment,
            timing_state=timing_state,
            scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
            published_at=published_at.isoformat() if published_at else None,
            received_at=received_at.isoformat() if received_at else None,
            age_seconds=round(age, 3) if age is not None else None,
            event_countdown_seconds=(
                round(countdown, 3) if countdown is not None else None
            ),
            source_name=source_name,
            source_type=source_type,
            source_confidence=source_confidence,
            source_url=_safe_url(item.source_url),
            country=_safe_text(scope.country, 40),
            market=_safe_text(scope.market, 60),
            affected_indices=_safe_values(scope.indices),
            affected_sectors=_safe_values(scope.sectors),
            affected_symbols=_safe_values(scope.symbols),
            currency=_safe_text(scope.currency, 20),
            commodity=_safe_text(scope.commodity, 40),
            affects_global=bool(scope.global_scope),
            tags=_safe_values(tags),
            reason_codes=tuple(_dedupe(reasons)),
            warnings=tuple(_dedupe(warnings)),
            raw_provider_id=_safe_provider_id(item.raw_provider_id),
            provider_name=_safe_text(item.provider_name, 80),
            is_scheduled=is_scheduled,
            is_confirmed=bool(item.is_confirmed),
            is_conflicting=False,
            duplicate_group_id=None,
            source_names=(source_name,) if source_name else (),
            source_count=1,
        )

    def _timing_state(
        self,
        event_type,
        is_scheduled,
        scheduled_at,
        published_at,
        received_at,
        now,
    ):
        if is_scheduled and scheduled_at is not None:
            countdown = (scheduled_at - now).total_seconds()
            if countdown > self.config.imminent_window_seconds:
                return TimingState.UPCOMING, countdown
            if countdown > 0:
                return TimingState.IMMINENT, countdown
            if countdown >= -self.config.live_after_seconds:
                return TimingState.LIVE, countdown
            if countdown >= -self.config.recent_window_seconds:
                return TimingState.RECENT, countdown
            return TimingState.EXPIRED, countdown
        observed = published_at or received_at
        if observed is None:
            return TimingState.UNKNOWN, None
        age = (now - observed).total_seconds()
        if age < 0:
            return TimingState.UNKNOWN, None
        if (
            event_type == EventType.BREAKING_NEWS
            and age <= self.config.live_after_seconds
        ):
            return TimingState.LIVE, None
        if age <= self.config.recent_window_seconds:
            return TimingState.RECENT, None
        return TimingState.EXPIRED, None

    def _retime_event(self, event, now):
        scheduled = (
            datetime.fromisoformat(event.scheduled_at)
            if event.scheduled_at
            else None
        )
        published = (
            datetime.fromisoformat(event.published_at)
            if event.published_at
            else None
        )
        received = (
            datetime.fromisoformat(event.received_at)
            if event.received_at
            else None
        )
        timing, countdown = self._timing_state(
            event.event_type,
            event.is_scheduled,
            scheduled,
            published,
            received,
            now,
        )
        observed = published or received
        age = (
            max(0.0, (now - observed).total_seconds())
            if observed is not None
            else max(0.0, (now - scheduled).total_seconds())
            if scheduled is not None and scheduled <= now
            else None
        )
        reasons = [
            code
            for code in event.reason_codes
            if not code.startswith("EVENT_")
        ] + [f"EVENT_{timing.value}"]
        return replace(
            event,
            timing_state=timing,
            age_seconds=round(age, 3) if age is not None else None,
            event_countdown_seconds=(
                round(countdown, 3) if countdown is not None else None
            ),
            reason_codes=tuple(_dedupe(reasons)),
        )

    def _merge_duplicates(
        self, events: Sequence[NormalizedHermesEvent]
    ) -> list[NormalizedHermesEvent]:
        groups: dict[str, list[NormalizedHermesEvent]] = {}
        for event in events:
            groups.setdefault(_duplicate_key(event), []).append(event)
        return [self._merge_group(key, group) for key, group in groups.items()]

    def _merge_group(
        self, key: str, group: list[NormalizedHermesEvent]
    ) -> NormalizedHermesEvent:
        if len(group) == 1:
            return group[0]
        ordered = sorted(
            group,
            key=lambda item: (
                -_confidence_rank(item.source_confidence),
                -_impact_rank(item.impact),
                item.event_id,
            ),
        )
        representative = ordered[0]
        sentiments = {
            event.sentiment
            for event in group
            if event.sentiment != Sentiment.UNKNOWN
        }
        impacts = {event.impact for event in group}
        scheduled_times = [
            datetime.fromisoformat(event.scheduled_at)
            for event in group
            if event.scheduled_at
        ]
        timing_conflict = (
            len(scheduled_times) > 1
            and (max(scheduled_times) - min(scheduled_times)).total_seconds() > 60
        )
        conflict = len(sentiments) > 1 or len(impacts) > 1 or timing_conflict
        sentiment = Sentiment.MIXED if len(sentiments) > 1 else representative.sentiment
        impact = max(impacts, key=_impact_rank)
        reasons = [
            code for event in group for code in event.reason_codes
        ] + ["DUPLICATE_EVENT_MERGED"]
        warnings = [warning for event in group for warning in event.warnings]
        if conflict:
            reasons.append("CONFLICTING_SOURCES")
            warnings.append("CONFLICTING_SOURCE_EVIDENCE")
        group_id = _stable_id("duplicate", key)
        source_names = _safe_values(
            name for event in group for name in event.source_names
        )
        return replace(
            representative,
            event_id=group_id,
            impact=impact,
            sentiment=sentiment,
            affected_indices=_safe_values(
                value for event in group for value in event.affected_indices
            ),
            affected_sectors=_safe_values(
                value for event in group for value in event.affected_sectors
            ),
            affected_symbols=_safe_values(
                value for event in group for value in event.affected_symbols
            ),
            tags=_safe_values(value for event in group for value in event.tags),
            reason_codes=tuple(_dedupe(reasons)),
            warnings=tuple(_dedupe(warnings)),
            is_conflicting=conflict,
            duplicate_group_id=group_id,
            source_names=source_names,
            source_count=len(group),
        )

    def _build_assessment(
        self,
        now,
        events,
        refreshed_at,
        normalized_count,
        rejected_count,
    ) -> HermesAssessment:
        provider_mode = getattr(self.provider, "mode", "UNCONFIGURED")
        provider_name = _safe_text(getattr(self.provider, "name", None), 80)
        if refreshed_at is None:
            return self._unavailable(now, provider_mode, provider_name)

        snapshot_age = max(0.0, (now - refreshed_at).total_seconds())
        if normalized_count == 0 and rejected_count > 0:
            return self._unavailable(
                now,
                provider_mode,
                provider_name,
                refreshed_at=refreshed_at,
                rejected_count=rejected_count,
            )

        active = tuple(
            event
            for event in events
            if event.timing_state != TimingState.EXPIRED
        )
        stale_events = tuple(
            event
            for event in events
            if event.timing_state == TimingState.EXPIRED
            or (
                event.age_seconds is not None
                and event.age_seconds > self.config.relevance_horizon_seconds
            )
        )
        high = tuple(event for event in active if event.impact == Impact.HIGH)
        critical = tuple(
            event for event in active if event.impact == Impact.CRITICAL
        )
        imminent = tuple(
            event
            for event in active
            if event.timing_state in {TimingState.IMMINENT, TimingState.LIVE}
        )
        conflicts = tuple(event for event in active if event.is_conflicting)
        high_conflict = any(
            event.is_conflicting
            and event.source_confidence == SourceConfidence.HIGH
            for event in active
        )

        stale_snapshot = snapshot_age > self.config.stale_after_seconds
        partial = rejected_count > 0
        fixture = provider_mode == "FIXTURE"
        reasons = ["ADVISORY_ONLY"]
        warnings = []
        missing = ["market_session_context", "live_external_provider"]

        if not active:
            risk = "NONE"
            recommendation = "NORMAL"
            reasons.append("NO_MATERIAL_EVENT")
        elif any(
            event.impact == Impact.CRITICAL
            and event.timing_state in {TimingState.IMMINENT, TimingState.LIVE}
            for event in active
        ):
            risk = "CRITICAL"
            recommendation = "AVOID_NEW_TRADES"
            reasons.extend(
                ["CRITICAL_EVENT", "AVOID_NEW_TRADES_RECOMMENDED"]
            )
        elif any(
            event.impact == Impact.HIGH
            and event.timing_state in {TimingState.IMMINENT, TimingState.LIVE}
            for event in active
        ) or any(
            event.event_type == EventType.BREAKING_NEWS
            and event.impact in {Impact.HIGH, Impact.CRITICAL}
            for event in active
        ) or high_conflict:
            risk = "HIGH"
            recommendation = "WAIT"
            reasons.extend(["HIGH_IMPACT_EVENT", "WAIT_RECOMMENDED"])
        elif high or critical or any(
            event.impact == Impact.MEDIUM for event in active
        ):
            risk = "MODERATE"
            recommendation = "CAUTION"
            reasons.append(
                "HIGH_IMPACT_EVENT" if high or critical else "MEDIUM_IMPACT_EVENT"
            )
        else:
            risk = "LOW"
            recommendation = "NORMAL"
            reasons.append("LOW_IMPACT_EVENT")

        if stale_snapshot:
            status = "STALE"
            risk = "UNKNOWN"
            recommendation = "WAIT"
            reasons.extend(["DATA_STALE", "WAIT_RECOMMENDED"])
            warnings.append("HERMES_SNAPSHOT_STALE")
        elif partial or fixture:
            status = "DEGRADED"
            reasons.extend(["HERMES_DEGRADED", "DATA_PARTIAL"])
            if recommendation == "NORMAL" and partial:
                recommendation = "CAUTION"
            if fixture:
                warnings.append("FIXTURE_DATA_NOT_LIVE")
        else:
            status = "READY"
            reasons.append("HERMES_READY")

        if conflicts:
            reasons.append("CONFLICTING_SOURCES")
            warnings.append("CONFLICTING_SOURCE_EVIDENCE")
        if rejected_count:
            warnings.append("MALFORMED_INPUTS_REJECTED")

        ordered = tuple(sorted(events, key=_event_sort_key))
        top = ordered[: self.config.top_event_limit]
        next_major = next(
            (
                event
                for event in sorted(
                    active,
                    key=lambda item: (
                        item.event_countdown_seconds
                        if item.event_countdown_seconds is not None
                        and item.event_countdown_seconds >= 0
                        else float("inf"),
                        _event_sort_key(item),
                    ),
                )
                if event.impact in {Impact.HIGH, Impact.CRITICAL}
                and event.event_countdown_seconds is not None
                and event.event_countdown_seconds >= 0
            ),
            None,
        )
        sentiment = _dominant_sentiment(active)
        reasons.extend(_sentiment_reasons(Sentiment(sentiment)))
        freshest = min(
            (event.age_seconds for event in events if event.age_seconds is not None),
            default=None,
        )
        oldest = max(
            (event.age_seconds for event in events if event.age_seconds is not None),
            default=None,
        )
        summary = _assessment_summary(
            risk, recommendation, next_major, len(conflicts), status
        )
        return HermesAssessment(
            generated_at=now.isoformat(),
            hermes_status=status,
            market_session_context=None,
            overall_event_risk=risk,
            recommendation=recommendation,
            dominant_sentiment=sentiment,
            imminent_event_count=len(imminent),
            high_impact_event_count=len(high),
            critical_event_count=len(critical),
            conflicting_event_count=len(conflicts),
            stale_event_count=len(stale_events),
            next_major_event=next_major,
            top_events=top,
            affected_markets=_safe_values(
                event.market for event in active if event.market
            ),
            affected_indices=_safe_values(
                value for event in active for value in event.affected_indices
            ),
            affected_sectors=_safe_values(
                value for event in active for value in event.affected_sectors
            ),
            affected_symbols=_safe_values(
                value for event in active for value in event.affected_symbols
            ),
            reason_codes=tuple(_dedupe(reasons)),
            human_readable_summary=summary,
            warnings=tuple(_dedupe(warnings)),
            missing_inputs=tuple(_dedupe(missing)),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=HermesSourceMetadata(
                provider_mode=provider_mode,
                provider_name=provider_name,
                provider_configured=self.provider is not None,
                advisory_only=True,
                external_refresh_on_read=False,
                fixture_data=fixture,
                normalized_input_count=normalized_count,
                rejected_input_count=rejected_count,
                last_refresh_at=refreshed_at.isoformat(),
            ),
            freshness_metadata=HermesFreshnessMetadata(
                snapshot_age_seconds=round(snapshot_age, 3),
                stale_after_seconds=self.config.stale_after_seconds,
                freshest_event_age_seconds=(
                    round(freshest, 3) if freshest is not None else None
                ),
                oldest_event_age_seconds=(
                    round(oldest, 3) if oldest is not None else None
                ),
                timestamp_semantics="provider publication/receipt and scheduled event times",
            ),
        )

    def _unavailable(
        self,
        now,
        provider_mode,
        provider_name,
        *,
        refreshed_at=None,
        rejected_count=0,
    ):
        configured = self.provider is not None
        reason = (
            "DATA_PARTIAL"
            if configured and rejected_count
            else "EXTERNAL_PROVIDER_NOT_CONFIGURED"
        )
        return HermesAssessment(
            generated_at=now.isoformat(),
            hermes_status="UNAVAILABLE" if configured else "NOT_CONFIGURED",
            market_session_context=None,
            overall_event_risk="UNKNOWN",
            recommendation="WAIT",
            dominant_sentiment="UNKNOWN",
            imminent_event_count=None,
            high_impact_event_count=None,
            critical_event_count=None,
            conflicting_event_count=None,
            stale_event_count=None,
            next_major_event=None,
            top_events=(),
            affected_markets=(),
            affected_indices=(),
            affected_sectors=(),
            affected_symbols=(),
            reason_codes=(
                "HERMES_UNAVAILABLE" if configured else "HERMES_NOT_CONFIGURED",
                reason,
                "SENTIMENT_UNKNOWN",
                "ADVISORY_ONLY",
                "WAIT_RECOMMENDED",
            ),
            human_readable_summary=(
                "HERMES has no trustworthy current event set; WAIT is advisory until a configured provider is explicitly refreshed."
            ),
            warnings=(reason,),
            missing_inputs=(
                "market_session_context",
                "current_event_provider_data",
                "source_coverage",
            ),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=HermesSourceMetadata(
                provider_mode=provider_mode,
                provider_name=provider_name,
                provider_configured=configured,
                advisory_only=True,
                external_refresh_on_read=False,
                fixture_data=provider_mode == "FIXTURE",
                normalized_input_count=0,
                rejected_input_count=rejected_count,
                last_refresh_at=(refreshed_at.isoformat() if refreshed_at else None),
            ),
            freshness_metadata=HermesFreshnessMetadata(
                snapshot_age_seconds=(
                    round(max(0.0, (now - refreshed_at).total_seconds()), 3)
                    if refreshed_at
                    else None
                ),
                stale_after_seconds=self.config.stale_after_seconds,
                freshest_event_age_seconds=None,
                oldest_event_age_seconds=None,
                timestamp_semantics="no trustworthy provider snapshot available",
            ),
        )

    def _now(self):
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("HERMES clock must be timezone-aware")
        return value.astimezone(IST)


def _source_confidence(source_type, verified):
    if source_type in {
        SourceType.OFFICIAL_GOVERNMENT,
        SourceType.OFFICIAL_CENTRAL_BANK,
        SourceType.OFFICIAL_EXCHANGE,
        SourceType.OFFICIAL_REGULATOR,
        SourceType.AUTHENTICATED_OFFICIAL,
    } and verified is not False:
        return SourceConfidence.HIGH
    if source_type in {SourceType.NEWSWIRE, SourceType.APPROVED_NEWS_PROVIDER}:
        return SourceConfidence.MEDIUM
    if source_type in {
        SourceType.SECONDARY_AGGREGATOR,
        SourceType.UNVERIFIED_SOCIAL,
        SourceType.UNKNOWN_PUBLISHER,
    }:
        return SourceConfidence.LOW
    return SourceConfidence.UNKNOWN


def _sentiment_reasons(sentiment):
    return [f"SENTIMENT_{sentiment.value}"]


def _scope_reasons(scope):
    reasons = []
    indices = {value.upper() for value in scope.indices}
    if "NIFTY" in indices:
        reasons.append("AFFECTS_NIFTY")
    if "BANKNIFTY" in indices:
        reasons.append("AFFECTS_BANKNIFTY")
    if str(scope.country or "").upper() == "IN":
        reasons.append("AFFECTS_INDIA")
    if str(scope.market or "").upper() == "US":
        reasons.append("AFFECTS_US_MARKET")
    if scope.global_scope:
        reasons.append("AFFECTS_GLOBAL_MARKETS")
    return reasons


def _dominant_sentiment(events):
    values = {
        event.sentiment
        for event in events
        if event.sentiment != Sentiment.UNKNOWN
    }
    if not values:
        return Sentiment.UNKNOWN.value
    if Sentiment.MIXED in values or (
        Sentiment.BULLISH in values and Sentiment.BEARISH in values
    ):
        return Sentiment.MIXED.value
    directional = values - {Sentiment.NEUTRAL}
    if len(directional) == 1:
        return next(iter(directional)).value
    if not directional:
        return Sentiment.NEUTRAL.value
    return Sentiment.MIXED.value


def _assessment_summary(risk, recommendation, next_major, conflicts, status):
    if status == "STALE":
        return "HERMES data is stale; WAIT is advisory until a fresh provider snapshot is ingested."
    if next_major:
        return (
            f"Event risk is {risk}; {recommendation} is advised. Next major event: "
            f"{next_major.headline} ({next_major.timing_state.value})."
        )
    if conflicts:
        return f"Event risk is {risk}; {recommendation} is advised with {conflicts} conflicting event group(s)."
    return f"Event risk is {risk}; {recommendation} is advised from the current normalized event set."


def _merge_scope(default, explicit):
    return AffectedScope(
        country=explicit.country or default.country,
        market=explicit.market or default.market,
        indices=_safe_values((*default.indices, *explicit.indices)),
        sectors=_safe_values((*default.sectors, *explicit.sectors)),
        symbols=_safe_values((*default.symbols, *explicit.symbols)),
        currency=explicit.currency or default.currency,
        commodity=explicit.commodity or default.commodity,
        global_scope=explicit.global_scope or default.global_scope,
    )


def _duplicate_key(event):
    taxonomy = next(
        (tag for tag in event.tags if tag.startswith("TAXONOMY_")), None
    )
    event_time = event.scheduled_at or event.published_at or event.received_at or "UNKNOWN"
    date_key = event_time[:10]
    if taxonomy:
        return f"{taxonomy}|{date_key}"
    headline = re.sub(r"[^a-z0-9]+", " ", event.headline.lower()).strip()
    return f"{headline}|{event_time[:13]}"


def _event_sort_key(event):
    timing_rank = {
        TimingState.LIVE: 0,
        TimingState.IMMINENT: 1,
        TimingState.UPCOMING: 2,
        TimingState.RECENT: 3,
        TimingState.UNKNOWN: 4,
        TimingState.EXPIRED: 5,
    }[event.timing_state]
    countdown = (
        abs(event.event_countdown_seconds)
        if event.event_countdown_seconds is not None
        else float("inf")
    )
    return (-_impact_rank(event.impact), timing_rank, countdown, event.event_id)


def _impact_rank(value):
    return {
        Impact.UNKNOWN: 0,
        Impact.LOW: 1,
        Impact.MEDIUM: 2,
        Impact.HIGH: 3,
        Impact.CRITICAL: 4,
    }[value]


def _confidence_rank(value):
    return {
        SourceConfidence.UNKNOWN: 0,
        SourceConfidence.LOW: 1,
        SourceConfidence.MEDIUM: 2,
        SourceConfidence.HIGH: 3,
    }[value]


def _aware(value):
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("HERMES timestamps must be timezone-aware")
    return value.astimezone(IST)


def _safe_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(str(value).strip())
    except ValueError:
        return None
    try:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        return None
    return urlunsplit((parsed.scheme, host, parsed.path[:300], "", ""))


def _safe_text(value, limit):
    if value is None:
        return None
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text[:limit] or None


def _safe_provider_id(value):
    text = _safe_text(value, 120)
    if text is None or not re.fullmatch(r"[A-Za-z0-9._:-]+", text):
        return None
    if any(
        marker in text.lower()
        for marker in ("token", "secret", "password", "bearer", "credential")
    ):
        return None
    return text


def _safe_values(values):
    return tuple(
        sorted(
            {
                text
                for value in values
                if (text := _safe_text(value, 80)) is not None
            }
        )
    )


def _stable_id(prefix, *values):
    material = "|".join(str(value or "") for value in values)
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def _dedupe(values):
    return list(dict.fromkeys(value for value in values if value))
