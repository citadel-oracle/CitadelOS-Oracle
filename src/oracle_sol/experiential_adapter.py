"""CITADEL Experiential Labs Provider Adapter.

Implements official Experiential Labs platform API integration:
- Base endpoint: https://api.experientiallabs.ai/v1/chat/completions
- Strict TLS certificate verification via certifi
- Zero-cost promotional enforcement (fails closed if cost > 0)
- Stable error taxonomy matching official gateway codes
- Structured output support (NATIVE_JSON_SCHEMA, JSON_OBJECT, LOCAL_POST_VALIDATION)
- Zero silent model substitution detection
- ZDR and privacy boundary compliance tracking
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import certifi

from src.oracle_sol.brain_provider_adapter import BrainProviderAdapter
from src.oracle_sol.provider_secrets import create_strict_ssl_context, get_secret, redact_text, resolve_secret, safe_key_fingerprint

logger = logging.getLogger(__name__)


# Stable Error Taxonomy Constants
ERR_INVALID_KEY = "INVALID_KEY"
ERR_MODEL_NOT_GRANTED = "MODEL_NOT_GRANTED"
ERR_MODEL_LOCATION_NOT_SUPPORTED = "MODEL_LOCATION_NOT_SUPPORTED"
ERR_ORG_UNDER_REVIEW = "ORG_UNDER_REVIEW"
ERR_BUDGET_EXHAUSTED = "CREDIT_BUDGET_EXHAUSTED"
ERR_RATE_LIMIT = "RATE_LIMIT"
ERR_INVALID_REQUEST = "INVALID_REQUEST"
ERR_INVALID_PARAMETER = "INVALID_PARAMETER"
ERR_UNSUPPORTED_PARAMETER = "UNSUPPORTED_PARAMETER"
ERR_UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
ERR_PREVIOUS_RESPONSE_NOT_FOUND = "PREVIOUS_RESPONSE_NOT_FOUND"
ERR_POLICY_RETENTION_BLOCKED = "POLICY_RETENTION_BLOCKED"
ERR_PROVIDER_CAPACITY = "PROVIDER_CAPACITY"
ERR_TIMEOUT = "TIMEOUT"
ERR_UNKNOWN = "UNKNOWN"

# Non-retryable error categories (Fail immediately)
NON_RETRYABLE_ERRORS = {
    ERR_INVALID_KEY,
    ERR_MODEL_NOT_GRANTED,
    ERR_MODEL_LOCATION_NOT_SUPPORTED,
    ERR_ORG_UNDER_REVIEW,
    ERR_BUDGET_EXHAUSTED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PARAMETER,
    ERR_UNSUPPORTED_PARAMETER,
    ERR_UNSUPPORTED_CAPABILITY,
    ERR_POLICY_RETENTION_BLOCKED,
}

# Retention / Privacy classifications
MODEL_RETENTION_MAP = {
    "gpt-6-astra": "not_zdr",
    "gpt-5.6-luna": "not_zdr",
    # Mixed-retention waterfalls are not pinned/enforced by this adapter.
    "deepseek-v4-flash": "unknown",
    "qwen3.8-27b": "unknown",
    "claude-fable-5.1": "not_zdr",
}


class ExperientialAdapter(BrainProviderAdapter):
    """Secure, zero-cost aware Experiential Labs adapter."""

    API_URL = "https://api.experientiallabs.ai/v1/chat/completions"
    RESPONSES_URL = "https://api.experientiallabs.ai/v1/responses"
    MGMT_URL = "https://api.experientiallabs.ai/api"

    BANNED_PRIVACY_TERMS = [
        "dhan_client_id",
        "access_token",
        "broker_secret",
        "api_key",
        "place_order",
        "modify_order",
        "cancel_order",
        "/Users/ayushmudgal/",
    ]

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enforce_zero_cost: bool = True,
        reject_substituted_model: bool = True,
    ) -> None:
        self.model_name = model_name or "gpt-6-astra"
        resolved_key, key_src = resolve_secret("experiential")
        self.api_key = api_key or resolved_key
        self.key_source = key_src
        self.base_url = base_url or self.API_URL
        self.enforce_zero_cost = enforce_zero_cost
        self.reject_substituted_model = reject_substituted_model

        try:
            self._ssl_context = create_strict_ssl_context()
            self._ssl_error = None
        except Exception as e:
            self._ssl_context = None
            self._ssl_error = f"TLS_CONFIGURATION_ERROR: {e}"

        self.rate_limits: Dict[str, Any] = {
            "limit_requests": None,
            "remaining_requests": None,
            "limit_tokens": None,
            "remaining_tokens": None,
            "reset_requests": None,
            "reset_tokens": None,
            "retry_after_seconds": None,
            "last_429_timestamp": None,
            "total_requests_made": 0,
            "total_tokens_consumed": 0,
            "total_429_count": 0,
            "cost_micro_usd_total": 0,
        }

    @property
    def configured_model(self) -> str:
        return self.model_name

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 8 and not self._ssl_error)

    def verify_privacy_boundary(self, text_payload: str) -> Tuple[bool, Optional[str]]:
        lower_payload = text_payload.lower()
        for term in self.BANNED_PRIVACY_TERMS:
            if term.lower() in lower_payload:
                return False, f"Banned privacy token detected: '{term}'"
        return True, None

    def get_retention_verdict(self, model_id: Optional[str] = None) -> str:
        target = model_id or self.model_name
        return MODEL_RETENTION_MAP.get(target, "not_zdr")

    def is_privacy_restricted(self, model_id: Optional[str] = None) -> bool:
        verdict = self.get_retention_verdict(model_id)
        return verdict != "zdr_enforced"

    @staticmethod
    def classify_error(status_code: int, error_body: Optional[Dict[str, Any]]) -> Tuple[str, str]:
        """Classify gateway error response into CITADEL error taxonomy."""
        err_obj = (error_body or {}).get("error", {})
        code = str(err_obj.get("code", "")).lower()
        err_type = str(err_obj.get("type", "")).lower()
        msg = str(err_obj.get("message", ""))

        if status_code == 401 or "unauthorized" in code or "invalid_key" in code:
            return ERR_INVALID_KEY, msg or "Invalid or unauthorized API key."

        if status_code == 403:
            if code == "model_not_granted":
                return ERR_MODEL_NOT_GRANTED, msg or "Requested model is not granted to this identity."
            if code == "model_location_not_supported":
                return ERR_MODEL_LOCATION_NOT_SUPPORTED, msg or "Model location is not supported."
            if "policy" in code or "retention" in code:
                return ERR_POLICY_RETENTION_BLOCKED, msg or "Blocked by organization or retention policy."
            return ERR_POLICY_RETENTION_BLOCKED, msg or "Access forbidden."

        if status_code == 429:
            if code == "org_under_review":
                return ERR_ORG_UNDER_REVIEW, msg or "Organization under anti-spam review; models disabled."
            if code in ("insufficient_quota", "credit_exhausted", "budget_exceeded") or err_type == "insufficient_quota":
                return ERR_BUDGET_EXHAUSTED, msg or "Credit budget or quota exhausted."
            return ERR_RATE_LIMIT, msg or "Rate limit exceeded."

        if status_code == 400:
            if code in ("invalid_parameter", "invalid_param"):
                return ERR_INVALID_PARAMETER, msg or "Invalid parameter."
            if code == "unsupported_parameter":
                return ERR_UNSUPPORTED_PARAMETER, msg or "Unsupported parameter for model."
            if code == "unsupported_capability":
                return ERR_UNSUPPORTED_CAPABILITY, msg or "Requested capability unsupported by model."
            return ERR_INVALID_REQUEST, msg or "Invalid request."

        if status_code == 404:
            if code == "previous_response_not_found":
                return ERR_PREVIOUS_RESPONSE_NOT_FOUND, msg or "Previous response continuation not found."
            return ERR_INVALID_REQUEST, msg or "Resource not found."

        if status_code in (502, 503):
            return ERR_PROVIDER_CAPACITY, msg or "Upstream provider capacity error."

        if status_code == 504:
            return ERR_TIMEOUT, msg or "Gateway timeout."

        return ERR_UNKNOWN, msg or f"HTTP error {status_code}"

    def invoke_reasoning(
        self,
        request_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
        max_output_tokens: Optional[int] = None,
        structured_mode: str = "JSON_OBJECT",
        reasoning_effort: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Invoke Experiential Labs model with schema enforcement and zero-cost protection."""
        t_start = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        req_id = request_id or f"xpl_{int(time.time()*1000)}"

        telemetry: Dict[str, Any] = {
            "request_id": req_id,
            "provider": "experiential",
            "model": self.model_name,
            "requested_model": self.model_name,
            "response_model": None,
            "started_at": started_at,
            "latency_ms": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_micro_usd": 0,
            "credit_delta": 0,
            "schema_status": "SKIPPED",
            "error": None,
            "error_class": None,
            "http_status": None,
            "finish_reason": None,
            "retention": self.get_retention_verdict(self.model_name),
            "privacy_restricted": self.is_privacy_restricted(self.model_name),
            "model_substitution_detected": False,
        }

        # 1. TLS Check
        if self._ssl_error or not self._ssl_context:
            telemetry["error"] = self._ssl_error or "TLS trust store unavailable."
            telemetry["error_class"] = "TLS_CONFIGURATION_ERROR"
            return None, telemetry

        # 2. Key Check
        if not self.is_available():
            telemetry["error"] = "Experiential Labs API key not configured or invalid."
            telemetry["error_class"] = ERR_INVALID_KEY
            return None, telemetry

        # 3. Privacy boundary check
        combined_prompt = f"{system_prompt}\n{user_prompt}"
        boundary_ok, violation = self.verify_privacy_boundary(combined_prompt)
        if not boundary_ok:
            telemetry["error"] = f"PRIVACY_VIOLATION_BLOCKED: {violation}"
            telemetry["error_class"] = "PRIVACY_POLICY_BLOCKED"
            return None, telemetry

        # Build payload
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
        }
        if max_output_tokens:
            payload["max_tokens"] = max_output_tokens

        # Reasoning
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        # Structured Output
        if schema:
            if structured_mode == "NATIVE_JSON_SCHEMA":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "citadel_reasoning_contract",
                        "strict": True,
                        "schema": schema,
                    },
                }
            elif structured_mode == "JSON_OBJECT":
                payload["response_format"] = {"type": "json_object"}
            # LOCAL_POST_VALIDATION relies on prompt-level schema specification

        data_bytes = json.dumps(payload).encode("utf-8")
        # Optional audit callback receives the exact bytes, never credentials.
        # Failure must prevent dispatch, not silently lose request provenance.
        before_send = kwargs.get("before_send")
        if before_send is not None:
            try:
                before_send(data_bytes)
            except Exception:
                telemetry["error_class"] = "INPUT_RECEIPT_PERSISTENCE_FAILED"
                telemetry["error"] = "Request audit persistence failed; no request sent."
                return None, telemetry
        req = urllib.request.Request(
            self.base_url,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "CitadelOS-ExperientialAdapter/1.0",
            },
            method="POST",
        )

        max_attempts = 1 if kwargs.get("single_attempt") else 2
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                telemetry["dispatch_at"] = datetime.now(timezone.utc).isoformat()
                with urllib.request.urlopen(req, context=self._ssl_context, timeout=timeout_seconds) as resp:
                    raw_body = resp.read().decode("utf-8")
                    telemetry["latency_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
                    telemetry["http_status"] = resp.status
                    self._extract_headers(resp.headers)

                    resp_json = json.loads(raw_body)
                    return self._process_success_response(resp_json, schema, telemetry)

            except urllib.error.HTTPError as e:
                telemetry["latency_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
                telemetry["http_status"] = e.code
                self._extract_headers(e.headers)

                raw_err = e.read().decode("utf-8")
                err_dict = None
                try:
                    err_dict = json.loads(raw_err)
                except Exception:
                    pass

                err_class, err_msg = self.classify_error(e.code, err_dict)
                telemetry["error_class"] = err_class
                telemetry["error"] = redact_text(err_msg)

                # Update governor metrics
                if e.code == 429:
                    self.rate_limits["total_429_count"] += 1
                    self.rate_limits["last_429_timestamp"] = time.time()

                # Fail closed on non-retryable errors
                if err_class in NON_RETRYABLE_ERRORS or attempt >= max_attempts:
                    return None, telemetry

                # Transient retry backoff (e.g. 502/503/504)
                time.sleep(1.0 * attempt)

            except Exception as e:
                telemetry["latency_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
                telemetry["error"] = redact_text(str(e))
                telemetry["error_class"] = ERR_TIMEOUT if "timed out" in str(e).lower() else ERR_UNKNOWN
                return None, telemetry
            finally:
                telemetry["completed_at"] = datetime.now(timezone.utc).isoformat()

        return None, telemetry

    def _extract_headers(self, headers: Any) -> None:
        """Parse rate limit, cost, and route headers."""
        for k, v in headers.items():
            kl = k.lower()
            if "x-ratelimit-remaining-requests" in kl:
                try:
                    self.rate_limits["remaining_requests"] = int(v)
                except ValueError:
                    pass
            elif "x-ratelimit-remaining-tokens" in kl:
                try:
                    self.rate_limits["remaining_tokens"] = int(v)
                except ValueError:
                    pass
            elif "retry-after" in kl:
                try:
                    self.rate_limits["retry_after_seconds"] = float(v)
                except ValueError:
                    pass

    def _process_success_response(
        self,
        resp_json: Dict[str, Any],
        schema: Optional[Dict[str, Any]],
        telemetry: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Process successful completion payload and enforce zero-cost and model invariants."""
        # 1. Model identity verification
        ret_model = resp_json.get("model")
        telemetry["response_model"] = ret_model
        if ret_model and ret_model != self.model_name:
            telemetry["model_substitution_detected"] = True
            if self.reject_substituted_model:
                telemetry["error_class"] = "MODEL_SUBSTITUTION_REJECTED"
                telemetry["error"] = f"Model substitution detected: requested '{self.model_name}', received '{ret_model}'"
                return None, telemetry

        # 2. Usage and cost parsing
        usage = resp_json.get("usage", {})
        p_tokens = usage.get("prompt_tokens", 0)
        c_tokens = usage.get("completion_tokens", 0)
        t_tokens = usage.get("total_tokens", p_tokens + c_tokens)
        cost_micro = resp_json.get("cost_micro_usd", 0)

        telemetry["input_tokens"] = p_tokens
        telemetry["output_tokens"] = c_tokens
        telemetry["total_tokens"] = t_tokens
        telemetry["cost_micro_usd"] = cost_micro

        # Cumulative counters
        self.rate_limits["total_requests_made"] += 1
        self.rate_limits["total_tokens_consumed"] += t_tokens
        self.rate_limits["cost_micro_usd_total"] += cost_micro

        # 3. Commercial state zero-cost verification
        if self.enforce_zero_cost and cost_micro > 0:
            telemetry["error_class"] = "COMMERCIAL_STATE_VIOLATION"
            telemetry["error"] = f"Zero-cost model incurred monetary spend: {cost_micro} micro-USD."
            return None, telemetry

        # 4. Extract content
        choices = resp_json.get("choices", [])
        if not choices:
            telemetry["error_class"] = "EMPTY_CHOICES"
            telemetry["error"] = "Provider response contained empty choices array."
            return None, telemetry

        first_choice = choices[0]
        telemetry["finish_reason"] = first_choice.get("finish_reason")
        msg = first_choice.get("message", {})
        content = msg.get("content", "")

        # 5. Schema / JSON parsing
        if schema is not None:
            parsed = self._extract_json(content)
            if parsed is None:
                telemetry["schema_status"] = "INVALID_JSON"
                if telemetry.get("finish_reason") == "length":
                    telemetry["error_class"] = "COMPLETION_TRUNCATED"
                    telemetry["error"] = f"Completion truncated by max_tokens limit (finish_reason='length'): {content[:100]}"
                else:
                    telemetry["error_class"] = "SCHEMA_INVALID"
                    telemetry["error"] = f"Failed to parse valid JSON from completion content: {content[:100]}"
                return None, telemetry
            telemetry["schema_status"] = "VALID_JSON"
            return parsed, telemetry

        # Return dict wrapping content if no explicit schema
        return {"content": content}, telemetry

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON object from text or markdown blocks."""
        if not text or not text.strip():
            return None
        clean = text.strip()
        # Direct parse
        try:
            val = json.loads(clean)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Markdown json fence
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean, re.DOTALL)
        if match:
            try:
                fence_text = match.group(1).strip()
                val = json.loads(fence_text)
                if isinstance(val, dict):
                    return val
                # If fence has outer text, try brace extraction within fence
                s_idx = fence_text.find("{")
                e_idx = fence_text.rfind("}")
                if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
                    val = json.loads(fence_text[s_idx : e_idx + 1])
                    if isinstance(val, dict):
                        return val
            except Exception:
                pass

        # First outer brace pair
        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                val = json.loads(clean[start : end + 1])
                if isinstance(val, dict):
                    return val
            except Exception:
                pass

        return None

    def get_telemetry(self) -> Dict[str, Any]:
        return dict(self.rate_limits)
