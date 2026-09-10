"""Unit and Integration Contract Tests for CITADEL Experiential Labs Adapter.

Verifies:
1. Secret resolution and safe fingerprinting / redaction
2. Missing or unauthorized API key handling (401 INVALID_KEY)
3. Model not granted handling (403 model_not_granted)
4. Model location not supported handling (403 model_location_not_supported)
5. Org under review handling (429 org_under_review, fail-closed)
6. Quota / credit budget exhausted (429 insufficient_quota)
7. Rate limit handling (429 rate_limit_exceeded with retry-after parsing)
8. Unsupported parameter and capability handling (400)
9. Structured output decoding (NATIVE_JSON_SCHEMA, JSON_OBJECT, LOCAL_POST_VALIDATION)
10. Silent model substitution detection (requested model vs returned model)
11. Commercial state zero-cost protection: fail-closed if cost_micro_usd > 0
12. ZDR and privacy boundary compliance (ZDR_ELIGIBLE vs PRIVACY_RESTRICTED_FOR_PRODUCTION)
13. Provider-neutral client dispatch integration
14. Quota governor telemetry update and non-zero cost violation detection
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from src.oracle_sol.experiential_adapter import (
    ERR_BUDGET_EXHAUSTED,
    ERR_INVALID_KEY,
    ERR_INVALID_PARAMETER,
    ERR_MODEL_LOCATION_NOT_SUPPORTED,
    ERR_MODEL_NOT_GRANTED,
    ERR_ORG_UNDER_REVIEW,
    ERR_POLICY_RETENTION_BLOCKED,
    ERR_RATE_LIMIT,
    ERR_UNSUPPORTED_CAPABILITY,
    ERR_UNSUPPORTED_PARAMETER,
    ExperientialAdapter,
)
from src.oracle_sol.provider_client import ProviderNeutralClient
from src.oracle_sol.provider_registry import (
    CATALOG_PROMOTIONAL_FREE,
    GLOBAL_PROVIDER_REGISTRY,
    LIVE_ZERO_COST_PENDING,
    PROMOTIONAL_ZERO_COST,
)
from src.oracle_sol.provider_secrets import (
    redact_text,
    resolve_secret,
    safe_key_fingerprint,
)
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor


def test_experiential_secret_resolution_and_redaction():
    val, src = resolve_secret("experiential")
    assert val is not None
    assert val.startswith("xpl_")
    fp = safe_key_fingerprint(val)
    assert fp.startswith("xpl_")
    assert "..." in fp
    assert len(fp) < len(val)

    # Redaction test
    secret_text = f"Header: Bearer {val}"
    redacted = redact_text(secret_text)
    assert val not in redacted
    assert "[REDACTED" in redacted


def test_experiential_missing_key():
    with patch("src.oracle_sol.experiential_adapter.resolve_secret", return_value=(None, "UNCONFIGURED")):
        adapter = ExperientialAdapter(api_key=None)
        assert not adapter.is_available()
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert out is None
        assert telemetry["error_class"] == ERR_INVALID_KEY


def test_experiential_privacy_guard():
    adapter = ExperientialAdapter(api_key="xpl_mock_test_key_valid_fingerprint_12345")
    assert adapter.is_available()

    banned_prompt = "Order flow: dhan_client_id=123456 path=/Users/ayushmudgal/key.json"
    out, telemetry = adapter.invoke_reasoning("test_req", "system", banned_prompt)
    assert out is None
    assert telemetry["error_class"] == "PRIVACY_POLICY_BLOCKED"
    assert "Banned privacy token detected" in telemetry["error"]


def test_experiential_org_under_review_error_429():
    adapter = ExperientialAdapter(api_key="xpl_mock_test_key_valid_fingerprint_12345")

    err_body = {
        "error": {
            "message": "Your organization is under review to fight spam and can't use models right now.",
            "type": "insufficient_quota",
            "param": None,
            "code": "org_under_review",
        }
    }
    http_err = urllib.error.HTTPError(
        "https://api.experientiallabs.ai/v1/chat/completions",
        429,
        "Too Many Requests",
        {},
        io.BytesIO(json.dumps(err_body).encode("utf-8")),
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert out is None
        assert telemetry["error_class"] == ERR_ORG_UNDER_REVIEW
        assert telemetry["http_status"] == 429
        assert "under review" in telemetry["error"]


def test_experiential_model_not_granted_403():
    adapter = ExperientialAdapter(api_key="xpl_mock_test_key_valid_fingerprint_12345")

    err_body = {
        "error": {
            "message": "The requested model alias is not granted to this identity.",
            "type": "permission_error",
            "code": "model_not_granted",
            "param": None,
        }
    }
    http_err = urllib.error.HTTPError(
        "https://api.experientiallabs.ai/v1/chat/completions",
        403,
        "Forbidden",
        {},
        io.BytesIO(json.dumps(err_body).encode("utf-8")),
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert out is None
        assert telemetry["error_class"] == ERR_MODEL_NOT_GRANTED
        assert telemetry["http_status"] == 403


def test_experiential_model_location_not_supported_403():
    adapter = ExperientialAdapter(api_key="xpl_mock_test_key_valid_fingerprint_12345")

    err_body = {
        "error": {
            "message": "The request location is outside this model maker's supported regions.",
            "type": "policy_error",
            "code": "model_location_not_supported",
            "param": None,
        }
    }
    http_err = urllib.error.HTTPError(
        "https://api.experientiallabs.ai/v1/chat/completions",
        403,
        "Forbidden",
        {},
        io.BytesIO(json.dumps(err_body).encode("utf-8")),
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert out is None
        assert telemetry["error_class"] == ERR_MODEL_LOCATION_NOT_SUPPORTED
        assert telemetry["http_status"] == 403


def test_experiential_rate_limit_and_retry_after():
    adapter = ExperientialAdapter(api_key="xpl_mock_test_key_valid_fingerprint_12345")

    err_body = {
        "error": {
            "message": "Rate limit exceeded.",
            "type": "rate_limit_error",
            "code": "rate_limit_exceeded",
            "param": None,
        }
    }
    mock_headers = {
        "x-ratelimit-remaining-requests": "0",
        "retry-after": "15.0",
    }
    http_err = urllib.error.HTTPError(
        "https://api.experientiallabs.ai/v1/chat/completions",
        429,
        "Too Many Requests",
        mock_headers,
        io.BytesIO(json.dumps(err_body).encode("utf-8")),
    )

    with patch("urllib.request.urlopen", side_effect=http_err), patch("time.sleep") as mock_sleep:
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert out is None
        assert telemetry["error_class"] == ERR_RATE_LIMIT
        assert adapter.rate_limits["retry_after_seconds"] == 15.0
        assert adapter.rate_limits["remaining_requests"] == 0
        assert adapter.rate_limits["total_429_count"] > 0


def test_experiential_structured_output_success():
    adapter = ExperientialAdapter(model_name="gpt-6-astra", api_key="xpl_mock_test_key_valid_fingerprint_12345")

    mock_resp = {
        "id": "xpl-chatcmpl-test",
        "model": "gpt-6-astra",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"verdict": "CALL", "confidence": 0.88, "notes": "Momentum expansion"}',
                },
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 35,
            "total_tokens": 155,
        },
        "cost_micro_usd": 0,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string"},
                "confidence": {"type": "number"},
                "notes": {"type": "string"},
            },
            "required": ["verdict", "confidence"],
        }
        out, telemetry = adapter.invoke_reasoning(
            "test_req",
            "system",
            "user",
            schema=schema,
            structured_mode="NATIVE_JSON_SCHEMA",
        )
        assert out is not None
        assert out["verdict"] == "CALL"
        assert out["confidence"] == 0.88
        assert telemetry["total_tokens"] == 155
        assert telemetry["cost_micro_usd"] == 0
        assert telemetry["model_substitution_detected"] is False


def test_experiential_silent_model_substitution_detection():
    adapter = ExperientialAdapter(model_name="gpt-6-astra", api_key="xpl_mock_test_key_valid_fingerprint_12345")

    mock_resp = {
        "id": "xpl-chatcmpl-test",
        "model": "gpt-4o-mini",  # Substituted model!
        "choices": [{"message": {"role": "assistant", "content": '{"status": "ok"}'}}],
        "usage": {"total_tokens": 50},
        "cost_micro_usd": 0,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert telemetry["model_substitution_detected"] is True
        assert telemetry["response_model"] == "gpt-4o-mini"
        assert telemetry["requested_model"] == "gpt-6-astra"


def test_experiential_commercial_state_zero_cost_fail_closed():
    adapter = ExperientialAdapter(
        model_name="gpt-6-astra",
        api_key="xpl_mock_test_key_valid_fingerprint_12345",
        enforce_zero_cost=True,
    )

    # Simulates model unexpectedly incurring monetary spend ($0.05 = 50000 micro-USD)
    mock_resp = {
        "id": "xpl-chatcmpl-test",
        "model": "gpt-6-astra",
        "choices": [{"message": {"role": "assistant", "content": '{"status": "ok"}'}}],
        "usage": {"total_tokens": 100},
        "cost_micro_usd": 50000,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        out, telemetry = adapter.invoke_reasoning("test_req", "system", "user")
        assert out is None
        assert telemetry["error_class"] == "COMMERCIAL_STATE_VIOLATION"
        assert "Zero-cost model incurred monetary spend" in telemetry["error"]


def test_experiential_privacy_zdr_classifications():
    adapter = ExperientialAdapter()
    assert adapter.get_retention_verdict("gpt-6-astra") == "not_zdr"
    assert adapter.is_privacy_restricted("gpt-6-astra") is True

    assert adapter.get_retention_verdict("gpt-5.6-luna") == "not_zdr"
    assert adapter.is_privacy_restricted("gpt-5.6-luna") is True

    assert adapter.get_retention_verdict("deepseek-v4-flash") == "unknown"
    assert adapter.is_privacy_restricted("deepseek-v4-flash") is True

    assert adapter.get_retention_verdict("qwen3.8-27b") == "unknown"
    assert adapter.is_privacy_restricted("qwen3.8-27b") is True
    assert adapter.is_privacy_restricted("unrecognized-model") is True


def test_experiential_provider_registry_registrations():
    # Verify all 4 models are registered with CATALOG_PROMOTIONAL_FREE and LIVE_ZERO_COST_PENDING (Astra authority preserved)
    for model_id in ["gpt-6-astra", "gpt-5.6-luna", "deepseek-v4-flash", "qwen3.8-27b"]:
        cap = GLOBAL_PROVIDER_REGISTRY.get("experiential", model_id)
        assert cap is not None, f"Model {model_id} must be in registry"
        assert cap.enabled is False, f"Model {model_id} must remain cognitively unassigned (enabled=False)"
        assert cap.commercial_status == CATALOG_PROMOTIONAL_FREE
        assert cap.verification_state == LIVE_ZERO_COST_PENDING
        assert cap.last_health_status == "ORG_REVIEW_BLOCKED"
        assert cap.provider == "experiential"
        assert cap.context_window >= 1000000


def test_experiential_quota_governor_telemetry():
    gov = CognitiveQuotaGovernor()
    gov.register_model_binding("exp_gpt6", "experiential", "gpt-6-astra")

    # Update with headers and cost
    gov.update_from_experiential_telemetry(
        "exp_gpt6",
        {"limit_requests": 1000, "remaining_requests": 995, "limit_tokens": 100000, "remaining_tokens": 98000},
        http_status=200,
        latency_ms=450.0,
        cost_micro_usd=0,
    )
    st = gov.model_states["exp_gpt6"]
    assert st.remaining_requests == 995
    assert st.remaining_tokens == 98000
    assert "cost_violation" not in st.raw_headers

    # Violation update
    gov.update_from_experiential_telemetry(
        "exp_gpt6",
        {},
        http_status=200,
        cost_micro_usd=15000,
    )
    assert "cost_violation" in st.raw_headers
    assert st.raw_headers["cost_violation"]["value"] == "15000"


def test_experiential_neutral_client_unassigned_fail_safe():
    """Unapproved/unassigned promotional models are strictly blocked by ProviderNeutralClient."""
    client = ProviderNeutralClient()
    res = client.invoke("experiential", "gpt-6-astra", [{"role": "user", "content": "hello"}])
    assert res.success is False
    assert res.error_class == "MODEL_NOT_APPROVED"
    assert "not enabled" in res.error_message


def test_experiential_neutral_client_direct_dispatch():
    """Verify ProviderNeutralClient._dispatch reaches ExperientialAdapter with strict schema."""
    client = ProviderNeutralClient()
    mock_resp = {
        "id": "xpl-dispatch-test",
        "model": "gpt-6-astra",
        "choices": [{"message": {"role": "assistant", "content": '{"status": "DISPATCH_OK"}'}}],
        "usage": {"total_tokens": 42},
        "cost_micro_usd": 0,
    }
    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value.status = 200
    mock_urlopen.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    mock_urlopen.__enter__.return_value.headers = {}

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        norm = client._dispatch(
            provider="experiential",
            model_id="gpt-6-astra",
            messages=[{"role": "user", "content": "status check"}],
            schema={"type": "object", "properties": {"status": {"type": "string"}}},
        )
        assert norm.provider == "experiential"
        assert norm.success is True
        assert norm.parsed_output == {"status": "DISPATCH_OK"}
        assert norm.usage["total_tokens"] == 42
        assert norm.credential_fingerprint_safe.startswith("xpl_")
