"""Cloudflare Workers AI Cognitive Brain Adapter (Edge Zero-Cost Inference).

Implements Cloudflare Workers AI integration:
- Base URL: https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions
- Zero-cost allocation: 10,000 Neurons/day free tier
- Scoped API Token authentication (preferred) with Global API Key backward compatibility
- Zero-trust privacy boundary guard
- Normalized error handling and structured JSON output parsing
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


class CloudflareWorkersAIAdapter(BrainProviderAdapter):
    """Secure adapter for Cloudflare Workers AI inference with scoped API tokens."""

    DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8"

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
        account_id: Optional[str] = None,
        api_token: Optional[str] = None,
    ) -> None:
        self.model_name = (
            model_name
            or os.getenv("CITADEL_CLOUDFLARE_MODEL")
            or self.DEFAULT_MODEL
        )
        self.account_id = account_id or get_secret("cloudflare_account")
        # Prefer scoped token, then general api token
        self.api_token = api_token or get_secret("cloudflare")

        try:
            from src.oracle_sol.provider_secrets import create_strict_ssl_context
            self._ssl_context = create_strict_ssl_context()
            self._ssl_error = None
        except Exception as e:
            self._ssl_context = None
            self._ssl_error = f"TLS_CONFIGURATION_ERROR: {e}"

        self.rate_limits: Dict[str, Any] = {
            "daily_neuron_allowance": 10000,
            "neurons_consumed": 0.0,
            "total_requests_made": 0,
            "last_http_status": None,
        }

    @property
    def configured_model(self) -> str:
        return self.model_name

    def is_available(self) -> bool:
        return bool(
            self.account_id
            and len(self.account_id.strip()) > 0
            and self.api_token
            and len(self.api_token.strip()) > 0
        )

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
        """Invoke Cloudflare Workers AI model with fail-closed credential verification."""
        t_start = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        req_id = request_id or f"cf_{int(time.time()*1000)}"

        telemetry: Dict[str, Any] = {
            "request_id": req_id,
            "provider": "cloudflare",
            "model": self.model_name,
            "started_at": started_at,
            "error_class": None,
            "schema_status": "PENDING",
            "total_duration_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "neurons": 0.0,
            "error": None,
            "http_status": None,
            "request_attempted": True,
            "request_sent": False,
            "response_received": False,
        }

        # 1. Guard against incomplete credentials
        if not self.is_available():
            telemetry["error_class"] = "AUTH_ERROR"
            telemetry["schema_status"] = "CREDENTIALS_INCOMPLETE"
            missing_items = []
            if not self.account_id:
                missing_items.append("CLOUDFLARE_ACCOUNT_ID")
            if not self.api_token:
                missing_items.append("CLOUDFLARE_API_TOKEN")
            telemetry["error"] = f"Cloudflare credentials incomplete. Missing: {', '.join(missing_items)}"
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        # 2. Privacy Boundary Check
        is_private, priv_err = self.verify_privacy_boundary(user_prompt)
        if not is_private:
            telemetry["error_class"] = "PRIVACY_POLICY_BLOCKED"
            telemetry["schema_status"] = "PRIVACY_VIOLATION_BLOCKED"
            telemetry["error"] = priv_err
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        # 3. TLS Strict Verification Check
        if self._ssl_context is None:
            telemetry["error_class"] = "TLS_CONFIGURATION_ERROR"
            telemetry["schema_status"] = "TLS_VERIFICATION_FAILED"
            telemetry["error"] = self._ssl_error or "Secure TLS context unavailable"
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        endpoint = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/v1/chat/completions"

        effective_system = system_prompt
        if schema and "json" not in effective_system.lower():
            effective_system += "\n\nYou must output strictly valid JSON conforming to the requested schema."

        messages = [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_prompt},
        ]

        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": kwargs.get("max_output_tokens", 4096),
        }

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }

        req = urllib.request.Request(
            endpoint,
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
                telemetry["response_received"] = True
                telemetry["http_status"] = getattr(resp, "status", 200)

            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()

            # Extract content from OpenAI-compatible choices format
            choices = raw_json.get("choices", [])
            content = ""
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip()
                telemetry["finish_reason"] = choices[0].get("finish_reason")
            elif "result" in raw_json:
                content = raw_json.get("result", {}).get("response", "").strip()

            telemetry["response_text"] = content

            # Usage extraction
            usage = raw_json.get("usage", {})
            telemetry["prompt_tokens"] = usage.get("prompt_tokens", 0)
            telemetry["completion_tokens"] = usage.get("completion_tokens", 0)
            telemetry["total_tokens"] = usage.get("total_tokens", 0)
            telemetry["neurons"] = usage.get("neurons", 0.0)

            self.rate_limits["total_requests_made"] += 1
            self.rate_limits["neurons_consumed"] += telemetry["neurons"]
            self.rate_limits["last_http_status"] = telemetry["http_status"]
            telemetry["rate_limits"] = dict(self.rate_limits)

            if not content:
                telemetry["error_class"] = "BAD_RESPONSE"
                telemetry["schema_status"] = "EMPTY_MODEL_RESPONSE"
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
                parsed = json.loads(clean_content)
                telemetry["schema_status"] = "SCHEMA_VALID_JSON"
                return parsed, telemetry
            except Exception:
                if schema:
                    telemetry["error_class"] = "SCHEMA_INVALID"
                    telemetry["schema_status"] = "INVALID_JSON"
                    return None, telemetry
                telemetry["schema_status"] = "TEXT_RESPONSE"
                return {"text": content}, telemetry

        except urllib.error.HTTPError as http_err:
            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            telemetry["response_received"] = True
            telemetry["http_status"] = http_err.code
            try:
                err_body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            telemetry["error"] = redact_text(f"{http_err}: {err_body}" if err_body else str(http_err))

            if http_err.code == 403:
                if any(m in err_body.lower() for m in ("free plan", "upgrade", "5035", "not available on")):
                    telemetry["error_class"] = "PLAN_GATED"
                else:
                    telemetry["error_class"] = "AUTH_ERROR"
            elif http_err.code == 401:
                telemetry["error_class"] = "AUTH_ERROR"
            elif http_err.code == 429:
                telemetry["error_class"] = "RATE_LIMITED"
            elif http_err.code in (500, 502, 503, 504):
                telemetry["error_class"] = "PROVIDER_UNAVAILABLE"
            else:
                telemetry["error_class"] = f"HTTP_ERROR_{http_err.code}"
            return None, telemetry

        except Exception as exc:
            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            telemetry["error_class"] = "TIMEOUT" if "timed out" in str(exc).lower() else "UNKNOWN_ERROR"
            telemetry["error"] = redact_text(str(exc))
            return None, telemetry

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "provider": "cloudflare",
            "model": self.model_name,
            "configured": self.is_available(),
            "rate_limits": dict(self.rate_limits),
        }
