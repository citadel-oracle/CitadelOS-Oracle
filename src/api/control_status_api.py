"""Sanitized read-only risk and authoritative paper-state status responses."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from src.execution.paper_state import PaperStateService, PaperStateUnavailable
from src.risk.authorization import (
    RiskAuditLogger,
    RiskConfigurationError,
    RiskControlStore,
    RiskLimits,
    RiskStateUnavailable,
)


IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ControlStatusAPI:
    """Read-only projection; it exposes no mutation or credential surface."""

    def __init__(
        self,
        *,
        settings_path: Optional[Path | str] = None,
        risk_store: Optional[RiskControlStore] = None,
        paper_state: Optional[PaperStateService] = None,
        audit_logger: Optional[RiskAuditLogger] = None,
        now_provider=None,
    ):
        self.settings_path = Path(
            settings_path or PROJECT_ROOT / "config" / "settings.json"
        )
        self.risk_store = risk_store or RiskControlStore()
        self.paper_state = paper_state or PaperStateService()
        self.audit_logger = audit_logger or RiskAuditLogger()
        self.now_provider = now_provider or (lambda: datetime.now(IST))

    def risk_summary(self) -> dict[str, Any]:
        limits = None
        config_error = None
        try:
            limits = RiskLimits.from_mapping(self._load_settings())
        except (RiskConfigurationError, OSError, json.JSONDecodeError):
            config_error = "Risk configuration is unavailable or invalid"

        kill_projection = self.risk_store.projection()
        kill_switch = kill_projection if kill_projection.state in {"ACTIVE", "INACTIVE"} else None
        kill_error = None if kill_switch is not None else "Kill-switch state is unavailable"

        paper_available = True
        try:
            self.paper_state.risk_snapshot(self._now().date())
        except PaperStateUnavailable:
            paper_available = False

        available = limits is not None and kill_switch is not None and paper_available
        known_components = sum(
            (limits is not None, kill_switch is not None, paper_available)
        )
        status = "healthy" if available else "degraded" if known_components else "unavailable"
        error_messages = [
            message
            for message in (config_error, kill_error, None if paper_available else "Paper state is unavailable")
            if message
        ]

        openalgo_reachable = False
        analyzer_mode_active = False
        try:
            from src.broker.openalgo_client import OpenAlgoClient
            oa_client = OpenAlgoClient()
            an_res = oa_client.get_analyzer_status()
            if isinstance(an_res, dict) and an_res.get("status") == "success":
                openalgo_reachable = True
                an_data = an_res.get("data", {})
                if an_data.get("mode") == "analyze" and an_data.get("analyze_mode") is True:
                    analyzer_mode_active = True
        except Exception:
            openalgo_reachable = False
            analyzer_mode_active = False

        current_broker_status = "CONNECTED" if openalgo_reachable else "DISCONNECTED"
        raw_kill_reason = _safe_text(kill_switch.reason) if kill_switch is not None else None
        kill_reason_applicable = True
        kill_reason_reported = raw_kill_reason

        if openalgo_reachable and raw_kill_reason == "BROKER_DISCONNECTED":
            kill_reason_applicable = False
            kill_reason_reported = "HISTORICAL_BROKER_DISCONNECT_RESET_REQUIRED"

        return {
            "status": status,
            "state_health": status.upper(),
            "live_trading_enabled": (
                limits.live_trading_enabled if limits is not None else None
            ),
            "kill_switch_active": (
                kill_projection.active
            ),
            "kill_switch_state": kill_projection.state,
            "kill_switch_reason": kill_reason_reported,
            "kill_switch_reason_raw": raw_kill_reason,
            "kill_switch_reason_currently_applicable": kill_reason_applicable,
            "kill_switch_activated_at": (
                kill_switch.activated_at
                if kill_switch is not None and kill_switch.active
                else None
            ),
            "risk_state_available": available,
            "current_broker_status": current_broker_status,
            "openalgo_connected": openalgo_reachable,
            "openalgo_reachable": openalgo_reachable,
            "openalgo_mode": "analyze" if analyzer_mode_active else "off",
            "analyzer_mode": analyzer_mode_active,
            "broker_session_status": "AUTHENTICATED" if openalgo_reachable else "DISCONNECTED",
            "limits": self._limits(limits),
            "latest_authorization": self._latest_authorization(),
            "error": (
                {
                    "code": "RISK_STATE_DEGRADED",
                    "message": "; ".join(error_messages),
                }
                if error_messages
                else None
            ),
            "last_updated": self._now().isoformat(),
        }

    def kill_switch_summary(self) -> dict[str, Any]:
        projection = self.risk_store.projection()
        value = projection.to_dict()
        value["status"] = "healthy" if projection.state in {"ACTIVE", "INACTIVE"} else "unavailable"
        value["warning"] = projection.warnings[0] if projection.warnings else None
        return value

    def paper_summary(self) -> dict[str, Any]:
        observed_at = self._now()
        try:
            state = self.paper_state.load(observed_at.date())
        except PaperStateUnavailable:
            return {
                "status": "unavailable",
                "state_health": "UNAVAILABLE",
                "trading_date": None,
                "cash_balance": None,
                "realized_pnl": None,
                "unrealized_pnl": None,
                "total_daily_pnl": None,
                "trades_taken_today": None,
                "consecutive_losses": None,
                "open_position_count": None,
                "accepted_request_count": None,
                "last_updated": None,
                "state_last_mutated_at": None,
                "projection_observed_at": observed_at.isoformat(),
                "freshness_semantics": "STATE_UNAVAILABLE",
                "error": {
                    "code": "PAPER_STATE_UNAVAILABLE",
                    "message": "Authoritative paper state is unavailable",
                },
            }

        return {
            "status": "healthy",
            "state_health": "HEALTHY",
            "trading_date": state.trading_date,
            "cash_balance": state.cash_balance,
            "realized_pnl": state.realized_pnl,
            "unrealized_pnl": state.unrealized_pnl,
            "total_daily_pnl": state.total_daily_pnl,
            "trades_taken_today": state.trades_taken,
            "consecutive_losses": state.consecutive_losses,
            "open_position_count": len(state.open_positions),
            "accepted_request_count": len(state.accepted_request_ids),
            "last_updated": state.last_updated,
            "state_last_mutated_at": state.last_updated,
            "projection_observed_at": observed_at.isoformat(),
            "freshness_semantics": "CURRENT_TRADING_DATE_STATE; LAST_UPDATED_IS_LAST_MUTATION_NOT_POLL_TIME",
            "error": None,
        }

    def _load_settings(self) -> Mapping[str, Any]:
        value = json.loads(self.settings_path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise RiskConfigurationError("Risk settings must be a mapping")
        return value

    @staticmethod
    def _limits(limits: Optional[RiskLimits]) -> dict[str, Any]:
        if limits is None:
            return {
                "max_daily_loss": None,
                "max_trades_per_day": None,
                "max_consecutive_losses": None,
                "max_risk_per_trade": None,
                "max_raw_quantity": None,
                "max_open_positions": None,
                "max_market_data_age_seconds": None,
                "max_volatility": None,
            }
        return {
            "max_daily_loss": limits.max_daily_loss,
            "max_trades_per_day": limits.max_trades_per_day,
            "max_consecutive_losses": limits.max_consecutive_losses,
            "max_risk_per_trade": limits.max_risk_per_trade,
            "max_raw_quantity": limits.max_position_quantity,
            "max_open_positions": limits.max_open_positions,
            "max_market_data_age_seconds": limits.max_market_data_age_seconds,
            "max_volatility": limits.max_volatility,
        }

    def _latest_authorization(self) -> Optional[dict[str, Any]]:
        path = self.audit_logger.path
        if not path.exists():
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                return None
            value = json.loads(lines[-1])
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, Mapping):
            return None
        return {
            "decision": _safe_text(value.get("decision")),
            "reason_code": _safe_text(value.get("reason_code")),
            "reason": _safe_text(value.get("reason")),
            "timestamp": _safe_text(value.get("timestamp")),
        }

    def _now(self) -> datetime:
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RiskStateUnavailable("Timezone-aware status clock unavailable")
        return value.astimezone(IST)


def _safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text[:240] or None
