"""Cognitive Quota Governor (Phase-1.1 Truth Repair).

Learns real provider quotas from live response headers:
- x-ratelimit-limit-requests
- x-ratelimit-limit-tokens
- x-ratelimit-remaining-requests
- x-ratelimit-remaining-tokens
- x-ratelimit-reset-requests
- x-ratelimit-reset-tokens
- retry-after

Maintains BOTH:
1. PROVIDER LEVEL: GROQ (shared infrastructure)
2. MODEL LEVEL:
   - openai/gpt-oss-120b
   - qwen/qwen3.8-27b
3. GEMINI: Runtime ledger & error metadata

Calculates dynamic TARGET BURN RATE across remaining Indian market seconds (09:15 - 15:30 IST).
NO hardcoded fictitious daily limits (30k, 5M, etc.). Limits remain UNKNOWN until observed from headers.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MARKET_OPEN_SECONDS = 9 * 3600 + 15 * 60    # 09:15 IST (33,300)
MARKET_CLOSE_SECONDS = 15 * 3600 + 30 * 60  # 15:30 IST (55,800)
TOTAL_MARKET_SECONDS = 22500


def _reset_deadline(value: Any, observed_at: float) -> Optional[float]:
    """Parse observed duration headers only; unknown formats never refill quota."""
    text = str(value).strip()
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", text)
    if not parts or "".join(number + unit for number, unit in parts) != text:
        return None
    seconds = sum(float(number) * {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
                  for number, unit in parts)
    return observed_at + seconds if math.isfinite(seconds) else None


def _retry_deadline(value: Any, observed_at: float) -> Optional[float]:
    try:
        seconds = float(value)
        return observed_at + max(0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(str(value))
            return date.timestamp() if date.tzinfo is not None else None
        except (ValueError, TypeError, OverflowError):
            return None


@dataclass
class ObservedQuotaState:
    entity_key: str
    model_name: str
    provider_name: str
    mode: str = "BOOTSTRAP_SAFE_MODE"  # BOOTSTRAP_SAFE_MODE until real headers arrive, then OBSERVED_PROVIDER_LIMITS
    # Real observed limits from provider response headers (Strictly None until observed)
    limit_requests: Optional[int] = None
    remaining_requests: Optional[int] = None
    limit_tokens: Optional[int] = None
    remaining_tokens: Optional[int] = None
    reset_requests: Optional[str] = None
    reset_tokens: Optional[str] = None
    reset_requests_at: Optional[float] = None
    reset_tokens_at: Optional[float] = None
    retry_after_until: float = 0.0
    raw_headers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Runtime usage counters
    requests_made: int = 0
    tokens_consumed: int = 0
    consecutive_429_count: int = 0
    last_http_status: Optional[int] = None  # MUST default to None, NOT 200
    last_call_timestamp: float = 0.0
    last_latency_ms: float = 0.0
    avg_tokens_per_call: int = 800

    def is_blocked(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now < self.retry_after_until

    def expire_observations(self, now: float) -> None:
        # A reset invalidates the old observation, not proof of a full refill.
        # Lifetime counters and original header evidence remain intact.
        for kind in ("requests", "tokens"):
            deadline = getattr(self, f"reset_{kind}_at")
            if deadline is not None and now >= deadline:
                setattr(self, f"remaining_{kind}", None)
                setattr(self, f"reset_{kind}_at", None)

    def has_observed_headers(self) -> bool:
        return self.mode == "OBSERVED_PROVIDER_LIMITS" and self.remaining_tokens is not None

    def safe_pacing_tokens(self) -> int:
        """Internal conservative pacing budget; NOT claimed as real provider quota."""
        if self.remaining_tokens is not None:
            return max(0, self.remaining_tokens)
        # Conservative bootstrap floor for rate limiter pacing only
        return max(0, 50000 - self.tokens_consumed)

    def safe_pacing_requests(self) -> int:
        """Internal conservative pacing request budget; NOT claimed as real provider quota."""
        if self.remaining_requests is not None:
            return max(0, self.remaining_requests)
        return max(0, 100 - self.requests_made)


class CognitiveQuotaGovernor:
    """Header-learning multi-provider and model-level quota governor."""

    def __init__(self) -> None:
        self.provider_states: Dict[str, ObservedQuotaState] = {
            "groq": ObservedQuotaState(
                entity_key="groq",
                model_name="shared-groq-infrastructure",
                provider_name="groq",
                avg_tokens_per_call=800,
            ),
            "google": ObservedQuotaState(
                entity_key="google",
                model_name="gemini-3.8-flash",
                provider_name="google",
                avg_tokens_per_call=800,
            ),
            "gemini_primary": ObservedQuotaState(
                entity_key="gemini_primary",
                model_name="gemini-3.8-flash",
                provider_name="gemini_primary",
                avg_tokens_per_call=800,
            ),
            "gemini_secondary": ObservedQuotaState(
                entity_key="gemini_secondary",
                model_name="gemini-3.8-flash",
                provider_name="gemini_secondary",
                avg_tokens_per_call=800,
            ),
            "gemini_tertiary": ObservedQuotaState(
                entity_key="gemini_tertiary",
                model_name="gemini-3.8-flash",
                provider_name="gemini_tertiary",
                avg_tokens_per_call=800,
            ),
        }
        self.model_states: Dict[str, ObservedQuotaState] = {
            "qwen": ObservedQuotaState(
                entity_key="qwen",
                model_name="qwen/qwen3.8-27b",
                provider_name="groq",
                avg_tokens_per_call=250,
            ),
            "gpt_oss": ObservedQuotaState(
                entity_key="gpt_oss",
                model_name="openai/gpt-oss-120b",
                provider_name="groq",
                avg_tokens_per_call=1200,
            ),
            "gemini": ObservedQuotaState(
                entity_key="gemini",
                model_name="gemini-3.8-flash",
                provider_name="google",
                avg_tokens_per_call=800,
            ),
            "gemini_primary": ObservedQuotaState(
                entity_key="gemini_primary",
                model_name="gemini-3.8-flash",
                provider_name="gemini_primary",
                avg_tokens_per_call=800,
            ),
            "gemini_secondary": ObservedQuotaState(
                entity_key="gemini_secondary",
                model_name="gemini-3.8-flash",
                provider_name="gemini_secondary",
                avg_tokens_per_call=800,
            ),
            "gemini_tertiary": ObservedQuotaState(
                entity_key="gemini_tertiary",
                model_name="gemini-3.8-flash",
                provider_name="gemini_tertiary",
                avg_tokens_per_call=800,
            ),
        }

    def register_model_binding(self, model_key: str, provider: str, model_name: str) -> None:
        """Add an explicit role binding to this governor, with no claimed quota.

        Never replace a live binding or reset an existing provider's budget.
        """
        existing = self.model_states.get(model_key)
        if existing:
            if (existing.provider_name, existing.model_name) != (provider, model_name):
                raise ValueError("QUOTA_BINDING_IDENTITY_CONFLICT")
            return
        self.provider_states.setdefault(provider, ObservedQuotaState(
            entity_key=provider, model_name=f"shared-{provider}-infrastructure", provider_name=provider))
        self.model_states[model_key] = ObservedQuotaState(
            entity_key=model_key, model_name=model_name, provider_name=provider)

    def update_from_groq_headers(
        self,
        model_key: str,
        rate_headers: Dict[str, Any],
        http_status: Optional[int] = 200,
        latency_ms: float = 0.0,
        *,
        observed_at: Optional[float] = None,
    ) -> None:
        """Learns and records real provider limits directly from Groq response headers."""
        now = time.time() if observed_at is None else observed_at
        model = self.model_states.get(model_key)
        provider = model.provider_name if model else "groq"
        def first(*keys):
            return next((rate_headers[key] for key in keys if rate_headers.get(key) is not None), None)
        for target in (self.provider_states.get(provider), model):
            if not target:
                continue
            target.last_http_status = http_status
            target.last_call_timestamp = now
            target.last_latency_ms = latency_ms

            has_real_limit = False
            for rk, rv in rate_headers.items():
                if rv is not None:
                    target.raw_headers[rk] = {
                        "raw_header": rk,
                        "value": str(rv),
                        "scope_interpretation": "PROVIDER_REPORTED_WINDOW_UNKNOWN",
                        "observed_at": now,
                    }

            limit_req = rate_headers.get("limit_requests") or rate_headers.get("x-ratelimit-limit-requests")
            rem_req = first("remaining_requests", "x-ratelimit-remaining-requests")
            limit_tok = rate_headers.get("limit_tokens") or rate_headers.get("x-ratelimit-limit-tokens")
            rem_tok = first("remaining_tokens", "x-ratelimit-remaining-tokens")
            reset_req = rate_headers.get("reset_requests") or rate_headers.get("x-ratelimit-reset-requests")
            reset_tok = rate_headers.get("reset_tokens") or rate_headers.get("x-ratelimit-reset-tokens")

            if limit_req is not None:
                target.limit_requests = int(limit_req)
                has_real_limit = True
            if rem_req is not None:
                target.remaining_requests = int(rem_req)
                target.reset_requests_at = _reset_deadline(reset_req, now)
                has_real_limit = True
            if limit_tok is not None:
                target.limit_tokens = int(limit_tok)
                has_real_limit = True
            if rem_tok is not None:
                target.remaining_tokens = int(rem_tok)
                target.reset_tokens_at = _reset_deadline(reset_tok, now)
                has_real_limit = True
            if reset_req is not None:
                target.reset_requests = str(reset_req)
            if reset_tok is not None:
                target.reset_tokens = str(reset_tok)

            if has_real_limit:
                target.mode = "OBSERVED_PROVIDER_LIMITS"

            retry_sec = first("retry_after_seconds", "retry-after")
            deadline = _retry_deadline(retry_sec, now)
            if deadline is not None:
                target.retry_after_until = max(target.retry_after_until, deadline)
                target.consecutive_429_count += 1
            elif http_status == 200:
                target.consecutive_429_count = 0

    def update_from_experiential_telemetry(
        self,
        model_key: str,
        rate_headers: Dict[str, Any],
        http_status: Optional[int] = 200,
        latency_ms: float = 0.0,
        cost_micro_usd: int = 0,
        *,
        observed_at: Optional[float] = None,
    ) -> None:
        """Records Experiential Labs telemetry, credit usage, and status in quota state."""
        self.update_from_groq_headers(model_key, rate_headers, http_status, latency_ms, observed_at=observed_at)
        model = self.model_states.get(model_key)
        if model and cost_micro_usd > 0:
            model.raw_headers["cost_violation"] = {
                "raw_header": "cost_micro_usd",
                "value": str(cost_micro_usd),
                "scope_interpretation": "NON_ZERO_COST_ON_PROMOTIONAL_MODEL",
                "observed_at": time.time() if observed_at is None else observed_at,
            }

    def get_remaining_market_seconds(self, now_utc: Optional[datetime] = None) -> int:
        """Computes remaining seconds in the Indian trading session (IST = UTC + 5:30)."""
        now_utc = now_utc or datetime.now(timezone.utc)
        ist_seconds = (now_utc.hour * 3600 + now_utc.minute * 60 + now_utc.second + 19800) % 86400
        if ist_seconds < MARKET_OPEN_SECONDS:
            return TOTAL_MARKET_SECONDS
        if ist_seconds > MARKET_CLOSE_SECONDS:
            return 60
        return max(60, MARKET_CLOSE_SECONDS - ist_seconds)

    def compute_target_burn_rate(self, model_key: str, now_utc: Optional[datetime] = None) -> Optional[float]:
        """Calculates dynamic target burn rate (tokens/second) across remaining market session.

        Returns None (UNKNOWN) if headers have not yet been observed.
        """
        st = self.model_states.get(model_key)
        if st:
            st.expire_observations(now_utc.timestamp() if now_utc is not None else time.time())
        if not st or st.remaining_tokens is None:
            return None
        rem_sec = self.get_remaining_market_seconds(now_utc)
        return st.remaining_tokens / rem_sec

    def compute_recommended_interval(self, model_key: str, now_utc: Optional[datetime] = None) -> float:
        """Computes recommended pacing interval (seconds) between model invocations."""
        st = self.model_states.get(model_key)
        if not st:
            return 10.0
        burn_rate = self.compute_target_burn_rate(model_key, now_utc)
        if burn_rate is None or burn_rate <= 0:
            # Conservative bootstrap pacing interval
            if model_key == "qwen":
                return 4.0
            elif model_key == "gpt_oss":
                return 10.0
            else:
                return 30.0
        interval = st.avg_tokens_per_call / burn_rate
        if model_key == "qwen":
            return max(3.0, min(interval, 30.0))
        elif model_key == "gpt_oss":
            return max(8.0, min(interval, 60.0))
        else:
            return max(15.0, min(interval, 180.0))

    def can_invoke(self, model_key: str, now: Optional[float] = None) -> bool:
        """Fail-closed check on whether a model is safe to invoke."""
        st = self.model_states.get(model_key)
        if not st:
            return False
        now = time.time() if now is None else now
        st.expire_observations(now)
        # Check model and shared provider blockage
        if st.is_blocked(now):
            return False
        shared_provider = self.provider_states.get(st.provider_name)
        if shared_provider:
            shared_provider.expire_observations(now)
            if shared_provider.is_blocked(now):
                return False
            if shared_provider.safe_pacing_tokens() <= 0:
                return False
            # Qwen and GPT share Groq infrastructure.  Enforce the already
            # established request budget at that shared provider boundary too;
            # otherwise each model can independently consume the same allowance.
            if shared_provider.safe_pacing_requests() <= 2:
                return False
        if st.safe_pacing_requests() <= 2:
            return False
        if st.safe_pacing_tokens() <= 0:
            return False
        return True

    def record_call_success(
        self,
        model_key: str,
        tokens_consumed: int,
        latency_ms: float,
        http_status: int = 200,
    ) -> None:
        """Updates internal counters upon successful call."""
        now = time.time()
        model = self.model_states.get(model_key)
        for target in (model, self.provider_states.get(model.provider_name) if model else None):
            if target:
                target.requests_made += 1
                target.tokens_consumed += tokens_consumed
                target.last_http_status = http_status
                target.last_call_timestamp = now
                target.last_latency_ms = latency_ms
                target.consecutive_429_count = 0
                if target.avg_tokens_per_call == 0:
                    target.avg_tokens_per_call = tokens_consumed
                else:
                    target.avg_tokens_per_call = int(target.avg_tokens_per_call * 0.85 + tokens_consumed * 0.15)

    def record_rate_limit(
        self,
        model_key: str,
        retry_after_seconds: float = 30.0,
        http_status: int = 429,
    ) -> None:
        """Records 429 rate limit backoff honoring retry-after without retry storms."""
        now = time.time()
        until = now + max(5.0, retry_after_seconds)
        st = self.model_states.get(model_key)
        if st:
            st.retry_after_until = max(st.retry_after_until, until)
            st.last_http_status = http_status
            st.consecutive_429_count += 1
        prov = self.provider_states.get(st.provider_name) if st else None
        if prov:
            prov.retry_after_until = max(prov.retry_after_until, until)
            prov.last_http_status = http_status
            prov.consecutive_429_count += 1

    def get_provider_status_summary(self) -> Dict[str, Any]:
        """Provides status summary for backend telemetry and dashboard rendering."""
        for state in (*self.provider_states.values(), *self.model_states.values()):
            state.expire_observations(time.time())
        return {
            "providers": {
                k: {
                    "provider": v.provider_name,
                    "mode": v.mode,
                    "limit_requests": v.limit_requests,
                    "remaining_requests": v.remaining_requests,
                    "limit_tokens": v.limit_tokens,
                    "remaining_tokens": v.remaining_tokens,
                    "reset_tokens": v.reset_tokens,
                    "is_blocked": v.is_blocked(),
                    "last_http_status": v.last_http_status,
                    "raw_headers": v.raw_headers,
                }
                for k, v in self.provider_states.items()
            },
            "models": {
                k: {
                    "model_id": v.model_name,
                    "provider": v.provider_name,
                    "mode": v.mode,
                    "remaining_tokens": v.remaining_tokens if v.remaining_tokens is not None else "UNKNOWN",
                    "burn_rate": round(self.compute_target_burn_rate(k), 2) if self.compute_target_burn_rate(k) is not None else "UNKNOWN",
                    "recommended_interval_sec": round(self.compute_recommended_interval(k), 1),
                    "is_blocked": v.is_blocked(),
                    "last_latency_ms": round(v.last_latency_ms, 1) if v.last_latency_ms else "NOT_MEASURED",
                    "last_http_status": v.last_http_status,
                }
                for k, v in self.model_states.items()
            },
        }
