"""Comprehensive network-free unit tests for Gemini Quota Ledger, Pacing Governor, and Fail-Closed Gate."""

from __future__ import annotations

import json
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.oracle_sol_api import router
from src.oracle_sol.contracts import (
    DevelopingState,
    MarketEvent,
    MarketThesisVerdict,
    SolBeaconOutput,
    SolEvidenceSnapshot,
    SystemStatus,
    ThesisState,
)
from src.oracle_sol.event_sourced_memory import EventSourcedMarketMemory
from src.oracle_sol.gemini_adapter import (
    GeminiModelAdapter,
    get_secure_gemini_api_key,
    resolve_gemini_api_key_with_source,
)
from src.oracle_sol.quota_ledger import (
    DEFAULT_FOLLOWING_MORNING_RESERVE,
    DEFAULT_OBSERVED_37_RPD_LIMIT,
    GeminiQuotaLedger,
    IST_TZ,
    PT_TZ,
    UTC_TZ,
)
from src.oracle_sol.reasoning_protocol import SolReasoningOrchestrator
from src.oracle_sol.service import SolMarketBrainService
from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
from src.oracle_sol.thesis_memory import ThesisMemory
from tests.oracle_sol.test_oracle_sol import _full_canonical_feeds

TEST_API_KEY = "test-only-key-quota-governor-123456789"


def _unblock_model(ledger: GeminiQuotaLedger, model: str = "gemini-3.7-flash") -> None:
    """Helper to clear RPD block for testing normal operational flow."""
    state, _ = ledger.get_or_create_model_state(model)
    state.requests_attempted = 0
    state.requests_succeeded = 0
    state.requests_failed = 0
    state.afternoon_requests_spent = 0
    state.morning_requests_spent = 0
    state.rpd_blocked_until_utc = None
    state.cooldown_until_utc = None
    state.in_flight = False
    state.provider_known_exhausted = False
    state.quota_status = "HEALTHY"


def test_keychain_lookup_compatibility(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    fake_run = MagicMock()
    fake_run.return_value.returncode = 0
    fake_run.return_value.stdout = "fake-keychain-citadel-secret-123456789\n"

    with patch("subprocess.run", fake_run):
        key, source = resolve_gemini_api_key_with_source()
        assert key == "fake-keychain-citadel-secret-123456789"
        assert "CITADEL_GEMINI_API_KEY" in source


def test_fresh_empty_ledger_on_arbitrary_date_no_historical_incident(tmp_path: Path) -> None:
    # A fresh empty ledger on any arbitrary date (past, present, or future) starts cleanly
    for arbitrary_date in (
        datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC_TZ),
        datetime(2026, 9, 5, 10, 0, 0, tzinfo=UTC_TZ),
        datetime(2026, 12, 1, 10, 0, 0, tzinfo=UTC_TZ),
    ):
        ledger = GeminiQuotaLedger(storage_dir=str(tmp_path / arbitrary_date.strftime("%Y%m%d")), api_key=TEST_API_KEY)
        state_37, _ = ledger.get_or_create_model_state("gemini-3.7-flash", arbitrary_date)
        is_blocked, blocked_until = ledger.is_rpd_blocked("gemini-3.7-flash", arbitrary_date)

        assert is_blocked is False
        assert blocked_until is None
        assert state_37.requests_attempted == 0
        assert state_37.requests_failed == 0
        assert state_37.provider_known_exhausted is False
        assert state_37.quota_status == "HEALTHY"


