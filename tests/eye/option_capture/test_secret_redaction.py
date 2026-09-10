"""E4A-E Test for Secret & Token Redaction Engine."""

import pytest
from src.eye.option_capture.endpoint_guard import redact_text, redact_headers


def test_secret_redaction_in_text():
    raw_str = '{"access-token": "secret_abc_123", "symbol": "NIFTY"}'
    redacted = redact_text(raw_str)

    assert "[REDACTED_SECRET]" in redacted
    assert "secret_abc_123" not in redacted
