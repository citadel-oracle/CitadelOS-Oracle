import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.hermes import (
    AffectedScope,
    EventType,
    FixtureHermesProvider,
    HermesInput,
    HermesService,
    Impact,
    InMemoryHermesProvider,
    InputKind,
    Sentiment,
    SourceConfidence,
    SourceType,
    TimingState,
)


pytestmark = [pytest.mark.unit, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 11, 10, 0, tzinfo=IST)


class MutableClock:
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


def event(
    headline="Event",
    *,
    impact=Impact.LOW,
    sentiment=Sentiment.UNKNOWN,
    event_type=EventType.ECONOMIC,
    scheduled_at=None,
    published_at=NOW - timedelta(minutes=5),
    source_name="Test Source",
    source_type=SourceType.NEWSWIRE,
    taxonomy_key=None,
    input_kind=InputKind.MARKET_NEWS,
    confirmed=False,
    verified=None,
    scope=AffectedScope(),
    source_url=None,
):
    return HermesInput(
        input_kind=input_kind,
        headline=headline,
        summary="Bounded offline fixture event",
        taxonomy_key=taxonomy_key,
        event_type=event_type,
        impact=impact,
        sentiment=sentiment,
        scheduled_at=scheduled_at,
        published_at=published_at,
        received_at=NOW - timedelta(minutes=4),
        source_name=source_name,
        source_type=source_type,
        source_url=source_url,
        provider_name="pytest",
        raw_provider_id=f"raw-{headline}",
        is_scheduled=scheduled_at is not None,
        is_confirmed=confirmed,
        is_verified_source=verified,
        affected_scope=scope,
    )


def service(events=(), *, clock=None, fixture=False):
    provider_class = FixtureHermesProvider if fixture else InMemoryHermesProvider
    provider = provider_class(events)
    hermes = HermesService(provider, now_provider=clock or MutableClock())
    return hermes, provider


def test_no_event_normal_state():
    hermes, _ = service()

    result = hermes.refresh_from_provider()

    assert result.hermes_status == "READY"
    assert result.overall_event_risk == "NONE"
    assert result.recommendation == "NORMAL"
    assert "NO_MATERIAL_EVENT" in result.reason_codes


def test_low_impact_event_remains_normal():
    hermes, _ = service([event()])

    result = hermes.refresh_from_provider()

    assert result.overall_event_risk == "LOW"
    assert result.recommendation == "NORMAL"
    assert "LOW_IMPACT_EVENT" in result.reason_codes


def test_medium_impact_event_maps_to_caution():
    hermes, _ = service([event(impact=Impact.MEDIUM)])

    result = hermes.refresh_from_provider()

    assert result.overall_event_risk == "MODERATE"
    assert result.recommendation == "CAUTION"
    assert "MEDIUM_IMPACT_EVENT" in result.reason_codes


def test_high_impact_imminent_event_maps_to_wait():
    hermes, _ = service(
        [
            event(
                impact=Impact.HIGH,
                scheduled_at=NOW + timedelta(minutes=20),
                published_at=NOW - timedelta(minutes=2),
                input_kind=InputKind.SCHEDULED_ECONOMIC,
                confirmed=True,
            )
        ]
    )

    result = hermes.refresh_from_provider()

    assert result.overall_event_risk == "HIGH"
    assert result.recommendation == "WAIT"
    assert result.imminent_event_count == 1
    assert "EVENT_IMMINENT" in result.top_events[0].reason_codes
    assert "WAIT_RECOMMENDED" in result.reason_codes


def test_critical_live_official_event_avoids_new_trades():
    hermes, _ = service(
        [
            event(
                impact=Impact.CRITICAL,
                scheduled_at=NOW - timedelta(minutes=5),
                published_at=NOW - timedelta(minutes=1),
                source_type=SourceType.OFFICIAL_CENTRAL_BANK,
                input_kind=InputKind.SCHEDULED_ECONOMIC,
                confirmed=True,
                verified=True,
            )
        ]
    )

    result = hermes.refresh_from_provider()

    assert result.overall_event_risk == "CRITICAL"
    assert result.recommendation == "AVOID_NEW_TRADES"
    assert result.critical_event_count == 1
    assert "CRITICAL_EVENT" in result.reason_codes
    assert "AVOID_NEW_TRADES_RECOMMENDED" in result.reason_codes