def test_persisted_current_rpd_block_hydrates_and_expires_on_rollover(tmp_path: Path) -> None:
    # 1. Setup a persisted ledger file with an authoritative RPD block for 3.7
    ledger_file = tmp_path / "gemini_quota_ledger.json"
    persisted_payload = {
        "version": "1.2.0-quota-ledger",
        "updated_at_utc": "2026-09-01T10:00:00Z",
        "models": {
            "gemini-3.7-flash": {
                "provider_model": "gemini-3.7-flash",
                "credential_identity_safe_hash": "a60d408498ee",
                "provider_project_identity_safe_hash": "UNKNOWN",
                "provider_day_pt": "2026-09-01",
                "observed_rpd_limit": 20,
                "quota_status": "QUOTA_LIMIT_RPD",
                "requests_attempted": 0,
                "requests_succeeded": 0,
                "requests_failed": 0,
                "afternoon_requests_spent": 0,
                "morning_requests_spent": 0,
                "last_error_category": "QUOTA_LIMIT_RPD",
                "rpd_blocked_until_utc": "2026-09-02T07:00:00+00:00",
                "provider_known_exhausted": True,
            }
        },
    }
    with open(ledger_file, "w", encoding="utf-8") as f:
        json.dump(persisted_payload, f)

    # 2. Hydrate ledger from disk during active blocked period
    t_before_reset = datetime(2026, 9, 1, 15, 0, 0, tzinfo=UTC_TZ)
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), api_key=TEST_API_KEY)
    is_blocked, blocked_until = ledger.is_rpd_blocked("gemini-3.7-flash", t_before_reset)
    assert is_blocked is True
    assert blocked_until == "2026-09-02T07:00:00+00:00"

    tel = ledger.get_telemetry("gemini-3.7-flash", t_before_reset)
    assert tel["local_requests_attempted"] == 0
    assert tel["fake_historical_counters_present"] is False
    assert tel["provider_observed_state"] == "QUOTA_LIMIT_RPD"

    # 3. Crossing rollover boundary: 2026-09-02 08:00 UTC (01:00 PDT)
    t_after_reset = datetime(2026, 9, 2, 8, 0, 0, tzinfo=UTC_TZ)
    state, rolled = ledger.get_or_create_model_state("gemini-3.7-flash", t_after_reset)
    assert rolled is True
    assert state.provider_day_pt == "2026-09-02"

    is_blocked_after, blocked_until_after = ledger.is_rpd_blocked("gemini-3.7-flash", t_after_reset)
    assert is_blocked_after is False
    assert blocked_until_after is None
    assert state.provider_known_exhausted is False
    assert state.quota_status == "HEALTHY"


def test_gemini_36_quota_starts_unknown_and_cannot_auto_fallback(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), api_key=TEST_API_KEY)
    tel_36 = ledger.get_telemetry("gemini-3.6-flash")

    assert tel_36["observed_rpd_limit"] is None
    assert tel_36["quota_status"] == "UNKNOWN"
    assert tel_36["requests_attempted"] == 0

    # Automated check for 3.6 without probe or manual override is rejected
    eligible, reason, _ = ledger.check_eligibility("gemini-3.6-flash", is_manual=False)
    assert eligible is False
    assert reason == "MODEL_QUOTA_UNPROVEN"


def test_project_identity_distinct_from_credential_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CITADEL_GEMINI_PROJECT_ID", raising=False)
    ledger_no_proj = GeminiQuotaLedger(storage_dir=str(tmp_path / "1"), api_key="secret-api-key-12345")
    tel1 = ledger_no_proj.get_telemetry("gemini-3.7-flash")
    assert tel1["provider_project_identity_safe_hash"] == "UNKNOWN"
    assert tel1["credential_identity_safe_hash"] != "UNKNOWN"

    monkeypatch.setenv("CITADEL_GEMINI_PROJECT_ID", "citadel-gcp-prod-001")
    ledger_with_proj = GeminiQuotaLedger(storage_dir=str(tmp_path / "2"), api_key="secret-api-key-12345")
    tel2 = ledger_with_proj.get_telemetry("gemini-3.7-flash")
    assert tel2["provider_project_identity_safe_hash"] != "UNKNOWN"
    assert tel2["provider_project_identity_safe_hash"] != tel2["credential_identity_safe_hash"]


