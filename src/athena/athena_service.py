"""Deterministic, read-only ATHENA risk and capital intelligence."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class AthenaSourceMetadata:
    source: str
    advisory_only: bool
    risk_authorization_final_veto: bool
    risk_state_health: str
    paper_state_health: str
    live_trading_enabled: Optional[bool]
    latest_authorization_decision: Optional[str]
    latest_authorization_reason_code: Optional[str]
    exposure_basis: Optional[str]
    capital_basis: Optional[str]
    drawdown_basis: Optional[str]
    risk_source_last_updated: Optional[str]
    paper_source_last_updated: Optional[str]


@dataclass(frozen=True)
class AthenaAssessment:
    generated_at: str
    trading_date: Optional[str]
    athena_status: str
    risk_state: str
    recommendation: str
    recommended_size_multiplier: float
    advisory_only: bool
    daily_realized_pnl: Optional[float]
    daily_unrealized_pnl: Optional[float]
    total_daily_pnl: Optional[float]
    daily_loss_limit: Optional[float]
    daily_loss_used_percentage: Optional[float]
    daily_loss_headroom: Optional[float]
    trades_taken: Optional[int]
    maximum_trades: Optional[int]
    trade_usage_percentage: Optional[float]
    consecutive_losses: Optional[int]
    maximum_consecutive_losses: Optional[int]
    loss_streak_usage_percentage: Optional[float]
    open_positions: Optional[int]
    maximum_open_positions: Optional[int]
    exposure_usage_percentage: Optional[float]
    exposure_acceptable: Optional[bool]
    current_drawdown: Optional[float]
    maximum_allowed_drawdown: Optional[float]
    available_capital: Optional[float]
    blocked_capital: Optional[float]
    current_equity: Optional[float]
    risk_headroom_percentage: Optional[float]
    reason_codes: tuple[str, ...]
    explanation: str
    warnings: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    maturity_label: str
    source_metadata: AthenaSourceMetadata

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        value["warnings"] = list(self.warnings)
        value["missing_inputs"] = list(self.missing_inputs)
        return value


class AthenaService:
    """Advisory projection over sanitized authoritative risk/paper status."""

    MATURITY_LABEL = "DETERMINISTIC_ADVISORY_V1"
    CAUTION_USAGE_PERCENT = 50.0
    HIGH_RISK_USAGE_PERCENT = 80.0

    def __init__(
        self,
        *,
        risk_provider: Callable[[], Mapping[str, Any]],
        paper_provider: Callable[[], Mapping[str, Any]],
        development_capital: float = 50_000.0,
        now_provider=None,
    ):
        self.risk_provider = risk_provider
        self.paper_provider = paper_provider
        self.development_capital = _positive_number(development_capital)
        self.now_provider = now_provider or (lambda: datetime.now(IST))

    def assess(self) -> AthenaAssessment:
        now = self._now()
        try:
            risk = self.risk_provider()
            paper = self.paper_provider()
            return self._assess_sources(risk, paper, now)
        except Exception:
            return self._unavailable(
                now,
                "RISK_STATE_UNAVAILABLE",
                "Authoritative risk or paper state could not be interpreted safely.",
            )

    def _assess_sources(
        self,
        risk: Mapping[str, Any],
        paper: Mapping[str, Any],
        now: datetime,
    ) -> AthenaAssessment:
        if not isinstance(risk, Mapping) or not isinstance(paper, Mapping):
            return self._unavailable(
                now,
                "RISK_STATE_UNAVAILABLE",
                "Authoritative risk or paper state is unavailable.",
            )

        risk_health = _text(risk.get("state_health")) or "UNAVAILABLE"
        paper_health = _text(paper.get("state_health")) or "UNAVAILABLE"
        live_enabled = risk.get("live_trading_enabled")
        kill_switch = risk.get("kill_switch_active")
        if (
            risk.get("risk_state_available") is not True
            or risk_health != "HEALTHY"
            or paper_health != "HEALTHY"
            or type(live_enabled) is not bool
            or type(kill_switch) is not bool
        ):
            return self._unavailable(
                now,
                "RISK_STATE_UNAVAILABLE",
                "Required authoritative state is unavailable or degraded; no new trade is advised.",
                risk=risk,
                paper=paper,
            )

        limits = risk.get("limits")
        if not isinstance(limits, Mapping):
            return self._unavailable(
                now,
                "RISK_STATE_UNAVAILABLE",
                "Risk limits are unavailable; no new trade is advised.",
                risk=risk,
                paper=paper,
            )

        try:
            daily_loss_limit = _positive_number(limits.get("max_daily_loss"))
            maximum_trades = _positive_int(limits.get("max_trades_per_day"))
            maximum_losses = _positive_int(
                limits.get("max_consecutive_losses")
            )
            maximum_positions = _positive_int(
                limits.get("max_open_positions")
            )
            realized = _number(paper.get("realized_pnl"))
            unrealized = _number(paper.get("unrealized_pnl"))
            total = _number(paper.get("total_daily_pnl"))
            trades = _non_negative_int(paper.get("trades_taken_today"))
            losses = _non_negative_int(paper.get("consecutive_losses"))
            positions = _non_negative_int(paper.get("open_position_count"))
            trading_date = date.fromisoformat(str(paper.get("trading_date"))).isoformat()
            if not math.isclose(realized + unrealized, total, abs_tol=0.01):
                raise ValueError("Daily P&L is inconsistent")
        except (TypeError, ValueError):
            return self._unavailable(
                now,
                "RISK_STATE_UNAVAILABLE",
                "Authoritative risk or paper values are malformed; no new trade is advised.",
                risk=risk,
                paper=paper,
            )

        current_loss = max(0.0, -total)
        daily_usage = _percentage(current_loss, daily_loss_limit)
        trade_usage = _percentage(trades, maximum_trades)
        streak_usage = _percentage(losses, maximum_losses)
        exposure_usage = _percentage(positions, maximum_positions)
        headroom = max(0.0, daily_loss_limit - current_loss)
        overall_usage = max(
            daily_usage, trade_usage, streak_usage, exposure_usage
        )
        risk_headroom = round(max(0.0, 100.0 - overall_usage), 2)

        paper_capital = _optional_non_negative_number(paper.get("cash_balance"))
        available_capital = paper_capital if paper_capital is not None else self.development_capital
        capital_basis = (
            "PAPER_CASH_BALANCE"
            if paper_capital is not None
            else "DEVELOPMENT_CAPITAL_SIMULATION_ONLY"
        )
        blocked_capital = _optional_non_negative_number(
            paper.get("blocked_capital")
        )
        current_equity = _optional_non_negative_number(
            paper.get("current_equity")
        )
        maximum_drawdown = _optional_positive_number(
            limits.get("maximum_allowed_drawdown")
        )

        missing_inputs = []
        if blocked_capital is None:
            missing_inputs.append("blocked_capital")
        if current_equity is None:
            missing_inputs.append("current_equity")
        if maximum_drawdown is None:
            missing_inputs.append("maximum_allowed_drawdown")
        missing_inputs.extend(
            ["weekly_risk_usage", "monthly_risk_usage", "rupee_exposure"]
        )

        reasons = []
        warnings = []
        if paper_capital is None:
            reasons.append("DEVELOPMENT_CAPITAL_APPLIED")
            warnings.append("DEVELOPMENT_CAPITAL_SIMULATION_ONLY")
        if current_equity is None:
            warnings.append("CURRENT_EQUITY_UNAVAILABLE")
        reasons.append("EXPOSURE_UNAVAILABLE")
        warnings.append("RUPEE_EXPOSURE_UNAVAILABLE_POSITION_CAPACITY_USED")
        if maximum_drawdown is None:
            warnings.append("MAXIMUM_ALLOWED_DRAWDOWN_UNAVAILABLE")
        warnings.extend(["WEEKLY_RISK_USAGE_UNAVAILABLE", "MONTHLY_RISK_USAGE_UNAVAILABLE"])
        if not live_enabled:
            warnings.append("LIVE_TRADING_DISABLED")

        latest = risk.get("latest_authorization")
        latest_decision = None
        latest_reason = None
        if isinstance(latest, Mapping):
            latest_decision = _text(latest.get("decision"))
            latest_reason = _text(latest.get("reason_code"))

        hard_stop = False
        if kill_switch:
            hard_stop = True
            reasons.append("KILL_SWITCH_ACTIVE")
        if latest_decision == "DENY":
            hard_stop = True
            reasons.extend(["RISK_AUTHORIZATION_DENY", latest_reason or "RISK_DENY"])
        if daily_usage >= 100:
            hard_stop = True
            reasons.append("DAILY_LOSS_LIMIT_REACHED")
        if trade_usage >= 100:
            hard_stop = True
            reasons.append("MAX_TRADES_REACHED")
        if streak_usage >= 100:
            hard_stop = True
            reasons.append("MAX_CONSECUTIVE_LOSSES_REACHED")
        if exposure_usage >= 100:
            hard_stop = True
            reasons.append("OPEN_POSITION_LIMIT_REACHED")

        if hard_stop:
            athena_status = "BLOCKED"
            risk_state = "STOP"
            recommendation = "STOP"
            multiplier = 0.0
            reasons.extend(["ATHENA_STOP", "NO_NEW_TRADE_RECOMMENDED"])
        elif overall_usage >= self.HIGH_RISK_USAGE_PERCENT:
            athena_status = "READY"
            risk_state = "HIGH_RISK"
            recommendation = "PAUSE"
            multiplier = 0.25
            reasons.extend(
                [
                    "ATHENA_HIGH_RISK",
                    "REDUCED_SIZE_RECOMMENDED",
                    "NO_NEW_TRADE_RECOMMENDED",
                ]
            )
        elif overall_usage >= self.CAUTION_USAGE_PERCENT:
            athena_status = "READY"
            risk_state = "CAUTION"
            recommendation = "REDUCE"
            multiplier = 0.5 if overall_usage >= 75 else 0.75
            reasons.extend(["ATHENA_CAUTION", "REDUCED_SIZE_RECOMMENDED"])
        else:
            athena_status = "DEGRADED" if missing_inputs else "READY"
            risk_state = "SAFE"
            recommendation = "CONTINUE"
            multiplier = 1.0
            reasons.append("ATHENA_SAFE")

        if daily_usage >= self.CAUTION_USAGE_PERCENT:
            reasons.append("DAILY_LOSS_USAGE_HIGH")
        if trade_usage >= self.CAUTION_USAGE_PERCENT:
            reasons.append("TRADE_USAGE_HIGH")
        if streak_usage >= self.CAUTION_USAGE_PERCENT:
            reasons.append("LOSS_STREAK_HIGH")
        if exposure_usage >= self.CAUTION_USAGE_PERCENT and exposure_usage < 100:
            reasons.append("OPEN_POSITION_USAGE_HIGH")

        multiplier = round(min(1.0, max(0.0, multiplier)), 2)
        reasons = _dedupe(reasons)
        warnings = _dedupe(warnings)
        explanation = _explanation(
            risk_state,
            recommendation,
            overall_usage,
            reasons,
        )

        return AthenaAssessment(
            generated_at=now.isoformat(),
            trading_date=trading_date,
            athena_status=athena_status,
            risk_state=risk_state,
            recommendation=recommendation,
            recommended_size_multiplier=multiplier,
            advisory_only=True,
            daily_realized_pnl=round(realized, 2),
            daily_unrealized_pnl=round(unrealized, 2),
            total_daily_pnl=round(total, 2),
            daily_loss_limit=round(daily_loss_limit, 2),
            daily_loss_used_percentage=daily_usage,
            daily_loss_headroom=round(headroom, 2),
            trades_taken=trades,
            maximum_trades=maximum_trades,
            trade_usage_percentage=trade_usage,
            consecutive_losses=losses,
            maximum_consecutive_losses=maximum_losses,
            loss_streak_usage_percentage=streak_usage,
            open_positions=positions,
            maximum_open_positions=maximum_positions,
            exposure_usage_percentage=exposure_usage,
            exposure_acceptable=positions < maximum_positions,
            current_drawdown=round(current_loss, 2),
            maximum_allowed_drawdown=maximum_drawdown,
            available_capital=available_capital,
            blocked_capital=blocked_capital,
            current_equity=current_equity,
            risk_headroom_percentage=risk_headroom,
            reason_codes=tuple(reasons),
            explanation=explanation,
            warnings=tuple(warnings),
            missing_inputs=tuple(_dedupe(missing_inputs)),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=self._metadata(
                risk,
                paper,
                live_enabled,
                latest_decision,
                latest_reason,
                capital_basis,
            ),
        )

    def _unavailable(
        self,
        now: datetime,
        code: str,
        explanation: str,
        *,
        risk: Optional[Mapping[str, Any]] = None,
        paper: Optional[Mapping[str, Any]] = None,
    ) -> AthenaAssessment:
        risk = risk if isinstance(risk, Mapping) else {}
        paper = paper if isinstance(paper, Mapping) else {}
        live = risk.get("live_trading_enabled")
        live = live if type(live) is bool else None
        return AthenaAssessment(
            generated_at=now.isoformat(),
            trading_date=None,
            athena_status="UNAVAILABLE",
            risk_state="STOP",
            recommendation="STOP",
            recommended_size_multiplier=0.0,
            advisory_only=True,
            daily_realized_pnl=None,
            daily_unrealized_pnl=None,
            total_daily_pnl=None,
            daily_loss_limit=None,
            daily_loss_used_percentage=None,
            daily_loss_headroom=None,
            trades_taken=None,
            maximum_trades=None,
            trade_usage_percentage=None,
            consecutive_losses=None,
            maximum_consecutive_losses=None,
            loss_streak_usage_percentage=None,
            open_positions=None,
            maximum_open_positions=None,
            exposure_usage_percentage=None,
            exposure_acceptable=None,
            current_drawdown=None,
            maximum_allowed_drawdown=None,
            available_capital=None,
            blocked_capital=None,
            current_equity=None,
            risk_headroom_percentage=None,
            reason_codes=(
                "ATHENA_STOP",
                code,
                "CAPITAL_UNAVAILABLE",
                "EXPOSURE_UNAVAILABLE",
                "DRAW_DOWN_UNAVAILABLE",
                "NO_NEW_TRADE_RECOMMENDED",
            ),
            explanation=explanation,
            warnings=(code,),
            missing_inputs=(
                "authoritative_risk_state",
                "authoritative_paper_state",
                "available_capital",
                "blocked_capital",
                "current_equity",
                "current_drawdown",
                "weekly_risk_usage",
                "monthly_risk_usage",
                "rupee_exposure",
            ),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=self._metadata(
                risk,
                paper,
                live,
                None,
                None,
                None,
            ),
        )

    @staticmethod
    def _metadata(risk, paper, live, latest_decision, latest_reason, capital_basis):
        return AthenaSourceMetadata(
            source="sanitized_control_status_projections",
            advisory_only=True,
            risk_authorization_final_veto=True,
            risk_state_health=_text(risk.get("state_health")) or "UNAVAILABLE",
            paper_state_health=_text(paper.get("state_health")) or "UNAVAILABLE",
            live_trading_enabled=live,
            latest_authorization_decision=latest_decision,
            latest_authorization_reason_code=latest_reason,
            exposure_basis="OPEN_POSITION_CAPACITY",
            capital_basis=capital_basis,
            drawdown_basis="NEGATIVE_TOTAL_DAILY_PNL",
            risk_source_last_updated=_text(risk.get("last_updated")),
            paper_source_last_updated=_text(paper.get("last_updated")),
        )

    def _now(self) -> datetime:
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("ATHENA clock must be timezone-aware")
        return value.astimezone(IST)


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Number must be finite")
    return number


def _positive_number(value: Any) -> float:
    number = _number(value)
    if number <= 0:
        raise ValueError("Number must be positive")
    return number


def _optional_non_negative_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = _number(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if number >= 0 else None


def _optional_positive_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(_positive_number(value), 2)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Integer must be positive")
    return value


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Integer must be non-negative")
    return value


def _percentage(value: float, limit: float) -> float:
    return round(max(0.0, value / limit * 100.0), 2)


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\n", " ").replace("\r", " ").strip().upper()
    return text[:120] or None


def _dedupe(values):
    return list(dict.fromkeys(value for value in values if value))


def _explanation(risk_state, recommendation, usage, reasons):
    facts = []
    if "KILL_SWITCH_ACTIVE" in reasons:
        facts.append("the kill switch is active")
    if "RISK_AUTHORIZATION_DENY" in reasons:
        facts.append("the latest Risk Authorization decision is DENY")
    if "DAILY_LOSS_LIMIT_REACHED" in reasons:
        facts.append("the daily loss limit is reached")
    if "MAX_TRADES_REACHED" in reasons:
        facts.append("the maximum trade count is reached")
    if "MAX_CONSECUTIVE_LOSSES_REACHED" in reasons:
        facts.append("the consecutive-loss limit is reached")
    if "OPEN_POSITION_LIMIT_REACHED" in reasons:
        facts.append("the open-position limit is reached")
    detail = "; ".join(facts) if facts else f"highest hard-limit utilization is {round(usage, 2)}%"
    return (
        f"ATHENA classifies risk as {risk_state} and advises {recommendation}: "
        f"{detail}. The size multiplier is advisory and cannot override Risk Authorization."
    )
