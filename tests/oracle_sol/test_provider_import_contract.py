"""Offline import trust gate. All provider dispatch is mocked."""
import ssl
from unittest.mock import Mock

import pytest

from src.oracle_sol.provider_client import ProviderNeutralClient, NormalizedProviderResponse
from src.oracle_sol.provider_registry import GLOBAL_PROVIDER_REGISTRY
from src.oracle_sol.provider_secrets import create_strict_ssl_context, redact_text, PROVIDER_SECRET_MAP


@pytest.mark.parametrize("provider,model", [
    ("openrouter", "openrouter/free"),
    ("openrouter", "unregistered/paid"),
    ("nvidia", "openai/gpt-oss-20b"),
    ("gemini_secondary", "gemini-3.8-flash"),
    ("gemini_primary", "gemini-3.8-flash"),
    ("cloudflare", "@cf/zai-org/glm-5.3-flash"),
])
def test_unapproved_models_never_dispatch(provider, model):
    client = ProviderNeutralClient()
    client._dispatch = Mock(side_effect=AssertionError("network boundary reached"))
    result = client.invoke(provider, model, [])
    assert not result.success
    assert result.error_class == "MODEL_NOT_APPROVED"
    client._dispatch.assert_not_called()


def test_schema_is_validated_not_merely_json_parsed():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    client = ProviderNeutralClient(CognitiveQuotaGovernor())
    client._dispatch = Mock(return_value=NormalizedProviderResponse(
        provider="groq", model_id="openai/gpt-oss-120b", success=True,
        parsed_output={"invented": "field"}, response_text='{"invented":"field"}',
    ))
    result = client.invoke("groq", "openai/gpt-oss-120b", [], quota_key="gpt_oss", schema={
        "type": "object", "properties": {"state": {"type": "string"}},
        "required": ["state"], "additionalProperties": False,
    })
    assert not result.success
    assert result.error_class == "SCHEMA_INVALID"
    assert result.parsed_output is None
    assert result.response_text == ""
    assert client._dispatch.call_count == 1


def test_system_prompt_is_also_inside_privacy_boundary():
    client = ProviderNeutralClient()
    client._dispatch = Mock()
    result = client.invoke("groq", "openai/gpt-oss-120b", [
        {"role": "system", "content": "broker_secret must not leave this machine"},
    ])
    assert result.error_class == "PRIVACY_POLICY_BLOCKED"
    client._dispatch.assert_not_called()


def test_tls_remains_verified_when_certifi_fails(monkeypatch):
    import certifi
    monkeypatch.setattr(certifi, "where", Mock(side_effect=RuntimeError("unavailable")))
    context = create_strict_ssl_context()
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_authorization_redaction_consumes_entire_bearer_token():
    assert "not-a-real-token" not in redact_text('Authorization: Bearer not-a-real-token')
    assert "not-a-real-token" not in redact_text('{"Authorization": "Bearer not-a-real-token"}')


def test_free_catalog_excludes_trial_credit():
    assert all(c.commercial_status in {"FREE_TIER", "ZERO_COST_RECURRING"}
               for c in GLOBAL_PROVIDER_REGISTRY.list_models(free_only=True))


def test_secondary_profile_has_no_generic_credential_fallback():
    assert all("SECONDARY" in name for pair in PROVIDER_SECRET_MAP["gemini_secondary"] for name in pair)


def test_unarmed_client_cannot_bypass_coordinator_quota():
    client = ProviderNeutralClient()
    client._dispatch = Mock()
    assert client.invoke("groq", "openai/gpt-oss-120b", []).error_class == "QUOTA_ADMISSION_REQUIRED"
    client._dispatch.assert_not_called()


@pytest.mark.parametrize("field", ["remaining_tokens", "remaining_requests"])
def test_observed_zero_budget_is_preserved_and_blocks_shared_groq(field):
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    governor.update_from_groq_headers("qwen", {field: 0})
    assert getattr(governor.model_states["qwen"], field) == 0
    assert getattr(governor.provider_states["groq"], field) == 0
    assert not governor.can_invoke("qwen")
    assert not governor.can_invoke("gpt_oss")


def test_provider_identity_is_not_inferred_from_role_name():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    governor.register_model_binding("specialist", "openrouter", "inclusionai/ling-3.0-flash-fin:free")
    governor.record_rate_limit("specialist", 60)
    assert not governor.can_invoke("specialist")
    assert governor.can_invoke("qwen")
    assert governor.provider_states["openrouter"].last_http_status == 429
    governor.register_model_binding("specialist", "openrouter", "inclusionai/ling-3.0-flash-fin:free")
    assert not governor.can_invoke("specialist")
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        governor.register_model_binding("specialist", "groq", "openai/gpt-oss-120b")