def test_pacific_provider_day_rollover(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), observed_rpd_limit=20)
    _unblock_model(ledger, "gemini-3.7-flash")

    # Day 1 in PT: 2026-09-01 10:00 UTC = 03:00 PT (2026-09-01)
    t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC_TZ)
    state1, rolled1 = ledger.get_or_create_model_state("gemini-3.7-flash", t1)
    assert state1.provider_day_pt == "2026-09-01"

    # Spend 5 requests on Day 1
    for _ in range(5):
        ledger.record_request_start("gemini-3.7-flash", is_manual=True, now_utc=t1)
        ledger.record_request_result("gemini-3.7-flash", "SUCCESS", now_utc=t1)

    t1_telemetry = ledger.get_telemetry("gemini-3.7-flash", t1)
    assert t1_telemetry["requests_attempted"] == 5
    assert t1_telemetry["requests_succeeded"] == 5
    assert t1_telemetry["total_day_remaining"] == 15

    # Day 2 in PT: 2026-09-02 08:00 UTC = 01:00 PT (2026-09-02)
    t2 = datetime(2026, 9, 2, 8, 0, 0, tzinfo=UTC_TZ)
    state2, rolled2 = ledger.get_or_create_model_state("gemini-3.7-flash", t2)
    assert rolled2 is True
    assert state2.provider_day_pt == "2026-09-02"
    assert state2.requests_attempted == 0
    assert state2.requests_succeeded == 0
    assert state2.afternoon_requests_spent == 0
    assert state2.morning_requests_spent == 0


def test_pdt_pst_dynamic_reset_conversion(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path))

    # Summer date (PDT, UTC-7): 2026-07-15 00:00 PDT -> 07:00 UTC -> 12:30 IST
    summer_utc = datetime(2026, 7, 15, 6, 0, 0, tzinfo=UTC_TZ)
    seg_summer = ledger.get_market_segment_info(summer_utc)
    assert "12:30:00 IST" in seg_summer["next_reset_ist"]

    # Winter date (PST, UTC-8): 2026-12-15 00:00 PST -> 08:00 UTC -> 13:30 IST
    winter_utc = datetime(2026, 12, 15, 7, 0, 0, tzinfo=UTC_TZ)
    seg_winter = ledger.get_market_segment_info(winter_utc)
    assert "13:30:00 IST" in seg_winter["next_reset_ist"]


def test_real_call_gate_does_not_increment_quota(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CITADEL_ALLOW_REAL_GEMINI_CALLS", raising=False)
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), observed_rpd_limit=20)
    _unblock_model(ledger, "gemini-3.7-flash")

    adapter = GeminiModelAdapter(api_key=TEST_API_KEY, quota_ledger=ledger)
    assert adapter._is_real_call_permitted() is False

    with patch("google.genai.Client", side_effect=ImportError("force rest")):
        parsed, telemetry, _ = adapter.invoke_reasoning(
            "cycle-gate", "system", {"snapshot": {}}, is_manual=True
        )
        assert parsed is None
        assert telemetry["status"] == "REAL_CALLS_DISABLED"
        assert telemetry["real_api_call_occurred"] is False

    # Invariant: Gate denial MUST NOT increment attempted count or spend quota
    tel = ledger.get_telemetry("gemini-3.7-flash")
    assert tel["requests_attempted"] == 0
    assert tel["requests_failed"] == 0


def test_one_reasoning_cycle_equals_max_one_google_request(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CITADEL_ALLOW_REAL_GEMINI_CALLS", "1")
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), observed_rpd_limit=20)
    _unblock_model(ledger, "gemini-3.7-flash")

    adapter = GeminiModelAdapter(api_key=TEST_API_KEY, quota_ledger=ledger)
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.json.return_value = {"error": {"code": 503, "message": "Service Unavailable"}}

    with patch("google.genai.Client", side_effect=ImportError("force rest")), patch(
        "requests.post", return_value=mock_resp
    ) as mock_post:
        parsed, telemetry, _ = adapter.invoke_reasoning(
            "cycle-503", "system", {"snapshot": {}}, is_manual=True
        )
        assert parsed is None
        assert telemetry["status"] == "HTTP_ERROR_503"
        # Must execute exactly 1 attempt, zero retries
        assert mock_post.call_count == 1


