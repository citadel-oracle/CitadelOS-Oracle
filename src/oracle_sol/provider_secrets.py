"""CITADEL Provider Secrets Management (Zero-Trust macOS Keychain & Redaction).

Safely discovers and loads provider credentials without disk persistence or logging.
Supports:
- GROQ
- GOOGLE GEMINI (PRIMARY & SECONDARY PROFILES)
- NVIDIA NIM / API
- OPENROUTER
- CLOUDFLARE WORKERS AI (SCOPED TOKEN & GLOBAL KEY)
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Service name mapping: provider -> list of (Keychain service, Env var)
PROVIDER_SECRET_MAP: Dict[str, List[Tuple[str, str]]] = {
    "groq": [
        ("CITADEL_GROQ_API_KEY", "GROQ_API_KEY"),
        ("GROQ_API_KEY", "CITADEL_GROQ_API_KEY"),
    ],
    "google": [
        ("CITADEL_GEMINI_API_KEY_PRIMARY", "GEMINI_API_KEY_PRIMARY"),
        ("CITADEL_GEMINI_API_KEY", "GEMINI_API_KEY"),
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        ("GOOGLE_API_KEY", "CITADEL_GEMINI_API_KEY"),
    ],
    "gemini_primary": [
        ("CITADEL_GEMINI_API_KEY_PRIMARY", "GEMINI_API_KEY_PRIMARY"),
        ("GEMINI_API_KEY_PRIMARY", "CITADEL_GEMINI_API_KEY_PRIMARY"),
    ],
    "gemini_secondary": [
        ("CITADEL_GEMINI_API_KEY_SECONDARY", "GEMINI_API_KEY_SECONDARY"),
        ("GEMINI_API_KEY_SECONDARY", "CITADEL_GEMINI_API_KEY_SECONDARY"),
    ],
    "gemini_tertiary": [
        ("CITADEL_GEMINI_API_KEY_TERTIARY", "GEMINI_API_KEY_TERTIARY"),
        ("GEMINI_API_KEY_TERTIARY", "CITADEL_GEMINI_API_KEY_TERTIARY"),
    ],
    "nvidia": [
        ("CITADEL_NVIDIA_API_KEY", "NVIDIA_API_KEY"),
        ("NVIDIA_API_KEY", "CITADEL_NVIDIA_API_KEY"),
    ],
    "openrouter": [
        ("CITADEL_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        ("OPENROUTER_API_KEY", "CITADEL_OPENROUTER_API_KEY"),
    ],
    "cloudflare": [
        ("CITADEL_CLOUDFLARE_SCOPED_TOKEN", "CLOUDFLARE_SCOPED_TOKEN"),
        ("CITADEL_CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_TOKEN"),
        ("CLOUDFLARE_API_TOKEN", "CITADEL_CLOUDFLARE_API_TOKEN"),
    ],
    "cloudflare_account": [
        ("CITADEL_CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID"),
        ("CLOUDFLARE_ACCOUNT_ID", "CITADEL_CLOUDFLARE_ACCOUNT_ID"),
    ],
    "cloudflare_email": [
        ("CITADEL_CLOUDFLARE_EMAIL", "CLOUDFLARE_EMAIL"),
        ("CLOUDFLARE_EMAIL", "CITADEL_CLOUDFLARE_EMAIL"),
    ],
    "experiential": [
        ("CITADEL_EXPERIENTIAL_API_KEY", "EXPERIENTIAL_API_KEY"),
        ("EXPERIENTIAL_API_KEY", "CITADEL_EXPERIENTIAL_API_KEY"),
        ("EXPLABS_API_KEY", "CITADEL_EXPERIENTIAL_API_KEY"),
    ],
}

# Cache secrets in memory during execution to avoid repeated keychain lookups
_SECRETS_CACHE: Dict[str, Optional[str]] = {}


def resolve_secret(service_key: str) -> Tuple[Optional[str], str]:
    """Retrieve secret from environment or macOS Keychain with provenance tracking.
    
    Returns:
        (secret_value_or_none, provenance_source)
    """
    if service_key in _SECRETS_CACHE and _SECRETS_CACHE[service_key]:
        return _SECRETS_CACHE[service_key], "CACHE"

    mappings = PROVIDER_SECRET_MAP.get(service_key.lower(), [(service_key, service_key)])

    # 1. Environment lookup
    for _, env_var in mappings:
        val = os.getenv(env_var)
        if val and len(val.strip()) > 5:
            clean_val = val.strip()
            _SECRETS_CACHE[service_key] = clean_val
            return clean_val, f"ENV:{env_var}"

    # 2. macOS Keychain lookup
    user_name = os.getenv("USER") or "ayushmudgal"
    for kc_service, _ in mappings:
        for cmd in (
            ["security", "find-generic-password", "-a", "citadel", "-s", kc_service, "-w"],
            ["security", "find-generic-password", "-a", user_name, "-s", kc_service, "-w"],
            ["security", "find-generic-password", "-s", kc_service, "-w"],
        ):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0 and len(res.stdout.strip()) > 5:
                    clean_val = res.stdout.strip()
                    _SECRETS_CACHE[service_key] = clean_val
                    return clean_val, f"KEYCHAIN:{kc_service}"
            except Exception:
                pass

    return None, "UNCONFIGURED"


def get_secret(service_key: str) -> Optional[str]:
    """Retrieve secret string without exposing source."""
    val, _ = resolve_secret(service_key)
    return val


def get_secret_status(service_key: str) -> Dict[str, Any]:
    """Return presence status and provenance without leaking secret value or length."""
    val, source = resolve_secret(service_key)
    return {
        "configured": bool(val),
        "source": source,
    }


def safe_key_fingerprint(key: Optional[str]) -> str:
    """Return non-sensitive prefix/suffix fingerprint of credential for telemetry audit."""
    if not key or not isinstance(key, str):
        return "[UNCONFIGURED]"
    clean = key.strip()
    if len(clean) < 14:
        return "[MASKED_SHORT_KEY]"
    return f"{clean[:7]}...{clean[-6:]}"


def redact_text(text: Any, additional_secrets: Optional[List[str]] = None) -> str:
    """Robustly redact API keys, tokens, and authorization strings from logs/telemetry."""
    if text is None:
        return ""
    rendered = str(text)

    # Redact cached secrets
    for cached in _SECRETS_CACHE.values():
        if cached and len(cached) > 5:
            rendered = rendered.replace(cached, "[REDACTED]")

    if additional_secrets:
        for s in additional_secrets:
            if s and len(s) > 5:
                rendered = rendered.replace(s, "[REDACTED]")

    # Consume the complete authorization scheme and credential, not just Bearer.
    rendered = re.sub(
        r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(?:Bearer|Basic)\s+[^\s'\",}]+",
        r"\1[REDACTED]", rendered,
    )
    # Generic patterns
    rendered = re.sub(r"gsk_[0-9A-Za-z]{20,}", "[REDACTED_GROQ]", rendered)
    rendered = re.sub(r"nvapi-[0-9A-Za-z_\-]{20,}", "[REDACTED_NVIDIA]", rendered)
    rendered = re.sub(r"sk-or-v1-[0-9A-Za-z]{20,}", "[REDACTED_OPENROUTER]", rendered)
    rendered = re.sub(r"cfk_[0-9A-Za-z]{20,}", "[REDACTED_CLOUDFLARE]", rendered)
    rendered = re.sub(r"xpl_[0-9A-Za-z_\-]{20,}", "[REDACTED_EXPERIENTIAL]", rendered)
    rendered = re.sub(r"AQ\.[0-9A-Za-z_\-]{20,}", "[REDACTED_GEMINI]", rendered)
    rendered = re.sub(r"AIza[0-9A-Za-z\-_]{35}", "[REDACTED_GEMINI]", rendered)
    rendered = re.sub(
        r"(?i)(key|token|authorization|x-goog-api-key|x-auth-key)\s*[:=]\s*['\"]?[0-9A-Za-z\-_.]+['\"]?",
        r"\1=[REDACTED]",
        rendered,
    )
    return rendered


def create_strict_ssl_context() -> Any:
    """Create a strictly verified SSL/TLS context.
    
    Ensures check_hostname=True and verify_mode=CERT_REQUIRED.
    Fails closed with RuntimeError if valid CA certificates cannot be loaded.
    NEVER sets check_hostname=False or verify_mode=CERT_NONE.
    """
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception as e:
        logger.warning("certifi bundle failed, attempting system CA: %s", e)
        ctx = ssl.create_default_context()

    if not ctx.check_hostname or ctx.verify_mode != ssl.CERT_REQUIRED:
        raise RuntimeError("TLS_CONFIGURATION_ERROR: Secure certificate verification cannot be guaranteed.")
    return ctx
