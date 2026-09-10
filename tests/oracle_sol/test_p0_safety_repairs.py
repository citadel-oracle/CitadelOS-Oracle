"""Focused regressions for the six confirmed Gemini Brain P0 safety defects."""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.oracle_sol_api import router, validate_sol_sse_frame
from src.oracle_sol.contracts import DevelopingState, MarketThesisVerdict, SolModelRequestEnvelope
from src.oracle_sol.gemini_adapter import GeminiModelAdapter
from src.oracle_sol.service import SolMarketBrainService
from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
from src.oracle_sol.thesis_memory import ThesisMemory
from tests.oracle_sol.test_external_context import _valid_spark_payload
from tests.oracle_sol.test_oracle_sol import _full_canonical_feeds


def _model_output(verdict: str | None, *, evidence_references: list[str] | None = None) -> dict:
    return {
        "market_verdict": verdict,
        "developing_state": "NONE",
        "core_narrative": f"{verdict} test output",
        "what_changed": "Test cycle completed.",
        "positioning_story": "Test positioning.",
        "oi_story": "Test OI.",
        "flow_story": "Test flow.",
        "option_response_story": "Test option response.",
        "call_case": "Test call case.",
        "put_case": "Test put case.",
        "no_trade_case": "Test wait case.",
        "strongest_contradiction": "NONE_OBSERVED",
        "why_bullets": ["Test evidence."],
        "expectation_evaluations": [],
        "pre_registered_expectations": [],
        "data_gaps": [],
        "evidence_references": evidence_references or [],
    }


def _envelope(cycle_id: str, payload: dict) -> SolModelRequestEnvelope:
    return SolModelRequestEnvelope(
        cycle_id=cycle_id,
        prompt_version="p0-test",
        prompt_hash="prompt-hash",
        input_hash="input-hash",
        system_prompt="test",
        user_payload=payload,
        configured_model="gemini-3.7-flash",
        requested_model="gemini-3.7-flash",
        reasoning_effort="medium",
    )


class StaticAdapter:
    configured_model = "gemini-3.7-flash"
    is_configured = True

    def __init__(self, output: dict | None, status: str) -> None:
        self.output = output
        self.status = status

    def invoke_reasoning(self, cycle_id: str, system_prompt: str, user_payload: dict):
        telemetry = {
            "cycle_id": cycle_id,
            "status": self.status,
            "successful_reasoning_model": (
                self.configured_model if self.output is not None else "NONE"
            ),
        }
        return self.output, telemetry, _envelope(cycle_id, user_payload)


@pytest.mark.parametrize(
    "provider_status",
    ["QUOTA_EXHAUSTED", "HTTP_ERROR_503", "INVOCATION_TIMEOUT", "MALFORMED_OUTPUT"],
)
def test_p0_01_healthy_market_provider_failure_never_becomes_no_trade(
    tmp_path: Path, provider_status: str
) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(None, provider_status),
        runtime_mode="TEST",
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())

    _, beacon, telemetry, _ = service._process_snapshot_sync(snapshot)

    assert snapshot.system_status.value == "HEALTHY"
    assert telemetry["status"] == provider_status
    assert beacon.market_verdict is None
    assert beacon.reasoning_status == "DEGRADED_ADVISORY"
    assert beacon.market_verdict != "NO_TRADE"
    service.worker.stop()


@pytest.mark.parametrize(
    "output, expected_status",
    [
        (_model_output("CALL", evidence_references=["evt_not_real"]), "INVALID_EVIDENCE_REFERENCES"),
        (_model_output(None), "OUTPUT_SCHEMA_INVALID"),
    ],
)
def test_p0_01_invalid_evidence_or_null_verdict_never_becomes_no_trade(
    tmp_path: Path, output: dict, expected_status: str
) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(output, "SUCCESS"),
        runtime_mode="TEST",
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())

    _, beacon, telemetry, _ = service._process_snapshot_sync(snapshot)

    assert telemetry["status"] == expected_status
    assert beacon.market_verdict is None
    assert beacon.reasoning_status == "OUTPUT_INVALID"
    service.worker.stop()