def test_actual_target_model_fallback_accounting(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), observed_rpd_limit=20)
    now_utc = datetime.now(UTC_TZ)

    # 3.7 is RPD blocked
    state_37, _ = ledger.get_or_create_model_state("gemini-3.7-flash", now_utc)
    state_37.requests_attempted = 20
    state_37.rpd_blocked_until_utc = (now_utc + timedelta(days=1)).isoformat()

    state_36, _ = ledger.get_or_create_model_state("gemini-3.6-flash", now_utc)
    state_36.requests_attempted = 0
    state_36.rpd_blocked_until_utc = None

    adapter = GeminiModelAdapter(
        configured_model="gemini-3.7-flash",
        api_key=TEST_API_KEY,
        quota_ledger=ledger,
        allow_fallback=True,
    )

    # Mock 3.6 returning 429 RPD failure
    mock_error_resp = MagicMock()
    mock_error_resp.status_code = 429
    mock_error_resp.json.return_value = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "Resource exhausted",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                            "quotaValue": "20",
                        }
                    ],
                }
            ],
        }
    }

    with patch("google.genai.Client", side_effect=ImportError("force rest")), patch(
        "requests.post", return_value=mock_error_resp
    ):
        parsed, telemetry, envelope = adapter.invoke_reasoning(
            "cycle-fb-fail", "prompt", {"snapshot": {}}, is_manual=True
        )

    assert parsed is None
    assert telemetry["status"] == "QUOTA_LIMIT_RPD"
    assert envelope.configured_model == "gemini-3.7-flash"
    assert envelope.requested_model == "gemini-3.6-flash"
    assert telemetry["configured_model"] == "gemini-3.7-flash"
    assert telemetry["requested_model"] == "gemini-3.6-flash"
    assert telemetry["provider_response_model"] == "NONE"
    assert telemetry["successful_reasoning_model"] == "NONE"
    assert "(FALLBACK)" in telemetry["model_label"]

    # Only 3.6 is updated; 3.7 was unchanged
    state_36_after, _ = ledger.get_or_create_model_state("gemini-3.6-flash", now_utc)
    assert state_36_after.rpd_blocked_until_utc is not None


def test_unused_afternoon_quota_carries_over_into_morning(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), observed_rpd_limit=20)
    afternoon_utc = datetime(2026, 9, 1, 7, 30, 0, tzinfo=UTC_TZ)
    state, _ = ledger.get_or_create_model_state("gemini-3.7-flash", afternoon_utc)
    state.requests_attempted = 3
    state.afternoon_requests_spent = 3
    state.morning_requests_spent = 0
    state.rpd_blocked_until_utc = None

    # Next morning (before reset): 09:30 IST on 2026-09-02 (04:00 UTC)
    morning_utc = datetime(2026, 9, 2, 4, 0, 0, tzinfo=UTC_TZ)
    seg_m = ledger.get_market_segment_info(morning_utc)
    allocs = ledger.compute_segment_allocations(state, seg_m)

    # 20 total - 3 spent in afternoon = 17 available in morning!
    assert allocs["morning_budget"] == 17
    assert allocs["segment_budget"] == 17
    assert allocs["segment_remaining"] == 17
    assert allocs["total_day_remaining"] == 17


def test_manual_call_protects_morning_reserve(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path), observed_rpd_limit=20, morning_reserve=10)
    _unblock_model(ledger, "gemini-3.7-flash")
    afternoon_utc = datetime(2026, 9, 1, 7, 30, 0, tzinfo=UTC_TZ)
    state, _ = ledger.get_or_create_model_state("gemini-3.7-flash", afternoon_utc)
    state.requests_attempted = 10
    state.afternoon_requests_spent = 10
    state.morning_requests_spent = 0
    state.rpd_blocked_until_utc = None

    # Afternoon budget of 10 is fully spent; 10 remains in reserve for tomorrow morning.
    # Manual call without explicit override must be held to protect morning reserve
    eligible_default, reason_def, _ = ledger.check_eligibility(
        "gemini-3.7-flash", is_manual=True, use_reserved_quota=False, now_utc=afternoon_utc
    )
    assert eligible_default is False
    assert reason_def == "RESERVED_QUOTA_PROTECTED"

    # Explicit override allows using reserved capacity
    eligible_override, reason_over, _ = ledger.check_eligibility(
        "gemini-3.7-flash", is_manual=True, use_reserved_quota=True, now_utc=afternoon_utc
    )
    assert eligible_override is True
    assert reason_over == "ELIGIBLE"


