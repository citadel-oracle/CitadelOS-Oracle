"""Focused, network-free regressions for Gemini provider error telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.oracle_sol_api import router
from src.oracle_sol.contracts import SolModelRequestEnvelope
from src.oracle_sol.gemini_adapter import GeminiModelAdapter
from src.oracle_sol.service import SolMarketBrainService
from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
from tests.oracle_sol.test_oracle_sol import _full_canonical_feeds


TEST_KEY = "test-only-gemini-provider-key-123456789"


class FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class FakeProviderError(Exception):
    def __init__(
        self,
        *,
        code: int | None,
        status: str | None,
        message: str,
        details: dict | None = None,
        headers: dict | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.message = message
        self.details = details or {
            "error": {"code": code, "status": status, "message": message}
        }
        self.response = FakeResponse(code or 0, headers=headers)
        super().__init__(message)


def _quota_error(
    *,
    quota_metric: str,
    quota_id: str,
    quota_value: str = "10",
    headers: dict | None = None,
) -> FakeProviderError:
    return FakeProviderError(
        code=429,
        status="RESOURCE_EXHAUSTED",
        message="Quota limit reached for the configured project.",
        headers=headers,
        details={
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota limit reached for the configured project.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": quota_metric,
                                "quotaId": quota_id,
                                "quotaValue": quota_value,
                                "quotaDimensions": {
                                    "model": "gemini-3.7-flash",
                                    "location": "global",
                                },
                            }
                        ],
                    }
                ],
            }
        },
    )


def _invoke_sdk_failure(error: BaseException) -> tuple[dict | None, dict]:
    adapter = GeminiModelAdapter(api_key=TEST_KEY)
    with patch("google.genai.Client") as client:
        client.return_value.models.generate_content.side_effect = error
        parsed, telemetry, _ = adapter.invoke_reasoning(
            "cycle-provider-error", "system", {"snapshot": {}}
        )
        assert client.return_value.models.generate_content.call_count == 1
        http_options = client.call_args.kwargs["http_options"]
        assert http_options.retry_options.attempts == 1
    return parsed, telemetry


@pytest.mark.parametrize(
    "quota_metric, quota_id, expected_category",
    [
        (
            "generativelanguage.googleapis.com/generate_content_requests",
            "GenerateRequestsPerMinutePerProjectPerModel",
            "QUOTA_LIMIT_RPM",
        ),
        (
            "generativelanguage.googleapis.com/generate_content_input_tokens",
            "GenerateContentInputTokensPerModelPerMinute",
            "QUOTA_LIMIT_TPM",
        ),
        (
            "generativelanguage.googleapis.com/generate_content_requests",
            "GenerateRequestsPerDayPerProjectPerModel",
            "QUOTA_LIMIT_RPD",
        ),
    ],
)
def test_sdk_429_quota_metadata_has_specific_safe_category(
    quota_metric: str, quota_id: str, expected_category: str
) -> None:
    parsed, telemetry = _invoke_sdk_failure(
        _quota_error(quota_metric=quota_metric, quota_id=quota_id)
    )

    assert parsed is None
    assert telemetry["status"] == expected_category
    assert telemetry["http_status"] == 429
    assert telemetry["provider_error_code"] == 429
    assert telemetry["provider_error_status"] == "RESOURCE_EXHAUSTED"
    assert telemetry["quota_metric"] == quota_metric
    assert telemetry["quota_id"] == quota_id
    assert telemetry["quota_dimensions"] == {
        "model": "gemini-3.7-flash",
        "location": "global",
    }
    assert telemetry["provider_request_attempt"] == 1


def test_sdk_429_without_quota_or_capacity_evidence_stays_unknown() -> None:
    parsed, telemetry = _invoke_sdk_failure(
        FakeProviderError(
            code=429,
            status="RESOURCE_EXHAUSTED",
            message="Request rejected.",
        )
    )

    assert parsed is None
    assert telemetry["status"] == "UNKNOWN_429"
    assert telemetry["quota_metric"] is None


def test_explicit_provider_capacity_is_single_attempt_without_immediate_retry() -> None:
    adapter = GeminiModelAdapter(api_key=TEST_KEY)
    error = FakeProviderError(
        code=503,
        status="RESOURCE_EXHAUSTED",
        message="Model capacity exhausted due to high demand.",
    )
    with patch("google.genai.Client") as client, patch("time.sleep") as sleep:
        client.return_value.models.generate_content.side_effect = error
        parsed, telemetry, _ = adapter.invoke_reasoning(
            "cycle-capacity", "system", {"snapshot": {}}
        )

    assert parsed is None
    assert telemetry["status"] == "PROVIDER_CAPACITY"
    assert telemetry["provider_request_attempt"] == 1
    assert client.return_value.models.generate_content.call_count == 1
    assert sleep.call_count == 0


def test_sdk_timeout_is_not_retried_or_called_quota() -> None:
    parsed, telemetry = _invoke_sdk_failure(TimeoutError("provider timed out after 30 seconds"))

    assert parsed is None
    assert telemetry["status"] == "TIMEOUT"
    assert telemetry["http_status"] is None
    assert telemetry["provider_request_attempt"] == 1


def _force_rest_import_failure(name: str, *args, **kwargs):
    if name == "google" or name.startswith("google."):
        raise ImportError("force REST fallback")
    return _force_rest_import_failure.original(name, *args, **kwargs)


_force_rest_import_failure.original = __import__


def test_rest_429_extracts_metadata_and_honors_retry_after_without_second_call() -> None:
    adapter = GeminiModelAdapter(api_key=TEST_KEY)
    response = MagicMock()
    response.status_code = 429
    response.headers = {"Retry-After": "120"}
    quota_error = _quota_error(
        quota_metric="generativelanguage.googleapis.com/generate_content_requests",
        quota_id="GenerateRequestsPerMinutePerProjectPerModel",
    )
    response.json.return_value = quota_error.details

    with patch("builtins.__import__", side_effect=_force_rest_import_failure), patch(
        "requests.post", return_value=response
    ) as post:
        parsed, telemetry, _ = adapter.invoke_reasoning(
            "cycle-rest-quota", "system", {"snapshot": {}}
        )
        deferred, deferred_telemetry, _ = adapter.invoke_reasoning(
            "cycle-rest-deferred", "system", {"snapshot": {}}
        )

    assert parsed is None
    assert telemetry["status"] == "QUOTA_LIMIT_RPM"
    assert telemetry["retry_after"] == "120"
    assert telemetry["retry_after_seconds"] == 120.0
    assert deferred is None
    assert deferred_telemetry["status"] == "RETRY_DEFERRED"
    assert deferred_telemetry["request_attempted"] is False
    assert post.call_count == 1


def test_rest_timeout_is_safe_and_not_retried() -> None:
    adapter = GeminiModelAdapter(api_key=TEST_KEY)
    with patch("builtins.__import__", side_effect=_force_rest_import_failure), patch(
        "requests.post", side_effect=requests.Timeout("read timed out")
    ) as post:
        parsed, telemetry, _ = adapter.invoke_reasoning(
            "cycle-rest-timeout", "system", {"snapshot": {}}
        )

    assert parsed is None
    assert telemetry["status"] == "TIMEOUT"
    assert telemetry["provider_request_attempt"] == 1
    assert post.call_count == 1


def test_secret_shaped_sdk_error_is_redacted_from_all_telemetry() -> None:
    error = FakeProviderError(
        code=None,
        status=None,
        message=(
            f"request URL https://example.invalid/path?key={TEST_KEY} "
            f"Authorization: Bearer {TEST_KEY} x-goog-api-key: {TEST_KEY}"
        ),
    )
    parsed, telemetry = _invoke_sdk_failure(error)
    serialized = json.dumps(telemetry)

    assert parsed is None
    assert TEST_KEY not in serialized
    assert "[REDACTED]" in telemetry["safe_provider_message"]


class StaticFailureAdapter:
    configured_model = "gemini-3.7-flash"
    is_configured = True
    api_key = TEST_KEY

    def __init__(self, status: str) -> None:
        self.status = status

    def invoke_reasoning(self, cycle_id: str, system_prompt: str, user_payload: dict):
        envelope = SolModelRequestEnvelope(
            cycle_id=cycle_id,
            prompt_version="provider-error-test",
            prompt_hash="prompt-hash",
            input_hash="input-hash",
            system_prompt=system_prompt,
            user_payload=user_payload,
            configured_model=self.configured_model,
            requested_model=self.configured_model,
            reasoning_effort="medium",
        )
        return None, {
            "cycle_id": cycle_id,
            "status": self.status,
            "http_status": 429 if "429" in self.status or "QUOTA" in self.status else None,
            "provider_error_code": 429,
            "provider_error_status": "RESOURCE_EXHAUSTED",
            "safe_provider_message": f"x-goog-api-key: {TEST_KEY}",
            "provider_request_attempt": 1,
            "successful_reasoning_model": "NONE",
        }, envelope


@pytest.mark.parametrize(
    "status",
    [
        "QUOTA_LIMIT_RPM",
        "QUOTA_LIMIT_TPM",
        "QUOTA_LIMIT_RPD",
        "UNKNOWN_429",
        "PROVIDER_CAPACITY",
        "TIMEOUT",
    ],
)
def test_every_provider_failure_category_keeps_market_verdict_null(
    tmp_path: Path, status: str
) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path / status),
        model_adapter=StaticFailureAdapter(status),
        runtime_mode="TEST",
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())

    _, beacon, telemetry, _ = service._process_snapshot_sync(snapshot)

    assert telemetry["status"] == status
    assert beacon.market_verdict is None
    assert beacon.market_verdict != "NO_TRADE"
    assert beacon.reasoning_status == "DEGRADED_ADVISORY"
    service.worker.stop()


def test_safe_last_error_is_exposed_and_persisted_without_secret(tmp_path: Path) -> None:
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=StaticFailureAdapter("UNKNOWN_429"),
        runtime_mode="TEST",
    )
    snapshot = extract_sol_evidence_snapshot(_full_canonical_feeds())
    service._process_snapshot_sync(snapshot)

    state = service.get_latest_state()
    provider = state["provider_telemetry"]
    cycles = service.shadow_ledger.read_recent_cycles(limit=1)
    serialized_state = json.dumps(state)
    serialized_cycle = json.dumps(cycles[0])

    assert provider["provider_status"] == "DEGRADED"
    assert provider["last_http_status"] == 429
    assert provider["last_error_category"] == "UNKNOWN_429"
    assert provider["last_error_at"] is not None
    assert provider["provider_request_attempt"] == 1
    assert cycles[0]["provider_error_telemetry"]["last_error_category"] == "UNKNOWN_429"
    assert TEST_KEY not in serialized_state
    assert TEST_KEY not in serialized_cycle

    app = FastAPI()
    app.include_router(router)
    with patch(
        "src.api.oracle_sol_api.SolMarketBrainService.get_instance",
        return_value=service,
    ):
        health = TestClient(app).get("/v1/oracle/sol/health")
    assert health.status_code == 200
    assert health.json()["provider_telemetry"]["last_error_category"] == "UNKNOWN_429"
    assert TEST_KEY not in health.text
    service.worker.stop()