def _api_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_sol_sse_broadcast_frames_match_streaming_bytes_contract(tmp_path: Path) -> None:
    service = SolMarketBrainService(storage_dir=str(tmp_path), runtime_mode="TEST")
    subscriber = service.subscribe_sse()

    service._broadcast_sse(service.get_latest_beacon())

    frame = subscriber.get_nowait()
    assert isinstance(frame, bytes)
    assert frame.startswith(b"event: beacon_state\ndata: ")
    payload = json.loads(frame.split(b"data: ", 1)[1])
    assert payload["state_revision"] == 1
    assert payload["runtime_instance_id"] == service.get_latest_state()["runtime_instance_id"]
    assert payload["canonical_market_state"] is None

    service._broadcast_sse(service.get_latest_beacon())
    second_payload = json.loads(subscriber.get_nowait().split(b"data: ", 1)[1])
    assert second_payload["state_revision"] == 2
    streamed = validate_sol_sse_frame(frame)
    assert streamed == frame
    assert streamed.count(b"event: beacon_state") == 1
    assert streamed.count(b"data: ") == 1
    service.unsubscribe_sse(subscriber)
    service.worker.stop()


def test_conflicting_five_state_output_fails_closed_without_thesis_commit(tmp_path: Path) -> None:
    output = _model_output("CALL")
    output["developing_state"] = "PUT_DEVELOPING"
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(output, "SUCCESS"),
        runtime_mode="TEST",
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())
    initial_thesis_id = service.get_latest_thesis().thesis_id

    _, beacon, telemetry, _ = service._process_snapshot_sync(snapshot)

    assert telemetry["status"] == "INVALID_FIVE_STATE_CONTRACT"
    assert beacon.market_verdict is None
    assert beacon.developing_state == "UNRESOLVED"
    assert service.get_latest_thesis().thesis_id == initial_thesis_id
    assert service.get_latest_state()["canonical_market_state"] is None
    service.worker.stop()


def test_missing_structured_output_field_fails_closed_before_thesis_commit(tmp_path: Path) -> None:
    output = _model_output("CALL")
    output.pop("flow_story")
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(output, "SUCCESS"),
        runtime_mode="TEST",
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())
    initial_thesis_id = service.get_latest_thesis().thesis_id

    _, beacon, telemetry, _ = service._process_snapshot_sync(snapshot)

    assert telemetry["status"] == "OUTPUT_SCHEMA_INVALID"
    assert beacon.market_verdict is None
    assert beacon.reasoning_status == "OUTPUT_INVALID"
    assert service.get_latest_thesis().thesis_id == initial_thesis_id
    service.worker.stop()


def test_thesis_atomic_write_reports_success_and_uses_configured_model(tmp_path: Path) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(None, "PROVIDER_UNAVAILABLE"),
        runtime_mode="TEST",
    )
    session_date = service.thesis_memory._session_date

    service.thesis_memory.reset_session(session_date)

    state = service.get_latest_state()
    thesis_file = tmp_path / f"sol_active_thesis_{session_date}.json"
    persisted = json.loads(thesis_file.read_text(encoding="utf-8"))
    assert state["persistence"]["thesis_store_status"] == "OK"
    assert state["persistence"]["last_persistence_error"] is None
    assert persisted["configured_model"] == "gemini-3.7-flash"
    assert not list(tmp_path.glob("*.tmp"))
    service.worker.stop()


def test_reasoning_cursor_does_not_advance_when_thesis_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(None, "PROVIDER_UNAVAILABLE"),
        runtime_mode="TEST",
    )
    memory = service.thesis_memory
    original_thesis = memory.get_active_thesis()
    original_cursor = memory.last_analyzed_event_id
    monkeypatch.setattr(memory, "_persist_active_thesis", lambda: False)

    with pytest.raises(RuntimeError, match="Thesis commit failed"):
        memory.commit_reasoning_result(
            original_thesis,
            last_analyzed_event_id="evt_must_not_commit",
            expectations=[],
            evaluations=[],
        )

    assert memory.last_analyzed_event_id == original_cursor
    assert memory.get_active_thesis() is original_thesis
    service.worker.stop()