def test_one_429_dispatch_blocks_following_attempt_without_retry():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    client = ProviderNeutralClient(governor)
    client._dispatch = Mock(return_value=NormalizedProviderResponse(
        provider="groq", model_id="openai/gpt-oss-120b", http_status=429,
        error_class="RATE_LIMITED", rate_limits={"retry_after_seconds": 60},
    ))
    assert client.invoke("groq", "openai/gpt-oss-120b", [], quota_key="gpt_oss").http_status == 429
    assert client.invoke("groq", "openai/gpt-oss-120b", [], quota_key="gpt_oss").error_class == "QUOTA_ADMISSION_REQUIRED"
    assert client._dispatch.call_count == 1


def test_truncated_json_is_not_accepted_even_if_it_parses():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    client = ProviderNeutralClient(CognitiveQuotaGovernor())
    client._dispatch = Mock(return_value=NormalizedProviderResponse(
        provider="groq", model_id="openai/gpt-oss-120b", success=True,
        parsed_output={}, http_status=200, finish_reason="length"))
    result = client.invoke("groq", "openai/gpt-oss-120b", [], quota_key="gpt_oss")
    assert not result.success
    assert result.parsed_output is None
    assert result.error_class == "OUTPUT_TRUNCATED"


def test_exact_schema_reaches_instruction_channel_without_provider_call():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    client = ProviderNeutralClient(CognitiveQuotaGovernor())
    client._invoke_groq = Mock(return_value=NormalizedProviderResponse(
        provider="groq", model_id="openai/gpt-oss-120b", success=True, parsed_output={}))
    client.invoke("groq", "openai/gpt-oss-120b", [], quota_key="gpt_oss", schema={"type": "object"})
    system_prompt = client._invoke_groq.call_args.args[2]
    assert '"type":"object"' in system_prompt


def test_timeout_usage_is_unknown_not_free_zero_usage():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    client = ProviderNeutralClient(CognitiveQuotaGovernor())
    client._dispatch = Mock(return_value=NormalizedProviderResponse(
        provider="groq", model_id="openai/gpt-oss-120b", error_class="TIMEOUT"))
    result = client.invoke("groq", "openai/gpt-oss-120b", [], quota_key="gpt_oss")
    assert result.usage["total_tokens"] is None
    assert result.parsed_output is None


@pytest.mark.parametrize("duration,seconds", [("1m26.4s", 86.4), ("35.662s", 35.662), ("40.53s", 40.53)])
def test_observed_reset_expires_to_unknown_without_refill(duration, seconds):
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    governor.update_from_groq_headers("qwen", {
        "remaining_tokens": 0, "limit_tokens": 6000, "reset_tokens": duration,
    }, observed_at=1000)
    assert not governor.can_invoke("gpt_oss", now=1000 + seconds - .001)
    assert governor.can_invoke("qwen", now=1000 + seconds)
    for state in (governor.model_states["qwen"], governor.provider_states["groq"]):
        assert state.remaining_tokens is None
        assert state.limit_tokens == 6000
        assert state.tokens_consumed == 0
        assert state.raw_headers["remaining_tokens"]["observed_at"] == 1000


def test_new_zero_without_reset_cannot_inherit_old_reset():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    governor.update_from_groq_headers("qwen", {"remaining_tokens": 0, "reset_tokens": "1s"}, observed_at=1000)
    governor.update_from_groq_headers("qwen", {"remaining_tokens": 0}, observed_at=1000.5)
    assert not governor.can_invoke("qwen", now=1002)


@pytest.mark.parametrize("reset", [None, "unknown", "NaN", "1m-junk", "-1s"])
def test_unproven_reset_does_not_unblock(reset):
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    governor.update_from_groq_headers("qwen", {"remaining_tokens": 0, "reset_tokens": reset}, observed_at=1000)
    assert not governor.can_invoke("qwen", now=999999)


def test_retry_after_http_date_survives_budget_reset():
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    governor = CognitiveQuotaGovernor()
    governor.update_from_groq_headers("qwen", {
        "remaining_tokens": 0, "reset_tokens": "1s",
        "retry-after": "Thu, 01 Jan 1970 00:18:20 GMT",
    }, http_status=429, observed_at=1000)
    assert not governor.can_invoke("qwen", now=1002)
    assert governor.can_invoke("qwen", now=1100)


def test_generic_429_fallback_cannot_shorten_provider_cooldown(monkeypatch):
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    monkeypatch.setattr("src.oracle_sol.quota_governor.time.time", lambda: 1000)
    governor = CognitiveQuotaGovernor()
    governor.update_from_groq_headers("qwen", {
        "retry-after": "Thu, 01 Jan 1970 00:18:20 GMT",
    }, http_status=429)
    governor.record_rate_limit("qwen", 30)
    assert not governor.can_invoke("qwen", now=1031)
    assert governor.can_invoke("qwen", now=1100)
