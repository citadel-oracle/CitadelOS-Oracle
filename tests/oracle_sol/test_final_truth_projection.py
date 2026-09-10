from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from src.oracle_sol.cognitive_projection import project_cognitive_decision
from src.oracle_sol.evidence_gate import EvidenceGate
from src.external_context.presentation import project_world_context
from src.external_context.core import ExternalContextCore

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def test_exact_legacy_oi_claim_rejected_and_history_unchanged():
    legacy = dict(thesis_id="legacy", session_id="2026-09-03", input_revision=68,
        created_at=STAMP, state="CALL_DEVELOPING", entry_window="WAIT", input_hash="recorded",
        market_story="Aggressive call OI build and positive flow contrast with a weakening spot, suggesting hidden bullish pressure.",
        qwen_observation={}, gemini_review={})
    before = deepcopy(legacy)
    active = SimpleNamespace(to_dict=lambda: deepcopy(legacy))
    result = project_cognitive_decision(active, None, {},
        {"market_session_date": "2026-09-03", "system_status": "OFF_MARKET"}, NOW)
    assert result["retained_validation"]["status"] == "REJECTED"
    assert "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED" in result["retained_validation"]["reason"]
    assert result["primary_decision"]["state"] is None
    assert result["primary_decision"]["why_now"] == []
    assert result["gpt"]["status"] == "REJECTED"
    assert result["gpt"]["output"] is None
    assert result["historical_rejected_thesis"] == before == legacy


def test_closed_session_remains_off_market_when_transport_has_no_prices():
    from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
    snapshot = extract_sol_evidence_snapshot({
        "oracle": {"ok": False, "data": {"market_open": False, "dhan_connected": False}},
        "order_flow": {"ok": False, "data": {}},
        "argus": {"ok": False, "data": {}},
    })
    assert snapshot.system_status.value == "OFF_MARKET"
    assert snapshot.spot_ltp is None and snapshot.futures_ltp is None


def test_missing_original_context_cannot_be_declared_last_valid():
    result = EvidenceGate.revalidate_retained({"state": "NO_TRADE", "market_story": "Direction unclear."})
    assert not result.is_valid
    assert result.error_details == "LEGACY_VALIDATION_CONTEXT_MISSING"


def test_malformed_retained_material_is_rejected_not_an_api_exception():
    assert not EvidenceGate.revalidate_retained({"why_now": [3.5], "state": "CALL"}).is_valid


def test_new_commit_preserves_material_for_current_semantic_revalidation(tmp_path):
    from tests.oracle_sol.test_phase1_cognitive_architecture import make_valid_raw_response, make_test_snapshot
    from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
    from src.oracle_sol.thesis_graph import ThesisGraph
    packet = BrainPacketCompiler().compile_packet("2026-09-03", 1, make_test_snapshot(), None, [], [], [])
    ledger = tmp_path / "theses.jsonl"
    graph = ThesisGraph(storage_path=str(ledger))
    result = EvidenceGate(graph).validate_and_commit(make_valid_raw_response(), packet, "isolated", "test")
    assert result.is_valid
    before = ledger.read_bytes()
    restored = ThesisGraph(storage_path=str(ledger)).get_active_thesis()
    assert EvidenceGate.revalidate_retained(restored.to_dict()).is_valid
    assert ledger.read_bytes() == before


def test_current_rules_recheck_displayed_prose_not_just_the_saved_receipt():
    node = {"input_revision": 12, "input_hash": "hash", "market_story": "Institutional absorption",
        "semantic_validation": {"input_hash": "hash", "revision": 12, "response": {"market_story": "No view"},
            "context": {"canonical_state": {}, "cited_ids": ["metric:flow_net_delta", "metric:spot_price"]}}}
    result = EvidenceGate.revalidate_retained(node)
    assert not result.is_valid and "INSTITUTIONAL_CLAIM_UNSUPPORTED" in result.error_details


def test_current_schema_orphan_evidence_is_rejected_without_cursor_advance():
    from tests.oracle_sol.test_phase1_cognitive_architecture import make_valid_raw_response, make_test_snapshot
    from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
    from src.oracle_sol.thesis_graph import ThesisGraph
    packet = BrainPacketCompiler().compile_packet("2026-09-03", 1, make_test_snapshot(), None, [], [], [])
    response = make_valid_raw_response()
    response["synthesis"]["supporting_evidence_ids"] = ["not:a_canonical_evidence_id"]
    graph = ThesisGraph()
    result = EvidenceGate(graph).validate_and_commit(response, packet, "isolated", "test")
    assert result.status == "MODEL_CLAIM_UNSUPPORTED"
    assert result.unsupported_evidence_ids == ["not:a_canonical_evidence_id"]
    assert graph.get_cursor() is None


