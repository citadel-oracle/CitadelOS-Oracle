"""Institutional, isolated paper execution for Strategy Lab runtimes only."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from .events import DomainEvent, InternalEventBus
from .execution_provider import ExecutionProvider, PaperExecutionProvider
from .storage import StrategyWorkspace


_COMMAND_CONFLICT_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _identifier(prefix: str, *parts: Any) -> str:
    body = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(body.encode('utf-8')).hexdigest()[:24]}"


def _date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _seconds(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(start.replace("Z", "+00:00"))
        right = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0.0, (right - left).total_seconds())
    except ValueError:
        return None


def _optional_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


@dataclass(frozen=True)
class PaperRiskPolicy:
    initial_capital: float
    sizing_mode: str
    fixed_lots: Optional[int]
    lot_size: Optional[int]
    fixed_rupee_risk: Optional[float]
    fixed_risk_percent: Optional[float]
    max_daily_loss: float
    max_concurrent_positions: int
    max_trades_per_day: int
    margin_rate: float
    fee_rate_bps: float
    flat_fee_per_fill: float
    slippage_bps: float
    portfolio_capital_limit: float
    configured: bool

    @classmethod
    def from_parameters(cls, parameters: Mapping[str, Any]) -> "PaperRiskPolicy":
        raw = parameters.get("paper_account")
        if not isinstance(raw, Mapping):
            return cls(
                initial_capital=0.0,
                sizing_mode="UNCONFIGURED",
                fixed_lots=None,
                lot_size=None,
                fixed_rupee_risk=None,
                fixed_risk_percent=None,
                max_daily_loss=0.0,
                max_concurrent_positions=0,
                max_trades_per_day=0,
                margin_rate=1.0,
                fee_rate_bps=0.0,
                flat_fee_per_fill=0.0,
                slippage_bps=0.0,
                portfolio_capital_limit=150000.0,
                configured=False,
            )
        mode = str(raw.get("sizing_mode") or "").upper()
        allowed = {"FIXED_LOTS", "FIXED_RUPEE_RISK", "FIXED_PERCENT"}
        initial = _number(raw.get("initial_capital"))
        daily = _number(raw.get("max_daily_loss"))
        concurrent = raw.get("max_concurrent_positions")
        trades = raw.get("max_trades_per_day")
        margin_rate = _number(raw.get("margin_rate"))
        portfolio_limit = _number(raw.get("portfolio_capital_limit") or raw.get("combined_capital_limit"))
        if portfolio_limit is None or portfolio_limit <= 0:
            try:
                with open("config/settings.json", encoding="utf-8") as f:
                    settings = json.load(f)
                    portfolio_limit = _number(settings.get("portfolio_capital_limit"))
            except Exception:
                portfolio_limit = None
        if portfolio_limit is None or portfolio_limit <= 0:
            portfolio_limit = 150000.0
        configured = (
            mode in allowed
            and initial is not None and initial > 0
            and daily is not None and daily > 0
            and isinstance(concurrent, int) and not isinstance(concurrent, bool) and concurrent > 0
            and isinstance(trades, int) and not isinstance(trades, bool) and trades > 0
            and portfolio_limit > 0
        )
        return cls(
            initial_capital=initial or 0.0,
            sizing_mode=mode if mode in allowed else "UNCONFIGURED",
            fixed_lots=int(raw["fixed_lots"]) if isinstance(raw.get("fixed_lots"), int) and raw["fixed_lots"] > 0 else None,
            lot_size=int(raw["lot_size"]) if isinstance(raw.get("lot_size"), int) and raw["lot_size"] > 0 else None,
            fixed_rupee_risk=_number(raw.get("fixed_rupee_risk")),
            fixed_risk_percent=_number(raw.get("fixed_risk_percent")),
            max_daily_loss=daily or 0.0,
            max_concurrent_positions=int(concurrent) if isinstance(concurrent, int) and not isinstance(concurrent, bool) else 0,
            max_trades_per_day=int(trades) if isinstance(trades, int) and not isinstance(trades, bool) else 0,
            margin_rate=margin_rate if margin_rate is not None and 0 < margin_rate <= 1 else 1.0,
            fee_rate_bps=max(0.0, _number(raw.get("fee_rate_bps")) or 0.0),
            flat_fee_per_fill=max(0.0, _number(raw.get("flat_fee_per_fill")) or 0.0),
            slippage_bps=max(0.0, _number(raw.get("slippage_bps")) or 0.0),
            portfolio_capital_limit=float(portfolio_limit),
            configured=configured,
        )

    def validation_reason(self) -> Optional[str]:
        if not self.configured:
            return "PAPER_RISK_POLICY_REQUIRED"
        if self.sizing_mode == "FIXED_LOTS" and (not self.fixed_lots or not self.lot_size):
            return "FIXED_LOTS_CONFIGURATION_REQUIRED"
        if self.sizing_mode == "FIXED_RUPEE_RISK" and not self.fixed_rupee_risk:
            return "FIXED_RUPEE_RISK_CONFIGURATION_REQUIRED"
        if self.sizing_mode == "FIXED_PERCENT" and not self.fixed_risk_percent:
            return "FIXED_PERCENT_CONFIGURATION_REQUIRED"
        return None


def calculate_institutional_statistics(trades: Iterable[Mapping[str, Any]], drawdown: float = 0.0) -> Dict[str, Any]:
    rows = [dict(row) for row in trades if str(row.get("status") or "").upper() == "CLOSED"]
    pnl = [float(row.get("realized_pnl") or 0.0) for row in rows]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    durations = [value for value in (_number(row.get("duration_seconds")) for row in rows) if value is not None]
    mfe = [value for value in (_number(row.get("mfe")) for row in rows) if value is not None]
    mae = [value for value in (_number(row.get("mae")) for row in rows) if value is not None]
    realized_r = [value for value in (_number(row.get("rr")) for row in rows) if value is not None]
    equity_curve = []
    cumulative = 0.0
    for index, value in enumerate(pnl, start=1):
        cumulative += value
        equity_curve.append({"trade": index, "equity": round(cumulative, 8)})
    net = sum(pnl)
    return {
        "completed_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(rows) * 100, 6) if rows else None,
        "net_profit": round(net, 8),
        "net_pnl": round(net, 8),
        "gross_profit": round(sum(wins), 8),
        "gross_loss": round(sum(losses), 8),
        "average_win": round(statistics.mean(wins), 8) if wins else None,
        "average_loss": round(statistics.mean(losses), 8) if losses else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 6) if losses else None,
        "expectancy": round(statistics.mean(pnl), 8) if pnl else None,
        "sharpe": None,
        "sharpe_status": "PLACEHOLDER_REQUIRES_RETURN_SERIES_POLICY",
        "recovery_factor": round(net / drawdown, 6) if drawdown > 0 else None,
        "average_hold_time_seconds": round(statistics.mean(durations), 3) if durations else None,
        "average_mfe": round(statistics.mean(mfe), 8) if mfe else None,
        "average_mae": round(statistics.mean(mae), 8) if mae else None,
        "mfe": round(statistics.mean(mfe), 8) if mfe else None,
        "mae": round(statistics.mean(mae), 8) if mae else None,
        "rr": round(statistics.mean(realized_r), 8) if realized_r else None,
        "drawdown": round(drawdown, 8),
        "equity_curve": equity_curve,
        "ranking_eligible": bool(rows),
        "basis": "COMPLETED_PAPER_TRADES_ONLY",
    }


class InstitutionalPaperTradingEngine:
    """One engine instance owns exactly one Strategy Lab workspace/account."""

    SCHEMA_VERSION = 1
    _TRANSITIONS = {
        "IDLE": {"SIGNAL_PENDING"},
        "SIGNAL_PENDING": {"ENTRY_CONFIRMED", "CANCELLED"},
        "ENTRY_CONFIRMED": {"POSITION_OPEN", "CANCELLED"},
        "POSITION_OPEN": {"MANAGING"},
        "MANAGING": {"TARGET", "STOP", "SESSION_EXIT", "CANCELLED"},
        "TARGET": {"POSITION_CLOSED"},
        "STOP": {"POSITION_CLOSED"},
        "SESSION_EXIT": {"POSITION_CLOSED"},
        "CANCELLED": {"POSITION_CLOSED"},
        "POSITION_CLOSED": {"IDLE"},
    }

    def __init__(
        self,
        *,
        strategy_id: str,
        workspace: StrategyWorkspace,
        policy: PaperRiskPolicy,
        execution_provider: Optional[ExecutionProvider] = None,
    ):
        self.strategy_id = strategy_id
        self.workspace = workspace
        self.policy = policy
        self.execution_provider: ExecutionProvider = execution_provider or PaperExecutionProvider()
        self.event_bus = InternalEventBus()
        self.event_bus.subscribe_all(self._persist_event)
        self._lock = threading.RLock()
        self._state = self._recover()

    @classmethod
    def from_metadata(cls, *, metadata: Mapping[str, Any], workspace: StrategyWorkspace) -> "InstitutionalPaperTradingEngine":
        return cls(
            strategy_id=str(metadata["strategy_id"]),
            workspace=workspace,
            policy=PaperRiskPolicy.from_parameters(dict(metadata.get("parameters") or {})),
        )

    def _initial_state(self) -> Dict[str, Any]:
        legacy = self.workspace.read("paper_state")
        closed = list(legacy.get("closed_trades") or [])
        account = {
            "initial_capital": self.policy.initial_capital,
            "current_equity": self.policy.initial_capital,
            "cash": self.policy.initial_capital,
            "buying_power": self.policy.initial_capital,
            "margin_used": 0.0,
            "available_margin": self.policy.initial_capital,
            "open_risk": 0.0,
            "realized_pnl": round(sum(float(row.get("realized_pnl") or 0.0) for row in closed), 8),
            "unrealized_pnl": 0.0,
            "daily_pnl": 0.0,
            "peak_equity": self.policy.initial_capital,
            "drawdown": 0.0,
            "maximum_drawdown": 0.0,
            "recovery": 0.0,
            "fees_paid": 0.0,
            "updated_at": None,
        }
        state = {
            "schema_version": self.SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "execution_provider": self.execution_provider.provider_name,
            "portfolio_id": "portfolio_strategy_lab_default",
            "risk_policy": asdict(self.policy),
            "account": account,
            "orders": [],
            "fills": [],
            "missions": [],
            "positions": [],
            "closed_trades": closed,
            "processed_evaluations": {},
            "lifecycle": {"state": "IDLE", "transitions": []},
            "statistics": calculate_institutional_statistics(closed),
            "updated_at": None,
        }
        self._revalue(state, timestamp=_now())
        return state

    def _recover(self) -> Dict[str, Any]:
        transactions = self.workspace.transactions.read()
        for transaction in reversed(transactions):
            snapshot = transaction.get("payload", {}).get("state")
            if isinstance(snapshot, Mapping) and snapshot.get("strategy_id") == self.strategy_id:
                state = deepcopy(dict(snapshot))
                self._normalize_lifecycle(state)
                self._materialize(state)
                return state
        persisted = self.workspace.read("paper_engine_state")
        if persisted.get("strategy_id") == self.strategy_id:
            state = deepcopy(persisted)
            self._normalize_lifecycle(state)
            return state
        state = self._initial_state()
        self._materialize(state)
        return state

    def process(self, *, evaluation: Mapping[str, Any], context: Mapping[str, Any], workspace: StrategyWorkspace) -> Mapping[str, Any]:
        if workspace.root != self.workspace.root:
            raise ValueError("STRATEGY_LAB_WORKSPACE_MISMATCH")
        with self._lock:
            timestamp = str(evaluation.get("evaluated_at") or context.get("timestamp") or _now())
            state = deepcopy(self._state)
            changed = self._service_pending(state, context, timestamp)
            changed = self._mark_positions(state, context, timestamp) or changed
            changed = self._sync_position_risk(state, evaluation, timestamp) or changed
            evaluation_id = str(evaluation.get("evaluation_id") or "").strip()
            if not evaluation_id:
                return self._reject_without_order("EVALUATION_ID_REQUIRED")
            existing = state["processed_evaluations"].get(evaluation_id)
            if existing is not None:
                if changed:
                    self._commit(state, "MARK_TO_MARKET", {"evaluation_id": evaluation_id}, f"mtm:{evaluation_id}:{timestamp}")
                return deepcopy(existing)

            signal = str(evaluation.get("signal") or "WAIT").upper()
            open_positions = [row for row in state["positions"] if row.get("status") == "OPEN"]
            pending_entries = [row for row in state["orders"] if row.get("position_effect") == "OPEN" and row.get("status") in {"PENDING", "PARTIAL"}]
            if signal == "BUY" and (open_positions or pending_entries):
                reason = "ACTIVE_POSITION_SUPPRESSED" if open_positions else "ENTRY_ORDER_PENDING_SUPPRESSED"
                result = self._result("NO_ACTION", reason, evaluation_id=evaluation_id)
                state["processed_evaluations"][evaluation_id] = result
                self._commit(state, "DUPLICATE_SIGNAL_SUPPRESSED", result, evaluation_id)
                return result
            if signal == "SELL" and not open_positions:
                result = self._result("NO_ACTION", "DUPLICATE_EXIT_SUPPRESSED", evaluation_id=evaluation_id)
                state["processed_evaluations"][evaluation_id] = result
                self._commit(state, "DUPLICATE_SIGNAL_SUPPRESSED", result, evaluation_id)
                return result
            signal_id = _identifier("sig", self.strategy_id, evaluation_id)
            base_lineage = [signal_id]
            self._emit(
                "SignalCreated",
                signal_id,
                None,
                base_lineage,
                {"strategy_id": self.strategy_id, "evaluation_id": evaluation_id, "signal": signal},
            )
            if signal == "WAIT":
                result = self._result("NO_ACTION", "STRATEGY_WAIT", evaluation_id=evaluation_id, signal_id=signal_id, entity_id=signal_id, lineage=base_lineage)
                state["processed_evaluations"][evaluation_id] = result
                self._commit(state, "STRATEGY_WAIT", {"evaluation_id": evaluation_id}, evaluation_id)
                return result
            if signal not in {"BUY", "SELL"}:
                result = self._reject_without_order("UNSUPPORTED_SIGNAL", evaluation_id)
                state["processed_evaluations"][evaluation_id] = result
                self._commit(state, "SIGNAL_REJECTED", result, evaluation_id)
                return result

            if signal == "BUY":
                self._transition(state, "SIGNAL_PENDING", timestamp, evaluation_id)
            with _COMMAND_CONFLICT_LOCK:
                result = self._submit_signal(
                    state,
                    evaluation,
                    context,
                    timestamp,
                    signal_id,
                    base_lineage,
                )
                state["processed_evaluations"][evaluation_id] = result
                self._commit(state, "PAPER_EXECUTION", result, evaluation_id)
                return deepcopy(result)

    def cancel_order(self, order_id: str, reason: str = "CANCELLED_BY_STRATEGY") -> Dict[str, Any]:
        with self._lock:
            state = deepcopy(self._state)
            order = self._order(state, order_id)
            if order is None or order["status"] not in {"PENDING", "PARTIAL"}:
                return self._result("NOT_CANCELLED", "ORDER_NOT_CANCELLABLE", order_id=order_id)
            timestamp = _now()
            order.update({"status": "CANCELLED", "cancelled_at": timestamp, "updated_at": timestamp, "rejection_reason": reason})
            self.workspace.order_ledger.append("ORDER_CANCELLED", order, recorded_at=timestamp, idempotency_key=f"{order_id}:CANCELLED")
            result = self._result("CANCELLED", reason, order_id=order_id)
            if order.get("position_effect") == "OPEN" and state.get("lifecycle", {}).get("state") in {"SIGNAL_PENDING", "ENTRY_CONFIRMED"}:
                self._transition(state, "CANCELLED", timestamp, order_id)
                self._transition(state, "POSITION_CLOSED", timestamp, order_id)
                self._transition(state, "IDLE", timestamp, order_id)
            self._commit(state, "ORDER_CANCELLED", result, f"cancel:{order_id}")
            return result

    def expire_order(self, order_id: str, reason: str = "ORDER_EXPIRED") -> Dict[str, Any]:
        with self._lock:
            state = deepcopy(self._state)
            order = self._order(state, order_id)
            if order is None or order["status"] not in {"PENDING", "PARTIAL"}:
                return self._result("NOT_EXPIRED", "ORDER_NOT_EXPIRABLE", order_id=order_id)
            timestamp = _now()
            order.update({"status": "EXPIRED", "expired_at": timestamp, "updated_at": timestamp, "rejection_reason": reason})
            self.workspace.order_ledger.append("ORDER_EXPIRED", order, recorded_at=timestamp, idempotency_key=f"{order_id}:EXPIRED")
            result = self._result("EXPIRED", reason, order_id=order_id)
            if order.get("position_effect") == "OPEN" and state.get("lifecycle", {}).get("state") in {"SIGNAL_PENDING", "ENTRY_CONFIRMED"}:
                self._transition(state, "CANCELLED", timestamp, order_id)
                self._transition(state, "POSITION_CLOSED", timestamp, order_id)
                self._transition(state, "IDLE", timestamp, order_id)
            self._commit(state, "ORDER_EXPIRED", result, f"expire:{order_id}")
            return result

    def projection(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def close_open_position(
        self,
        *,
        price: float,
        reason: str = "MANUAL_PAPER_CLOSE",
        evaluation_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Paper-only manual/strategy close through the same immutable OMS path."""

        with self._lock:
            position = next((row for row in self._state.get("positions") or [] if row.get("status") == "OPEN"), None)
        if position is None:
            return self._result("NO_ACTION", "DUPLICATE_EXIT_SUPPRESSED")
        if _number(price) is None or float(price) <= 0:
            return self._result("REJECTED", "AUTHORITATIVE_PRICE_REQUIRED")
        event_id = evaluation_id or _identifier("manual-close", self.strategy_id, position["position_id"], reason)
        evaluated_at = timestamp or _now()
        return dict(self.process(
            evaluation={
                "evaluation_id": event_id,
                "evaluated_at": evaluated_at,
                "signal": "SELL",
                "position_effect": "CLOSE",
                "side": position["side"],
                "contract": position["contract"],
                "exit": float(price),
                "execution_price": float(price),
                "exit_reason": reason,
                "reason": reason,
            },
            context={"timestamp": evaluated_at, "contract": position["contract"], "current_price": float(price)},
            workspace=self.workspace,
        ))

    def cancel_strategy(self, *, price: Optional[float] = None, timestamp: Optional[str] = None) -> Dict[str, Any]:
        """Cancel pending entries and optionally flatten one open paper position."""

        with self._lock:
            pending = [row["order_id"] for row in self._state.get("orders") or [] if row.get("status") in {"PENDING", "PARTIAL"}]
            has_open = any(row.get("status") == "OPEN" for row in self._state.get("positions") or [])
        cancelled = [self.cancel_order(order_id, "STRATEGY_CANCEL") for order_id in pending]
        if has_open:
            if _number(price) is None or float(price) <= 0:
                return self._result("REJECTED", "AUTHORITATIVE_PRICE_REQUIRED", cancelled_orders=cancelled)
            closed = self.close_open_position(price=float(price), reason="STRATEGY_CANCEL", timestamp=timestamp)
            return {**closed, "cancelled_orders": cancelled}
        return self._result("CANCELLED" if cancelled else "NO_ACTION", "STRATEGY_CANCEL", cancelled_orders=cancelled)

    def record_lineage_event(
        self,
        event_type: str,
        entity_id: str,
        parent_id: Optional[str],
        lineage: Iterable[str],
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        event = self._emit(event_type, entity_id, parent_id, list(lineage), payload)
        return event.to_dict()

    def finalize_decision_lineage(
        self,
        *,
        journal_id: str,
        replay_id: str,
        execution: Mapping[str, Any],
    ) -> None:
        """Publish post-execution lineage after Runtime owns Journal/Replay IDs."""

        lineage = list(execution.get("lineage") or [])
        parent = str(execution.get("entity_id") or execution.get("fill_id") or execution.get("order_id") or execution.get("signal_id") or "")
        journal_lineage = [*lineage, journal_id]
        self._emit("JournalCreated", journal_id, parent or None, journal_lineage, {"strategy_id": self.strategy_id})
        replay_lineage = [*journal_lineage, replay_id]
        self._emit("ReplayCreated", replay_id, journal_id, replay_lineage, {"strategy_id": self.strategy_id})
        statistics_id = str(self._state.get("statistics", {}).get("statistics_id") or _identifier("stats", self.strategy_id, 0))
        statistics_lineage = [*replay_lineage, statistics_id]
        self._emit("StatisticsUpdated", statistics_id, replay_id, statistics_lineage, {"strategy_id": self.strategy_id})
        portfolio_id = str(self._state["portfolio_id"])
        self._emit("DashboardUpdated", portfolio_id, statistics_id, [*statistics_lineage, portfolio_id], {"strategy_id": self.strategy_id, "portfolio_id": portfolio_id})

    def _submit_signal(self, state: Dict[str, Any], evaluation: Mapping[str, Any], context: Mapping[str, Any], timestamp: str, signal_id: str, lineage: List[str]) -> Dict[str, Any]:
        evaluation_id = str(evaluation["evaluation_id"])
        signal = str(evaluation["signal"]).upper()
        contract = str(evaluation.get("contract") or context.get("contract") or evaluation.get("symbol") or context.get("symbol") or "").strip()
        position_effect = str(evaluation.get("position_effect") or ("OPEN" if signal == "BUY" else "CLOSE")).upper()
        side = str(evaluation.get("side") or ("LONG" if signal == "BUY" else "SHORT")).upper()
        order_side = "BUY" if signal == "BUY" else "SELL"
        order_type = str(evaluation.get("order_type") or "MARKET").upper()
        stop = _number(evaluation.get("stop"))
        target = _number(evaluation.get("target"))
        resolved_lot_size = evaluation.get("lot_size")
        if isinstance(resolved_lot_size, bool) or not isinstance(resolved_lot_size, int) or resolved_lot_size <= 0:
            resolved_lot_size = None
        reason = self.policy.validation_reason() if position_effect == "OPEN" else None
        if reason == "FIXED_LOTS_CONFIGURATION_REQUIRED" and resolved_lot_size:
            reason = None
        open_positions = [row for row in state["positions"] if row["status"] == "OPEN"]
        current = None
        if position_effect == "CLOSE":
            position_id = str(evaluation.get("position_id") or "").strip()
            if position_id:
                current = next((row for row in open_positions if str(row.get("position_id") or "") == position_id), None)
            if current is None:
                current = next((row for row in open_positions if str(row.get("contract") or "") == contract), None)
            if current is None and len(open_positions) == 1:
                current = open_positions[0]
            elif current is None and len(open_positions) > 1:
                reason = reason or "OPEN_POSITION_AMBIGUOUS"
            if current is not None:
                contract = str(current["contract"])
                side = str(current["side"]).upper()
        price = (
            self._mark_price_for_contract(context, contract)
            if position_effect == "CLOSE" and current is not None
            else self._authoritative_price(evaluation, context, signal)
        )

        if not contract:
            reason = reason or "CONTRACT_REQUIRED"
        if order_type not in {"MARKET", "LIMIT", "STOP"}:
            reason = reason or "ORDER_TYPE_UNSUPPORTED"
        if price is None or price <= 0:
            reason = reason or ("AUTHORITATIVE_EXIT_PRICE_REQUIRED" if position_effect == "CLOSE" else "AUTHORITATIVE_PRICE_REQUIRED")
        if position_effect not in {"OPEN", "CLOSE"}:
            reason = reason or "POSITION_EFFECT_INVALID"
        if side not in {"LONG", "SHORT"}:
            reason = reason or "POSITION_SIDE_INVALID"
        if position_effect == "CLOSE" and current is None:
            reason = reason or "OPEN_POSITION_NOT_FOUND"
        if position_effect == "OPEN" and open_positions:
            reason = reason or "POSITION_ALREADY_OPEN"
        today = _date(timestamp)
        entries_today = sum(1 for order in state["orders"] if order.get("position_effect") == "OPEN" and _date(order.get("created_at")) == today and order.get("status") in {"FILLED", "PARTIAL"})
        if position_effect == "OPEN" and entries_today >= self.policy.max_trades_per_day:
            reason = reason or "MAX_TRADES_PER_DAY_REACHED"
        if position_effect == "OPEN" and state["account"]["daily_pnl"] <= -self.policy.max_daily_loss:
            reason = reason or "MAX_DAILY_LOSS_REACHED"
        mission_required = (
            position_effect == "OPEN"
            and evaluation.get("mission_required") is True
        )
        invalidation_operator = str(
            evaluation.get("invalidation_operator") or ""
        ).strip()
        if mission_required and stop is None:
            reason = reason or "NUMERIC_INVALIDATION_REQUIRED"
        if mission_required and invalidation_operator not in {"<=", ">="}:
            reason = reason or "INVALIDATION_OPERATOR_REQUIRED"

        quantity = current["quantity"] if position_effect == "CLOSE" and current else self._quantity(state, price, stop, resolved_lot_size)
        if not quantity or quantity <= 0:
            reason = reason or "VALID_QUANTITY_REQUIRED"
        command_risk = evaluation.get("command_risk_configuration")
        conflict_decision = {
            "policy": "NOT_APPLICABLE",
            "decision": "ALLOW",
            "reason": "NO_COMMAND_CONFLICT_POLICY",
            "candidate": {
                "deployment_instance_id": evaluation.get("deployment_instance_id"),
                "strategy_id": evaluation.get("strategy_id"),
                "instrument": evaluation.get("instrument"),
                "direction": evaluation.get("direction"),
                "score": evaluation.get("total_score"),
            },
            "incumbents": [],
        }
        if position_effect == "OPEN" and isinstance(command_risk, Mapping):
            position_rules = (
                command_risk.get("position")
                if isinstance(command_risk.get("position"), Mapping)
                else {}
            )
            session_rules = (
                command_risk.get("session")
                if isinstance(command_risk.get("session"), Mapping)
                else {}
            )
            fixed_lots = position_rules.get("fixed_lots")
            maximum_lots = position_rules.get("maximum_lots")
            if (
                isinstance(fixed_lots, int)
                and isinstance(maximum_lots, int)
                and fixed_lots > maximum_lots
            ):
                reason = reason or "FIXED_LOTS_EXCEEDS_MAXIMUM"
            if price is not None and stop is not None and quantity:
                monetary_risk = abs(float(price) - stop) * int(quantity)
                allowed_risk = _number(position_rules.get("fixed_rupee_risk"))
                if allowed_risk is not None and monetary_risk > allowed_risk:
                    reason = reason or "FIXED_RUPEE_RISK_EXCEEDED"
            try:
                evaluated = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                local_time = evaluated.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
                first_entry = str(session_rules.get("first_entry_time") or "00:00")
                last_entry = str(session_rules.get("last_entry_time") or "23:59")
                if local_time < first_entry or local_time > last_entry:
                    reason = reason or "ENTRY_TIME_WINDOW_CLOSED"
            except ValueError:
                reason = reason or "EVALUATION_TIMESTAMP_INVALID"
            cooldown = session_rules.get("cooldown_seconds")
            prior_entries = [
                row for row in state["orders"]
                if row.get("position_effect") == "OPEN"
                and row.get("status") in {"FILLED", "PARTIAL"}
                and row.get("filled_at")
            ]
            if (
                isinstance(cooldown, (int, float))
                and not isinstance(cooldown, bool)
                and cooldown > 0
                and prior_entries
            ):
                elapsed = _seconds(prior_entries[-1]["filled_at"], timestamp)
                if elapsed is not None and elapsed < float(cooldown):
                    reason = reason or "ENTRY_COOLDOWN_ACTIVE"
            conflict_decision = self._command_conflict_decision(
                evaluation,
                command_risk,
            )
            if conflict_decision["decision"] == "BLOCK":
                reason = reason or str(conflict_decision["reason"])
        margin_required = (price or 0.0) * (quantity or 0.0) * self.policy.margin_rate
        if position_effect == "OPEN":
            combined_limit = self.policy.portfolio_capital_limit
            active_margin_used = 0.0
            if self.workspace and self.workspace.root:
                runtimes_dir = self.workspace.root.parent
                for path in runtimes_dir.glob("**/paper_engine_state.json"):
                    if path.is_file() and path.parent.name != self.strategy_id:
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                other_state = json.load(f)
                                active_margin_used += float(other_state.get("account", {}).get("margin_used") or 0.0)
                        except Exception:
                            pass
            if active_margin_used + margin_required > combined_limit:
                reason = reason or "CAPITAL_UNAVAILABLE"
            elif margin_required > state["account"]["available_margin"]:
                reason = reason or "INSUFFICIENT_AVAILABLE_MARGIN"


        risk_snapshot = (
            deepcopy(dict(current.get("risk_snapshot") or {}))
            if current is not None
            else self._new_risk_snapshot(evaluation, contract, side, price, timestamp)
        )
        order_id = _identifier("ord", self.strategy_id, evaluation_id, order_side, position_effect)
        mission = None
        if position_effect == "OPEN" and not reason and mission_required:
            mission_id = _identifier("mission", self.strategy_id, evaluation_id)
            mission = {
                "mission_id": mission_id,
                "strategy_id": evaluation.get("strategy_id") or self.strategy_id,
                "strategy_version": evaluation.get("strategy_version"),
                "deployment_instance_id": evaluation.get("deployment_instance_id") or self.strategy_id,
                "configuration_hash": evaluation.get("configuration_hash"),
                "instrument": evaluation.get("instrument") or context.get("underlying") or context.get("symbol"),
                "timeframe_set": deepcopy(dict(evaluation.get("timeframe_set") or {})),
                "execution_path": evaluation.get("execution_path"),
                "direction": evaluation.get("direction"),
                "contract": contract,
                "option_contract": deepcopy(dict(evaluation.get("option_contract") or {})),
                "contract_selection": deepcopy(dict(evaluation.get("contract_selection") or {})),
                "entry_policy": evaluation.get("entry_condition") or evaluation.get("reason"),
                "entry_zone": evaluation.get("entry_zone"),
                "invalidation": stop,
                "invalidation_operator": invalidation_operator,
                "targets": list(evaluation.get("targets") or ([target] if target is not None else [])),
                "lots": self.policy.fixed_lots,
                "quantity": quantity,
                "monetary_risk": (
                    round(abs(float(price) - stop) * int(quantity), 8)
                    if price is not None and stop is not None and quantity
                    else None
                ),
                "maximum_permitted_loss": self.policy.fixed_rupee_risk,
                "timeframe_evidence": deepcopy(dict(evaluation.get("timeframe_consensus") or {})),
                "decision_evidence": deepcopy(dict(evaluation.get("decision") or {})),
                "conflict_decision": deepcopy(conflict_decision),
                "authoritative_input_timestamps": deepcopy(dict(evaluation.get("input_freshness") or {})),
                "created_at": timestamp,
                "expires_at": evaluation.get("expires_at"),
                "status": "MISSION_READY",
                "paper_only": True,
                "live_trading_enabled": False,
                "broker_submission": False,
            }
            state["missions"].append(mission)
            self._emit(
                "MissionCreated",
                mission_id,
                signal_id,
                [*lineage, mission_id],
                {"mission": deepcopy(mission)},
            )
        elif position_effect == "CLOSE" and current is not None:
            mission_id = current.get("mission_id")
            mission = next(
                (
                    row for row in state.get("missions") or []
                    if row.get("mission_id") == mission_id
                ),
                None,
            )
        oracle_entry_context = (
            self._oracle_entry_context(
                strategy_id=self.strategy_id,
                order_id=order_id,
                candidate_signal_id=signal_id,
                contract=contract,
                evaluation=evaluation,
                context=context,
                risk_snapshot=risk_snapshot,
                quantity=quantity,
                entry_price=price,
                timestamp=timestamp,
            )
            if position_effect == "OPEN" and not reason
            else None
        )
        if oracle_entry_context is not None:
            try:
                self._emit(
                    "TradeCandidateFormed",
                    signal_id,
                    evaluation_id,
                    [*lineage, signal_id],
                    {"strategy_id": self.strategy_id, "candidate": deepcopy(oracle_entry_context)},
                )
            except Exception:
                # Personal ORACLE shadow subscribers are strictly fail-open.
                pass
        order = {
            "order_id": order_id,
            "mission_id": mission.get("mission_id") if mission else None,
            "strategy_id": self.strategy_id,
            "canonical_strategy_id": evaluation.get("strategy_id"),
            "strategy_version": evaluation.get("strategy_version"),
            "deployment_instance_id": evaluation.get("deployment_instance_id"),
            "configuration_hash": evaluation.get("configuration_hash"),
            "evaluation_id": evaluation_id,
            "signal_id": signal_id,
            "parent_id": mission.get("mission_id") if mission else signal_id,
            "lineage": [
                *lineage,
                *([mission["mission_id"]] if mission else []),
                order_id,
            ],
            "replay_id": evaluation.get("replay_id"),
            "position_id": current.get("position_id") if current else None,
            "contract": contract or None,
            "side": order_side,
            "position_side": side,
            "position_effect": position_effect,
            "order_type": order_type,
            "requested_quantity": quantity,
            "filled_quantity": 0,
            "remaining_quantity": quantity,
            "limit_price": _number(evaluation.get("limit_price")),
            "stop_price": _number(evaluation.get("stop_price")),
            "protective_stop": risk_snapshot.get("protective_stop") if position_effect == "OPEN" else current.get("protective_stop") if current else stop,
            "initial_stop": risk_snapshot.get("initial_stop"),
            "current_stop": risk_snapshot.get("current_stop"),
            "initial_risk_per_unit": risk_snapshot.get("initial_risk_per_unit"),
            "target_price": risk_snapshot.get("target") if position_effect == "OPEN" else current.get("target") if current else target,
            "trailing_enabled": risk_snapshot.get("trailing_enabled"),
            "trailing_activation_price": risk_snapshot.get("trailing_activation_price"),
            "trailing_anchor": risk_snapshot.get("trailing_anchor"),
            "trailing_distance": risk_snapshot.get("trailing_distance"),
            "trailing_step": risk_snapshot.get("trailing_step"),
            "risk_source": risk_snapshot.get("risk_source"),
            "risk_source_timestamp": risk_snapshot.get("risk_source_timestamp"),
            "strategy_version": risk_snapshot.get("strategy_version"),
            "risk_rule_version": risk_snapshot.get("risk_rule_version"),
            "risk_snapshot": risk_snapshot,
            "oracle_entry_context": oracle_entry_context,
            "conflict_decision": deepcopy(conflict_decision),
            "lot_size": resolved_lot_size or self.policy.lot_size,
            "option_contract": current.get("option_contract") if current else evaluation.get("option_contract"),
            "underlying_stop": evaluation.get("underlying_stop"),
            "underlying_target": evaluation.get("underlying_target"),
            "exit_reference_type": current.get("exit_reference_type") if current else evaluation.get("exit_reference_type"),
            "exit_reference_id": current.get("exit_reference_id") if current else evaluation.get("exit_reference_id"),
            "exit_reference_instrument": current.get("exit_reference_instrument") if current else evaluation.get("exit_reference_instrument"),
            "exit_reference_timeframe": current.get("exit_reference_timeframe") if current else evaluation.get("exit_reference_timeframe"),
            "exit_reference_rule_version": current.get("exit_reference_rule_version") if current else evaluation.get("exit_reference_rule_version"),
            "exit_reason": evaluation.get("exit_reason") or evaluation.get("reason"),
            "status": "REJECTED" if reason else "PENDING",
            "rejection_reason": reason,
            "created_at": timestamp,
            "updated_at": timestamp,
            "filled_at": None,
            "cancelled_at": None,
            "expired_at": None,
            "expires_at": evaluation.get("expires_at"),
            "paper_only": True,
        }
        state["orders"].append(order)
        self._emit(
            "ConflictEvaluated",
            order_id,
            signal_id,
            order["lineage"],
            {"conflict_decision": deepcopy(conflict_decision)},
        )
        created_type = "ORDER_REJECTED" if reason else "ORDER_CREATED"
        self.workspace.order_ledger.append(created_type, order, recorded_at=timestamp, idempotency_key=f"{order_id}:{created_type}")
        if reason:
            if signal == "BUY" and state.get("lifecycle", {}).get("state") == "SIGNAL_PENDING":
                self._transition(state, "CANCELLED", timestamp, order_id)
                self._transition(state, "POSITION_CLOSED", timestamp, order_id)
                self._transition(state, "IDLE", timestamp, order_id)
            self._write_risk(state, "REJECTED", reason, order, timestamp)
            self._emit("RiskRejected", order_id, signal_id, order["lineage"], {"reason": reason, "order": order})
            return self._result("REJECTED", reason, evaluation_id=evaluation_id, signal_id=signal_id, order_id=order_id, order_status="REJECTED", entity_id=order_id, lineage=order["lineage"])

        if mission is not None:
            mission["status"] = "ORDER_WORKING"
            mission["paper_order_id"] = order_id
            mission["updated_at"] = timestamp
        self._write_risk(state, "AUTHORIZED", "PAPER_RISK_AUTHORIZED", order, timestamp)
        self._emit("OrderCreated", order_id, signal_id, order["lineage"], {"order": order})
        return self._fill_order(state, order, price, context, evaluation, timestamp)

    def _command_conflict_decision(
        self,
        evaluation: Mapping[str, Any],
        command_risk: Mapping[str, Any],
    ) -> Dict[str, Any]:
        conflict = (
            command_risk.get("conflict")
            if isinstance(command_risk.get("conflict"), Mapping)
            else {}
        )
        policy = str(conflict.get("policy") or "ONE_TRADE_PER_INSTRUMENT").upper()
        candidate = {
            "deployment_instance_id": evaluation.get("deployment_instance_id"),
            "strategy_id": evaluation.get("strategy_id"),
            "instrument": str(evaluation.get("instrument") or "").upper() or None,
            "direction": str(evaluation.get("direction") or "NONE").upper(),
            "score": _number(evaluation.get("total_score")),
            "priority": conflict.get("priority"),
            "evaluated_at": evaluation.get("evaluated_at"),
        }
        if policy == "INDEPENDENT_EXECUTION":
            return {
                "policy": policy,
                "decision": "ALLOW",
                "reason": "INDEPENDENT_EXECUTION",
                "candidate": candidate,
                "incumbents": [],
            }
        incumbents: List[Dict[str, Any]] = []
        runtimes_dir = self.workspace.root.parent
        for path in sorted(runtimes_dir.glob("*/paper_engine_state.json")):
            if path.parent == self.workspace.root:
                continue
            try:
                other = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            active_positions = [
                row
                for row in other.get("positions") or []
                if isinstance(row, Mapping) and row.get("status") == "OPEN"
            ]
            active_orders = [
                row
                for row in other.get("orders") or []
                if isinstance(row, Mapping)
                and row.get("position_effect") == "OPEN"
                and row.get("status") in {"PENDING", "PARTIAL"}
            ]
            if not active_positions and not active_orders:
                continue
            missions = {
                str(row.get("mission_id")): row
                for row in other.get("missions") or []
                if isinstance(row, Mapping) and row.get("mission_id")
            }
            for active in [*active_positions, *active_orders]:
                mission = missions.get(str(active.get("mission_id") or ""), {})
                option = active.get("option_contract")
                option_map = option if isinstance(option, Mapping) else {}
                incumbent = {
                    "deployment_instance_id": active.get("deployment_instance_id")
                    or other.get("strategy_id"),
                    "strategy_id": active.get("canonical_strategy_id")
                    or active.get("strategy_id"),
                    "instrument": str(
                        mission.get("instrument")
                        or option_map.get("underlying")
                        or ""
                    ).upper() or None,
                    "direction": str(
                        mission.get("direction")
                        or (
                            "CALL"
                            if option_map.get("option_type") == "CE"
                            else "PUT"
                            if option_map.get("option_type") == "PE"
                            else "NONE"
                        )
                    ).upper(),
                    "score": _number(
                        (mission.get("decision_evidence") or {}).get("total_score")
                        if isinstance(mission.get("decision_evidence"), Mapping)
                        else None
                    ),
                    "entity_id": active.get("position_id") or active.get("order_id"),
                    "status": active.get("status"),
                }
                same_instrument = (
                    candidate["instrument"] is not None
                    and incumbent["instrument"] == candidate["instrument"]
                )
                same_strategy = (
                    candidate["strategy_id"] is not None
                    and incumbent["strategy_id"] == candidate["strategy_id"]
                )
                opposing = (
                    same_instrument
                    and {candidate["direction"], incumbent["direction"]}
                    == {"CALL", "PUT"}
                )
                relevant = (
                    policy == "ONE_TRADE_PER_INSTRUMENT" and same_instrument
                    or policy == "ONE_TRADE_PER_STRATEGY" and same_strategy
                    or policy == "BLOCK_OPPOSING_DIRECTION" and opposing
                    or policy == "REQUIRE_AGREEMENT" and same_instrument
                    or policy in {
                        "HIGHEST_SCORE_WINS",
                        "HIGHEST_PRIORITY_WINS",
                        "EARLIEST_SIGNAL_WINS",
                        "USER_DEFINED_CAPITAL_ALLOCATION",
                    }
                    and same_instrument
                )
                if relevant:
                    incumbents.append(incumbent)
        if not incumbents:
            return {
                "policy": policy,
                "decision": "ALLOW",
                "reason": "NO_CONFLICTING_ACTIVE_CANDIDATE",
                "candidate": candidate,
                "incumbents": [],
            }
        if policy == "REQUIRE_AGREEMENT" and all(
            row["direction"] == candidate["direction"] for row in incumbents
        ):
            return {
                "policy": policy,
                "decision": "ALLOW",
                "reason": "ACTIVE_CANDIDATES_AGREE",
                "candidate": candidate,
                "incumbents": incumbents,
            }
        return {
            "policy": policy,
            "decision": "BLOCK",
            "reason": f"CONFLICT_POLICY_{policy}_ACTIVE",
            "candidate": candidate,
            "incumbents": incumbents,
        }

    def _quantity(self, state: Mapping[str, Any], entry: float, stop: Optional[float], resolved_lot_size: Optional[int] = None) -> Optional[int]:
        lot = resolved_lot_size or self.policy.lot_size or 1
        if self.policy.sizing_mode == "FIXED_LOTS":
            return (self.policy.fixed_lots or 0) * lot
        distance = abs(entry - stop) if stop is not None else 0.0
        if distance <= 0:
            return None
        if self.policy.sizing_mode == "FIXED_RUPEE_RISK":
            budget = self.policy.fixed_rupee_risk or 0.0
        elif self.policy.sizing_mode == "FIXED_PERCENT":
            budget = state["account"]["current_equity"] * (self.policy.fixed_risk_percent or 0.0) / 100.0
        else:
            return None
        units = int(budget // distance)
        return (units // lot) * lot if units >= lot else None

    def _fill_order(self, state: Dict[str, Any], order: Dict[str, Any], price: float, context: Mapping[str, Any], evaluation: Mapping[str, Any], timestamp: str) -> Dict[str, Any]:
        market_context = {**context}
        if evaluation.get("available_quantity") is not None:
            market_context["available_quantity"] = evaluation.get("available_quantity")
        report = self.execution_provider.execute(
            order=order,
            market_context=market_context,
            reference_price=price,
            fee_rate_bps=self.policy.fee_rate_bps,
            flat_fee_per_fill=self.policy.flat_fee_per_fill,
            slippage_bps=self.policy.slippage_bps,
        )
        if report.status == "PENDING":
            return self._result("PENDING", report.reason, evaluation_id=order["evaluation_id"], signal_id=order["signal_id"], order_id=order["order_id"], order_status=order["status"], entity_id=order["order_id"], lineage=order["lineage"])
        fill_quantity = report.quantity
        fill_price = float(report.price)
        fees = report.fees
        sequence = 1 + sum(1 for row in state["fills"] if row["order_id"] == order["order_id"])
        fill_id = _identifier("fill", order["order_id"], sequence, fill_quantity, fill_price)
        fill = {
            "fill_id": fill_id,
            "order_id": order["order_id"],
            "mission_id": order.get("mission_id"),
            "signal_id": order["signal_id"],
            "parent_id": order["order_id"],
            "lineage": list(order["lineage"]),
            "strategy_id": self.strategy_id,
            "canonical_strategy_id": order.get("canonical_strategy_id"),
            "strategy_version": order.get("strategy_version"),
            "deployment_instance_id": order.get("deployment_instance_id"),
            "configuration_hash": order.get("configuration_hash"),
            "replay_id": order.get("replay_id"),
            "contract": order["contract"],
            "side": order["side"],
            "position_side": order["position_side"],
            "position_effect": order["position_effect"],
            "time": timestamp,
            "price": round(fill_price, 8),
            "quantity": fill_quantity,
            "fees": round(fees, 8),
            "slippage": report.slippage,
            "slippage_per_unit": report.slippage_per_unit,
            "paper_only": True,
        }
        fill["lineage"] = [*order["lineage"], fill_id]
        state["fills"].append(fill)
        self.workspace.fill_ledger.append("PAPER_FILL", fill, recorded_at=timestamp, idempotency_key=fill_id)
        self._emit("OrderFilled", fill_id, order["order_id"], fill["lineage"], {"fill": fill})
        order["filled_quantity"] += fill_quantity
        order["remaining_quantity"] -= fill_quantity
        order["status"] = "FILLED" if order["remaining_quantity"] == 0 else "PARTIAL"
        order["filled_at"] = timestamp if order["status"] == "FILLED" else None
        order["updated_at"] = timestamp
        if order.get("mission_id"):
            mission = next(
                (
                    row for row in state.get("missions") or []
                    if row.get("mission_id") == order.get("mission_id")
                ),
                None,
            )
            if mission is not None:
                mission["status"] = (
                    "GUARDIAN_ACTIVE"
                    if order["position_effect"] == "OPEN"
                    else "EXITING"
                )
                mission["fill_id"] = fill_id
                mission["updated_at"] = timestamp
        self.workspace.order_ledger.append(f"ORDER_{order['status']}", order, recorded_at=timestamp, idempotency_key=f"{order['order_id']}:{order['status']}:{order['filled_quantity']}")
        if order["position_effect"] == "OPEN":
            self._apply_open_fill(state, order, fill, evaluation, timestamp)
        else:
            self._apply_close_fill(state, order, fill, timestamp)
        return self._result(order["status"], "PAPER_FILL_RECORDED", evaluation_id=order["evaluation_id"], signal_id=order["signal_id"], order_id=order["order_id"], fill_id=fill_id, order_status=order["status"], entity_id=fill_id, lineage=fill["lineage"])

    def _apply_open_fill(self, state: Dict[str, Any], order: Mapping[str, Any], fill: Mapping[str, Any], evaluation: Mapping[str, Any], timestamp: str) -> None:
        position = next((row for row in state["positions"] if row["status"] == "OPEN" and row["contract"] == order["contract"]), None)
        created = position is None
        if position is None:
            risk_snapshot = deepcopy(dict(order.get("risk_snapshot") or {}))
            protective_stop = _number(risk_snapshot.get("current_stop"))
            target_price = _number(risk_snapshot.get("target"))
            initial_stop = _number(risk_snapshot.get("initial_stop"))
            initial_risk = abs(fill["price"] - initial_stop) if initial_stop is not None else None
            position_id = _identifier("pos", self.strategy_id, order["order_id"])
            entry_context = deepcopy(dict(order.get("oracle_entry_context") or {}))
            entry_context.update({
                "source_trade_id": _identifier("trade", self.strategy_id, order["order_id"]),
                "position_id": position_id,
                "entry_price": fill["price"],
                "entry_timestamp": timestamp,
                "capture_timestamp": timestamp,
            })
            entry_context = self._complete_oracle_entry_context(entry_context)
            if isinstance(order, dict):
                order["oracle_entry_context"] = deepcopy(entry_context)
            risk_snapshot.update({
                "position_id": position_id,
                "held_security_id": str(order["contract"]),
                "initial_risk_per_unit": initial_risk,
            })
            risk_snapshot["risk_status"] = self._risk_status(risk_snapshot)
            risk_audit = [{
                "event": "POSITION_RISK_INITIALIZED",
                "timestamp": timestamp,
                "position_id": position_id,
                "held_security_id": str(order["contract"]),
                "initial_stop": initial_stop,
                "current_stop": protective_stop,
                "underlying_initial_stop": risk_snapshot.get("underlying_initial_stop"),
                "underlying_current_stop": risk_snapshot.get("underlying_current_stop"),
            }]
            position = {
                "position_id": position_id,
                "trade_id": _identifier("trade", self.strategy_id, order["order_id"]),
                "mission_id": order.get("mission_id"),
                "strategy_id": self.strategy_id,
                "canonical_strategy_id": order.get("canonical_strategy_id"),
                "strategy_version": order.get("strategy_version"),
                "deployment_instance_id": order.get("deployment_instance_id"),
                "configuration_hash": order.get("configuration_hash"),
                "replay_id": order.get("replay_id"),
                "signal_id": order.get("signal_id"),
                "parent_id": fill["fill_id"],
                "lineage": [*fill["lineage"], _identifier("pos", self.strategy_id, order["order_id"])],
                "contract": order["contract"],
                "side": order["position_side"],
                "quantity": 0,
                "entry": fill["price"],
                "exit": None,
                "average_price": 0.0,
                "current_price": None,
                "pnl": None,
                "pnl_valid": False,
                "pnl_status": "MTM_UNAVAILABLE",
                "quote_timestamp": None,
                "quote_age_seconds": None,
                "quote_source": None,
                "quote_security_id": order["contract"],
                "quote_status": "UNAVAILABLE",
                "quote_stale_reason": "HELD_CONTRACT_QUOTE_PENDING",
                "mfe": 0.0,
                "mae": 0.0,
                "duration_seconds": 0.0,
                "rr": None,
                "held_security_id": str(order["contract"]),
                "protective_stop": protective_stop,
                "initial_stop": initial_stop,
                "current_stop": protective_stop,
                "stop": protective_stop,
                "target": target_price,
                "underlying_stop": risk_snapshot.get("underlying_current_stop"),
                "underlying_initial_stop": risk_snapshot.get("underlying_initial_stop"),
                "underlying_current_stop": risk_snapshot.get("underlying_current_stop"),
                "underlying_target": order.get("underlying_target"),
                "exit_reference_type": order.get("exit_reference_type"),
                "exit_reference_id": order.get("exit_reference_id"),
                "exit_reference_instrument": order.get("exit_reference_instrument"),
                "exit_reference_timeframe": order.get("exit_reference_timeframe"),
                "exit_reference_rule_version": order.get("exit_reference_rule_version"),
                "option_contract": order.get("option_contract"),
                "initial_risk_per_unit": initial_risk,
                "trailing_enabled": risk_snapshot.get("trailing_enabled"),
                "trailing_activation_price": risk_snapshot.get("trailing_activation_price"),
                "trailing_anchor": risk_snapshot.get("trailing_anchor"),
                "trailing_distance": risk_snapshot.get("trailing_distance"),
                "trailing_step": risk_snapshot.get("trailing_step"),
                "last_stop_update_time": risk_snapshot.get("last_stop_update_time"),
                "risk_source": risk_snapshot.get("risk_source"),
                "risk_source_timestamp": risk_snapshot.get("risk_source_timestamp"),
                "strategy_version": risk_snapshot.get("strategy_version"),
                "risk_rule_version": risk_snapshot.get("risk_rule_version"),
                "risk_status": risk_snapshot.get("risk_status"),
                "risk_snapshot": risk_snapshot,
                "risk_audit": risk_audit,
                "oracle_entry_context": deepcopy(entry_context),
                "entry_fees": 0.0,
                "exit_fees": 0.0,
                "realized_gross_pnl": 0.0,
                "entry_time": timestamp,
                "exit_time": None,
                "status": "OPEN",
            }
            state["positions"].append(position)
            self._emit(
                "PositionRiskInitialized",
                position_id,
                fill["fill_id"],
                position["lineage"],
                {
                    "position": deepcopy(position),
                    "risk_snapshot": risk_snapshot,
                },
            )
        old_quantity = position["quantity"]
        new_quantity = old_quantity + fill["quantity"]
        position["average_price"] = round((position["average_price"] * old_quantity + fill["price"] * fill["quantity"]) / new_quantity, 8)
        position["entry"] = position["average_price"]
        position["quantity"] = new_quantity
        position["entry_fees"] = round(position["entry_fees"] + fill["fees"], 8)
        if not created:
            self._mark_position(position, fill["price"], timestamp)
        if created:
            if state.get("lifecycle", {}).get("state") == "SIGNAL_PENDING":
                self._transition(state, "ENTRY_CONFIRMED", timestamp, order["order_id"])
            self._transition(state, "POSITION_OPEN", timestamp, position["position_id"])
            self._transition(state, "MANAGING", timestamp, position["position_id"])
            self._emit("PositionOpened", position["position_id"], fill["fill_id"], position["lineage"], {"position": position})

    def _apply_close_fill(self, state: Dict[str, Any], order: Mapping[str, Any], fill: Mapping[str, Any], timestamp: str) -> None:
        position = next((row for row in state["positions"] if row["status"] == "OPEN" and row["contract"] == order["contract"]), None)
        if position is None:
            raise RuntimeError("OPEN_POSITION_DISAPPEARED")
        quantity = min(position["quantity"], fill["quantity"])
        multiplier = 1.0 if position["side"] == "LONG" else -1.0
        gross = (fill["price"] - position["average_price"]) * quantity * multiplier
        position["realized_gross_pnl"] = round(position["realized_gross_pnl"] + gross, 8)
        position["exit_fees"] = round(position["exit_fees"] + fill["fees"], 8)
        position["quantity"] -= quantity
        position["exit"] = fill["price"]
        position["exit_time"] = timestamp
        if position["quantity"] == 0:
            position["status"] = "CLOSED"
            position["current_price"] = fill["price"]
            position["pnl"] = 0.0
            position["duration_seconds"] = _seconds(position["entry_time"], timestamp)
            net = position["realized_gross_pnl"] - position["entry_fees"] - position["exit_fees"]
            risk = position.get("initial_risk_per_unit")
            initial_quantity = sum(row["quantity"] for row in state["fills"] if row["position_effect"] == "OPEN" and row["contract"] == position["contract"] and row.get("replay_id") == position.get("replay_id"))
            position["rr"] = round(net / (risk * initial_quantity), 8) if risk and initial_quantity else None
            trade = deepcopy(position)
            trade["exit_reason"] = str(order.get("exit_reason") or "UNSPECIFIED")
            trade["exit_trigger"] = order.get("exit_reason") or "UNSPECIFIED"
            trade["guardian_contribution"] = (
                "PAPER_GUARDIAN"
                if str(order.get("exit_reason") or "").upper()
                in {
                    "TARGET",
                    "STOP",
                    "STOP_LOSS",
                    "LEG_STOP_LOSS_HIT",
                    "OVERALL_LOCKED_PROFIT_TRIGGERED",
                    "SESSION_EXIT",
                    "SESSION_SQUARE_OFF",
                    "FORCED_SQUARE_OFF",
                }
                else "NOT_APPLICABLE"
            )
            trade["realized_pnl"] = round(net, 8)
            state["closed_trades"].append(trade)
            if position.get("mission_id"):
                mission = next(
                    (
                        row for row in state.get("missions") or []
                        if row.get("mission_id") == position.get("mission_id")
                    ),
                    None,
                )
                if mission is not None:
                    mission.update({
                        "status": "EXITED",
                        "exit_order_id": order.get("order_id"),
                        "exit_fill_id": fill.get("fill_id"),
                        "trade_id": trade.get("trade_id"),
                        "realized_pnl": trade["realized_pnl"],
                        "exit_reason": trade["exit_reason"],
                        "updated_at": timestamp,
                    })
            terminal = self._exit_lifecycle_state(str(order.get("exit_reason") or ""))
            self._transition(state, terminal, timestamp, order["order_id"])
            self._transition(state, "POSITION_CLOSED", timestamp, position["position_id"])
            self._transition(state, "IDLE", timestamp, position["position_id"])
            self.workspace.journal.append("TRADE_CLOSED", trade, recorded_at=timestamp, idempotency_key=trade["trade_id"])
            self._emit("PositionClosed", position["position_id"], fill["fill_id"], [*position["lineage"], fill["fill_id"]], {"position": position})
            self._emit("TradeCompleted", trade["trade_id"], position["position_id"], [*position["lineage"], trade["trade_id"]], {"trade": trade})

    def _mark_positions(self, state: Dict[str, Any], context: Mapping[str, Any], timestamp: str) -> bool:
        changed = False
        for position in state["positions"]:
            if position["status"] != "OPEN":
                continue
            quote = self._mark_quote_for_contract(context, str(position.get("contract") or ""), timestamp)
            price = quote.get("price")
            if price is not None and price > 0:
                self._mark_position(position, price, timestamp)
                position.update({
                    "quote_timestamp": quote.get("timestamp"), "quote_age_seconds": quote.get("age_seconds"),
                    "quote_source": quote.get("source"), "quote_security_id": quote.get("security_id"),
                    "quote_status": quote.get("status"), "quote_stale_reason": quote.get("reason"),
                    "pnl_valid": quote.get("status") == "FRESH",
                    "pnl_status": "AVAILABLE" if quote.get("status") == "FRESH" else "MTM_STALE",
                })
                self._record_stop_breach(position, price, quote, timestamp, state)
            else:
                position.update({
                    "quote_status": "UNAVAILABLE", "quote_stale_reason": quote.get("reason") or "HELD_CONTRACT_QUOTE_UNAVAILABLE",
                    "quote_security_id": str(position.get("contract") or ""), "pnl_valid": False,
                    "pnl_status": "MTM_UNAVAILABLE",
                })
            changed = True
        if changed:
            self._revalue(state, timestamp)
        return changed

    @staticmethod
    def _risk_status(snapshot: Mapping[str, Any]) -> str:
        reported = (
            "initial_stop", "current_stop", "underlying_initial_stop", "underlying_current_stop",
            "target", "trailing_enabled", "trailing_activation_price", "trailing_anchor",
            "trailing_distance", "trailing_step",
        )
        return "REPORTED" if any(snapshot.get(key) is not None for key in reported) else "NOT_REPORTED"

    _ORACLE_CONTEXT_FIELDS = (
        "source_trade_id", "entry_timestamp", "instrument", "underlying", "option_side",
        "strike", "expiry", "strategy", "setup", "timeframe", "entry_reason",
        "signal_price", "reference_price", "stop_loss", "target", "market_regime",
        "quantity", "entry_price", "data_provenance", "capture_timestamp",
    )

    @classmethod
    def _complete_oracle_entry_context(cls, context: Mapping[str, Any]) -> Dict[str, Any]:
        result = deepcopy(dict(context))
        missing = [key for key in cls._ORACLE_CONTEXT_FIELDS if result.get(key) is None or result.get(key) == ""]
        result["missing_reasons"] = {key: "SOURCE_NOT_REPORTED_AT_ENTRY" for key in missing}
        result["missing_context_fields"] = missing
        result["context_completeness_percentage"] = round(
            100.0 * (len(cls._ORACLE_CONTEXT_FIELDS) - len(missing)) / len(cls._ORACLE_CONTEXT_FIELDS), 2
        )
        result["context_captured"] = True
        result["context_schema_version"] = 1
        return result

    @classmethod
    def _oracle_entry_context(
        cls,
        *,
        strategy_id: str,
        order_id: str,
        candidate_signal_id: str,
        contract: str,
        evaluation: Mapping[str, Any],
        context: Mapping[str, Any],
        risk_snapshot: Mapping[str, Any],
        quantity: Optional[int],
        entry_price: Optional[float],
        timestamp: str,
    ) -> Dict[str, Any]:
        option = dict(evaluation.get("option_contract") or {}) if isinstance(evaluation.get("option_contract"), Mapping) else {}

        def reported(*values: Any) -> Any:
            return next((value for value in values if value is not None and value != ""), None)

        position_id = _identifier("pos", strategy_id, order_id)
        trade_id = _identifier("trade", strategy_id, order_id)
        return cls._complete_oracle_entry_context({
            "source_trade_id": trade_id,
            "candidate_signal_id": candidate_signal_id,
            "position_id": position_id,
            "entry_timestamp": timestamp,
            "instrument": reported(option.get("trading_symbol"), evaluation.get("symbol"), context.get("symbol"), contract),
            "contract_security_id": str(reported(option.get("security_id"), contract)) if reported(option.get("security_id"), contract) is not None else None,
            "underlying": reported(option.get("underlying"), evaluation.get("underlying"), context.get("underlying")),
            "option_side": reported(option.get("option_type"), evaluation.get("option_type")),
            "strike": _number(reported(option.get("strike"), evaluation.get("strike"))),
            "expiry": reported(option.get("expiry"), evaluation.get("expiry")),
            "strategy": strategy_id,
            "setup": reported(evaluation.get("setup_tag"), evaluation.get("setup")),
            "timeframe": reported(evaluation.get("timeframe"), context.get("timeframe")),
            "entry_reason": reported(evaluation.get("entry_reason"), evaluation.get("reason")),
            "signal_price": _number(reported(evaluation.get("signal_price"), evaluation.get("entry"))),
            "reference_price": _number(reported(evaluation.get("reference_price"), evaluation.get("entry_reference_price"), context.get("reference_price"))),
            "stop_loss": _number(risk_snapshot.get("current_stop")),
            "underlying_stop": _number(risk_snapshot.get("underlying_current_stop")),
            "target": _number(risk_snapshot.get("target")),
            "underlying_target": _number(evaluation.get("underlying_target")),
            "market_regime": reported(evaluation.get("market_regime"), context.get("market_regime")),
            "quantity": quantity,
            "entry_price": entry_price,
            "data_provenance": "STRATEGY_LAB_PAPER_ENGINE_ENTRY",
            "provenance": {
                "evaluation_id": evaluation.get("evaluation_id"),
                "market_context_timestamp": context.get("timestamp"),
                "option_contract_source": option.get("instrument_source"),
                "quote_source": option.get("quote_source"),
            },
            "capture_timestamp": timestamp,
        })

    @classmethod
    def _new_risk_snapshot(
        cls,
        evaluation: Mapping[str, Any],
        contract: str,
        side: str,
        entry_price: Optional[float],
        timestamp: str,
    ) -> Dict[str, Any]:
        initial_option_stop = _number(evaluation.get("initial_stop"))
        current_option_stop = _number(evaluation.get("current_stop"))
        legacy_option_stop = _number(evaluation.get("stop"))
        if initial_option_stop is None:
            initial_option_stop = current_option_stop if current_option_stop is not None else legacy_option_stop
        if current_option_stop is None:
            current_option_stop = legacy_option_stop if legacy_option_stop is not None else initial_option_stop
        underlying_initial_stop = _number(evaluation.get("underlying_initial_stop"))
        underlying_current_stop = _number(evaluation.get("underlying_current_stop"))
        legacy_underlying_stop = _number(evaluation.get("underlying_stop"))
        if underlying_initial_stop is None:
            underlying_initial_stop = underlying_current_stop if underlying_current_stop is not None else legacy_underlying_stop
        if underlying_current_stop is None:
            underlying_current_stop = legacy_underlying_stop if legacy_underlying_stop is not None else underlying_initial_stop
        target = _number(evaluation.get("target"))
        snapshot = {
            "schema_version": 1,
            "position_id": None,
            "held_security_id": str(contract),
            "side": str(side).upper(),
            "initial_stop": initial_option_stop,
            "current_stop": current_option_stop,
            "protective_stop": current_option_stop,
            "initial_risk_per_unit": abs(float(entry_price) - initial_option_stop) if entry_price is not None and initial_option_stop is not None else None,
            "target": target,
            "underlying_initial_stop": underlying_initial_stop,
            "underlying_current_stop": underlying_current_stop,
            "trailing_enabled": _optional_bool(evaluation.get("trailing_enabled")),
            "trailing_activation_price": _number(evaluation.get("trailing_activation_price")),
            "trailing_anchor": _number(evaluation.get("trailing_anchor")),
            "trailing_distance": _number(evaluation.get("trailing_distance")),
            "trailing_step": _number(evaluation.get("trailing_step")),
            "last_stop_update_time": timestamp if current_option_stop is not None or underlying_current_stop is not None else None,
            "risk_source": _optional_text(evaluation.get("risk_source")),
            "risk_source_timestamp": _optional_text(evaluation.get("risk_source_timestamp")) or timestamp,
            "strategy_version": _optional_text(evaluation.get("strategy_version")),
            "risk_rule_version": _optional_text(evaluation.get("risk_rule_version")),
        }
        snapshot["risk_status"] = cls._risk_status(snapshot)
        return snapshot

    def _sync_position_risk(self, state: Dict[str, Any], evaluation: Mapping[str, Any], timestamp: str) -> bool:
        position_id = _optional_text(evaluation.get("risk_position_id") or evaluation.get("position_id"))
        contract = _optional_text(evaluation.get("risk_contract"))
        if not position_id or not contract:
            return False
        position = next((
            row for row in state.get("positions") or []
            if row.get("status") == "OPEN"
            and str(row.get("position_id") or "") == position_id
            and str(row.get("contract") or "") == contract
        ), None)
        if position is None:
            return False
        snapshot = deepcopy(dict(position.get("risk_snapshot") or {}))
        before = deepcopy(snapshot)
        side = str(position.get("side") or "LONG").upper()

        def monotonic(key: str, candidate: Optional[float]) -> None:
            if candidate is None:
                return
            prior = _number(snapshot.get(key))
            allowed = prior is None or (candidate >= prior if side == "LONG" else candidate <= prior)
            if allowed:
                snapshot[key] = candidate

        explicit_option_stop = _number(evaluation.get("current_stop"))
        if explicit_option_stop is None and "stop" in evaluation:
            explicit_option_stop = _number(evaluation.get("stop"))
        monotonic("current_stop", explicit_option_stop)
        monotonic("underlying_current_stop", _number(evaluation.get("underlying_stop")))
        if snapshot.get("current_stop") is not None:
            snapshot["protective_stop"] = snapshot["current_stop"]
        if "target" in evaluation and _number(evaluation.get("target")) is not None:
            snapshot["target"] = _number(evaluation.get("target"))
        for key in ("trailing_activation_price", "trailing_anchor", "trailing_distance", "trailing_step"):
            value = _number(evaluation.get(key))
            if value is not None:
                snapshot[key] = value
        trailing_enabled = _optional_bool(evaluation.get("trailing_enabled"))
        if trailing_enabled is not None:
            snapshot["trailing_enabled"] = trailing_enabled
        if snapshot == before:
            return False
        snapshot.update({
            "position_id": position_id,
            "held_security_id": contract,
            "last_stop_update_time": timestamp,
            "risk_source": _optional_text(evaluation.get("risk_source")) or snapshot.get("risk_source"),
            "risk_source_timestamp": _optional_text(evaluation.get("risk_source_timestamp")) or timestamp,
            "strategy_version": _optional_text(evaluation.get("strategy_version")) or snapshot.get("strategy_version"),
            "risk_rule_version": _optional_text(evaluation.get("risk_rule_version")) or snapshot.get("risk_rule_version"),
        })
        snapshot["risk_status"] = self._risk_status(snapshot)
        position.update({
            "protective_stop": snapshot.get("protective_stop"),
            "current_stop": snapshot.get("current_stop"),
            "stop": snapshot.get("current_stop"),
            "target": snapshot.get("target"),
            "underlying_stop": snapshot.get("underlying_current_stop"),
            "underlying_current_stop": snapshot.get("underlying_current_stop"),
            "trailing_enabled": snapshot.get("trailing_enabled"),
            "trailing_activation_price": snapshot.get("trailing_activation_price"),
            "trailing_anchor": snapshot.get("trailing_anchor"),
            "trailing_distance": snapshot.get("trailing_distance"),
            "trailing_step": snapshot.get("trailing_step"),
            "last_stop_update_time": timestamp,
            "risk_source": snapshot.get("risk_source"),
            "risk_source_timestamp": snapshot.get("risk_source_timestamp"),
            "strategy_version": snapshot.get("strategy_version"),
            "risk_rule_version": snapshot.get("risk_rule_version"),
            "risk_status": snapshot.get("risk_status"),
            "risk_snapshot": snapshot,
        })
        audit = {
            "event": "POSITION_RISK_UPDATED",
            "timestamp": timestamp,
            "position_id": position_id,
            "held_security_id": contract,
            "before_current_stop": before.get("current_stop"),
            "after_current_stop": snapshot.get("current_stop"),
            "before_underlying_stop": before.get("underlying_current_stop"),
            "after_underlying_stop": snapshot.get("underlying_current_stop"),
        }
        position.setdefault("risk_audit", []).append(audit)
        self._emit(
            "PositionRiskUpdated",
            position_id,
            position.get("parent_id"),
            position.get("lineage") or [],
            {"position": deepcopy(position), "audit": audit},
        )
        return True

    def _mark_position(self, position: Dict[str, Any], price: float, timestamp: str) -> None:
        multiplier = 1.0 if position["side"] == "LONG" else -1.0
        pnl = (price - position["average_price"]) * position["quantity"] * multiplier
        position["current_price"] = round(price, 8)
        position["pnl"] = round(pnl, 8)
        position["mfe"] = round(max(position.get("mfe") or 0.0, pnl), 8)
        position["mae"] = round(min(position.get("mae") or 0.0, pnl), 8)
        position["duration_seconds"] = _seconds(position.get("entry_time"), timestamp)
        risk = float(position.get("initial_risk_per_unit") or 0.0) * int(position.get("quantity") or 0)
        position["rr"] = round(pnl / risk, 8) if risk > 0 else None

    @staticmethod
    def _mark_price_for_contract(context: Mapping[str, Any], contract: str) -> Optional[float]:
        return InstitutionalPaperTradingEngine._mark_quote_for_contract(
            context, contract, str(context.get("timestamp") or _now())
        ).get("price")

    @staticmethod
    def _mark_quote_for_contract(context: Mapping[str, Any], contract: str, observed_at: str) -> Dict[str, Any]:
        def result(price, stamp, source, security_id):
            age = None
            try:
                age = max(0.0, (datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")) - datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))).total_seconds())
            except (TypeError, ValueError):
                pass
            stale = age is not None and age > 600
            return {
                "price": price, "timestamp": stamp, "age_seconds": age, "source": source,
                "security_id": str(security_id or contract), "status": "STALE" if stale else "FRESH",
                "reason": "HELD_CONTRACT_QUOTE_STALE" if stale else None,
            }
        argus = context.get("argus")
        data = argus.get("data") if isinstance(argus, Mapping) else None
        rows = data.get("atm_window") if isinstance(data, Mapping) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                for side in ("ce", "pe"):
                    quote = row.get(side)
                    if isinstance(quote, Mapping) and str(quote.get("security_id") or "") == contract:
                        price = _number(quote.get("ltp"))
                        if price is not None:
                            underlying = data.get("underlying") if isinstance(data, Mapping) else {}
                            return result(price, quote.get("fetched_at") or (underlying or {}).get("fetched_at") or context.get("timestamp"), quote.get("source") or "ARGUS_DHAN_OPTION_CHAIN", contract)
        context_contract = str(context.get("contract") or context.get("option_contract") or "")
        if not context_contract or context_contract == contract:
            for key in ("current_price", "paper_price", "option_price", "close", "ltp"):
                price = _number(context.get(key))
                if price is not None:
                    return result(price, context.get("source_timestamp") or context.get("timestamp"), context.get("source"), context_contract or contract)
            bar = context.get("bar")
            if isinstance(bar, Mapping):
                price = _number(bar.get("close"))
                if price is not None and context_contract == contract:
                    return result(price, bar.get("timestamp") or context.get("timestamp"), context.get("source"), contract)
        return {"price": None, "timestamp": None, "age_seconds": None, "source": None, "security_id": contract, "status": "UNAVAILABLE", "reason": "HELD_CONTRACT_QUOTE_UNAVAILABLE"}

    @staticmethod
    def _record_stop_breach(position: Dict[str, Any], price: float, quote: Mapping[str, Any], timestamp: str, state: Mapping[str, Any]) -> None:
        stop = _number(position.get("protective_stop")) or _number(position.get("stop"))
        if stop is None:
            return
        breached = price <= stop if str(position.get("side") or "LONG").upper() == "LONG" else price >= stop
        if not breached:
            return
        close_orders = [
            row for row in state.get("orders") or []
            if row.get("position_effect") == "CLOSE" and (
                row.get("position_id") == position.get("position_id")
                or str(row.get("contract") or "") == str(position.get("contract") or "")
            )
        ]
        latest = close_orders[-1] if close_orders else None
        existing = dict(position.get("stop_breach") or {})
        position["stop_breach"] = {
            "breached": True, "stop_price": stop, "breach_price": existing.get("breach_price", price),
            "breach_timestamp": existing.get("breach_timestamp", timestamp),
            "quote_timestamp": quote.get("timestamp"), "quote_source": quote.get("source"),
            "held_security_id": str(position.get("contract") or ""),
            "exit_order_status": latest.get("status") if latest else "NOT_SUBMITTED",
            "latest_exit_attempt": latest.get("updated_at") if latest else None,
            "retry_eligible": latest is None or str(latest.get("status") or "").upper() in {"REJECTED", "CANCELLED", "EXPIRED"},
            "failure_reason": latest.get("rejection_reason") if latest else None,
        }

    def _service_pending(self, state: Dict[str, Any], context: Mapping[str, Any], timestamp: str) -> bool:
        changed = False
        price = _number(context.get("current_price")) or _number(context.get("close")) or _number(context.get("ltp"))
        if price is None:
            return False
        for order in state["orders"]:
            if order["status"] not in {"PENDING", "PARTIAL"}:
                continue
            if order.get("expires_at") and str(order["expires_at"]) <= timestamp:
                order.update({"status": "EXPIRED", "expired_at": timestamp, "updated_at": timestamp, "rejection_reason": "ORDER_EXPIRED"})
                self.workspace.order_ledger.append("ORDER_EXPIRED", order, recorded_at=timestamp, idempotency_key=f"{order['order_id']}:EXPIRED")
                if order.get("position_effect") == "OPEN" and state.get("lifecycle", {}).get("state") in {"SIGNAL_PENDING", "ENTRY_CONFIRMED"}:
                    self._transition(state, "CANCELLED", timestamp, order["order_id"])
                    self._transition(state, "POSITION_CLOSED", timestamp, order["order_id"])
                    self._transition(state, "IDLE", timestamp, order["order_id"])
                changed = True
                continue
            report = self.execution_provider.execute(
                order=order,
                market_context=context,
                reference_price=price,
                fee_rate_bps=self.policy.fee_rate_bps,
                flat_fee_per_fill=self.policy.flat_fee_per_fill,
                slippage_bps=self.policy.slippage_bps,
            )
            if report.status in {"FILLED", "PARTIAL"}:
                self._fill_order(state, order, price, context, {"available_quantity": context.get("available_quantity")}, timestamp)
                changed = True
        return changed

    def _authoritative_price(self, evaluation: Mapping[str, Any], context: Mapping[str, Any], signal: str) -> Optional[float]:
        keys = ("entry", "price", "execution_price") if signal == "BUY" else ("exit", "price", "execution_price")
        for key in keys:
            value = _number(evaluation.get(key))
            if value is not None:
                return value
        for key in ("current_price", "close", "ltp"):
            value = _number(context.get(key))
            if value is not None:
                return value
        return None

    def _revalue(self, state: Dict[str, Any], timestamp: str) -> None:
        open_positions = [row for row in state["positions"] if row["status"] == "OPEN"]
        closed_gross = sum(float(row.get("realized_gross_pnl") or 0.0) for row in state["closed_trades"])
        fees = sum(float(row.get("fees") or 0.0) for row in state["fills"])
        unrealized = sum(float(row.get("pnl") or 0.0) for row in open_positions)
        realized = closed_gross - fees
        equity = self.policy.initial_capital + realized + unrealized
        margin = sum(
            abs(float(row.get("current_price") if row.get("current_price") is not None else row.get("average_price") or 0.0) * int(row["quantity"]))
            * self.policy.margin_rate
            for row in open_positions
        )
        open_risk = sum((float(row.get("initial_risk_per_unit") or 0.0) * int(row["quantity"])) for row in open_positions)
        account = state["account"]
        peak = max(float(account.get("peak_equity") or self.policy.initial_capital), equity)
        drawdown = max(0.0, peak - equity)
        maximum = max(float(account.get("maximum_drawdown") or 0.0), drawdown)
        today = _date(timestamp)
        daily_gross = sum(float(row.get("realized_gross_pnl") or 0.0) for row in state["closed_trades"] if _date(row.get("exit_time")) == today)
        daily_fees = sum(float(row.get("fees") or 0.0) for row in state["fills"] if _date(row.get("time")) == today)
        available = max(0.0, equity - margin)
        account.update({
            "current_equity": round(equity, 8),
            "cash": round(self.policy.initial_capital + realized, 8),
            "buying_power": round(available, 8),
            "margin_used": round(margin, 8),
            "available_margin": round(available, 8),
            "open_risk": round(open_risk, 8),
            "realized_pnl": round(realized, 8),
            "unrealized_pnl": round(unrealized, 8),
            "daily_pnl": round(daily_gross - daily_fees + unrealized, 8),
            "peak_equity": round(peak, 8),
            "drawdown": round(drawdown, 8),
            "maximum_drawdown": round(maximum, 8),
            "recovery": round(max(0.0, maximum - drawdown), 8),
            "fees_paid": round(fees, 8),
            "updated_at": timestamp,
        })
        state["statistics"] = calculate_institutional_statistics(state["closed_trades"], maximum)
        state["statistics"]["statistics_id"] = _identifier("stats", self.strategy_id, len(state["closed_trades"]), state.get("updated_at"))
        state["statistics"]["parent_ids"] = [row["trade_id"] for row in state["closed_trades"]]
        state["updated_at"] = timestamp

    def _write_risk(self, state: Dict[str, Any], decision: str, reason: str, order: Mapping[str, Any], timestamp: str) -> None:
        self.workspace.write("risk_state", {
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "last_decision": decision,
            "reason": reason,
            "order_id": order["order_id"],
            "evaluated_at": timestamp,
            "policy": asdict(self.policy),
        })

    def _commit(self, state: Dict[str, Any], event_type: str, payload: Mapping[str, Any], idempotency_key: str) -> None:
        self._revalue(state, timestamp=_now())
        commit_id = _identifier("commit", self.strategy_id, idempotency_key)
        self.workspace.transactions.append("StateCommitted", {"event_type": event_type, "event": dict(payload), "state": state}, idempotency_key=commit_id)
        self._state = deepcopy(state)
        self._materialize(state)
        statistics_id = state["statistics"]["statistics_id"]
        parent_ids = state["statistics"].get("parent_ids") or [commit_id]

    def _materialize(self, state: Mapping[str, Any]) -> None:
        self.workspace.write("paper_engine_state", dict(state))
        open_positions = [deepcopy(row) for row in state.get("positions", []) if row.get("status") == "OPEN"]
        account = dict(state.get("account") or {})
        self.workspace.write("paper_state", {
            "open_position": open_positions[0] if len(open_positions) == 1 else None,
            "open_positions": open_positions,
            "missions": list(state.get("missions") or []),
            "closed_trades": list(state.get("closed_trades") or []),
            "realized_pnl": account.get("realized_pnl", 0.0),
            "unrealized_pnl": account.get("unrealized_pnl", 0.0),
            "paper_only": True,
            "lifecycle": deepcopy(state.get("lifecycle") or {"state": "IDLE", "transitions": []}),
        })
        self.workspace.write("statistics", dict(state.get("statistics") or {}))

    @staticmethod
    def _order(state: Mapping[str, Any], order_id: str) -> Optional[Dict[str, Any]]:
        return next((row for row in state["orders"] if row["order_id"] == order_id), None)

    @staticmethod
    def _result(status: str, reason: str, **values: Any) -> Dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            **values,
            "paper_only": True,
            "paper_state_mutated": status in {"FILLED", "PARTIAL"},
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    def _reject_without_order(self, reason: str, evaluation_id: Optional[str] = None) -> Dict[str, Any]:
        return self._result("REJECTED", reason, evaluation_id=evaluation_id)

    def _transition(self, state: Dict[str, Any], target: str, timestamp: str, entity_id: str) -> None:
        lifecycle = state.setdefault("lifecycle", {"state": "IDLE", "transitions": []})
        source = str(lifecycle.get("state") or "IDLE")
        if target == source:
            return
        if target not in self._TRANSITIONS.get(source, set()):
            raise RuntimeError(f"INVALID_POSITION_TRANSITION:{source}:{target}")
        lifecycle["state"] = target
        lifecycle.setdefault("transitions", []).append({
            "from": source, "to": target, "timestamp": timestamp, "entity_id": entity_id,
        })

    @staticmethod
    def _normalize_lifecycle(state: Dict[str, Any]) -> None:
        state.setdefault("missions", [])
        if not isinstance(state.get("lifecycle"), Mapping):
            has_open = any(row.get("status") == "OPEN" for row in state.get("positions") or [])
            has_pending = any(row.get("position_effect") == "OPEN" and row.get("status") in {"PENDING", "PARTIAL"} for row in state.get("orders") or [])
            state["lifecycle"] = {"state": "MANAGING" if has_open else "SIGNAL_PENDING" if has_pending else "IDLE", "transitions": []}

    @staticmethod
    def _exit_lifecycle_state(reason: str) -> str:
        value = reason.upper()
        if "TARGET" in value:
            return "TARGET"
        if "STOP" in value or "SL" in value:
            return "STOP"
        if "SESSION" in value or "SQUARE_OFF" in value:
            return "SESSION_EXIT"
        return "CANCELLED"

    def _emit(
        self,
        event_type: str,
        entity_id: str,
        parent_id: Optional[str],
        lineage: Iterable[str],
        payload: Mapping[str, Any],
    ) -> DomainEvent:
        return self.event_bus.publish(DomainEvent(
            event_type=event_type,
            entity_id=entity_id,
            parent_id=parent_id,
            lineage=list(dict.fromkeys(str(item) for item in lineage if item)),
            payload=dict(payload),
        ))

    def _persist_event(self, event: DomainEvent) -> None:
        self.workspace.transactions.append(
            event.event_type,
            {"domain_event": event.to_dict()},
            recorded_at=event.occurred_at,
            idempotency_key=event.event_id,
        )


def aggregate_portfolio(
    states: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> Dict[str, Any]:
    rows = [dict(row) for row in states]
    accounts = [dict(row.get("account") or {}) for row in rows]
    trades = [dict(trade) for row in rows for trade in row.get("closed_trades") or []]
    positions = [dict(position) for row in rows for position in row.get("positions") or [] if position.get("status") == "OPEN"]
    stats = calculate_institutional_statistics(trades, sum(float(account.get("maximum_drawdown") or 0.0) for account in accounts))
    statistics_ids = [str(row.get("statistics", {}).get("statistics_id")) for row in rows if row.get("statistics", {}).get("statistics_id")]
    initial_capital = sum(float(account.get("initial_capital") or 0.0) for account in accounts)
    current_equity = sum(float(account.get("current_equity") or 0.0) for account in accounts)
    available_capital = sum(float(account.get("available_margin") or 0.0) for account in accounts)
    used_capital = sum(float(account.get("margin_used") or 0.0) for account in accounts)
    ist_now = (now or datetime.now(timezone.utc)).astimezone(
        ZoneInfo("Asia/Kolkata")
    )
    trading_date = ist_now.date()
    session_rows = [
        row
        for row in rows
        if not str(row.get("strategy_id") or "").lower().startswith(
            ("validation_", "demo_", "test_")
        )
    ]
    session_trades = [
        trade
        for row in session_rows
        for trade in row.get("closed_trades") or []
        if trade.get("exclude_from_strategy_stats") is not True
        and str(trade.get("execution_origin") or "").upper()
        not in {"DEMO_PAPER", "BACKTEST", "TEST_FIXTURE"}
        and _ist_trading_date(trade.get("exit_time")) == trading_date
    ]
    session_realized = sum(
        float(
            trade.get("realized_pnl")
            if trade.get("realized_pnl") is not None
            else trade.get("pnl") or 0.0
        )
        for trade in session_trades
    )
    session_unrealized = sum(
        float((row.get("account") or {}).get("unrealized_pnl") or 0.0)
        for row in session_rows
        if any(
            position.get("status") == "OPEN"
            for position in row.get("positions") or []
            if isinstance(position, Mapping)
        )
    )
    daily_pnl = session_realized + session_unrealized
    realized_pnl = sum(float(account.get("realized_pnl") or 0.0) for account in accounts)
    unrealized_pnl = sum(float(account.get("unrealized_pnl") or 0.0) for account in accounts)
    configured_daily_limit = sum(
        float(row.get("risk_policy", {}).get("max_daily_loss") or 0.0)
        for row in rows if row.get("risk_policy", {}).get("configured") is True
    )
    risk_usage = (
        round(max(0.0, -daily_pnl) / configured_daily_limit * 100.0, 8)
        if configured_daily_limit > 0
        else None
    )
    return {
        "portfolio_id": "portfolio_strategy_lab_default",
        "parent_ids": statistics_ids,
        "lineage": [*statistics_ids, "portfolio_strategy_lab_default"],
        "status": "available",
        "generated_at": _now(),
        "trading_date": trading_date.isoformat(),
        "initial_capital": round(initial_capital, 8),
        "current_capital": round(current_equity, 8),
        "available_capital": round(available_capital, 8),
        "used_capital": round(used_capital, 8),
        "total_equity": round(current_equity, 8),
        "today_pnl": round(daily_pnl, 8),
        "open_pnl": round(session_unrealized, 8),
        "session_realized_pnl": round(session_realized, 8),
        "closed_pnl": round(realized_pnl, 8),
        "total_pnl": round(realized_pnl + unrealized_pnl, 8),
        "open_trades": len(positions),
        "closed_trades": len(trades),
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "expectancy": stats["expectancy"],
        "portfolio_drawdown": round(sum(float(account.get("drawdown") or 0.0) for account in accounts), 8),
        "exposure": round(sum(float(account.get("margin_used") or 0.0) for account in accounts), 8),
        "risk_usage": risk_usage,
        "strategy_accounts": len(accounts),
        "multi_portfolio_ready": True,
        "multi_portfolio_enabled": False,
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
    }


def _ist_trading_date(value: Any):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("Asia/Kolkata")).date()
    except (TypeError, ValueError):
        return None
