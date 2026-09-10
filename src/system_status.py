"""Canonical CITADEL status contract and deterministic status engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence


from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def _aware(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)
    if not value:
        return datetime.now(IST)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)
    except (ValueError, TypeError):
        return datetime.now(IST)


@dataclass(frozen=True)
class ComponentStatusBlock:
    state: str
    reason_code: str
    plain_language_reason: str
    source_timestamp: Optional[str]
    calculated_at: str
    age_seconds: Optional[float]
    action_required: bool
    recommended_action: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeploymentStatusBlock:
    deployment_id: str
    lifecycle: str
    readiness: str
    connectivity: str
    freshness: str
    cursor_lag: Optional[int]
    backlog_count: Optional[int]
    active_interruption: Optional[str]
    reason_code: str
    plain_language_reason: str
    source_timestamp: Optional[str]
    calculated_at: str
    age_seconds: Optional[float]
    action_required: bool
    recommended_action: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanonicalStatusEngine:
    """Builds authoritative, non-contradictory CITADEL status contracts."""

    @classmethod
    def evaluate(
        cls,
        *,
        backend_online: bool = True,
        session_calendar_status: Optional[Mapping[str, Any]] = None,
        safety_status: Optional[Mapping[str, Any]] = None,
        deployments_status: Optional[Sequence[Mapping[str, Any]]] = None,
        intelligence_modules: Optional[Mapping[str, Mapping[str, Any]]] = None,
        now_provider: Optional[Any] = None,
    ) -> dict[str, Any]:
        now_dt = _aware(now_provider() if callable(now_provider) else datetime.now(timezone.utc))
        now_iso = now_dt.isoformat()

        # 1. Operating Mode (Deterministically computed via NSESessionCalendar or fallback IST boundaries)
        from src.market.session_calendar import NSESessionCalendar
        calendar = NSESessionCalendar(clock=lambda: now_dt)
        cal_status = calendar.status(at=now_dt)

        operating_mode = "MARKET_CLOSED"
        mode_reason_code = str(cal_status.get("reason") or "OUTSIDE_REGULAR_SESSION")
        session_state = str(cal_status.get("session_state") or "UNKNOWN").upper()
        next_transition = cal_status.get("next_valid_open")

        if session_state in {"OPEN", "SPECIAL_SESSION"}:
            operating_mode = "MARKET_OPEN"
            next_transition = cal_status.get("scheduled_close")
        elif session_state == "PRE_OPEN":
            operating_mode = "PRE_MARKET"
            next_transition = cal_status.get("scheduled_open")
        elif session_state in {"CLOSED", "OUTSIDE_REGULAR_SESSION"}:
            # Check if after 15:30 IST on a trading weekday -> POST_MARKET
            time_val = now_dt.time()
            from datetime import time
            if now_dt.weekday() < 5 and cal_status.get("scheduled_close") and time_val >= time(15, 30):
                operating_mode = "POST_MARKET"
                mode_reason_code = "NSE_POST_MARKET_SESSION"
            elif now_dt.weekday() < 5 and time_val < time(9, 0):
                operating_mode = "MARKET_CLOSED"
                mode_reason_code = "BEFORE_PRE_OPEN"
            else:
                operating_mode = "MARKET_CLOSED"
        elif session_state == "WEEKEND":
            operating_mode = "MARKET_CLOSED"
            mode_reason_code = "NSE_WEEKEND_CLOSED"
        elif session_state == "HOLIDAY":
            operating_mode = "MARKET_CLOSED"
            mode_reason_code = f"NSE_HOLIDAY_{mode_reason_code}"

        server_time_utc = now_dt.astimezone(timezone.utc).isoformat()
        exchange_time_ist = now_dt.astimezone(IST).isoformat()
        trading_date = cal_status.get("session_date") or now_dt.date().isoformat()

        # 2. Safety Status
        safety_dict = dict(safety_status or {})
        kill_active = safety_dict.get("kill_switch_active") is True
        risk_avail = safety_dict.get("risk_state_available")
        if kill_active:
            safety_state = "BLOCKED"
            safety_code = "KILL_SWITCH_ACTIVE"
            safety_reason = "Safety kill-switch is active; new orders are blocked."
            safety_action = True
            safety_rec = "Deactivate kill-switch via administrative controls if clear to proceed."
        elif risk_avail is False:
            safety_state = "UNSAFE"
            safety_code = "RISK_STATE_UNAVAILABLE"
            safety_reason = "Authoritative risk limits or state are unavailable."
            safety_action = True
            safety_rec = "Inspect risk configuration and paper state store."
        elif risk_avail is True:
            safety_state = "SAFE"
            safety_code = "SAFETY_NORMAL"
            safety_reason = "Risk controls active and paper state accessible."
            safety_action = False
            safety_rec = None
        else:
            safety_state = "UNKNOWN"
            safety_code = "SAFETY_UNCHECKED"
            safety_reason = "Safety system status not provided."
            safety_action = False
            safety_rec = None

        safety_block = ComponentStatusBlock(
            state=safety_state,
            reason_code=safety_code,
            plain_language_reason=safety_reason,
            source_timestamp=safety_dict.get("last_updated"),
            calculated_at=now_iso,
            age_seconds=cls._calc_age(safety_dict.get("last_updated"), now_dt),
            action_required=safety_action,
            recommended_action=safety_rec,
        )

        # 3. Deployments Evaluation
        raw_deployments = list(deployments_status or [])
        eval_deployments: list[DeploymentStatusBlock] = []
        healthy_dep_count = 0
        total_dep_count = len(raw_deployments)

        for dep in raw_deployments:
            dep_dict = dict(dep)
            dep_id = str(dep_dict.get("strategy_id") or dep_dict.get("deployment_id") or "UNKNOWN")
            state_str = str(dep_dict.get("state") or "STOPPED").upper()
            health_str = str(dep_dict.get("health") or "HEALTHY").upper()
            readiness_str = str(dep_dict.get("readiness") or "NOT_READY").upper()

            # Lifecycle
            if state_str in {"RUNNING", "ACTIVE"}:
                lifecycle = "RUNNING"
            elif state_str in {"STOPPED", "NOT_LOADED"}:
                lifecycle = "STOPPED"
            elif state_str == "PAUSED":
                lifecycle = "PAUSED"
            elif state_str == "ERROR":
                lifecycle = "ERROR"
            elif state_str in {"STARTING", "INITIALIZING"}:
                lifecycle = "STARTING"
            elif state_str == "DISABLED":
                lifecycle = "DISABLED"
            else:
                lifecycle = "STOPPED"

            # Connectivity & Readiness
            if state_str == "NOT_LOADED":
                connectivity = "DISCONNECTED"
                readiness = "NOT_READY"
                dep_code = "DEPLOYMENT_NOT_LOADED"
                dep_reason = f"Deployment {dep_id} is not loaded into memory."
                dep_action = True
                dep_rec = f"Load or deploy runtime for {dep_id}."
            elif health_str not in {"HEALTHY", "LIVE"}:
                connectivity = "STALE"
                readiness = "NOT_READY"
                dep_code = "DEPLOYMENT_DEGRADED"
                dep_reason = f"Deployment {dep_id} is experiencing errors or degraded inputs."
                dep_action = True
                dep_rec = f"Check logs and dependencies for {dep_id}."
            else:
                connectivity = "CONNECTED"
                readiness = "READY" if readiness_str in {"READY", "DATA_READY", "LIVE"} else "NOT_READY"
                dep_code = "DEPLOYMENT_NORMAL"
                dep_reason = f"Deployment {dep_id} is healthy."
                dep_action = False
                dep_rec = None

            # Freshness
            sched = dep_dict.get("scheduler") or {}
            last_up = dep_dict.get("last_updated") or (sched.get("last_tick") if isinstance(sched, dict) else None)
            dep_age = cls._calc_age(last_up, now_dt)
            if dep_age is None or dep_age <= 300.0:
                freshness = "FRESH"
            elif dep_age <= 600.0:
                freshness = "AGING"
            else:
                freshness = "STALE"
                if connectivity == "CONNECTED":
                    connectivity = "STALE"

            if lifecycle == "RUNNING" and connectivity == "CONNECTED" and health_str in {"HEALTHY", "LIVE"}:
                healthy_dep_count += 1

            cursor_lag = sched.get("cursor_lag") if isinstance(sched, dict) else None
            backlog_count = sched.get("backlog_count") if isinstance(sched, dict) else None
            active_interruption = sched.get("active_interruption") if isinstance(sched, dict) else None

            eval_deployments.append(
                DeploymentStatusBlock(
                    deployment_id=dep_id,
                    lifecycle=lifecycle,
                    readiness=readiness,
                    connectivity=connectivity,
                    freshness=freshness,
                    cursor_lag=int(cursor_lag) if cursor_lag is not None else None,
                    backlog_count=int(backlog_count) if backlog_count is not None else None,
                    active_interruption=str(active_interruption) if active_interruption else None,
                    reason_code=dep_code,
                    plain_language_reason=dep_reason,
                    source_timestamp=str(last_up) if last_up else None,
                    calculated_at=now_iso,
                    age_seconds=dep_age,
                    action_required=dep_action,
                    recommended_action=dep_rec,
                )
            )

        # 4. Intelligence / Projection Freshness
        intel_dict = dict(intelligence_modules or {})
        stale_required_modules = []

        for name, mod in intel_dict.items():
            if not isinstance(mod, dict):
                continue
            is_optional = mod.get("advisory_only") is True or mod.get("optional") is True
            mod_freshness = str(mod.get("freshness") or "FRESH").upper()
            if mod_freshness in {"STALE", "UNAVAILABLE"} and not is_optional:
                stale_required_modules.append(name)

        # 5. Overall System Status Determination
        if not backend_online:
            overall_status = "OFFLINE"
            overall_code = "BACKEND_UNREACHABLE"
            overall_reason = "Backend server is unreachable or offline."
            overall_action = True
            overall_rec = "Restart the backend server via launchd supervisor."
        elif safety_state in {"BLOCKED", "UNSAFE"}:
            overall_status = "BLOCKED"
            overall_code = safety_code
            overall_reason = safety_reason
            overall_action = True
            overall_rec = safety_rec
        elif stale_required_modules:
            overall_status = "DEGRADED"
            overall_code = "REQUIRED_DEPENDENCY_STALE"
            overall_reason = f"Required module(s) stale/unavailable: {', '.join(stale_required_modules)}."
            overall_action = True
            overall_rec = "Check data feeds for stale dependencies."
        elif total_dep_count > 0 and healthy_dep_count == 0:
            overall_status = "DEGRADED"
            overall_code = "NO_HEALTHY_DEPLOYMENTS"
            overall_reason = f"0 of {total_dep_count} deployments are healthy and running."
            overall_action = True
            overall_rec = "Start required strategy deployments."
        elif healthy_dep_count < total_dep_count:
            overall_status = "DEGRADED"
            overall_code = "PARTIAL_DEPLOYMENTS_RUNNING"
            overall_reason = f"{healthy_dep_count} of {total_dep_count} deployments are healthy and running."
            overall_action = False
            overall_rec = "Verify non-running deployments if expected to be active."
        else:
            overall_status = "HEALTHY"
            overall_code = "ALL_SYSTEMS_NORMAL"
            overall_reason = "All backend services, risk controls, and deployments are healthy."
            overall_action = False
            overall_rec = None

        # Formulate Overall Block
        overall_block = ComponentStatusBlock(
            state=overall_status,
            reason_code=overall_code,
            plain_language_reason=overall_reason,
            source_timestamp=now_iso,
            calculated_at=now_iso,
            age_seconds=0.0,
            action_required=overall_action,
            recommended_action=overall_rec,
        )

        # Build Ranked Action Required Issues List
        action_issues = []
        if overall_action and overall_rec:
            action_issues.append({
                "priority": 1,
                "scope": "SYSTEM",
                "code": overall_code,
                "reason": overall_reason,
                "recommended_action": overall_rec,
            })
        if safety_action and safety_rec and safety_code != overall_code:
            action_issues.append({
                "priority": 2,
                "scope": "SAFETY",
                "code": safety_code,
                "reason": safety_reason,
                "recommended_action": safety_rec,
            })
        for dep_b in eval_deployments:
            if dep_b.action_required and dep_b.recommended_action:
                action_issues.append({
                    "priority": 3,
                    "scope": f"DEPLOYMENT:{dep_b.deployment_id}",
                    "code": dep_b.reason_code,
                    "reason": dep_b.plain_language_reason,
                    "recommended_action": dep_b.recommended_action,
                })

        wording_summary = (
            "All systems running normally"
            if overall_status == "HEALTHY"
            else f"System status {overall_status}: {healthy_dep_count}/{total_dep_count} deployments running"
        )

        return {
            "overall_status": overall_status,
            "operating_mode": operating_mode,
            "server_time_utc": server_time_utc,
            "exchange_time_ist": exchange_time_ist,
            "trading_date": trading_date,
            "reason_code": mode_reason_code,
            "next_transition_at": next_transition,
            "safety_status": safety_state,
            "freshness": "FRESH" if overall_status in {"HEALTHY", "DEGRADED"} else "UNAVAILABLE",
            "system": overall_block.to_dict(),
            "safety": safety_block.to_dict(),
            "deployments": [d.to_dict() for d in eval_deployments],
            "deployment_counts": {
                "total": total_dep_count,
                "healthy_running": healthy_dep_count,
                "stopped": sum(d.lifecycle == "STOPPED" for d in eval_deployments),
                "error": sum(d.lifecycle == "ERROR" for d in eval_deployments),
            },
            "wording_summary": wording_summary,
            "action_required_issues": action_issues,
            "generated_at": now_iso,
            "calculated_at": now_iso,
            "schema_version": 1,
        }

    @staticmethod
    def _calc_age(timestamp_str: Optional[str], now_dt: datetime) -> Optional[float]:
        if not timestamp_str:
            return None
        try:
            ts_dt = _aware(timestamp_str)
            return max(0.0, (now_dt - ts_dt).total_seconds())
        except Exception:
            return None