def verified_event(**updates):
    event = dict(event_id="isolated", provider="test-source", source_name="Isolated source",
        published_at=(NOW - timedelta(seconds=30)).isoformat(), retrieved_at=STAMP,
        headline="Isolated verified event", raw_hash="test-payload-hash", verification_status="VERIFIED",
        verification_record={"status": "MATCH", "verifier_id": "isolated-verifier", "payload_hash": "test-payload-hash",
                             "checked_at": STAMP, "valid_until": (NOW + timedelta(seconds=300)).isoformat()})
    event.update(updates)
    return event


def test_primary_stories_are_today_verified_and_bounded():
    old = verified_event(event_id="old", country="IN", published_at=(NOW - timedelta(days=1)).isoformat())
    india = verified_event(event_id="india", country="IN")
    global_event = verified_event(event_id="global", country="US", market_tags=["EQUITIES"])
    unverified = verified_event(event_id="bad", country="IN", verification_status="UNVERIFIED")
    result = project_world_context([old, global_event, india, unverified], [], health(), NOW)
    assert [row["event_id"] for row in result["top_stories"]] == ["india", "global"]
    stale = project_world_context([india], [], health(), NOW + timedelta(seconds=301))
    assert stale["top_stories"] == []


def health():
    return {"last_successful_refresh_at": STAMP, "poll_cadence_seconds": 300,
            "refresh_receipt_id": "isolated-refresh", "provider_success_at": {"test-source": STAMP}}


def test_verified_current_context_has_source_age_and_both_times():
    result = project_world_context([verified_event()], [], health(), NOW)
    assert result["status"] == "LIVE"
    assert result["headline"]["age_seconds"] == 30
    assert result["headline"]["source_name"] == "Isolated source"
    assert result["headline"]["published_at_utc"] and result["headline"]["retrieved_at_utc"]


@pytest.mark.parametrize("updates", [
    {"verification_record": {}}, {"verification_record": "malformed"}, {"raw_hash": "tampered"}, {"verification_status": "UNVERIFIED"},
    {"published_at": "2026-09-03"}, {"published_at": "2026-09-03T12:00:01Z"},
    {"published_at": None}, {"retrieved_at": "2026-09-03"},
])
def test_unknown_unverified_future_and_date_only_context_hidden(updates):
    result = project_world_context([verified_event(**updates)], [], health(), NOW)
    assert result["status"] == "UNAVAILABLE" and result["headline"] is None


def test_expiry_and_stale_source_refresh_cannot_look_current():
    assert project_world_context([verified_event()], [], health(), NOW + timedelta(seconds=301))["status"] == "STALE"
    stale_health = health()
    stale_health["provider_success_at"] = {}  # another provider succeeding is not this source succeeding
    assert project_world_context([verified_event()], [], stale_health, NOW)["status"] == "STALE"


def test_verified_session_last_quote_remains_session_last():
    quote = verified_event(symbol="SPY", price=0.0, data_age="SESSION_LAST", provider_timestamp=STAMP,
                           exact_or_proxy="PROXY")
    result = project_world_context([], [quote], health(), NOW)
    assert result["status"] == "SESSION_LAST"
    assert result["quotes"][0]["display_status"] == "SESSION_LAST"
    assert result["quotes"][0]["price"] == 0.0


def test_refresh_receipt_changes_only_on_actual_success_not_cache_or_failure(tmp_path, monkeypatch):
    import src.external_context.core as module
    class Adapter:
        next_status = "PROVIDER_HEALTHY"
        def __init__(self, name):
            self.provider_id = name
            self.is_configured = True
            self.last_poll_time = None
            self.last_status = "INITIALIZED"
            self.last_error = None
        def poll_events(self):
            if self.next_status != "CACHED":
                self.last_poll_time = (self.last_poll_time or 0) + 1
                self.last_status = self.next_status
            return []
        poll_quotes = poll_events
        def get_health(self):
            return {"status": self.last_status}
    for constructor, name in [("OfficialIndiaAdapter", "official_india"), ("FinanceNewsAdapter", "marketaux"),
                              ("GlobalShockAdapter", "gdelt"), ("WorldMarketAdapter", "twelve_data")]:
        monkeypatch.setattr(module, constructor, lambda n=name: Adapter(n))
    core = ExternalContextCore(ledger_dir=tmp_path)
    core.poll_all_now()
    first = core.get_health()
    assert first["last_poll_at"] and first["last_successful_refresh_at"] and first["refresh_receipt_id"]
    Adapter.next_status = "CACHED"
    core.poll_all_now()
    assert core.get_health()["refresh_receipt_id"] == first["refresh_receipt_id"]
    Adapter.next_status = "FETCH_FAILED"
    core.poll_all_now()
    assert core.get_health()["last_successful_refresh_at"] == first["last_successful_refresh_at"]


