"""GPT-5.6 Sol Model Adapter & Structured Output Interface (P0.3B Hardened).

Handles structured, schema-constrained reasoning invocations via OpenAI Responses API
transmitting:
- instructions = system prompt
- input = user payload
- reasoning = {"effort": "medium"} (labeled UNVALIDATED_REASONING_CONFIGURATION)
- text = {"format": {"type": "json_schema", "name": "...", "schema": ..., "strict": True}}
- store = False (stateless execution)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from src.oracle_sol.contracts import (
    SOL_STRUCTURED_OUTPUT_JSON_SCHEMA,
    SolModelRequestEnvelope,
)


class SolModelAdapter:
    """Secure, schema-constrained adapter for GPT-5.6 Sol via OpenAI Responses API."""

    def __init__(
        self,
        configured_model: str = "gpt-5.6-sol",
        api_key: Optional[str] = None,
        timeout_seconds: float = 12.0,
        reasoning_effort: str = "medium",
    ) -> None:
        self.configured_model = os.getenv("CITADEL_SOL_MODEL", configured_model)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort  # Labeled UNVALIDATED_REASONING_CONFIGURATION
        self.is_configured = bool(self.api_key and len(self.api_key.strip()) > 10)

    def invoke_reasoning(
        self,
        cycle_id: str,
        system_prompt: str,
        user_payload: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], SolModelRequestEnvelope]:
        """Invoke LLM reasoning with strict JSON Schema Structured Outputs via Responses API.

        Returns: (parsed_json_output, execution_telemetry, request_envelope)
        """
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()
        input_encoded = json.dumps(user_payload, sort_keys=True, default=str).encode()
        input_hash = hashlib.sha256(input_encoded).hexdigest()

        # Build exact normalized request envelope for 100% exact input replay
        envelope = SolModelRequestEnvelope(
            cycle_id=cycle_id,
            prompt_version="3.1.0-p0.3b",
            prompt_hash=prompt_hash,
            input_hash=input_hash,
            system_prompt=system_prompt,
            user_payload=user_payload,
            configured_model=self.configured_model,
            requested_model=self.configured_model,
            reasoning_effort=self.reasoning_effort,
        )

        telemetry: Dict[str, Any] = {
            "cycle_id": cycle_id,
            "configured_model": self.configured_model,
            "requested_model": self.configured_model,
            "request_attempted": False,
            "provider_response_model": "NONE",
            "successful_reasoning_model": "NONE",
            "reasoning_effort": self.reasoning_effort,
            "reasoning_configuration_status": "UNVALIDATED_REASONING_CONFIGURATION",
            "api_endpoint_family": "responses+structured_outputs (POST /v1/responses)",
            "is_configured": self.is_configured,
            "api_latency": "NOT MEASURED",
            "status": "UNAVAILABLE",
            "real_api_call_occurred": False,
            "prompt_hash": prompt_hash,
            "input_hash": input_hash,
            "token_usage": {},
        }

        if not self.is_configured:
            telemetry["status"] = "BLOCKED_NO_API_CREDENTIALS"
            return None, telemetry, envelope

        start_time = time.perf_counter()
        telemetry["request_attempted"] = True
        try:
            import requests

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            # Documented OpenAI Responses API format with text.format structured output
            body = {
                "model": self.configured_model,
                "instructions": system_prompt,
                "input": json.dumps(user_payload, sort_keys=True, default=str),
                "reasoning": {
                    "effort": self.reasoning_effort,
                },
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "sol_market_thesis_output",
                        "schema": SOL_STRUCTURED_OUTPUT_JSON_SCHEMA["schema"],
                        "strict": True,
                    }
                },
                "store": False,
            }

            resp = requests.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=body,
                timeout=self.timeout_seconds,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            telemetry["real_api_call_occurred"] = True
            telemetry["api_latency"] = f"{elapsed_ms:.1f}ms"

            if resp.status_code != 200:
                telemetry["status"] = f"HTTP_ERROR_{resp.status_code}"
                telemetry["error_message"] = resp.text[:200]
                return None, telemetry, envelope

            resp_data = resp.json()
            return self.parse_responses_api_payload(resp_data, telemetry, envelope)

        except Exception as exc:
            telemetry["status"] = "INVOCATION_EXCEPTION"
            telemetry["error_message"] = str(exc)
            telemetry["api_latency"] = "ERROR_DURING_INVOCATION"
            return None, telemetry, envelope

    def parse_responses_api_payload(
        self,
        resp_data: Dict[str, Any],
        telemetry: Dict[str, Any],
        envelope: SolModelRequestEnvelope,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], SolModelRequestEnvelope]:
        """Parse raw Responses API response payload safely with full refusal/incomplete checks."""
        returned_model = resp_data.get("model", self.configured_model)
        telemetry["provider_response_model"] = returned_model
        telemetry["token_usage"] = resp_data.get("usage", {})

        resp_status = resp_data.get("status")
        if resp_status and resp_status not in {"completed", "success"}:
            error_info = resp_data.get("error") or resp_data.get("incomplete_details") or resp_status
            telemetry["status"] = f"PROVIDER_ERROR_{resp_status}"
            telemetry["error_message"] = str(error_info)
            return None, telemetry, envelope

        raw_text: Optional[str] = None

        # Inspect output array -> message -> content -> output_text
        outputs = resp_data.get("output", [])
        if isinstance(outputs, list):
            for out_item in outputs:
                if isinstance(out_item, dict):
                    # Check for refusal
                    if out_item.get("type") == "refusal" or "refusal" in out_item:
                        telemetry["status"] = "MODEL_REFUSAL"
                        telemetry["error_message"] = str(out_item.get("refusal", "Model refused request"))
                        return None, telemetry, envelope

                    if out_item.get("type") == "message":
                        content_list = out_item.get("content", [])
                        if isinstance(content_list, list):
                            for c in content_list:
                                if isinstance(c, dict):
                                    if c.get("type") == "output_text" and "text" in c:
                                        raw_text = c["text"]
                                        break
                                    if c.get("type") == "text" and "text" in c:
                                        raw_text = c["text"]
                                        break
                                    if c.get("type") == "refusal":
                                        telemetry["status"] = "MODEL_REFUSAL"
                                        telemetry["error_message"] = str(c.get("refusal", "Model refused request"))
                                        return None, telemetry, envelope
                        elif isinstance(content_list, str):
                            raw_text = content_list

                    if raw_text is not None:
                        break

        # Fallback inspection for alternative response wrappers
        if raw_text is None and "choices" in resp_data:
            raw_text = resp_data["choices"][0]["message"]["content"]

        if not raw_text or not raw_text.strip():
            telemetry["status"] = "EMPTY_MODEL_RESPONSE"
            telemetry["error_message"] = "Model returned empty output text."
            return None, telemetry, envelope

        try:
            parsed = json.loads(raw_text)
            telemetry["status"] = "SUCCESS"
            telemetry["successful_reasoning_model"] = returned_model
            return parsed, telemetry, envelope
        except Exception as parse_exc:
            telemetry["status"] = "MALFORMED_OUTPUT"
            telemetry["error_message"] = f"JSON parse error: {str(parse_exc)}"
            return None, telemetry, envelope