def test_zero_event_loss_more_than_25_events(tmp_path: Path) -> None:
    mem = EventSourcedMarketMemory(storage_dir=str(tmp_path))
    th_mem = ThesisMemory(storage_dir=str(tmp_path))

    # Add 35 canonical events
    for i in range(1, 36):
        ev = MarketEvent(
            event_id=f"evt_{i:03d}",
            session_date="2026-09-01",
            timestamp_utc=f"2026-09-01T07:{i:02d}:00Z",
            timestamp_ist=f"12:{i:02d}:00",
            event_type="SPOT_MOVE",
            instrument="NIFTY",
            summary=f"Event {i}",
            provenance_hash=f"hash_{i}",
        )
        mem.append(ev)

    captured_payload = {}

    def mock_invoke_reasoning(cycle_id, system_prompt, user_payload, **kwargs):
        captured_payload.update(user_payload)
        output = {
            "market_verdict": "CALL",
            "developing_state": "NONE",
            "core_narrative": "Coalesced analysis",
            "what_changed": "Market moved",
            "positioning_story": "Call expansion",
            "oi_story": "PE writing",
            "flow_story": "Positive MLOFI",
            "option_response_story": "Expanding premiums",
            "call_case": "Bullish",
            "put_case": "None",
            "no_trade_case": "None",
            "strongest_contradiction": "NONE_OBSERVED",
            "why_bullets": ["Spot up", "Flow positive", "OI supportive"],
            "expectation_evaluations": [],
            "pre_registered_expectations": [],
            "data_gaps": [],
            "evidence_references": [f"evt_{i:03d}" for i in range(1, 36)],
        }
        telemetry = {"status": "SUCCESS", "successful_reasoning_model": "gemini-3.7-flash"}
        return output, telemetry, MagicMock()

    mock_adapter = MagicMock()
    mock_adapter.configured_model = "gemini-3.7-flash"
    mock_adapter.invoke_reasoning.side_effect = mock_invoke_reasoning

    orch = SolReasoningOrchestrator(
        model_adapter=mock_adapter,
        thesis_memory=th_mem,
        memory=mem,
    )

    feeds = _full_canonical_feeds()
    snap = extract_sol_evidence_snapshot(feeds)

    orch.execute_reasoning_cycle(snap, is_manual=True)

    # Invariant: ALL 35 events MUST be present in the request timeline!
    sent_events = captured_payload.get("recent_event_timeline", [])
    assert len(sent_events) == 35
    assert sent_events[0]["event_id"] == "evt_001"
    assert sent_events[-1]["event_id"] == "evt_035"
    assert th_mem.last_analyzed_event_id == "evt_035"