def test_official_source_confidence_is_high():
    hermes, _ = service(
        [event(source_type=SourceType.OFFICIAL_REGULATOR, verified=True)]
    )

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.source_confidence == SourceConfidence.HIGH
    assert "OFFICIAL_SOURCE" in normalized.reason_codes


def test_low_confidence_source_cannot_alone_be_critical():
    hermes, _ = service(
        [
            event(
                impact=Impact.CRITICAL,
                source_type=SourceType.SECONDARY_AGGREGATOR,
            )
        ]
    )

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.impact == Impact.HIGH
    assert normalized.source_confidence == SourceConfidence.LOW
    assert "LOW_CONFIDENCE_CRITICAL_IMPACT_CAPPED" in normalized.warnings


def test_unknown_sentiment_remains_unknown():
    hermes, _ = service([event(sentiment=Sentiment.UNKNOWN)])

    result = hermes.refresh_from_provider()

    assert result.dominant_sentiment == "UNKNOWN"
    assert result.top_events[0].sentiment == Sentiment.UNKNOWN
    assert "SENTIMENT_UNKNOWN" in result.reason_codes


def test_conflicting_high_confidence_sources_are_explicit():
    when = NOW + timedelta(minutes=45)
    events = [
        event(
            "RBI policy decision",
            taxonomy_key="RBI_RATE_DECISION",
            sentiment=Sentiment.BULLISH,
            scheduled_at=when,
            source_name="Official A",
            source_type=SourceType.OFFICIAL_CENTRAL_BANK,
            input_kind=InputKind.SCHEDULED_ECONOMIC,
            verified=True,
        ),
        event(
            "Reserve Bank policy outcome",
            taxonomy_key="RBI_RATE_DECISION",
            sentiment=Sentiment.BEARISH,
            scheduled_at=when + timedelta(minutes=10),
            source_name="Official B",
            source_type=SourceType.OFFICIAL_GOVERNMENT,
            input_kind=InputKind.SCHEDULED_ECONOMIC,
            verified=True,
        ),
    ]
    hermes, _ = service(events)

    result = hermes.refresh_from_provider()

    assert len(result.top_events) == 1
    assert result.top_events[0].is_conflicting is True
    assert result.top_events[0].sentiment == Sentiment.MIXED
    assert result.conflicting_event_count == 1
    assert result.recommendation == "WAIT"
    assert "CONFLICTING_SOURCES" in result.reason_codes


def test_duplicate_event_merging_preserves_source_traceability():
    duplicate = event("US CPI release", taxonomy_key="US_CPI")
    second = event(
        "US inflation report",
        taxonomy_key="US_CPI",
        source_name="Second Source",
    )
    hermes, _ = service([duplicate, second])

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.source_count == 2
    assert normalized.duplicate_group_id is not None
    assert normalized.source_names == ("Second Source", "Test Source")
    assert "DUPLICATE_EVENT_MERGED" in normalized.reason_codes


@pytest.mark.parametrize(
    ("offset_minutes", "expected"),
    [
        (60, TimingState.UPCOMING),
        (20, TimingState.IMMINENT),
        (-5, TimingState.LIVE),
        (-60, TimingState.RECENT),
        (-180, TimingState.EXPIRED),
    ],
)
def test_scheduled_event_timing_states(offset_minutes, expected):
    hermes, _ = service(
        [
            event(
                scheduled_at=NOW + timedelta(minutes=offset_minutes),
                input_kind=InputKind.SCHEDULED_ECONOMIC,
            )
        ]
    )

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.timing_state == expected


