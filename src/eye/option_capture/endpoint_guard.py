"""Read-Only Endpoint Safety Guard for Eye Engine Option Capture."""

import re
from typing import Dict, Any


class EndpointSafetyError(PermissionError):
    """Raised when an attempt is made to invoke a forbidden or non-allowlisted endpoint."""
    pass


ALLOWED_ENDPOINT_PATTERNS = [
    r"^https://api\.dhan\.co/v2/optionchain$",
    r"^https://api\.dhan\.co/v2/optionchain/expirylist$",
    r"^https://api\.dhan\.co/v2/marketfeed/quote$",
    r"^https://api\.dhan\.co/v2/marketfeed/ohlc$",
    r"^https://api\.dhan\.co/v2/marketfeed/ltp$",
    r"^wss://api-feed\.dhan\.co/?.*$",
    r"^https://images\.dhan\.co/.*$",
    r"^https://.*dhan.*master.*$",
]

FORBIDDEN_KEYWORDS = [
    "order",
    "orders",
    "super-order",
    "forever-order",
    "modify",
    "cancel",
    "convert-position",
    "exit-all",
    "margin",
    "fund",
    "pledge",
    "trade",
    "execution",
    "place",
]

SECRET_HEADER_KEYS = {
    "access-token",
    "client-id",
    "authorization",
    "x-api-key",
    "token",
    "secret",
    "api-secret",
}


def validate_request_url(url: str, method: str = "GET") -> None:
    """Validates that a target URL is strictly read-only and allowed.

    Raises:
        EndpointSafetyError: If url contains forbidden keywords or is not explicitly allowlisted.
    """
    url_lower = url.lower()

    # 1. Check for forbidden keywords in path
    for kw in FORBIDDEN_KEYWORDS:
        if kw in url_lower:
            raise EndpointSafetyError(f"FORBIDDEN_ENDPOINT_BLOCKED: URL contains forbidden keyword '{kw}': {url}")

    # 2. Check allowlist
    allowed = any(re.match(pattern, url, re.IGNORECASE) for pattern in ALLOWED_ENDPOINT_PATTERNS)
    if not allowed:
        raise EndpointSafetyError(f"NON_ALLOWLISTED_ENDPOINT_BLOCKED: URL is not in read-only allowlist: {url}")


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Returns a copy of headers with sensitive credential keys redacted."""
    redacted = {}
    for k, v in headers.items():
        if k.lower() in SECRET_HEADER_KEYS:
            redacted[k] = "[REDACTED_SECRET]"
        else:
            redacted[k] = v
    return redacted


def redact_text(text: str) -> str:
    """Redacts potential tokens or credentials from log/artifact text strings."""
    # Redact query params (key=value)
    text = re.sub(r'([?&])(access-token|access_token|token|client-id|client_id|secret)=[^&"\s]+', r'\1\2=[REDACTED_SECRET]', text, flags=re.IGNORECASE)
    # Redact JSON properties ("key": "value")
    text = re.sub(r'("(?:access-token|access_token|token|client-id|client_id|secret)")\s*:\s*"[^"]+"', r'\1: "[REDACTED_SECRET]"', text, flags=re.IGNORECASE)
    return text