def test_failed_calls_accumulate_events_and_succeed_in_one_call(tmp_path: Path) -> None:
    mem = EventSourcedMarketMemory(storage_dir=str(tmp_path))
    th_mem = ThesisMemory(storage_dir=str(tmp_path))

    # Add 5 events
    for i in range(1, 6):
        mem.append(
            MarketEvent(
                event_id=f"evt_{i:03d}",
                session_date="2026-09-01",
                timestamp_utc="2026-09-01T07:00:00Z",
                timestamp_ist="12:30:00",
                event_type="SPOT_MOVE",
                instrument="NIFTY",
                summary=f"Event {i}",
                provenance_hash=f"hash_{i}",
            )
        )

    # Mock failing adapter
    mock_failing = MagicMock()
    mock_failing.configured_model = "gemini-3.7-flash"
    mock_failing.invoke_reasoning.return_value = (
        None,
        {"status": "QUOTA_LIMIT_RPM", "successful_reasoning_model": "NONE"},
        MagicMock(),
    )

    orch = SolReasoningOrchestrator(
        model_adapter=mock_failing,
        thesis_memory=th_mem,
        memory=mem,
    )

    feeds = _full_canonical_feeds()
    snap = extract_sol_evidence_snapshot(feeds)

    orch.execute_reasoning_cycle(snap, is_manual=True)
    # Cursor unchanged on failure
    assert th_mem.last_analyzed_event_id is None

    # 3 more events arrive
    for i in range(6, 9):
        mem.append(
            MarketEvent(
                event_id=f"evt_{i:03d}",
                session_date="2026-09-01",
                timestamp_utc="2026-09-01T07:05:00Z",
                timestamp_ist="12:35:00",
                event_type="SPOT_MOVE",
                instrument="NIFTY",
                summary=f"Event {i}",
                provenance_hash=f"hash_{i}",
            )
        )

    captured_payload = {}

    def mock_success_invoke(cycle_id, system_prompt, user_payload, **kwargs):
        captured_payload.update(user_payload)
        output = {
            "market_verdict": "NO_TRADE",
            "developing_state": "UNRESOLVED",
            "core_narrative": "Coalesced 8 events",
            "what_changed": "Events arrived",
            "positioning_story": "Neutral",
            "oi_story": "Neutral",
            "flow_story": "Neutral",
            "option_response_story": "Neutral",
            "call_case": "Neutral",
            "put_case": "Neutral",
            "no_trade_case": "Neutral",
            "strongest_contradiction": "NONE_OBSERVED",
            "why_bullets": ["Neutral", "Neutral", "Neutral"],
            "expectation_evaluations": [],
            "pre_registered_expectations": [],
            "data_gaps": [],
            "evidence_references": [f"evt_{i:03d}" for i in range(1, 9)],
        }
        return output, {"status": "SUCCESS", "successful_reasoning_model": "gemini-3.7-flash"}, MagicMock()

    mock_success = MagicMock()
    mock_success.configured_model = "gemini-3.7-flash"
    mock_success.invoke_reasoning.side_effect = mock_success_invoke

    orch.adapter = mock_success
    orch.execute_reasoning_cycle(snap, is_manual=True)

    # Next request contains ALL 8 events in ONE call
    sent_events = captured_payload.get("recent_event_timeline", [])
    assert len(sent_events) == 8
    assert th_mem.last_analyzed_event_id == "evt_08" or th_mem.last_analyzed_event_id == "evt_008"


def test_token_usage_persistence_in_quota_ledger(tmp_path: Path) -> None:
    ledger = GeminiQuotaLedger(storage_dir=str(tmp_path))
    ledger.record_token_usage(
        "gemini-3.7-flash",
        prompt_tokens=1500,
        candidates_tokens=300,
        cached_tokens=500,
        thoughts_tokens=250,
        total_tokens=1800,
    )

    tel = ledger.get_telemetry("gemini-3.7-flash")
    assert tel["prompt_tokens"] == 1500
    assert tel["candidates_tokens"] == 300
    assert tel["cached_tokens"] == 500
    assert tel["thoughts_tokens"] == 250
    assert tel["total_tokens_used"] == 1800


def test_analyze_now_api_endpoint_with_reserved_quota_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CITADEL_ENABLE_MANUAL_GEMINI_ANALYSIS", "1")
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=GeminiModelAdapter(api_key=TEST_API_KEY),
        runtime_mode="TEST",
    )
    feeds = _full_canonical_feeds()
    snap = extract_sol_evidence_snapshot(feeds)
    service.ingest_snapshot(snap)

    app = FastAPI()
    app.include_router(router)

    with patch(
        "src.api.oracle_sol_api.SolMarketBrainService.get_instance",
        return_value=service,
    ):
        client = TestClient(app)
        resp = client.post("/v1/oracle/sol/analyze-now", json={"use_reserved_quota": True})

    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "beacon" in data
    assert "telemetry" in data
    service.worker.stop()


def test_analyze_now_api_is_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CITADEL_ENABLE_MANUAL_GEMINI_ANALYSIS", raising=False)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/v1/oracle/sol/analyze-now", json={})
    assert response.status_code == 404
