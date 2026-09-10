"""OpenRouter Zero-Cost Model Adapter (Strict Privacy Routing & :free Models Only).

Implements OpenRouter API integration with:
- Exact :free model IDs (never openrouter/free router)
- Mandatory privacy routing: provider.data_collection = "deny"
- Dynamic rate limit header parsing
- Zero-trust privacy boundary guard
- Error normalization
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
from src.oracle_sol.provider_secrets import get_secret, redact_text

logger = logging.getLogger(__name__)


class OpenRouterAdapter(BrainProviderAdapter):
    """Secure, privacy-enforced OpenRouter adapter for verified :free models."""

    DEFAULT_MODEL = "inclusionai/ling-3.0-flash-fin:free"
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

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
    ) -> None:
        self.model_name = (
            model_name
            or os.getenv("CITADEL_OPENROUTER_MODEL")
            or self.DEFAULT_MODEL
        )
        # Safety enforcement: reject openrouter/free router
        if self.model_name.strip() == "openrouter/free":
            raise ValueError("openrouter/free router is strictly prohibited for CITADEL model identity.")

        self.api_key = api_key or get_secret("openrouter")
        self.base_url = base_url or self.API_URL

        try:
            from src.oracle_sol.provider_secrets import create_strict_ssl_context
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
        }

    @property
    def configured_model(self) -> str:
        return self.model_name

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 8)

    def verify_privacy_boundary(self, text_payload: str) -> Tuple[bool, Optional[str]]:
        lower_payload = text_payload.lower()
        for term in self.BANNED_PRIVACY_TERMS:
            if term.lower() in lower_payload:
                return False, f"Banned privacy token detected: '{term}'"
        return True, None

    def invoke_reasoning(
        self,
        request_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
        **kwargs: Any,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Invoke OpenRouter model with privacy routing and schema enforcement."""
        t_start = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        req_id = request_id or f"or_{int(time.time()*1000)}"

        telemetry: Dict[str, Any] = {
            "request_id": req_id,
            "provider": "openrouter",
            "model": self.model_name,
            "started_at": started_at,
            "error_class": None,
            "schema_status": "PENDING",
            "total_duration_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "error": None,
            "http_status": None,
            "request_attempted": True,
            "request_sent": False,
            "response_received": False,
        }

        # 1. Key check
        if not self.is_available():
            telemetry["error_class"] = "AUTH_ERROR"
            telemetry["schema_status"] = "OPENROUTER_KEY_REQUIRED"
            telemetry["error"] = "CITADEL_OPENROUTER_API_KEY is not configured."
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        # 2. Safety check: Never route to openrouter/free
        if self.model_name.strip() == "openrouter/free":
            telemetry["error_class"] = "PRIVACY_POLICY_BLOCKED"
            telemetry["schema_status"] = "PROHIBITED_ROUTER_BLOCKED"
            telemetry["error"] = "openrouter/free wildcard router is prohibited for CITADEL cognition."
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        # 3. Privacy Boundary Check
        is_private, priv_err = self.verify_privacy_boundary(user_prompt)
        if not is_private:
            telemetry["error_class"] = "PRIVACY_POLICY_BLOCKED"
            telemetry["schema_status"] = "PRIVACY_VIOLATION_BLOCKED"
            telemetry["error"] = priv_err
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        # 4. TLS Strict Verification Check
        if self._ssl_context is None:
            telemetry["error_class"] = "TLS_CONFIGURATION_ERROR"
            telemetry["schema_status"] = "TLS_VERIFICATION_FAILED"
            telemetry["error"] = self._ssl_error or "Secure TLS context unavailable"
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        effective_system = system_prompt
        if schema and "json" not in effective_system.lower():
            effective_system += "\n\nYou must output strictly valid JSON conforming to the requested schema."

        messages = [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_prompt},
        ]

        # Enforce strict privacy routing: deny provider data collection and disallow paid fallbacks
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": kwargs.get("max_output_tokens", 4096),
            "provider": {
                "data_collection": "deny",
                "allow_fallbacks": False,
            },
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://citadel.local",
            "X-Title": "CitadelOS",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }

        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        telemetry["request_sent"] = True
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds, context=self._ssl_context) as resp:
                raw_bytes = resp.read()
                raw_json = json.loads(raw_bytes.decode("utf-8"))
                telemetry["response_model"] = raw_json.get("model")
                resp_headers = resp.headers
                telemetry["response_received"] = True
                telemetry["http_status"] = getattr(resp, "status", 200)

            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()

            self._update_rate_limits(resp_headers)
            telemetry["rate_limits"] = dict(self.rate_limits)

            usage = raw_json.get("usage", {})
            telemetry["prompt_tokens"] = usage.get("prompt_tokens", 0)
            telemetry["completion_tokens"] = usage.get("completion_tokens", 0)
            telemetry["total_tokens"] = usage.get("total_tokens", 0)
            telemetry["reasoning_tokens"] = (
                (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                or usage.get("reasoning_tokens")
            )
            telemetry["cost"] = usage.get("cost", raw_json.get("cost", 0.0))

            self.rate_limits["total_requests_made"] += 1
            self.rate_limits["total_tokens_consumed"] += telemetry["total_tokens"]

            choices = raw_json.get("choices", [])
            if not choices:
                telemetry["error_class"] = "BAD_RESPONSE"
                telemetry["schema_status"] = "EMPTY_MODEL_CHOICES"
                telemetry["error"] = "No choices returned from OpenRouter"
                return None, telemetry

            finish_reason = choices[0].get("finish_reason")
            telemetry["finish_reason"] = finish_reason

            message = choices[0].get("message", {})
            if kwargs.get("audit_sink") is not None:
                kwargs["audit_sink"]({"provider":"openrouter", "model":self.model_name,
                    "response_model":raw_json.get("model"), "request_id":req_id,
                    "started_at":started_at, "ended_at":telemetry["ended_at"],
                    "request_bytes":len(req.data), "usage":usage,
                    "finish_reason":finish_reason, "rate_limits":dict(self.rate_limits),
                    "content":message.get("content"), "reasoning":message.get("reasoning"),
                    "cost":telemetry["cost"], "audit_only":True, "accepted_synthesis":False})
            content = (message.get("content") or "").strip()
            telemetry["response_text"] = content
            if not content:
                telemetry["error_class"] = "BAD_RESPONSE"
                telemetry["schema_status"] = "EMPTY_MODEL_RESPONSE"
                telemetry["error"] = "Empty message content in OpenRouter response"
                return None, telemetry

            clean_content = content
            if "```" in clean_content:
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_content, re.DOTALL)
                if match:
                    clean_content = match.group(1).strip()
            elif not clean_content.startswith("{") and "{" in clean_content:
                match = re.search(r"(\{.*\})", clean_content, re.DOTALL)
                if match:
                    clean_content = match.group(1).strip()

            try:
                parsed_output = json.loads(clean_content)
                telemetry["schema_status"] = "SCHEMA_VALID_JSON"
                return parsed_output, telemetry
            except json.JSONDecodeError as err:
                telemetry["error_class"] = "SCHEMA_INVALID"
                telemetry["schema_status"] = "INVALID_JSON"
                telemetry["error"] = f"JSON decode error: {err}"
                return None, telemetry

        except urllib.error.HTTPError as http_err:
            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            telemetry["response_received"] = True
            telemetry["http_status"] = http_err.code
            self._update_rate_limits(http_err.headers)

            try:
                err_body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            telemetry["error"] = redact_text(f"{http_err}: {err_body}" if err_body else str(http_err))

            if http_err.code in (401, 403):
                telemetry["error_class"] = "AUTH_ERROR"
            elif http_err.code == 429:
                self.rate_limits["total_429_count"] += 1
                self.rate_limits["last_429_timestamp"] = datetime.now(timezone.utc).isoformat()
                telemetry["error_class"] = "RATE_LIMITED"
                telemetry["schema_status"] = "RATE_LIMITED"
            elif http_err.code == 404:
                telemetry["error_class"] = "MODEL_UNAVAILABLE"
            elif http_err.code == 400 and any(m in err_body.lower() for m in ("not available", "not found", "no endpoints", "retired")):
                telemetry["error_class"] = "MODEL_UNAVAILABLE"
            elif http_err.code in (500, 502, 503, 504):
                telemetry["error_class"] = "PROVIDER_UNAVAILABLE"
            else:
                telemetry["error_class"] = f"HTTP_ERROR_{http_err.code}"

            return None, telemetry

        except Exception as exc:
            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            telemetry["response_received"] = False
            telemetry["error_class"] = "TIMEOUT" if "timed out" in str(exc).lower() else "UNKNOWN_ERROR"
            telemetry["schema_status"] = "TRANSPORT_ERROR"
            telemetry["error"] = redact_text(str(exc))
            return None, telemetry

    def _update_rate_limits(self, headers: Any) -> None:
        if not headers:
            return

        def parse_header(name: str) -> Optional[int]:
            val = headers.get(name)
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    pass
            return None

        self.rate_limits["limit_requests"] = parse_header("x-ratelimit-limit-requests")
        self.rate_limits["remaining_requests"] = parse_header("x-ratelimit-remaining-requests")
        self.rate_limits["limit_tokens"] = parse_header("x-ratelimit-limit-tokens")
        self.rate_limits["remaining_tokens"] = parse_header("x-ratelimit-remaining-tokens")
        self.rate_limits["reset_requests"] = headers.get("x-ratelimit-reset-requests")
        self.rate_limits["reset_tokens"] = headers.get("x-ratelimit-reset-tokens")
        self.rate_limits["retry_after_seconds"] = headers.get("retry-after")

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "provider": "openrouter",
            "model": self.model_name,
            "configured": self.is_available(),
            "rate_limits": dict(self.rate_limits),
        }