def test_unscheduled_breaking_news_is_handled_without_inventing_sentiment():
    hermes, _ = service(
        [
            event(
                impact=Impact.HIGH,
                event_type=EventType.BREAKING_NEWS,
                published_at=NOW - timedelta(minutes=3),
                sentiment=Sentiment.UNKNOWN,
            )
        ]
    )

    result = hermes.refresh_from_provider()

    assert result.recommendation == "WAIT"
    assert result.top_events[0].timing_state == TimingState.LIVE
    assert result.top_events[0].sentiment == Sentiment.UNKNOWN
    assert "UNSCHEDULED_BREAKING_NEWS" in result.top_events[0].reason_codes


def test_stale_snapshot_never_defaults_to_normal():
    clock = MutableClock()
    hermes, _ = service([], clock=clock)
    hermes.refresh_from_provider()
    clock.value = NOW + timedelta(minutes=6)

    result = hermes.assessment()

    assert result.hermes_status == "STALE"
    assert result.overall_event_risk == "UNKNOWN"
    assert result.recommendation == "WAIT"
    assert "DATA_STALE" in result.reason_codes


def test_unavailable_provider_is_truthful_and_does_not_default_normal():
    hermes = HermesService(provider=None, now_provider=lambda: NOW)

    result = hermes.assessment()

    assert result.hermes_status == "NOT_CONFIGURED"
    assert result.overall_event_risk == "UNKNOWN"
    assert result.recommendation == "WAIT"
    assert result.top_events == ()
    assert "EXTERNAL_PROVIDER_NOT_CONFIGURED" in result.reason_codes


def test_malformed_provider_input_fails_safely():
    hermes, provider = service()
    provider.events = ({"headline": "untyped payload"},)

    result = hermes.refresh_from_provider()

    assert result.hermes_status == "UNAVAILABLE"
    assert result.recommendation == "WAIT"
    assert result.source_metadata.rejected_input_count == 1


def test_missing_event_time_and_source_metadata_remain_unknown():
    hermes, _ = service(
        [
            event(
                published_at=None,
                source_name=None,
                source_type=SourceType.UNKNOWN,
            )
        ]
    )

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.timing_state == TimingState.RECENT
    assert normalized.source_confidence == SourceConfidence.UNKNOWN
    assert "SOURCE_NAME_UNAVAILABLE" in normalized.warnings
    assert "SOURCE_CONFIDENCE_UNKNOWN" in normalized.reason_codes


def test_completely_missing_event_time_is_unknown():
    value = event(published_at=None)
    value = HermesInput(**{**value.__dict__, "received_at": None})
    hermes, _ = service([value])

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.timing_state == TimingState.UNKNOWN
    assert normalized.age_seconds is None
    assert "EVENT_TIME_UNAVAILABLE" in normalized.warnings


def test_india_taxonomy_is_supported_without_headline_guessing():
    keys = (
        "RBI_RATE_DECISION",
        "RBI_SPEECH",
        "INDIA_CPI",
        "INDIA_WPI",
        "INDIA_PMI",
        "INDIA_GDP",
        "INDIA_IIP",
        "INDIA_BUDGET",
        "INDIA_ELECTION_RESULT",
        "SEBI_REGULATORY_EVENT",
        "EXCHANGE_CIRCULAR",
    )
    for key in keys:
        hermes, _ = service([event(taxonomy_key=key, impact=Impact.UNKNOWN)])
        normalized = hermes.refresh_from_provider().top_events[0]
        assert normalized.country == "IN"
        assert "NIFTY" in normalized.affected_indices
        assert normalized.impact != Impact.UNKNOWN


def test_global_taxonomy_is_supported():
    keys = (
        "FED_RATE_DECISION",
        "FOMC_MINUTES",
        "US_CPI",
        "US_PPI",
        "US_NFP",
        "US_UNEMPLOYMENT",
        "US_GDP",
        "US_PMI",
        "ECB_RATE_DECISION",
        "BOE_RATE_DECISION",
        "GEOPOLITICAL_EVENT",
        "MAJOR_ELECTION_OUTCOME",
        "MAJOR_TARIFF_ANNOUNCEMENT",
        "OFFICIAL_SOCIAL_MEDIA_STATEMENT",
    )
    for key in keys:
        hermes, _ = service([event(taxonomy_key=key, impact=Impact.UNKNOWN)])
        normalized = hermes.refresh_from_provider().top_events[0]
        assert normalized.affects_global is True
        assert normalized.impact != Impact.UNKNOWN


