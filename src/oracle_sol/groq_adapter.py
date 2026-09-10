"""Groq Cloud Cognitive Brain Adapter (Strict Structured Outputs & Zero-Trust Boundary).

Implements BrainProviderAdapter for Groq Cloud API:
- Candidate Models:
  * Primary: openai/gpt-oss-120b (Groq production-listed)
  * Challenger: qwen/qwen3.8-27b (Groq Preview)
- Features:
  * Strict JSON Schema mode
  * Dynamic rate limit header parsing (TPM, RPD, Remaining, Retry-After)
  * 429 backoff policy (honors provider state, zero automatic live retries)
  * Privacy boundary guard (blocks broker credentials, raw packets, local paths)
  * ZDR status tracking (ZDR_MANUAL_VERIFICATION_REQUIRED)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.oracle_sol.brain_provider_adapter import BrainProviderAdapter

logger = logging.getLogger(__name__)


class GroqBrainAdapter(BrainProviderAdapter):
    """Secure, schema-constrained Groq Cloud provider adapter."""

    DEFAULT_PRODUCTION_MODEL = "openai/gpt-oss-120b"
    CHALLENGER_PREVIEW_MODEL = "qwen/qwen3.8-27b"
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    # Privacy boundary banned keywords
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
            or os.getenv("CITADEL_GROQ_MODEL")
            or self.DEFAULT_PRODUCTION_MODEL
        )
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            try:
                import subprocess
                res = subprocess.run(
                    ["security", "find-generic-password", "-s", "GROQ_API_KEY", "-w"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0 and len(res.stdout.strip()) > 8:
                    self.api_key = res.stdout.strip()
            except Exception:
                pass
        self.base_url = base_url or self.API_URL

        from src.oracle_sol.provider_secrets import create_strict_ssl_context
        self._ssl_context = create_strict_ssl_context()

        # Dynamic Rate Limit Tracking from Provider Headers
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

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 8)

    def is_available(self) -> bool:
        """Check if Groq API key is configured."""
        return bool(self.api_key and len(self.api_key.strip()) > 8)

    def verify_privacy_boundary(self, text_payload: str) -> Tuple[bool, Optional[str]]:
        """Verify that payload contains zero broker credentials, accounts, or local paths."""
        lower_payload = text_payload.lower()
        for term in self.BANNED_PRIVACY_TERMS:
            if term.lower() in lower_payload:
                return False, f"Banned privacy token detected: '{term}'"
        return True, None

    def invoke_reasoning(
        self,
        request_id: Optional[str] = None,
        system_prompt: str = "",
        user_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
        cycle_id: Optional[str] = None,
        user_payload: Optional[Any] = None,
        max_output_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke Groq model reasoning with strict JSON schema and dynamic rate monitoring."""
        t_start = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        req_id = request_id or cycle_id or f"req_{int(time.time()*1000)}"
        effective_user_prompt = user_prompt if user_prompt is not None else json.dumps(user_payload or {}, default=str)

        telemetry: Dict[str, Any] = {
            "request_id": req_id,
            "cycle_id": req_id,
            "provider": "groq",
            "model": self.model_name,
            "model_status": "PREVIEW" if "preview" in self.model_name.lower() or "qwen" in self.model_name.lower() else "PRODUCTION",
            "started_at": started_at,
            "zdr_status": "ZDR_MANUAL_VERIFICATION_REQUIRED",
            "schema_status": "PENDING",
            "total_duration_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": None,
            "http_status": None,
            "request_attempted": True,
            "request_sent": False,
            "response_received": False,
        }

        def _build_result(parsed: Optional[Dict[str, Any]]) -> Any:
            if user_payload is not None or cycle_id is not None:
                from src.oracle_sol.contracts import SolModelRequestEnvelope
                import hashlib
                p_hash = hashlib.sha256(effective_system.encode()).hexdigest()
                inp_bytes = json.dumps(user_payload if user_payload is not None else effective_user_prompt, sort_keys=True, default=str).encode()
                i_hash = hashlib.sha256(inp_bytes).hexdigest()
                envelope = SolModelRequestEnvelope(
                    cycle_id=req_id,
                    prompt_version="3.1.0-groq",
                    prompt_hash=p_hash,
                    input_hash=i_hash,
                    system_prompt=effective_system,
                    user_payload=user_payload if isinstance(user_payload, dict) else {"prompt": effective_user_prompt},
                    configured_model=self.model_name,
                    requested_model=self.model_name,
                    reasoning_effort="none",
                )
                return parsed, telemetry, envelope
            return parsed, telemetry

        # 1. Key check
        if not self.is_available():
            telemetry["schema_status"] = "GROQ_KEY_REQUIRED"
            telemetry["error"] = "GROQ_API_KEY is not configured in environment."
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return _build_result(None)

        # 2. Privacy Boundary check
        is_private, privacy_err = self.verify_privacy_boundary(system_prompt + "\n" + effective_user_prompt)
        if not is_private:
            telemetry["schema_status"] = "PRIVACY_VIOLATION_BLOCKED"
            telemetry["error"] = privacy_err
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return _build_result(None)

        # 3. Build request payload
        effective_system = system_prompt
        if schema and "json" not in effective_system.lower():
            effective_system = effective_system + "\n\nYou must output strictly valid JSON conforming to the schema."

        messages = [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": effective_user_prompt},
        ]

        effective_max_tokens = max_output_tokens if max_output_tokens is not None else 3500
        # GPT-OSS models generate 60-110 reasoning tokens; clamp lower bound to 1024 to prevent json_validate_failed
        if self.model_name.startswith("openai/gpt-oss") and effective_max_tokens < 1024:
            effective_max_tokens = 1024

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.1,  # Low temperature for deterministic reasoning
            "max_tokens": effective_max_tokens,
        }

        strict_schema = kwargs.get("strict_schema", False)
        effort = kwargs.get("reasoning_effort")
        supported = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"}
        if strict_schema:
            if self.model_name not in supported or schema is None:
                raise ValueError("STRICT_SCHEMA_UNSUPPORTED")
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "citadel_synthesis", "strict": True, "schema": schema}}
        elif schema and not self.model_name.startswith("openai/gpt-oss"):
            # Groq structured outputs JSON schema mode
            payload["response_format"] = {
                "type": "json_object",
            }
        if effort is not None:
            allowed = {"low", "medium", "high"}
            if self.model_name == "qwen/qwen3.8-27b":
                allowed |= {"none", "default"}
            if self.model_name not in supported or effort not in allowed:
                raise ValueError("REASONING_EFFORT_UNSUPPORTED")
            payload["reasoning_effort"] = effort
        if strict_schema or effort is not None:
            payload["max_completion_tokens"] = payload.pop("max_tokens")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
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

            # Dynamic Rate Limit Header Extraction
            self._update_rate_limits(resp_headers)
            telemetry["rate_limits"] = dict(self.rate_limits)

            # Token usage extraction
            usage = raw_json.get("usage", {})
            telemetry["prompt_tokens"] = usage.get("prompt_tokens", 0)
            telemetry["completion_tokens"] = usage.get("completion_tokens", 0)
            telemetry["reasoning_tokens"] = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            telemetry["total_tokens"] = usage.get("total_tokens", 0)
            prompt_details = usage.get("prompt_tokens_details") or {}
            telemetry["cached_tokens"] = prompt_details.get("cached_tokens", usage.get("cached_tokens", 0))

            self.rate_limits["total_requests_made"] += 1
            self.rate_limits["total_tokens_consumed"] += telemetry["total_tokens"]

            choices = raw_json.get("choices", [])
            if not choices:
                telemetry["schema_status"] = "EMPTY_MODEL_CHOICES"
                telemetry["error"] = f"No choices returned from Groq"
                return _build_result(None)

            finish_reason = choices[0].get("finish_reason")
            telemetry["finish_reason"] = finish_reason
            # Explicit offline audit sink only; never placed in public telemetry
            # or parsed output. Preserve content before strip/JSON extraction.
            if kwargs.get("audit_sink") is not None:
                kwargs["audit_sink"]({
                    "provider": "groq", "requested_model": self.model_name,
                    "response_model": raw_json.get("model"), "request_id": req_id,
                    "started_at": started_at, "ended_at": telemetry["ended_at"],
                    "request_bytes": len(req.data), "input_bytes": len(effective_user_prompt.encode()),
                    "finish_reason": finish_reason, "usage": usage,
                    "quota_headers": {k: v for k, v in resp_headers.items()
                                      if k.lower().startswith("x-ratelimit-") or k.lower() == "retry-after"},
                    "content": choices[0].get("message", {}).get("content"),
                    "reasoning": choices[0].get("message", {}).get("reasoning"),
                    "audit_only": True, "accepted_synthesis": False,
                })
            if finish_reason == "length":
                logger.warning("Groq response truncated due to max_tokens limit: finish_reason=length")

            content = choices[0].get("message", {}).get("content", "").strip()
            if not content:
                telemetry["schema_status"] = "EMPTY_MODEL_RESPONSE"
                telemetry["error"] = f"Empty message content in Groq response"
                return _build_result(None)

            # Robust JSON parsing
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
                return _build_result(parsed_output)
            except json.JSONDecodeError as err:
                telemetry["schema_status"] = "INVALID_JSON"
                telemetry["error"] = f"JSON decode error: {err}"
                return _build_result(None)

        except urllib.error.HTTPError as http_err:
            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            telemetry["response_received"] = True
            telemetry["http_status"] = http_err.code
            self._update_rate_limits(http_err.headers)

            if http_err.code == 429:
                self.rate_limits["total_429_count"] += 1
                self.rate_limits["last_429_timestamp"] = datetime.now(timezone.utc).isoformat()
                retry_after = http_err.headers.get("retry-after")
                telemetry["schema_status"] = "RATE_LIMITED"
                telemetry["error_class"] = "RATE_LIMITED"
                telemetry["error"] = f"Groq 429 Too Many Requests. Retry-After: {retry_after}s"
                logger.warning("Groq Rate Limit Exceeded (429). Retry-After: %s. Cursor unchanged.", retry_after)
            else:
                try:
                    err_body = http_err.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = ""
                telemetry["schema_status"] = f"HTTP_ERROR_{http_err.code}"
                try:
                    provider_error = json.loads(err_body).get("error", {})
                except (ValueError, AttributeError):
                    provider_error = {}
                if isinstance(provider_error, dict) and "failed_generation" in provider_error:
                    # A schema error can contain the entire model completion.
                    # Keep it out of runtime/frontend error text; explicit audit only.
                    if kwargs.get("audit_sink") is not None:
                        kwargs["audit_sink"]({"provider":"groq", "requested_model":self.model_name,
                            "http_status":http_err.code, "started_at":started_at,
                            "ended_at":telemetry["ended_at"], "request_bytes":len(req.data),
                            "input_bytes":len(effective_user_prompt.encode()),
                            "content":provider_error["failed_generation"], "reasoning":None,
                            "provider_error_code":provider_error.get("code"),
                            "audit_only":True,"accepted_synthesis":False})
                    telemetry["error_class"] = "SCHEMA_INVALID"
                    telemetry["error"] = f"HTTP {http_err.code}: provider structured-output validation failed; completion retained only in explicit audit."
                elif http_err.code in (401, 403):
                    telemetry["error_class"] = "AUTH_ERROR"
                    telemetry["error"] = f"{http_err}: {err_body}" if err_body else str(http_err)
                elif http_err.code == 404:
                    telemetry["error_class"] = "MODEL_UNAVAILABLE"
                    telemetry["error"] = f"{http_err}: {err_body}" if err_body else str(http_err)
                elif http_err.code in (500, 502, 503, 504):
                    telemetry["error_class"] = "PROVIDER_UNAVAILABLE"
                    telemetry["error"] = f"{http_err}: {err_body}" if err_body else str(http_err)
                else:
                    telemetry["error_class"] = f"HTTP_ERROR_{http_err.code}"
                    telemetry["error"] = f"{http_err}: {err_body}" if err_body else str(http_err)

            return _build_result(None)

        except Exception as exc:
            t_end = time.perf_counter()
            telemetry["total_duration_ms"] = round((t_end - t_start) * 1000.0, 2)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            telemetry["response_received"] = False
            telemetry["http_status"] = None
            telemetry["schema_status"] = "TRANSPORT_ERROR"
            telemetry["error"] = str(exc)
            return _build_result(None)

    def _update_rate_limits(self, headers: Any) -> None:
        """Dynamically parse Groq rate limit headers from HTTP response."""
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
        """Return cumulative telemetry and rate limit statistics."""
        return {
            "provider": "groq",
            "model": self.model_name,
            "configured": self.is_available(),
            "rate_limits": dict(self.rate_limits),
        }