def mocked_response(monkeypatch, payload):
    import io
    import json
    import urllib.request
    response = io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    response.headers = {}
    response.status = 200
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: response)


def isolated_world_adapter():
    from src.external_context.adapters.world_market import WorldMarketAdapter
    from src.external_context.adapters.base import BaseExternalAdapter
    adapter = WorldMarketAdapter.__new__(WorldMarketAdapter)
    BaseExternalAdapter.__init__(adapter, "twelve_data")
    adapter.api_key = "isolated-test-not-a-credential"
    adapter.min_poll_interval_seconds = 60
    adapter.timeout_seconds = 1
    adapter.cached_quotes = {}
    adapter.request_count_today = 0
    adapter.current_day_utc = datetime.now(timezone.utc).date()
    adapter.rate_limit_state = {}
    adapter._ssl_context = None
    return adapter


def test_world_http_200_error_is_not_a_successful_source_refresh(monkeypatch):
    mocked_response(monkeypatch, {"status": "error", "code": 400, "message": "isolated error"})
    adapter = isolated_world_adapter()
    assert adapter.poll_quotes() == []
    assert adapter.last_status == "FETCH_FAILED"
    assert adapter.last_error == "NO_VALID_QUOTES_IN_RESPONSE"


def test_missing_quote_source_time_does_not_become_retrieval_time(monkeypatch):
    mocked_response(monkeypatch, {"SPY": {"close": "0.0", "is_market_open": False}})
    quote = isolated_world_adapter().poll_quotes()[0]
    assert quote.provider_timestamp == ""
    assert quote.retrieved_at
    assert quote.verification_status == "UNVERIFIED"


def test_missing_news_publication_time_stays_unknown(monkeypatch):
    from src.external_context.adapters.finance_news import FinanceNewsAdapter
    from src.external_context.adapters.base import BaseExternalAdapter
    adapter = FinanceNewsAdapter.__new__(FinanceNewsAdapter)
    BaseExternalAdapter.__init__(adapter, "marketaux")
    adapter.api_key = "isolated-test-not-a-credential"
    adapter.daily_budget = 1
    adapter.request_count_today = 0
    adapter.current_day_utc = datetime.now(timezone.utc).date()
    adapter.timeout_seconds = 1
    adapter.seen_article_hashes = set()
    adapter._ssl_context = None
    mocked_response(monkeypatch, {"data": [{"uuid": "isolated", "title": "Isolated test article"}]})
    event = adapter.poll_events()[0]
    assert event.published_at == ""
    assert event.retrieved_at
    assert event.verification_status == "UNVERIFIED"


def test_missing_rss_publication_time_stays_unknown(monkeypatch):
    from src.external_context.adapters.official_india import OfficialIndiaAdapter
    adapter = OfficialIndiaAdapter()
    mocked_response(monkeypatch, b"<rss><channel><item><title>Isolated test item</title></item></channel></rss>")
    event = adapter._fetch_rss("https://example.invalid/rss", "rbi", "Isolated source", "REGULATORY_CIRCULAR", [])[0]
    assert event.published_at == ""
    assert event.retrieved_at
    assert event.verification_status == "UNVERIFIED"


def test_recovered_official_fetch_clears_previous_failure(monkeypatch):
    from src.external_context.adapters.official_india import OfficialIndiaAdapter
    adapter = OfficialIndiaAdapter()
    adapter.last_error = "previous failure"
    monkeypatch.setattr(adapter, "_fetch_rss", lambda **kwargs: [])
    monkeypatch.setattr(adapter, "_fetch_mospi_calendar", lambda: [])
    adapter.poll_events()
    assert adapter.last_error is None
    assert adapter.last_status == "NO_CURRENT_EVENTS"
