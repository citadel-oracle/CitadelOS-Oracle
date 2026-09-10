"""Unit and Contract Tests for GroqBrainAdapter (Zero-Trust Cloud Provider).

Verifies:
1. Missing GROQ_API_KEY -> GROQ_KEY_REQUIRED (no crash, zero cloud call)
2. Privacy guard -> Blocks broker credentials, client IDs, local paths
3. Strict Schema decoding -> Clean JSON dict extraction
4. Dynamic rate limit tracking -> Parses x-ratelimit headers
5. 429 Rate limit backoff -> Marks RATE_LIMITED, zero repeated retry loop
6. Model selection -> Configurable for openai/gpt-oss-120b and qwen/qwen3.8-27b
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from src.oracle_sol.groq_adapter import GroqBrainAdapter


def test_groq_missing_key_reports_groq_key_required():
    with patch.dict(os.environ, {}, clear=True), patch("subprocess.run") as mock_sub:
        mock_sub.return_value.returncode = 1
        adapter = GroqBrainAdapter(api_key=None)
        assert not adapter.is_available()

        output, telemetry = adapter.invoke_reasoning(
            request_id="test_req_001",
            system_prompt="system",
            user_prompt="user",
        )
        assert output is None
        assert telemetry["schema_status"] == "GROQ_KEY_REQUIRED"
        assert "GROQ_API_KEY is not configured" in telemetry["error"]


def test_groq_privacy_guard_blocks_sensitive_tokens():
    adapter = GroqBrainAdapter(api_key="gsk_mock_valid_key_for_testing_12345")
    assert adapter.is_available()

    banned_payload = "Here is my data: dhan_client_id = DHAN12345 and /Users/ayushmudgal/key.json"
    output, telemetry = adapter.invoke_reasoning(
        request_id="test_req_priv",
        system_prompt="system",
        user_prompt=banned_payload,
    )
    assert output is None
    assert telemetry["schema_status"] == "PRIVACY_VIOLATION_BLOCKED"
    assert "Banned privacy token detected" in telemetry["error"]


def test_groq_strict_json_schema_parsing():
    adapter = GroqBrainAdapter(api_key="gsk_mock_valid_key_for_testing_12345")

    mock_resp_body = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "observer": {"what_changed": "Baseline setup"},
                        "call_case": {"thesis": "None"},
                        "put_case": {"thesis": "None"},
                        "no_trade_case": {"thesis": "Range bound"},
                        "skeptic": {"critique": "Chop risk"},
                        "temporal_analyst": {"continuity": "Stable"},
                        "option_buyer_analyst": {"suitability": "Avoid"},
                        "external_context_analyst": {"macro": "Neutral"},
                        "synthesis": {"state": "NO_TRADE"},
                    }),
                }
            }
        ],
        "usage": {"prompt_tokens": 150, "completion_tokens": 80, "total_tokens": 230},
    }

    mock_headers = {
        "x-ratelimit-limit-requests": "14400",
        "x-ratelimit-remaining-requests": "14399",
        "x-ratelimit-limit-tokens": "500000",
        "x-ratelimit-remaining-tokens": "499770",
    }

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_resp_body).encode("utf-8")
    mock_response.headers = mock_headers
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        output, telemetry = adapter.invoke_reasoning(
            request_id="test_req_valid",
            system_prompt="system",
            user_prompt="{\"clean\": \"packet\"}",
            schema={"type": "object"},
        )

    assert output is not None
    assert output["synthesis"]["state"] == "NO_TRADE"
    assert telemetry["schema_status"] == "SCHEMA_VALID_JSON"
    assert telemetry["prompt_tokens"] == 150
    assert telemetry["completion_tokens"] == 80
    assert telemetry["rate_limits"]["remaining_requests"] == 14399


def test_groq_429_backoff_no_immediate_retry():
    adapter = GroqBrainAdapter(api_key="gsk_mock_valid_key_for_testing_12345")

    mock_headers = {
        "retry-after": "15",
        "x-ratelimit-remaining-requests": "0",
    }
    http_err = urllib.error.HTTPError(
        url="https://api.groq.com",
        code=429,
        msg="Too Many Requests",
        hdrs=mock_headers,
        fp=io.BytesIO(b"{\"error\": \"rate_limit_exceeded\"}"),
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        output, telemetry = adapter.invoke_reasoning(
            request_id="test_req_429",
            system_prompt="system",
            user_prompt="{\"clean\": \"packet\"}",
        )

    assert output is None
    assert telemetry["schema_status"] == "RATE_LIMITED"
    assert "Retry-After: 15s" in telemetry["error"]
    assert adapter.rate_limits["total_429_count"] == 1
    assert adapter.rate_limits["retry_after_seconds"] == "15"


def test_model_selection_between_120b_and_27b():
    adapter_prod = GroqBrainAdapter(model_name="openai/gpt-oss-120b")
    assert adapter_prod.model_name == "openai/gpt-oss-120b"

    adapter_challenger = GroqBrainAdapter(model_name="qwen/qwen3.8-27b")
    assert adapter_challenger.model_name == "qwen/qwen3.8-27b"
