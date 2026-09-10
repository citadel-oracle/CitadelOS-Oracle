"""CITADEL Provider-Neutral Client (Normalized Common Interface).

The Cognitive Coordinator invokes this neutral client without needing to know
whether a model is hosted on Groq, Google, NVIDIA, OpenRouter, or Cloudflare.

Contract:
- invoke(provider, model_id, messages, schema?, max_output_tokens?, reasoning?, timeout?)
- Returns NormalizedProviderResponse with:
  * provider, model_id, request_id
  * response_text, parsed_output, structured_output_mode
  * usage (prompt, completion, total, cached, neurons)
  * latency_ms
  * rate_limits
  * finish_reason
  * error_class (AUTH_ERROR, RATE_LIMITED, MODEL_UNAVAILABLE, PROVIDER_UNAVAILABLE, TIMEOUT, BAD_RESPONSE, SCHEMA_INVALID, PRIVACY_POLICY_BLOCKED, UNKNOWN_ERROR)
  * timestamp, success
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import certifi

from src.oracle_sol.cloudflare_adapter import CloudflareWorkersAIAdapter
from src.oracle_sol.experiential_adapter import ExperientialAdapter
from src.oracle_sol.gemini_adapter import clean_schema_for_gemini
from src.oracle_sol.groq_adapter import GroqBrainAdapter
from src.oracle_sol.nvidia_adapter import NvidiaNimAdapter
from src.oracle_sol.openrouter_adapter import OpenRouterAdapter
from src.oracle_sol.provider_registry import GLOBAL_PROVIDER_REGISTRY
from src.oracle_sol.provider_secrets import get_secret, redact_text, resolve_secret, safe_key_fingerprint

logger = logging.getLogger(__name__)


@dataclass
class NormalizedProviderResponse:
    """Normalized output contract across all AI model providers."""
    provider: str
    model_id: str
    request_id: Optional[str] = None
    response_text: str = ""
    parsed_output: Optional[Dict[str, Any]] = None
    structured_output_mode: str = "NONE"  # NATIVE_JSON_SCHEMA, JSON_OBJECT, LOCAL_POST_VALIDATION, TEXT_FALLBACK
    usage: Dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "neurons": 0.0,
    })
    latency_ms: float = 0.0
    rate_limits: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: str = ""
    success: bool = False
    http_status: Optional[int] = None
    response_model: Optional[str] = None
    schema_error_path: Optional[List[Any]] = None
    schema_error_keyword: Optional[str] = None
    requested_profile: Optional[str] = None
    actual_profile: Optional[str] = None
    requested_model: Optional[str] = None
    actual_model: Optional[str] = None
    credential_fingerprint_safe: Optional[str] = None
    attempt_count: int = 1
    fallback_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _fallback_validate_schema(schema: Any, data: Any) -> None:
    """Lightweight pure-python schema validator when jsonschema library is absent."""
    if not isinstance(schema, dict) or data is None:
        return
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(data, dict):
            raise ValueError(f"Expected object, got {type(data).__name__}")
        for req in schema.get("required", []):
            if req not in data:
                raise ValueError(f"Missing required property '{req}'")
        if schema.get("additionalProperties") is False:
            props = schema.get("properties", {})
            for k in data:
                if k not in props:
                    raise ValueError(f"Unexpected additional property '{k}'")
        props = schema.get("properties", {})
        for k, v in data.items():
            if k in props:
                _fallback_validate_schema(props[k], v)
    elif expected_type == "string" and not isinstance(data, str):
        raise ValueError(f"Expected string, got {type(data).__name__}")
    elif expected_type == "integer" and (not isinstance(data, int) or isinstance(data, bool)):
        raise ValueError(f"Expected int, got {type(data).__name__}")
    elif expected_type == "number" and not isinstance(data, (int, float)):
        raise ValueError(f"Expected number, got {type(data).__name__}")
    elif expected_type == "boolean" and not isinstance(data, bool):
        raise ValueError(f"Expected bool, got {type(data).__name__}")
    elif expected_type == "array":
        if not isinstance(data, list):
            raise ValueError(f"Expected list, got {type(data).__name__}")
        items_schema = schema.get("items")
        if items_schema:
            for item in data:
                _fallback_validate_schema(items_schema, item)


class ProviderNeutralClient:
    """Zero-trust unified client dispatching to provider adapters."""

    def __init__(self, quota_governor: Any = None) -> None:
        # Production must supply the coordinator's governor, never a second
        # independent budget. The module-level client is intentionally unarmed.
        self.quota_governor = quota_governor
        try:
            from src.oracle_sol.provider_secrets import create_strict_ssl_context
            self._ssl_context = create_strict_ssl_context()
            self._ssl_error = None
        except Exception as e:
            self._ssl_context = None
            self._ssl_error = f"TLS_CONFIGURATION_ERROR: {e}"

    def invoke(self, provider: str, model_id: str, messages: List[Dict[str, str]],
               **options: Any) -> NormalizedProviderResponse:
        """Dispatch only explicitly registered, enabled, live-proven free models.

        Catalog visibility is not execution approval. This client never probes a
        candidate or substitutes a provider; Arena probes need separate approval.
        """
        prov = provider.strip().lower()
        capability = GLOBAL_PROVIDER_REGISTRY.get(prov, model_id)
        failure = NormalizedProviderResponse(
            provider=prov, model_id=model_id, request_id=options.get("request_id"),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        if (capability is None or not capability.enabled
                or capability.verification_state != "LIVE_ZERO_COST_VERIFIED"
                or capability.commercial_status not in {"FREE_TIER", "ZERO_COST_RECURRING"}):
            failure.error_class = "MODEL_NOT_APPROVED"
            failure.error_message = "Exact model is not enabled for live-verified zero-cost execution."
            return failure
        if self._ssl_error:
            failure.error_class = "TLS_CONFIGURATION_ERROR"
            failure.error_message = "Strict TLS trust configuration unavailable."
            return failure
        content = "\n".join(str(message.get("content", "")) for message in messages)
        if any(term.lower() in content.lower() for term in GroqBrainAdapter.BANNED_PRIVACY_TERMS):
            failure.error_class = "PRIVACY_POLICY_BLOCKED"
            failure.error_message = "Request contains prohibited private context."
            return failure
        schema = options.get("schema")
        if schema is not None:
            try:
                from jsonschema import Draft202012Validator
                Draft202012Validator.check_schema(schema)
            except ImportError:
                failure.error_class = "SCHEMA_VALIDATOR_UNAVAILABLE"
                failure.error_message = "Full JSON Schema validation is required before dispatch."
                return failure
            except Exception:
                failure.error_class = "SCHEMA_INVALID"
                failure.error_message = "Invalid output schema; no request sent."
                return failure
        governor = self.quota_governor
        quota_key = options.pop("quota_key", None)
        quota_state = getattr(governor, "model_states", {}).get(quota_key)
        if (quota_state is None or quota_state.provider_name != prov
                or quota_state.model_name != model_id or not governor.can_invoke(quota_key)):
            failure.error_class = "QUOTA_ADMISSION_REQUIRED"
            failure.error_message = "No matching eligible shared-governor admission."
            return failure
        response = self._dispatch(prov, model_id, messages, **options)
        if response.http_status != 200:
            # Adapter initialization zeros are not provider usage observations.
            response.usage = {key: None if value == 0 else value for key, value in response.usage.items()}
        if response.finish_reason in {"length", "MAX_TOKENS"}:
            response.success = False
            response.error_class = "OUTPUT_TRUNCATED"
            response.error_message = "Provider reached the configured output budget."
            response.parsed_output = None
            response.response_text = ""
        governor.update_from_groq_headers(quota_key, response.rate_limits,
                                         response.http_status, response.latency_ms)
        if response.http_status == 429 or response.error_class == "RATE_LIMITED":
            retry = response.rate_limits.get("retry_after_seconds")
            try:
                retry = float(retry) if retry is not None else 30.0
            except (TypeError, ValueError):
                retry = 30.0  # Existing governor fallback, not a provider quota.
            governor.record_rate_limit(quota_key, retry_after_seconds=retry)
        elif response.http_status is not None:
            governor.record_call_success(quota_key, response.usage.get("total_tokens") or 0,
                                         response.latency_ms, http_status=response.http_status)

        if response.success and schema is not None:
            try:
                try:
                    from jsonschema import Draft202012Validator
                    Draft202012Validator(schema).validate(response.parsed_output)
                except ImportError:
                    raise ValueError("SCHEMA_VALIDATOR_UNAVAILABLE")
            except Exception as exc:
                response.success = False
                response.error_class = "SCHEMA_INVALID"
                response.error_message = "Provider output failed the requested schema."
                response.schema_error_path = list(getattr(exc, "absolute_path", []))
                response.schema_error_keyword = getattr(exc, "validator", None)
                response.parsed_output = None
                response.response_text = ""
        if response.error_message:
            response.error_message = redact_text(response.error_message)
        return response

    def _dispatch(
        self,
        provider: str,
        model_id: str,
        messages: List[Dict[str, str]],
        schema: Optional[Dict[str, Any]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
        request_id: Optional[str] = None,
        audit_sink=None,
        strict_schema: bool = False,
    ) -> NormalizedProviderResponse:
        """Unified model invocation with standardized output contract and explicit errors."""
        prov = provider.strip().lower()
        req_id = request_id or f"citadel_{prov}_{int(time.time()*1000)}"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Split system and user prompts
        sys_prompt = ""
        user_prompt_parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                sys_prompt = f"{sys_prompt}\n{content}".strip()
            else:
                user_prompt_parts.append(content)
        user_prompt = "\n\n".join(user_prompt_parts)
        if strict_schema and (prov != "groq" or schema is None):
            raise ValueError("STRICT_SCHEMA_CAPABILITY_NOT_CONFIGURED")
        if schema is not None and not strict_schema:
            # JSON-object mode is not schema enforcement. Supply the exact
            # contract in the instruction channel even for text-only adapters;
            # local validation below remains mandatory and never repairs output.
            sys_prompt += "\nRequired output JSON Schema (including nested object types):\n" + json.dumps(schema, separators=(",", ":"))

        # Dispatch by provider
        if prov in {"groq"}:
            return self._invoke_groq(model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, timestamp, audit_sink, reasoning, strict_schema)
        elif prov in {"google", "gemini", "gemini_primary"}:
            profiles_to_attempt = ["gemini_primary", "gemini_secondary", "gemini_tertiary"]
            attempted_profiles: List[str] = []
            last_response = None
            for prof in profiles_to_attempt:
                attempted_profiles.append(prof)
                resp = self._invoke_gemini(
                    prov, model_id, req_id, sys_prompt, user_prompt, schema,
                    timeout_seconds, max_output_tokens, reasoning, timestamp, profile=prof
                )
                if resp.success:
                    if len(attempted_profiles) > 1:
                        resp.fallback_path = " -> ".join(attempted_profiles)
                    return resp
                last_response = resp
                # Only fail over on transient/quota-local failures
                if resp.http_status not in (429, 500, 502, 503, 504) and resp.error_class not in ("RATE_LIMITED", "PROVIDER_UNAVAILABLE"):
                    break
            if last_response and len(attempted_profiles) > 1:
                last_response.fallback_path = " -> ".join(attempted_profiles)
            return last_response
        elif prov in {"gemini_secondary"}:
            return self._invoke_gemini(prov, model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, reasoning, timestamp, profile="gemini_secondary")
        elif prov in {"gemini_tertiary"}:
            return self._invoke_gemini(prov, model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, reasoning, timestamp, profile="gemini_tertiary")
        elif prov in {"nvidia"}:
            return self._invoke_nvidia(model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, timestamp)
        elif prov in {"openrouter"}:
            return self._invoke_openrouter(model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, timestamp, audit_sink)
        elif prov in {"cloudflare"}:
            return self._invoke_cloudflare(model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, timestamp)
        elif prov in {"experiential"}:
            return self._invoke_experiential(model_id, req_id, sys_prompt, user_prompt, schema, timeout_seconds, max_output_tokens, timestamp, reasoning, strict_schema)
        else:
            return NormalizedProviderResponse(
                provider=prov,
                model_id=model_id,
                request_id=req_id,
                error_class="PROVIDER_UNAVAILABLE",
                error_message=f"Unsupported provider: '{provider}'",
                timestamp=timestamp,
                success=False,
            )

    def _invoke_groq(
        self,
        model_id: str,
        req_id: str,
        sys_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]],
        timeout_seconds: float,
        max_output_tokens: Optional[int],
        timestamp: str,
        audit_sink=None,
        reasoning=None,
        strict_schema=False,
    ) -> NormalizedProviderResponse:
        api_key, _ = resolve_secret("groq")
        key_fp = safe_key_fingerprint(api_key)

        adapter = GroqBrainAdapter(model_name=model_id)
        parsed, telemetry = adapter.invoke_reasoning(
            request_id=req_id,
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            schema=schema,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            audit_sink=audit_sink,
            reasoning_effort=(reasoning or {}).get("effort"),
            strict_schema=strict_schema,
        )

        error_class = telemetry.get("error_class")
        if not error_class:
            if telemetry.get("schema_status") == "GROQ_KEY_REQUIRED":
                error_class = "AUTH_ERROR"
            elif telemetry.get("schema_status") == "PRIVACY_VIOLATION_BLOCKED":
                error_class = "PRIVACY_POLICY_BLOCKED"
            elif telemetry.get("schema_status") == "RATE_LIMITED":
                error_class = "RATE_LIMITED"
            elif telemetry.get("schema_status") == "INVALID_JSON":
                error_class = "SCHEMA_INVALID"
            elif telemetry.get("error"):
                error_class = "BAD_RESPONSE"

        structured_mode = "NATIVE_JSON_SCHEMA" if strict_schema else ("TEXT_FALLBACK" if model_id.startswith("openai/gpt-oss") else "JSON_OBJECT") if schema else "NONE"

        return NormalizedProviderResponse(
            provider="groq",
            requested_profile="groq",
            actual_profile="groq",
            requested_model=model_id,
            actual_model=telemetry.get("response_model") or model_id,
            credential_fingerprint_safe=key_fp,
            attempt_count=1,
            http_status=telemetry.get("http_status"),
            response_model=telemetry.get("response_model"),
            model_id=model_id,
            request_id=req_id,
            response_text=json.dumps(parsed) if parsed else "",
            parsed_output=parsed,
            structured_output_mode=structured_mode,
            usage={
                "prompt_tokens": telemetry.get("prompt_tokens", 0),
                "completion_tokens": telemetry.get("completion_tokens", 0),
                "total_tokens": telemetry.get("total_tokens", 0),
                "cached_tokens": telemetry.get("cached_tokens", 0),
                "reasoning_tokens": telemetry.get("reasoning_tokens"),
            },
            latency_ms=telemetry.get("total_duration_ms", 0.0),
            rate_limits=telemetry.get("rate_limits", {}),
            finish_reason=telemetry.get("finish_reason"),
            error_class=error_class,
            error_message=telemetry.get("error"),
            timestamp=timestamp,
            success=parsed is not None,
        )

    def _invoke_nvidia(
        self,
        model_id: str,
        req_id: str,
        sys_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]],
        timeout_seconds: float,
        max_output_tokens: Optional[int],
        timestamp: str,
    ) -> NormalizedProviderResponse:
        api_key, _ = resolve_secret("nvidia")
        key_fp = safe_key_fingerprint(api_key)

        adapter = NvidiaNimAdapter(model_name=model_id)
        parsed, telemetry = adapter.invoke_reasoning(
            request_id=req_id,
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            schema=schema,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens or 4096,
        )

        return NormalizedProviderResponse(
            provider="nvidia",
            requested_profile="nvidia",
            actual_profile="nvidia",
            requested_model=model_id,
            actual_model=telemetry.get("response_model") or model_id,
            credential_fingerprint_safe=key_fp,
            attempt_count=1,
            http_status=telemetry.get("http_status"),
            model_id=model_id,
            request_id=req_id,
            response_text=telemetry.get("response_text", ""),
            parsed_output=parsed,
            structured_output_mode="JSON_OBJECT" if schema else "NONE",
            usage={
                "prompt_tokens": telemetry.get("prompt_tokens", 0),
                "completion_tokens": telemetry.get("completion_tokens", 0),
                "total_tokens": telemetry.get("total_tokens", 0),
                "cached_tokens": telemetry.get("cached_tokens", 0),
            },
            latency_ms=telemetry.get("total_duration_ms", 0.0),
            rate_limits=telemetry.get("rate_limits", {}),
            finish_reason=telemetry.get("finish_reason"),
            error_class=telemetry.get("error_class"),
            error_message=telemetry.get("error"),
            timestamp=timestamp,
            success=parsed is not None,
        )

    def _invoke_openrouter(
        self,
        model_id: str,
        req_id: str,
        sys_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]],
        timeout_seconds: float,
        max_output_tokens: Optional[int],
        timestamp: str,
        audit_sink=None,
    ) -> NormalizedProviderResponse:
        api_key, _ = resolve_secret("openrouter")
        key_fp = safe_key_fingerprint(api_key)

        adapter = OpenRouterAdapter(model_name=model_id)
        parsed, telemetry = adapter.invoke_reasoning(
            request_id=req_id,
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            schema=schema,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens or 4096,
            audit_sink=audit_sink,
        )

        return NormalizedProviderResponse(
            provider="openrouter",
            requested_profile="openrouter",
            actual_profile="openrouter",
            requested_model=model_id,
            actual_model=telemetry.get("response_model") or model_id,
            credential_fingerprint_safe=key_fp,
            attempt_count=1,
            http_status=telemetry.get("http_status"),
            response_model=telemetry.get("response_model"),
            model_id=model_id,
            request_id=req_id,
            response_text=telemetry.get("response_text", ""),
            parsed_output=parsed,
            structured_output_mode="LOCAL_POST_VALIDATION" if schema else "NONE",
            usage={
                "prompt_tokens": telemetry.get("prompt_tokens", 0),
                "completion_tokens": telemetry.get("completion_tokens", 0),
                "total_tokens": telemetry.get("total_tokens", 0),
                "cached_tokens": telemetry.get("cached_tokens", 0),
                "reasoning_tokens": telemetry.get("reasoning_tokens"),
                "cost": telemetry.get("cost", 0.0),
            },
            latency_ms=telemetry.get("total_duration_ms", 0.0),
            rate_limits=telemetry.get("rate_limits", {}),
            finish_reason=telemetry.get("finish_reason"),
            error_class=telemetry.get("error_class"),
            error_message=telemetry.get("error"),
            timestamp=timestamp,
            success=parsed is not None,
        )

    def _invoke_cloudflare(
        self,
        model_id: str,
        req_id: str,
        sys_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]],
        timeout_seconds: float,
        max_output_tokens: Optional[int],
        timestamp: str,
    ) -> NormalizedProviderResponse:
        api_key, _ = resolve_secret("cloudflare")
        key_fp = safe_key_fingerprint(api_key)

        adapter = CloudflareWorkersAIAdapter(model_name=model_id)
        parsed, telemetry = adapter.invoke_reasoning(
            request_id=req_id,
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            schema=schema,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens or 4096,
        )

        return NormalizedProviderResponse(
            provider="cloudflare",
            requested_profile="cloudflare",
            actual_profile="cloudflare",
            requested_model=model_id,
            actual_model=telemetry.get("response_model") or model_id,
            credential_fingerprint_safe=key_fp,
            attempt_count=1,
            http_status=telemetry.get("http_status"),
            response_model=telemetry.get("response_model"),
            model_id=model_id,
            request_id=req_id,
            response_text=telemetry.get("response_text", ""),
            parsed_output=parsed,
            structured_output_mode="JSON_OBJECT" if schema else "NONE",
            usage={
                "prompt_tokens": telemetry.get("prompt_tokens", 0),
                "completion_tokens": telemetry.get("completion_tokens", 0),
                "total_tokens": telemetry.get("total_tokens", 0),
                "neurons": telemetry.get("neurons", 0.0),
            },
            latency_ms=telemetry.get("total_duration_ms", 0.0),
            rate_limits=telemetry.get("rate_limits", {}),
            finish_reason=telemetry.get("finish_reason"),
            error_class=telemetry.get("error_class"),
            error_message=telemetry.get("error"),
            timestamp=timestamp,
            success=parsed is not None,
        )

    def _invoke_gemini(
        self,
        provider_name: str,
        model_id: str,
        req_id: str,
        sys_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]],
        timeout_seconds: float,
        max_output_tokens: Optional[int],
        reasoning: Optional[Dict[str, Any]],
        timestamp: str,
        profile: str = "gemini_primary",
    ) -> NormalizedProviderResponse:
        """Invoke Gemini with native JSON Schema support, modern thinkingLevel, RPC RetryInfo backoff & fail-closed routing."""
        prof_key = profile.lower()
        if not prof_key.startswith("gemini_"):
            prof_key = f"gemini_{prof_key}"

        api_key, key_source = resolve_secret(prof_key)
        key_fp = safe_key_fingerprint(api_key)

        if not api_key:
            return NormalizedProviderResponse(
                provider=provider_name,
                requested_profile=prof_key,
                actual_profile=prof_key,
                requested_model=model_id,
                actual_model=model_id,
                credential_fingerprint_safe=key_fp,
                attempt_count=0,
                model_id=model_id,
                request_id=req_id,
                error_class="AUTH_ERROR",
                error_message=f"Gemini API key for profile '{prof_key}' is not configured in Keychain ({key_source}).",
                timestamp=timestamp,
                success=False,
            )

        if self._ssl_context is None:
            return NormalizedProviderResponse(
                provider=provider_name,
                requested_profile=prof_key,
                actual_profile=prof_key,
                requested_model=model_id,
                actual_model=model_id,
                credential_fingerprint_safe=key_fp,
                attempt_count=0,
                model_id=model_id,
                request_id=req_id,
                latency_ms=0.0,
                error_class="TLS_CONFIGURATION_ERROR",
                error_message=self._ssl_error or "Secure TLS context unavailable",
                timestamp=timestamp,
                success=False,
            )

        t_start = time.perf_counter()
        clean_model = model_id.replace("models/", "")
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"

        # Modern Gemini 3.8 thinkingLevel enum: LOW, MEDIUM, HIGH
        effort_raw = str((reasoning or {}).get("effort") or (reasoning or {}).get("thinking_level") or "").strip().upper()
        if effort_raw in {"HIGH", "DEEP"}:
            thinking_level = "HIGH"
        elif effort_raw in {"MEDIUM", "MODERATE"}:
            thinking_level = "MEDIUM"
        else:
            thinking_level = "LOW"

        generation_cfg: Dict[str, Any] = {
            "temperature": 0.1,
            "maxOutputTokens": max_output_tokens or 4096,
            "thinkingConfig": {
                "thinkingLevel": thinking_level,
            },
        }

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": generation_cfg,
        }

        if sys_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": sys_prompt}]
            }

        structured_mode = "NONE"
        if schema:
            structured_mode = "NATIVE_JSON_SCHEMA"
            cleaned_schema = clean_schema_for_gemini(schema.get("schema", schema))
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = cleaned_schema

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        # Every request needs its own shared-governor admission. Profiles are
        # explicit resources; an adapter cannot spend another project's quota.
        max_attempts = 1
        last_http_err = None
        last_exc = None
        attempt_taken = 0

        for attempt in range(max_attempts):
            attempt_taken = attempt + 1
            if attempt > 0:
                backoff = (1.0 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.4)
                time.sleep(backoff)

            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds, context=self._ssl_context) as resp:
                    raw_bytes = resp.read()
                    raw_json = json.loads(raw_bytes.decode("utf-8"))

                t_end = time.perf_counter()
                duration_ms = round((t_end - t_start) * 1000.0, 2)
                resp_model = raw_json.get("modelVersion", model_id)

                candidates = raw_json.get("candidates", [])
                if not candidates:
                    return NormalizedProviderResponse(
                        provider=provider_name,
                        requested_profile=prof_key,
                        actual_profile=prof_key,
                        requested_model=model_id,
                        actual_model=resp_model,
                        credential_fingerprint_safe=key_fp,
                        attempt_count=attempt_taken,
                        http_status=getattr(resp, "status", 200),
                        response_model=resp_model,
                        model_id=model_id,
                        request_id=req_id,
                        latency_ms=duration_ms,
                        error_class="BAD_RESPONSE",
                        error_message="No candidates returned from Gemini",
                        timestamp=timestamp,
                        success=False,
                    )

                candidate = candidates[0]
                finish_reason = candidate.get("finishReason")
                parts = candidate.get("content", {}).get("parts", [])
                text_chunks = [p.get("text", "") for p in parts if "text" in p]
                content = "".join(text_chunks).strip()

                usage_meta = raw_json.get("usageMetadata", {})
                prompt_tokens = usage_meta.get("promptTokenCount", 0)
                completion_tokens = usage_meta.get("candidatesTokenCount", 0)
                total_tokens = usage_meta.get("totalTokenCount", 0)
                cached_tokens = usage_meta.get("cachedContentTokenCount", 0)
                thoughts_tokens = usage_meta.get("thoughtsTokenCount", 0)

                parsed_output = None
                error_class = None
                if schema:
                    clean_content = content
                    if clean_content.startswith("```json"):
                        clean_content = clean_content[7:]
                    if clean_content.startswith("```"):
                        clean_content = clean_content[3:]
                    if clean_content.endswith("```"):
                        clean_content = clean_content[:-3]
                    clean_content = clean_content.strip()

                    try:
                        parsed_output = json.loads(clean_content)
                    except Exception:
                        error_class = "SCHEMA_INVALID"

                return NormalizedProviderResponse(
                    provider=provider_name,
                    requested_profile=prof_key,
                    actual_profile=prof_key,
                    requested_model=model_id,
                    actual_model=resp_model,
                    credential_fingerprint_safe=key_fp,
                    attempt_count=attempt_taken,
                    http_status=getattr(resp, "status", 200),
                    response_model=resp_model,
                    model_id=model_id,
                    request_id=req_id,
                    response_text=content,
                    parsed_output=parsed_output,
                    structured_output_mode=structured_mode,
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "cached_tokens": cached_tokens,
                        "thoughts_tokens": thoughts_tokens,
                    },
                    latency_ms=duration_ms,
                    rate_limits={},
                    finish_reason=finish_reason,
                    error_class=error_class,
                    timestamp=timestamp,
                    success=parsed_output is not None if schema else bool(content),
                )

            except urllib.error.HTTPError as http_err:
                last_http_err = http_err
                if http_err.code in (500, 502, 503, 504) and attempt < max_attempts - 1:
                    continue
                break
            except Exception as exc:
                last_exc = exc
                if "timed out" in str(exc).lower() and attempt < max_attempts - 1:
                    continue
                break

        t_end = time.perf_counter()
        duration_ms = round((t_end - t_start) * 1000.0, 2)

        if last_http_err:
            try:
                err_body = last_http_err.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            error_msg = redact_text(f"{last_http_err}: {err_body}" if err_body else str(last_http_err))

            # Parse Google RPC RetryInfo & Quota details
            retry_delay_seconds = 15.0
            if err_body:
                try:
                    parsed_err = json.loads(err_body)
                    for d in parsed_err.get("error", {}).get("details", []):
                        if d.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                            m_sec = re.search(r"([0-9.]+)", str(d.get("retryDelay", "")))
                            if m_sec:
                                retry_delay_seconds = float(m_sec.group(1))
                    if "Please retry in" in err_body:
                        m_msg = re.search(r"Please retry in ([0-9.]+)s", err_body)
                        if m_msg:
                            retry_delay_seconds = max(retry_delay_seconds, float(m_msg.group(1)))
                except Exception:
                    pass

            error_class = "UNKNOWN_ERROR"
            if last_http_err.code in (401, 403):
                error_class = "AUTH_ERROR"
                if last_http_err.code == 403:
                    # Quarantine this profile in registry
                    cap = GLOBAL_PROVIDER_REGISTRY.get(prof_key, model_id)
                    if cap:
                        cap.last_health_status = "PERMISSION_DENIED"
                        cap.enabled = False
            elif last_http_err.code == 429:
                error_class = "RATE_LIMITED"
                if self.quota_governor and hasattr(self.quota_governor, "record_rate_limit"):
                    self.quota_governor.record_rate_limit(prof_key, retry_after_seconds=retry_delay_seconds, http_status=429)
            elif last_http_err.code == 400:
                error_class = "SCHEMA_INVALID" if schema and "schema" in err_body.lower() else "INVALID_ARGUMENT"
            elif last_http_err.code == 404:
                error_class = "MODEL_UNAVAILABLE"
            elif last_http_err.code in (500, 502, 503, 504):
                error_class = "PROVIDER_UNAVAILABLE"

            return NormalizedProviderResponse(
                provider=provider_name,
                requested_profile=prof_key,
                actual_profile=prof_key,
                requested_model=model_id,
                actual_model=model_id,
                credential_fingerprint_safe=key_fp,
                attempt_count=attempt_taken,
                http_status=last_http_err.code,
                response_model=model_id,
                model_id=model_id,
                request_id=req_id,
                latency_ms=duration_ms,
                error_class=error_class,
                error_message=error_msg,
                timestamp=timestamp,
                success=False,
            )

        return NormalizedProviderResponse(
            provider=provider_name,
            requested_profile=prof_key,
            actual_profile=prof_key,
            requested_model=model_id,
            actual_model=model_id,
            credential_fingerprint_safe=key_fp,
            attempt_count=attempt_taken,
            http_status=None,
            response_model=model_id,
            model_id=model_id,
            request_id=req_id,
            latency_ms=duration_ms,
            error_class="TIMEOUT" if last_exc and "timed out" in str(last_exc).lower() else "UNKNOWN_ERROR",
            error_message=redact_text(str(last_exc)) if last_exc else "Unknown invocation failure",
            timestamp=timestamp,
            success=False,
        )

    def _invoke_experiential(
        self,
        model_id: str,
        req_id: str,
        sys_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]],
        timeout_seconds: float,
        max_output_tokens: Optional[int],
        timestamp: str,
        reasoning: Optional[Dict[str, Any]] = None,
        strict_schema: bool = False,
    ) -> NormalizedProviderResponse:
        api_key, _ = resolve_secret("experiential")
        key_fp = safe_key_fingerprint(api_key)

        structured_mode = "NATIVE_JSON_SCHEMA" if strict_schema else ("JSON_OBJECT" if schema else "NONE")
        adapter = ExperientialAdapter(model_name=model_id)

        parsed, telemetry = adapter.invoke_reasoning(
            request_id=req_id,
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            schema=schema,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            structured_mode=structured_mode,
            reasoning_effort=(reasoning or {}).get("effort"),
        )

        err_class = telemetry.get("error_class")
        err_msg = telemetry.get("error")
        if not err_class and err_msg:
            err_class = "BAD_RESPONSE"

        success = parsed is not None and err_class is None

        return NormalizedProviderResponse(
            provider="experiential",
            requested_profile="experiential",
            actual_profile="experiential",
            requested_model=model_id,
            actual_model=telemetry.get("response_model") or model_id,
            credential_fingerprint_safe=key_fp,
            attempt_count=1,
            http_status=telemetry.get("http_status"),
            response_model=telemetry.get("response_model"),
            model_id=model_id,
            request_id=req_id,
            response_text=json.dumps(parsed) if parsed else (err_msg or ""),
            parsed_output=parsed,
            structured_output_mode=structured_mode if schema else "NONE",
            usage={
                "prompt_tokens": telemetry.get("input_tokens", 0),
                "completion_tokens": telemetry.get("output_tokens", 0),
                "total_tokens": telemetry.get("total_tokens", 0),
                "cached_tokens": 0,
                "neurons": 0.0,
            },
            latency_ms=telemetry.get("latency_ms", 0.0),
            rate_limits=adapter.rate_limits,
            finish_reason=telemetry.get("finish_reason"),
            error_class=err_class,
            error_message=err_msg,
            timestamp=timestamp,
            success=success,
        )


GLOBAL_PROVIDER_CLIENT = ProviderNeutralClient()
