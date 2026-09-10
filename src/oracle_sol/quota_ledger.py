"""Durable Gemini Free-Tier Quota Ledger & Pacing Governor (P0 Final Runtime).

Manages scarce Google Gemini API rate limits with dynamic Pacific timezone reset boundary,
sustainable segment allocation (Afternoon + Following Morning Unused-Capacity Carryover),
elapsed-time pacing, manual reserve protection, token accounting, RPD circuit breaker,
and atomic disk persistence under Sol shadow root.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

PT_TZ = ZoneInfo("America/Los_Angeles")
IST_TZ = ZoneInfo("Asia/Kolkata")
UTC_TZ = timezone.utc

DEFAULT_OBSERVED_37_RPD_LIMIT = 20
DEFAULT_FOLLOWING_MORNING_RESERVE = 10


@dataclass
class ModelQuotaState:
    """Per-model rate limit, consumption, token, and circuit breaker state."""
    provider_model: str
    credential_identity_safe_hash: str
    provider_project_identity_safe_hash: str
    provider_day_pt: str
    observed_rpd_limit: Optional[int] = None
    quota_status: str = "UNKNOWN"
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    afternoon_requests_spent: int = 0
    morning_requests_spent: int = 0
    last_request_utc: Optional[str] = None
    last_success_utc: Optional[str] = None
    last_error_category: Optional[str] = None
    rpd_blocked_until_utc: Optional[str] = None
    cooldown_until_utc: Optional[str] = None
    in_flight: bool = False
    provider_known_exhausted: bool = False
    total_tokens_used: int = 0
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    cached_tokens: int = 0
    thoughts_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GeminiQuotaLedger:
    """Thread-safe, process-level durable quota ledger and pacing governor."""

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        observed_rpd_limit: int = DEFAULT_OBSERVED_37_RPD_LIMIT,
        morning_reserve: int = DEFAULT_FOLLOWING_MORNING_RESERVE,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        self.storage_dir = Path(storage_dir or "data/sol_shadow")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.storage_dir / "gemini_quota_ledger.json"
        self.default_37_rpd_limit = observed_rpd_limit
        self.morning_reserve = morning_reserve
        self._lock = threading.RLock()
        self._models: Dict[str, ModelQuotaState] = {}
        self._api_key = api_key
        self._project_id = project_id or os.getenv("CITADEL_GEMINI_PROJECT_ID")
        self._credential_hash = self._compute_safe_hash(api_key)
        self._project_hash = self._compute_safe_hash(self._project_id) if self._project_id else "UNKNOWN"

        if not self._hydrate_from_disk():
            self._seed_initial_state()

    @staticmethod
    def _compute_safe_hash(value: Optional[str]) -> str:
        if not value or not str(value).strip():
            return "UNCONFIGURED"
        return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:12]

    def set_credentials(self, api_key: Optional[str], project_id: Optional[str] = None) -> None:
        with self._lock:
            self._api_key = api_key
            if project_id:
                self._project_id = project_id
            self._credential_hash = self._compute_safe_hash(api_key)
            self._project_hash = self._compute_safe_hash(self._project_id) if self._project_id else "UNKNOWN"
            for state in self._models.values():
                state.credential_identity_safe_hash = self._credential_hash
                state.provider_project_identity_safe_hash = self._project_hash
            self._persist_to_disk()

    def _seed_initial_state(self) -> None:
        """Seed initial ledger models without hardcoded historical dates or fabricated counters."""
        now = datetime.now(UTC_TZ)
        now_pt = now.astimezone(PT_TZ)
        today_pt = now_pt.strftime("%Y-%m-%d")

        # Gemini 3.7 Flash: known observed limit = 20
        # Fresh unpersisted ledger starts healthy with 0 local attempts.
        # Active provider blocks are learned and preserved strictly via durable persistence / provider responses.
        state_38 = ModelQuotaState(
            provider_model="gemini-3.8-flash",
            credential_identity_safe_hash=self._credential_hash,
            provider_project_identity_safe_hash=self._project_hash,
            provider_day_pt=today_pt,
            observed_rpd_limit=self.default_37_rpd_limit,
            quota_status="HEALTHY",
            requests_attempted=0,
            requests_succeeded=0,
            requests_failed=0,
            afternoon_requests_spent=0,
            morning_requests_spent=0,
            last_error_category=None,
            rpd_blocked_until_utc=None,
            provider_known_exhausted=False,
        )
        self._models["gemini-3.8-flash"] = state_38
        self._models["gemini-3.7-flash"] = state_38

        # Gemini 3.6 Flash: quota is strictly UNKNOWN until proven for this project
        state_36 = ModelQuotaState(
            provider_model="gemini-3.6-flash",
            credential_identity_safe_hash=self._credential_hash,
            provider_project_identity_safe_hash=self._project_hash,
            provider_day_pt=today_pt,
            observed_rpd_limit=None,
            quota_status="UNKNOWN",
            requests_attempted=0,
            requests_succeeded=0,
            requests_failed=0,
            afternoon_requests_spent=0,
            morning_requests_spent=0,
            rpd_blocked_until_utc=None,
            provider_known_exhausted=False,
        )
        self._models["gemini-3.6-flash"] = state_36

        self._persist_to_disk()

    def _hydrate_from_disk(self) -> bool:
        """Load persisted quota ledger state from disk."""
        if not self.ledger_file.exists():
            return False
        with self._lock:
            try:
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    models_data = data.get("models", {})
                    for model_name, m_dict in models_data.items():
                        if isinstance(m_dict, dict):
                            obs_limit = m_dict.get("observed_rpd_limit")
                            if obs_limit is not None and str(obs_limit).isdigit():
                                obs_limit = int(obs_limit)
                            else:
                                obs_limit = self.default_37_rpd_limit if model_name == "gemini-3.7-flash" else None

                            self._models[model_name] = ModelQuotaState(
                                provider_model=m_dict.get("provider_model", model_name),
                                credential_identity_safe_hash=m_dict.get("credential_identity_safe_hash", self._credential_hash),
                                provider_project_identity_safe_hash=m_dict.get("provider_project_identity_safe_hash", self._project_hash),
                                provider_day_pt=m_dict.get("provider_day_pt", ""),
                                observed_rpd_limit=obs_limit,
                                quota_status=m_dict.get("quota_status", "UNKNOWN"),
                                requests_attempted=int(m_dict.get("requests_attempted", 0)),
                                requests_succeeded=int(m_dict.get("requests_succeeded", 0)),
                                requests_failed=int(m_dict.get("requests_failed", 0)),
                                afternoon_requests_spent=int(m_dict.get("afternoon_requests_spent", 0)),
                                morning_requests_spent=int(m_dict.get("morning_requests_spent", 0)),
                                last_request_utc=m_dict.get("last_request_utc"),
                                last_success_utc=m_dict.get("last_success_utc"),
                                last_error_category=m_dict.get("last_error_category"),
                                rpd_blocked_until_utc=m_dict.get("rpd_blocked_until_utc"),
                                cooldown_until_utc=m_dict.get("cooldown_until_utc"),
                                in_flight=False,
                                provider_known_exhausted=bool(m_dict.get("provider_known_exhausted", False)),
                                total_tokens_used=int(m_dict.get("total_tokens_used", 0)),
                                prompt_tokens=int(m_dict.get("prompt_tokens", 0)),
                                candidates_tokens=int(m_dict.get("candidates_tokens", 0)),
                                cached_tokens=int(m_dict.get("cached_tokens", 0)),
                                thoughts_tokens=int(m_dict.get("thoughts_tokens", 0)),
                            )
                    return bool(self._models)
                return False
            except Exception:
                return False

    def _persist_to_disk(self) -> None:
        """Atomically persist quota ledger state to disk."""
        payload = {
            "version": "1.2.0-quota-ledger",
            "updated_at_utc": datetime.now(UTC_TZ).isoformat(),
            "models": {k: v.to_dict() for k, v in self._models.items()},
        }
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.ledger_file.parent,
                prefix=f".{self.ledger_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                temp_path = Path(f.name)
                json.dump(payload, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.ledger_file)
            temp_path = None
            dir_fd = os.open(self.ledger_file.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def get_or_create_model_state(
        self, model: str, now_utc: Optional[datetime] = None
    ) -> Tuple[ModelQuotaState, bool]:
        """Get or initialize state for a model, rolling over if Pacific day changed."""
        now = now_utc or datetime.now(UTC_TZ)
        now_pt = now.astimezone(PT_TZ)
        today_pt = now_pt.strftime("%Y-%m-%d")

        with self._lock:
            state = self._models.get(model)
            if state is None:
                obs_limit = self.default_37_rpd_limit if model in ("gemini-3.7-flash", "gemini-3.8-flash") else None
                state = ModelQuotaState(
                    provider_model=model,
                    credential_identity_safe_hash=self._credential_hash,
                    provider_project_identity_safe_hash=self._project_hash,
                    provider_day_pt=today_pt,
                    observed_rpd_limit=obs_limit,
                    quota_status="HEALTHY" if model in ("gemini-3.7-flash", "gemini-3.8-flash") else "UNKNOWN",
                )
                self._models[model] = state
                self._persist_to_disk()
                return state, False

            # Check if Pacific date rolled over
            if state.provider_day_pt != today_pt:
                state.provider_day_pt = today_pt
                state.requests_attempted = 0
                state.requests_succeeded = 0
                state.requests_failed = 0
                state.afternoon_requests_spent = 0
                state.morning_requests_spent = 0
                state.rpd_blocked_until_utc = None
                state.cooldown_until_utc = None
                state.in_flight = False
                state.provider_known_exhausted = False
                state.quota_status = "HEALTHY" if model in ("gemini-3.7-flash", "gemini-3.8-flash") else state.quota_status
                state.total_tokens_used = 0
                state.prompt_tokens = 0
                state.candidates_tokens = 0
                state.cached_tokens = 0
                state.thoughts_tokens = 0
                self._persist_to_disk()
                return state, True

            return state, False

    def get_market_segment_info(
        self, now_utc: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Dynamically compute active market segment, reset boundaries, and elapsed times."""
        now = now_utc or datetime.now(UTC_TZ)
        now_ist = now.astimezone(IST_TZ)
        ist_date = now_ist.date()

        market_open_ist = datetime.combine(ist_date, dtime(9, 15), tzinfo=IST_TZ)
        market_close_ist = datetime.combine(ist_date, dtime(15, 30), tzinfo=IST_TZ)

        pt_midnight_today = datetime.combine(ist_date, dtime.min, tzinfo=PT_TZ)
        pt_midnight_today_ist = pt_midnight_today.astimezone(IST_TZ)
        pt_midnight_tomorrow = datetime.combine(ist_date + timedelta(days=1), dtime.min, tzinfo=PT_TZ)
        pt_midnight_tomorrow_ist = pt_midnight_tomorrow.astimezone(IST_TZ)

        is_weekday = now_ist.weekday() < 5
        is_market_hours = is_weekday and (market_open_ist <= now_ist < market_close_ist)

        if not is_market_hours:
            segment = "OFF_MARKET"
            next_reset_ist = pt_midnight_today_ist if now_ist < pt_midnight_today_ist else pt_midnight_tomorrow_ist
            next_reset_utc = next_reset_ist.astimezone(UTC_TZ)
            duration_seconds = 1.0
            elapsed_seconds = 0.0
        elif now_ist < pt_midnight_today_ist:
            segment = "MORNING"
            next_reset_ist = pt_midnight_today_ist
            next_reset_utc = next_reset_ist.astimezone(UTC_TZ)
            duration_seconds = max(1.0, (pt_midnight_today_ist - market_open_ist).total_seconds())
            elapsed_seconds = max(0.0, (now_ist - market_open_ist).total_seconds())
        else:
            segment = "AFTERNOON"
            next_reset_ist = pt_midnight_tomorrow_ist
            next_reset_utc = next_reset_ist.astimezone(UTC_TZ)
            duration_seconds = max(1.0, (market_close_ist - pt_midnight_today_ist).total_seconds())
            elapsed_seconds = max(0.0, (now_ist - pt_midnight_today_ist).total_seconds())

        provider_day_pt = now.astimezone(PT_TZ).strftime("%Y-%m-%d")

        return {
            "segment": segment,
            "is_market_hours": is_market_hours,
            "provider_day_pt": provider_day_pt,
            "next_reset_utc": next_reset_utc.isoformat(),
            "next_reset_ist": next_reset_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            "next_reset_ist_short": next_reset_ist.strftime("%H:%M:%S IST"),
            "segment_duration_seconds": duration_seconds,
            "elapsed_seconds": elapsed_seconds,
            "fraction_elapsed": min(1.0, max(0.0, elapsed_seconds / duration_seconds)),
        }

    def compute_segment_allocations(
        self, state: ModelQuotaState, segment_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Divide observed RPD sustainably between Afternoon and Following Morning with carryover."""
        if state.observed_rpd_limit is None:
            return {
                "total_limit": None,
                "morning_reserve": None,
                "afternoon_budget": None,
                "morning_budget": None,
                "segment_budget": None,
                "segment_spent": state.requests_attempted,
                "segment_remaining": None,
                "total_day_remaining": None,
            }

        total_limit = max(1, state.observed_rpd_limit)
        morning_reserve = min(total_limit, max(1, self.morning_reserve))
        afternoon_allowed_budget = max(0, total_limit - morning_reserve)

        total_spent = max(state.requests_attempted, state.afternoon_requests_spent + state.morning_requests_spent)
        total_day_remaining = max(0, total_limit - total_spent)

        current_segment = segment_info["segment"]
        if current_segment == "AFTERNOON":
            segment_budget = afternoon_allowed_budget
            spent = state.afternoon_requests_spent
            remaining = max(0, segment_budget - spent)
        elif current_segment == "MORNING":
            segment_budget = max(0, total_limit - state.afternoon_requests_spent)
            spent = state.morning_requests_spent
            remaining = max(0, segment_budget - spent)
        else:
            segment_budget = total_day_remaining
            spent = 0
            remaining = segment_budget

        return {
            "total_limit": total_limit,
            "morning_reserve": morning_reserve,
            "afternoon_budget": afternoon_allowed_budget,
            "morning_budget": max(0, total_limit - state.afternoon_requests_spent),
            "segment_budget": segment_budget,
            "segment_spent": spent,
            "segment_remaining": remaining,
            "total_day_remaining": total_day_remaining,
        }

    def is_rpd_blocked(
        self, model: str, now_utc: Optional[datetime] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check if model is currently blocked by the RPD circuit breaker."""
        now = now_utc or datetime.now(UTC_TZ)
        with self._lock:
            state, _ = self.get_or_create_model_state(model, now)
            if state.rpd_blocked_until_utc:
                try:
                    blocked_until = datetime.fromisoformat(state.rpd_blocked_until_utc)
                    if blocked_until.tzinfo is None:
                        blocked_until = blocked_until.replace(tzinfo=UTC_TZ)
                    if now < blocked_until:
                        return True, state.rpd_blocked_until_utc
                    else:
                        state.rpd_blocked_until_utc = None
                        state.provider_known_exhausted = False
                        state.quota_status = "HEALTHY" if model == "gemini-3.7-flash" else state.quota_status
                        self._persist_to_disk()
                except Exception:
                    state.rpd_blocked_until_utc = None

            if state.observed_rpd_limit is not None:
                total_spent = state.afternoon_requests_spent + state.morning_requests_spent
                if total_spent >= state.observed_rpd_limit or state.requests_attempted >= state.observed_rpd_limit:
                    seg_info = self.get_market_segment_info(now)
                    state.rpd_blocked_until_utc = seg_info["next_reset_utc"]
                    state.provider_known_exhausted = True
                    state.quota_status = "QUOTA_LIMIT_RPD"
                    self._persist_to_disk()
                    return True, state.rpd_blocked_until_utc

            return False, None

    def check_eligibility(
        self,
        model: str,
        is_manual: bool = False,
        use_reserved_quota: bool = False,
        new_events_count: int = 0,
        now_utc: Optional[datetime] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Comprehensive quota governor check evaluating all eligibility criteria."""
        now = now_utc or datetime.now(UTC_TZ)

        with self._lock:
            state, _ = self.get_or_create_model_state(model, now)
            seg_info = self.get_market_segment_info(now)
            allocs = self.compute_segment_allocations(state, seg_info)

            telemetry = {
                "model": model,
                "provider_day_pt": state.provider_day_pt,
                "current_segment": seg_info["segment"],
                "segment_budget": allocs["segment_budget"],
                "segment_spent": allocs["segment_spent"],
                "segment_remaining": allocs["segment_remaining"],
                "total_day_remaining": allocs["total_day_remaining"],
                "observed_rpd_limit": state.observed_rpd_limit,
                "morning_reserve": allocs["morning_reserve"],
                "next_reset_ist": seg_info["next_reset_ist"],
                "next_reset_utc": seg_info["next_reset_utc"],
                "in_flight": state.in_flight,
                "new_events_count": new_events_count,
            }

            # 1. Check Model Quota Provenance
            if state.observed_rpd_limit is None and not is_manual:
                return False, "MODEL_QUOTA_UNPROVEN", telemetry

            # 2. Check RPD Blocked
            is_blocked, blocked_until = self.is_rpd_blocked(model, now)
            if is_blocked:
                telemetry["rpd_blocked_until_utc"] = blocked_until
                return False, "QUOTA_LIMIT_RPD", telemetry

            # 3. Check In-Flight
            if state.in_flight:
                return False, "REQUEST_IN_FLIGHT", telemetry

            # 4. Check Cooldown (RPM/TPM Retry-After)
            if state.cooldown_until_utc:
                try:
                    cd_until = datetime.fromisoformat(state.cooldown_until_utc)
                    if cd_until.tzinfo is None:
                        cd_until = cd_until.replace(tzinfo=UTC_TZ)
                    if now < cd_until:
                        telemetry["cooldown_until_utc"] = state.cooldown_until_utc
                        return False, "RETRY_DEFERRED", telemetry
                    else:
                        state.cooldown_until_utc = None
                except Exception:
                    state.cooldown_until_utc = None

            # 5. Check Total Day Remaining (if observed limit is known)
            if allocs["total_day_remaining"] is not None and allocs["total_day_remaining"] <= 0:
                state.rpd_blocked_until_utc = seg_info["next_reset_utc"]
                state.provider_known_exhausted = True
                self._persist_to_disk()
                return False, "QUOTA_LIMIT_RPD", telemetry

            # 6. Check Market Session Eligibility (unless manual override)
            if not is_manual and not seg_info["is_market_hours"]:
                return False, "OFF_MARKET_SESSION", telemetry

            # 7. Check New Events (unless manual override)
            if not is_manual and new_events_count == 0:
                return False, "NO_NEW_EVENTS", telemetry

            # 8. Check Segment Budget / Reserve Protection
            if allocs["segment_remaining"] is not None:
                if seg_info["segment"] == "AFTERNOON":
                    if allocs["segment_remaining"] <= 0:
                        if is_manual and not use_reserved_quota:
                            return False, "RESERVED_QUOTA_PROTECTED", telemetry
                        elif not is_manual:
                            return False, "SEGMENT_BUDGET_EXHAUSTED", telemetry
                elif seg_info["segment"] == "MORNING":
                    if allocs["segment_remaining"] <= 0:
                        return False, "QUOTA_LIMIT_RPD", telemetry

            # 9. Pacing Governor: Check elapsed segment time vs allowed budget
            if not is_manual and seg_info["segment"] in {"AFTERNOON", "MORNING"} and allocs["segment_budget"] is not None:
                fraction = seg_info["fraction_elapsed"]
                seg_budget = allocs["segment_budget"]
                allowed_spent = min(seg_budget, math.floor(fraction * seg_budget) + 1)
                if allocs["segment_spent"] >= allowed_spent:
                    telemetry["pacing_allowed_spent"] = allowed_spent
                    return False, "PACING_GOVERNOR_HOLD", telemetry

            return True, "ELIGIBLE", telemetry

    def record_request_start(
        self, model: str, is_manual: bool = False, now_utc: Optional[datetime] = None
    ) -> bool:
        """Mark reasoning request started ONLY right before sending real Google network call."""
        now = now_utc or datetime.now(UTC_TZ)
        with self._lock:
            state, _ = self.get_or_create_model_state(model, now)
            seg_info = self.get_market_segment_info(now)

            state.in_flight = True
            state.requests_attempted += 1
            state.last_request_utc = now.isoformat()

            if seg_info["segment"] == "AFTERNOON":
                state.afternoon_requests_spent += 1
            elif seg_info["segment"] == "MORNING":
                state.morning_requests_spent += 1

            self._persist_to_disk()
            return True

    def record_token_usage(
        self,
        model: str,
        prompt_tokens: int = 0,
        candidates_tokens: int = 0,
        cached_tokens: int = 0,
        thoughts_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """Record token usage metadata from provider response."""
        with self._lock:
            state, _ = self.get_or_create_model_state(model)
            state.prompt_tokens += max(0, int(prompt_tokens))
            state.candidates_tokens += max(0, int(candidates_tokens))
            state.cached_tokens += max(0, int(cached_tokens))
            state.thoughts_tokens += max(0, int(thoughts_tokens))
            computed_total = total_tokens or (prompt_tokens + candidates_tokens)
            state.total_tokens_used += max(0, int(computed_total))
            self._persist_to_disk()

    def record_request_result(
        self,
        model: str,
        status: str,
        error_category: Optional[str] = None,
        quota_info: Optional[Dict[str, Any]] = None,
        retry_after_seconds: Optional[float] = None,
        now_utc: Optional[datetime] = None,
    ) -> None:
        """Record provider response result against the exact target model."""
        now = now_utc or datetime.now(UTC_TZ)
        with self._lock:
            state, _ = self.get_or_create_model_state(model, now)
            state.in_flight = False
            state.last_error_category = error_category or status

            if status == "SUCCESS":
                state.requests_succeeded += 1
                state.last_success_utc = now.isoformat()
                state.quota_status = "HEALTHY"
            else:
                state.requests_failed += 1
                state.quota_status = error_category or status

            if quota_info:
                limit_val = quota_info.get("quota_limit")
                if limit_val is not None and str(limit_val).isdigit() and int(limit_val) > 0:
                    state.observed_rpd_limit = int(limit_val)

            # RPD Circuit Breaker Trip
            if error_category == "QUOTA_LIMIT_RPD" or status == "QUOTA_LIMIT_RPD":
                seg_info = self.get_market_segment_info(now)
                state.rpd_blocked_until_utc = seg_info["next_reset_utc"]
                state.provider_known_exhausted = True
                state.quota_status = "QUOTA_LIMIT_RPD"

            # RPM / TPM Cooldown
            if retry_after_seconds and retry_after_seconds > 0:
                state.cooldown_until_utc = (now + timedelta(seconds=float(retry_after_seconds))).isoformat()

            self._persist_to_disk()

    def get_telemetry(
        self, model: str, now_utc: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Return rich, truthful quota, token, and pacing telemetry."""
        now = now_utc or datetime.now(UTC_TZ)
        with self._lock:
            state, _ = self.get_or_create_model_state(model, now)
            seg_info = self.get_market_segment_info(now)
            allocs = self.compute_segment_allocations(state, seg_info)
            is_blocked, blocked_until = self.is_rpd_blocked(model, now)
            provider_observed_state = "QUOTA_LIMIT_RPD" if is_blocked else state.quota_status

            return {
                "provider_model": model,
                "provider_observed_state": provider_observed_state,
                "local_requests_attempted": state.requests_attempted,
                "local_requests_succeeded": state.requests_succeeded,
                "local_requests_failed": state.requests_failed,
                "fake_historical_counters_present": False,
                "credential_identity_safe_hash": state.credential_identity_safe_hash,
                "provider_project_identity_safe_hash": state.provider_project_identity_safe_hash,
                "provider_day_pt": state.provider_day_pt,
                "observed_rpd_limit": state.observed_rpd_limit,
                "quota_status": state.quota_status,
                "requests_attempted": state.requests_attempted,
                "requests_succeeded": state.requests_succeeded,
                "requests_failed": state.requests_failed,
                "total_day_remaining": allocs.get("total_day_remaining"),
                "current_segment": seg_info["segment"],
                "segment_budget": allocs.get("segment_budget"),
                "segment_spent": allocs.get("segment_spent"),
                "segment_remaining": allocs.get("segment_remaining"),
                "morning_reserve": allocs.get("morning_reserve"),
                "afternoon_budget": allocs.get("afternoon_budget"),
                "morning_budget": allocs.get("morning_budget"),
                "afternoon_spent": state.afternoon_requests_spent,
                "morning_spent": state.morning_requests_spent,
                "last_request_utc": state.last_request_utc,
                "last_success_utc": state.last_success_utc,
                "last_error_category": state.last_error_category,
                "is_rpd_blocked": is_blocked,
                "rpd_blocked_until_utc": blocked_until,
                "provider_reset_utc": seg_info["next_reset_utc"],
                "provider_reset_ist": seg_info["next_reset_ist"],
                "provider_reset_ist_short": seg_info["next_reset_ist_short"],
                "in_flight": state.in_flight,
                "provider_known_exhausted": state.provider_known_exhausted,
                "total_tokens_used": state.total_tokens_used,
                "prompt_tokens": state.prompt_tokens,
                "candidates_tokens": state.candidates_tokens,
                "cached_tokens": state.cached_tokens,
                "thoughts_tokens": state.thoughts_tokens,
            }