def test_unverified_social_media_remains_low_confidence():
    hermes, _ = service(
        [
            event(
                taxonomy_key="OFFICIAL_SOCIAL_MEDIA_STATEMENT",
                impact=Impact.CRITICAL,
                event_type=EventType.OTHER,
                input_kind=InputKind.SOCIAL_MEDIA_CATALYST,
                source_type=SourceType.AUTHENTICATED_OFFICIAL,
                verified=False,
            )
        ]
    )

    normalized = hermes.refresh_from_provider().top_events[0]

    assert normalized.event_type == EventType.SOCIAL_MEDIA
    assert normalized.source_confidence == SourceConfidence.LOW
    assert normalized.impact == Impact.HIGH


def test_event_ordering_and_top_output_are_deterministic_and_bounded():
    events = [
        event(f"Event {index}", impact=Impact.HIGH if index % 2 else Impact.LOW)
        for index in range(8)
    ]
    first, _ = service(events)
    second, _ = service(reversed(events))

    first_result = first.refresh_from_provider()
    second_result = second.refresh_from_provider()

    assert len(first_result.top_events) == 5
    assert [item.event_id for item in first_result.top_events] == [
        item.event_id for item in second_result.top_events
    ]


def test_every_assessment_has_reasons_and_fixture_is_explicitly_degraded():
    hermes, _ = service([event()], fixture=True)

    result = hermes.refresh_from_provider()

    assert result.reason_codes
    assert result.hermes_status == "DEGRADED"
    assert result.source_metadata.fixture_data is True
    assert "FIXTURE_DATA_NOT_LIVE" in result.warnings


def test_source_url_is_sanitized_and_secrets_are_not_serialized():
    value = event(
        source_url="https://official.example/event?token=must-not-appear#secret",
    )
    value = HermesInput(**{**value.__dict__, "raw_provider_id": "safe-id"})
    hermes, _ = service([value])

    serialized = json.dumps(hermes.refresh_from_provider().to_dict()).lower()

    assert "https://official.example/event" in serialized
    assert "must-not-appear" not in serialized
    assert "token=" not in serialized


def test_cached_reads_never_refresh_provider():
    hermes, provider = service([event()])
    hermes.refresh_from_provider()
    assert provider.fetch_count == 1

    hermes.assessment()
    hermes.events_payload()
    hermes.assessment()

    assert provider.fetch_count == 1


def test_fastapi_routes_are_get_only_and_do_not_refresh_provider():
    hermes, provider = service([event()])
    hermes.refresh_from_provider()
    main = importlib.import_module("app.main")
    original = main.hermes_service
    main.hermes_service = hermes
    try:
        status = main.hermes_status()
        events = main.hermes_events()
        methods = {
            route.path: route.methods
            for route in main.app.routes
            if route.path.startswith("/v1/hermes/")
        }
        assert status["hermes_status"] == "READY"
        assert events["count"] == 1
        assert events["external_refresh_on_read"] is False
        assert provider.fetch_count == 1
        assert methods == {
            "/v1/hermes/status": {"GET"},
            "/v1/hermes/events": {"GET"},
        }
    finally:
        main.hermes_service = original

def test_service_has_no_broker_risk_or_paper_mutation_dependency(tmp_path):
    module = Path(
        importlib.import_module("src.hermes.hermes_service").__file__
    ).read_text(encoding="utf-8")
    risk_state = tmp_path / "risk.json"
    paper_state = tmp_path / "paper.json"
    risk_state.write_bytes(b"risk-state-unchanged")
    paper_state.write_bytes(b"paper-state-unchanged")
    hermes, _ = service([event()])

    hermes.refresh_from_provider()
    hermes.assessment()

    assert risk_state.read_bytes() == b"risk-state-unchanged"
    assert paper_state.read_bytes() == b"paper-state-unchanged"
    for forbidden in (
        "DhanClient",
        "RiskAuthorizationService",
        "PaperStateService",
        "place_order",
        "cancel_order",
    ):
        assert forbidden not in module
