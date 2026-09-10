"""Focused unit tests for Gemini multi-profile failover and transport isolation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from src.oracle_sol.gemini_adapter import (
    GeminiModelAdapter,
    _classify_provider_failure,
    _quota_limit_category,
    get_secure_gemini_api_key,
    resolve_gemini_api_key_with_source,
)
from src.oracle_sol.provider_client import ProviderNeutralClient, NormalizedProviderResponse
from src.oracle_sol.provider_secrets import safe_key_fingerprint, redact_text


def test_exact_model_and_profile_selection():
    adapter = GeminiModelAdapter(profile="gemini_secondary")
    assert adapter.configured_model == "gemini-3.8-flash"
    assert adapter.profile == "gemini_secondary"
    assert "gemini_primary" in adapter.fallback_profiles or "gemini_tertiary" in adapter.fallback_profiles


def test_secret_masking_never_exposes_full_key():
    test_key = "AQ.Ab8RNabc12345xyz678901234567890abcdef"
    fp = safe_key_fingerprint(test_key)
    assert test_key not in fp
    assert fp.startswith("AQ.Ab8R...")
    assert fp.endswith("abcdef")

    redacted = redact_text(f"error with key {test_key} in header")
    assert test_key not in redacted
    assert "[REDACTED_GEMINI]" in redacted or "[REDACTED]" in redacted


def test_quota_rpd_classification_for_free_tier_ceiling():
    failure = {
        "http_status": 429,
        "quota_metric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
        "quota_id": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        "quota_limit": "20",
    }
    cat = _quota_limit_category(failure)
    assert cat == "QUOTA_LIMIT_RPD"
    classified = _classify_provider_failure(failure)
    assert classified == "QUOTA_LIMIT_RPD"


def test_provider_client_gemini_failover_on_429():
    client = ProviderNeutralClient()
    invoked_profiles = []

    def mock_invoke_gemini(prov, model_id, req_id, sys_prompt, user_prompt, schema, timeout, max_tokens, reasoning, timestamp, profile="gemini_primary"):
        invoked_profiles.append(profile)
        if profile == "gemini_primary":
            return NormalizedProviderResponse(
                provider="google",
                model_id=model_id,
                http_status=429,
                error_class="RATE_LIMITED",
                error_message="Primary RPD exhausted",
                success=False,
                requested_profile=profile,
                actual_profile=profile,
            )
        elif profile == "gemini_secondary":
            return NormalizedProviderResponse(
                provider="google",
                model_id=model_id,
                http_status=200,
                success=True,
                response_text='{"status":"ok","number":7}',
                parsed_output={"status": "ok", "number": 7},
                requested_profile=profile,
                actual_profile=profile,
            )
        return NormalizedProviderResponse(provider="google", model_id=model_id, http_status=500, success=False)

    client._invoke_gemini = mock_invoke_gemini

    resp = client._dispatch(
        provider="gemini",
        model_id="gemini-3.8-flash",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert resp.success is True
    assert resp.http_status == 200
    assert resp.actual_profile == "gemini_secondary"
    assert resp.fallback_path == "gemini_primary -> gemini_secondary"
    assert invoked_profiles == ["gemini_primary", "gemini_secondary"]


def test_no_retry_storm_on_unanimous_failure():
    client = ProviderNeutralClient()
    invoked_profiles = []

    def mock_invoke_gemini(prov, model_id, req_id, sys_prompt, user_prompt, schema, timeout, max_tokens, reasoning, timestamp, profile="gemini_primary"):
        invoked_profiles.append(profile)
        return NormalizedProviderResponse(
            provider="google",
            model_id=model_id,
            http_status=429,
            error_class="RATE_LIMITED",
            error_message="RPD exhausted",
            success=False,
            requested_profile=profile,
            actual_profile=profile,
        )

    client._invoke_gemini = mock_invoke_gemini

    resp = client._dispatch(
        provider="gemini",
        model_id="gemini-3.8-flash",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert resp.success is False
    assert resp.http_status == 429
    # Exactly one call per profile across the 3 configured profiles
    assert invoked_profiles == ["gemini_primary", "gemini_secondary", "gemini_tertiary"]
    assert len(invoked_profiles) == 3


def test_no_cross_provider_fallback_to_groq_or_experiential():
    client = ProviderNeutralClient()
    client._invoke_groq = MagicMock(side_effect=AssertionError("Groq must NEVER be called"))
    client._invoke_experiential = MagicMock(side_effect=AssertionError("Experiential must NEVER be called"))

    def mock_invoke_gemini(*args, **kwargs):
        return NormalizedProviderResponse(
            provider="google", model_id="gemini-3.8-flash", http_status=429,
            error_class="RATE_LIMITED", success=False,
        )

    client._invoke_gemini = mock_invoke_gemini

    resp = client._dispatch(
        provider="gemini",
        model_id="gemini-3.8-flash",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert resp.success is False
    client._invoke_groq.assert_not_called()
    client._invoke_experiential.assert_not_called()