def test_production_projection_failure_suspends_market_semantics(tmp_path: Path) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticAdapter(None, "PROVIDER_UNAVAILABLE"),
        runtime_mode="TEST",
    )

    service.report_projection_failure("safe structural mismatch")

    beacon = service.get_latest_beacon()
    assert beacon.system_status == "DATA_DEGRADED"
    assert beacon.market_verdict is None
    assert beacon.developing_state == "UNRESOLVED"
    assert beacon.main_contradiction == "DATA_LINEAGE_CONTAMINATION"
    service.worker.stop()


def test_p0_02_unauthenticated_ingest_and_reload_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITADEL_SPARK_INGEST_TOKEN", "test-only-local-capability")
    client = _api_client()

    ingest = client.post("/v1/oracle/sol/external-context/ingest", json=_valid_spark_payload())
    reload_response = client.post("/v1/oracle/sol/external-context/reload")

    assert ingest.status_code == 401
    assert reload_response.status_code == 401


@pytest.mark.parametrize(
    "fixture_marker",
    [
        {"is_test_fixture": True},
        {"source_type": "TEST_FIXTURE"},
    ],
)
def test_p0_02_authenticated_production_route_rejects_test_fixtures(
    monkeypatch: pytest.MonkeyPatch, fixture_marker: dict
) -> None:
    token = "test-only-local-capability"
    monkeypatch.setenv("CITADEL_SPARK_INGEST_TOKEN", token)
    payload = _valid_spark_payload()
    payload.update(fixture_marker)

    response = _api_client().post(
        "/v1/oracle/sol/external-context/ingest",
        json=payload,
        headers={"x-citadel-spark-token": token},
    )

    assert response.status_code == 422


def test_p0_02_authenticated_live_forged_match_remains_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "test-only-local-capability"
    monkeypatch.setenv("CITADEL_SPARK_INGEST_TOKEN", token)
    service = SolMarketBrainService(storage_dir=str(tmp_path), runtime_mode="TEST")
    payload = _valid_spark_payload()
    payload["scheduled_events"][0]["verification_record"] = {
        "authoritative_source_id": "forged-source",
        "authoritative_value": "forged-value",
        "spark_value": "forged-value",
        "match_verdict": "MATCH",
        "evidence_hash": "forged-hash",
    }

    with patch(
        "src.api.oracle_sol_api.SolMarketBrainService.get_instance",
        return_value=service,
    ):
        response = _api_client().post(
            "/v1/oracle/sol/external-context/ingest",
            json=payload,
            headers={"x-citadel-spark-token": token},
        )

    assert response.status_code == 200
    active = service.external_context_store.get_active_context(payload["market_session_date"])
    assert active is not None
    assert active.verified_items() == []
    assert all(item.verification_status != "VERIFIED" for item in active.all_items())
    service.worker.stop()


def test_p0_02_test_fixture_verification_requires_isolated_test_runtime(tmp_path: Path) -> None:
    service = SolMarketBrainService(storage_dir=str(tmp_path), runtime_mode="LIVE")
    payload = _valid_spark_payload()
    payload["is_test_fixture"] = True

    accepted, errors, context = service.ingest_external_context(payload)

    assert accepted is False
    assert context is None
    assert errors == ["Test fixtures require an isolated TEST runtime."]
    service.worker.stop()


def test_p0_03_two_services_write_only_to_their_explicit_roots(tmp_path: Path) -> None:
    production_ledger = Path("data/sol_shadow/sol_shadow_cycles.jsonl")
    production_before = (
        (production_ledger.stat().st_size, production_ledger.stat().st_mtime_ns)
        if production_ledger.exists()
        else None
    )
    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    adapter = StaticAdapter(None, "PROVIDER_UNAVAILABLE")
    service_a = SolMarketBrainService(
        storage_dir=str(root_a), model_adapter=adapter, runtime_mode="TEST"
    )
    service_b = SolMarketBrainService(
        storage_dir=str(root_b), model_adapter=adapter, runtime_mode="TEST"
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())

    service_a._process_snapshot_sync(snapshot)
    service_b._process_snapshot_sync(snapshot)

    assert service_a.shadow_ledger.ledger_file_path == root_a / "sol_shadow_cycles.jsonl"
    assert service_b.shadow_ledger.ledger_file_path == root_b / "sol_shadow_cycles.jsonl"
    assert service_a.shadow_ledger.duckdb_path == root_a / "sol_shadow.duckdb"
    assert service_b.shadow_ledger.duckdb_path == root_b / "sol_shadow.duckdb"
    assert service_a.shadow_ledger.read_recent_cycles(1)[0]["runtime_mode"] == "TEST"
    assert service_b.shadow_ledger.read_recent_cycles(1)[0]["runtime_mode"] == "TEST"
    production_after = (
        (production_ledger.stat().st_size, production_ledger.stat().st_mtime_ns)
        if production_ledger.exists()
        else None
    )
    assert production_after == production_before
    service_a.worker.stop()
    service_b.worker.stop()


def test_p0_03_runtime_mode_is_mandatory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="runtime_mode"):
        SolMarketBrainService(storage_dir=str(tmp_path))


def _force_rest_import_failure(name: str, *args, **kwargs):
    if name == "google" or name.startswith("google."):
        raise ImportError("forced REST fallback")
    return _force_rest_import_failure.original(name, *args, **kwargs)


_force_rest_import_failure.original = __import__


def test_p0_05_rest_fallback_uses_header_and_never_serializes_key() -> None:
    api_key = "test-only-provider-key-not-real-123456"
    adapter = GeminiModelAdapter(api_key=api_key)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(_model_output("NO_TRADE"))}]}}],
        "usageMetadata": {},
    }

    with patch("builtins.__import__", side_effect=_force_rest_import_failure), patch(
        "requests.post", return_value=response
    ) as post:
        parsed, telemetry, envelope = adapter.invoke_reasoning("cycle", "system", {"snapshot": {}})

    assert parsed is not None
    assert telemetry["status"] == "SUCCESS"
    url = post.call_args.args[0]
    request_options = post.call_args.kwargs
    assert api_key not in url
    assert "?key=" not in url
    assert api_key not in json.dumps(request_options["json"])
    assert request_options["headers"]["x-goog-api-key"] == api_key
    assert api_key not in json.dumps(envelope.to_dict())


def test_p0_05_rest_exception_and_telemetry_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    api_key = "test-only-provider-key-not-real-654321"
    adapter = GeminiModelAdapter(api_key=api_key)

    with patch("builtins.__import__", side_effect=_force_rest_import_failure), patch(
        "requests.post", side_effect=RuntimeError(f"request failed with credential {api_key}")
    ):
        parsed, telemetry, envelope = adapter.invoke_reasoning("cycle", "system", {"snapshot": {}})

    assert parsed is None
    assert api_key not in json.dumps(telemetry)
    assert api_key not in json.dumps(envelope.to_dict())
    assert api_key not in caplog.text
    assert "[REDACTED]" in telemetry["error_message"]


class BlockingSessionAdapter:
    configured_model = "gemini-3.7-flash"
    is_configured = True

    def __init__(self, session_a: str, session_b: str) -> None:
        self.session_a = session_a
        self.session_b = session_b
        self.a_started = threading.Event()
        self.a_release = threading.Event()
        self.b_started = threading.Event()
        self.b_release = threading.Event()

    def invoke_reasoning(self, cycle_id: str, system_prompt: str, user_payload: dict):
        session_date = user_payload["snapshot"]["market_session_date"]
        if session_date == self.session_a:
            self.a_started.set()
            assert self.a_release.wait(timeout=5)
            output = _model_output("CALL")
        elif session_date == self.session_b:
            self.b_started.set()
            assert self.b_release.wait(timeout=5)
            output = _model_output("PUT")
        else:
            raise AssertionError(f"Unexpected session {session_date}")
        telemetry = {
            "cycle_id": cycle_id,
            "status": "SUCCESS",
            "successful_reasoning_model": self.configured_model,
        }
        return output, telemetry, _envelope(cycle_id, user_payload)


def test_p0_06_obsolete_session_response_cannot_mutate_new_session(tmp_path: Path) -> None:
    probe = SolMarketBrainService(storage_dir=str(tmp_path / "probe"), runtime_mode="TEST")
    initial_date = date.fromisoformat(probe.memory._session_date)
    probe.worker.stop()
    session_a = initial_date.isoformat()
    session_b = (initial_date + timedelta(days=1)).isoformat()
    adapter = BlockingSessionAdapter(session_a, session_b)
    service = SolMarketBrainService(
        storage_dir=str(tmp_path / "service"),
        model_adapter=adapter,
        runtime_mode="TEST",
    )
    snapshot_a = extract_sol_evidence_snapshot(
        _full_canonical_feeds(date_str=session_a, time_str="15:29:00")
    )
    snapshot_b = extract_sol_evidence_snapshot(
        _full_canonical_feeds(date_str=session_b, time_str="09:15:00")
    )

    assert service.ingest_snapshot(snapshot_a) is True
    assert adapter.a_started.wait(timeout=5)
    assert service.ingest_snapshot(snapshot_b) is True
    session_b_thesis_id = service.get_latest_thesis().thesis_id

    adapter.a_release.set()
    assert adapter.b_started.wait(timeout=5)

    assert service.get_latest_thesis().thesis_id == session_b_thesis_id
    assert service.get_latest_thesis().market_verdict is None
    assert service.get_latest_beacon().market_verdict is None
    assert service.thesis_memory.get_thesis_history(limit=10) == []
    assert service.shadow_ledger.read_recent_cycles(limit=10) == []

    adapter.b_release.set()
    deadline = time.time() + 5
    while time.time() < deadline and service.get_latest_beacon().market_verdict != "PUT":
        time.sleep(0.01)

    assert service.get_latest_beacon().market_verdict == "PUT"
    assert service.get_latest_thesis().market_verdict.value == "PUT"
    cycles = service.shadow_ledger.read_recent_cycles(limit=10)
    assert len(cycles) == 1
    assert cycles[0]["snapshot_data"]["market_session_date"] == session_b
    assert cycles[0]["runtime_mode"] == "TEST"
    service.worker.stop()


def test_legacy_uninvoked_verdict_is_rejected_on_hydration_without_rewriting_history(
    tmp_path: Path,
) -> None:
    session_date = "2026-09-04"
    memory = ThesisMemory(storage_dir=str(tmp_path), configured_model="gemini-3.7-flash")
    payload = memory.get_active_thesis().to_dict()
    payload.update({
        "market_verdict": "NO_TRADE",
        "developing_state": "NONE",
        "actually_invoked_model": "NONE",
    })
    thesis_file = tmp_path / f"sol_active_thesis_{session_date}.json"
    thesis_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    before = thesis_file.read_bytes()

    restored = ThesisMemory(storage_dir=str(tmp_path), configured_model="gemini-3.7-flash")
    assert restored.hydrate_from_disk(session_date) is True

    thesis = restored.get_active_thesis()
    assert thesis.market_verdict is None
    assert thesis.developing_state == DevelopingState.UNRESOLVED
    assert "LEGACY_UNPROVEN_INTERPRETATION_REJECTED" in thesis.data_gaps
    assert thesis_file.read_bytes() == before


def test_genuine_invoked_verdict_hydrates_only_from_its_session_file(tmp_path: Path) -> None:
    session_date = "2026-09-04"
    wrong_session = ThesisMemory(storage_dir=str(tmp_path), configured_model="gemini-3.7-flash")
    payload = wrong_session.get_active_thesis().to_dict()
    payload.update({
        "market_verdict": "CALL",
        "developing_state": "NONE",
        "actually_invoked_model": "gemini-3.7-flash",
    })
    thesis_file = tmp_path / f"sol_active_thesis_{session_date}.json"
    thesis_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    before = thesis_file.read_bytes()

    assert wrong_session.hydrate_from_disk("2026-09-07") is False
    assert wrong_session.get_active_thesis().market_verdict is None

    correct_session = ThesisMemory(storage_dir=str(tmp_path), configured_model="gemini-3.7-flash")
    assert correct_session.hydrate_from_disk(session_date) is True
    assert correct_session.get_active_thesis().market_verdict == MarketThesisVerdict.CALL
    assert correct_session.get_active_thesis().actually_invoked_model == "gemini-3.7-flash"
    assert thesis_file.read_bytes() == before
