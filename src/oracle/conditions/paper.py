"""Deterministic isolated paper execution using canonical CITADEL ledgers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.execution.paper_state import DuplicatePaperEvent, PaperState, PaperStateService
from src.order_ledger.models import FillEvent, OrderIntent
from src.order_ledger.service import OrderFillLedgerService
from src.strategy_lab.storage import ImmutableStream, _atomic_write
from src.risk.authorization import ExactPaperAuthorizationDecision

from .contracts import PaperOrderRequest, ProtectionPlan, seal


class PaperExecutionError(RuntimeError):
    pass


class Phase5PaperExecutionAdapter:
    """No network/broker client is accepted by this adapter."""

    def __init__(self, root: str | Path, *, ledger: OrderFillLedgerService,
                 paper_state: PaperStateService, clock=None, slippage_points: float = 0.0):
        self.root = Path(root)
        self.ledger = ledger
        self.paper_state = paper_state
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.slippage_points = max(0.0, float(slippage_points))
        self.protection_root = self.root / "protections"
        self.protection_events = ImmutableStream(self.root / "protection_events.jsonl",
                                                 max_bytes=100 * 1024 * 1024, max_files=1)
        self.execution_events = ImmutableStream(self.root / "execution_events.jsonl",
                                                max_bytes=100 * 1024 * 1024, max_files=1)

    def submit(self, request: PaperOrderRequest, authorization: ExactPaperAuthorizationDecision,
               quote: Mapping[str, Any]) -> dict[str, Any]:
        now = self._now()
        if not request.verify_hash() or not authorization.allowed:
            raise PaperExecutionError("EXACT_PAPER_AUTHORIZATION_REQUIRED")
        if authorization.paper_order_request_hash != request.content_hash:
            raise PaperExecutionError("ORDER_AUTHORIZATION_HASH_MISMATCH")
        if authorization.authorized_quantity != request.quantity:
            raise PaperExecutionError("ORDER_AUTHORIZATION_QUANTITY_MISMATCH")
        if now >= datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00")):
            raise PaperExecutionError("PAPER_AUTHORIZATION_EXPIRED")
        if request.live_trading_enabled or request.broker_submission or not request.paper_only:
            raise PaperExecutionError("LIVE_ROUTE_FORBIDDEN")
        intent_id = "p5order_" + hashlib.sha256(request.order_request_id.encode()).hexdigest()[:24]
        try:
            return self.order(intent_id)
        except KeyError:
            pass
        intent = OrderIntent(
            intent_id=intent_id, created_at=now.isoformat(), symbol=request.symbol,
            instrument_id=request.contract_id, exchange_segment=request.exchange_segment, side="BUY",
            order_type="LIMIT", time_in_force="DAY", requested_quantity=request.quantity,
            authorized_quantity=request.quantity, lot_size=request.lot_size,
            limit_price=Decimal(str(request.limit_price)), stop_price=Decimal(str(request.stop_price)),
            reference_price=Decimal(str(quote.get("ask") or request.limit_price)), reference_price_source="CANONICAL_ASK",
            strategy_id="ORACLE_PHASE5_USER_CONDITION", strategy_version="5.0.0",
            aegis_decision_id=request.decision_id, aegis_decision="ADVISORY_ZERO_INFLUENCE",
            risk_decision_id=authorization.authorization_id, risk_decision="ALLOW",
            market_data_timestamp=request.market_data_timestamp, session_state="OPEN",
            kill_switch_state="INACTIVE", live_trading_enabled=False,
            metadata={
                "paper_only": True, "broker_submission": False, "condition_id": request.condition_id,
                "revalidation_id": request.revalidation_id, "order_request_hash": request.content_hash,
                "authorization_hash": authorization.content_hash, "option_type": request.option_type,
                "stop_price": request.stop_price, "target_prices": list(request.target_prices),
                "estimated_maximum_loss": request.estimated_maximum_loss,
            },
        )
        self.ledger.create_order_intent(intent)
        self.ledger.validate_order_intent(intent_id, True)
        self.ledger.authorize_order_intent(
            intent_id, risk_decision="ALLOW", kill_switch_state="INACTIVE",
            aegis_decision="ADVISORY_ZERO_INFLUENCE", session_state="OPEN",
            authorized_quantity=request.quantity,
        )
        self.ledger.append_order_event(intent_id, "QUEUED", "INTERNAL_PAPER_ROUTE_QUEUED")
        self.ledger.append_order_event(intent_id, "SUBMITTED", "INTERNAL_SIMULATION_NO_BROKER")
        ask = quote.get("ask")
        depth = quote.get("ask_depth")
        if ask is None or float(ask) <= 0:
            self.ledger.append_order_event(intent_id, "REJECTED", "CANONICAL_ASK_UNAVAILABLE")
            return self.order(intent_id)
        fill_price = round(float(ask) + self.slippage_points, 4)
        if fill_price > request.limit_price or fill_price > authorization.authorized_price_band[1]:
            self.ledger.append_order_event(intent_id, "ACKNOWLEDGED", "LIMIT_NOT_MARKETABLE")
            return self.order(intent_id)
        available = request.quantity if depth is None else max(0, min(request.quantity, int(depth)))
        if available == 0:
            self.ledger.append_order_event(intent_id, "ACKNOWLEDGED", "NO_EXECUTABLE_DEPTH")
            return self.order(intent_id)
        fill_id = "p5fill_" + hashlib.sha256(f"{intent_id}|{fill_price}|{available}".encode()).hexdigest()[:24]
        self.ledger.append_fill(FillEvent(
            fill_id=fill_id, intent_id=intent_id, occurred_at=now.isoformat(), quantity=available,
            price=Decimal(str(fill_price)), side="BUY", source="INTERNAL_PAPER_CANONICAL_QUOTE",
        ))
        if available < request.quantity:
            self.ledger.request_cancel(intent_id)
            self.ledger.append_order_event(intent_id, "CANCELLED", "PARTIAL_FILL_REMAINDER_CANCELLED")
        position_id = "p5pos_" + hashlib.sha256(intent_id.encode()).hexdigest()[:24]
        event_id = f"paper-open-{fill_id}"
        try:
            position = self.paper_state.open_position(
                position_id=position_id, request_id=f"position:{request.order_request_id}", event_id=event_id,
                symbol=request.symbol, side="BUY", raw_quantity=available, entry_price=fill_price,
                instrument_id=request.contract_id, lot_size=request.lot_size, option_type=request.option_type,
                strike=request.strike, expiry=request.expiry,
                stop_price=request.stop_price, target_price=request.target_prices[0],
                reason=f"Phase-5 condition {request.condition_id}",
            )
        except DuplicatePaperEvent:
            position = next((row for row in self.paper_state.load().open_positions if row.position_id == position_id), None)
            if position is None:
                raise
        self.ledger.record_fill_application(fill_id, paper_event_id=event_id, applied_at=now.isoformat())
        value = self.order(intent_id)
        value.update({"position": position.to_dict(), "position_id": position_id,
                      "paper_state_applied": True, "partial_fill": available < request.quantity})
        return value

    def establish_protection(self, *, condition_id: str, position_id: str,
                             authorization: ExactPaperAuthorizationDecision,
                             request: PaperOrderRequest, structural_invalidation_id: str,
                             time_exit_at: str) -> ProtectionPlan:
        position = next((row for row in self.paper_state.load().open_positions if row.position_id == position_id), None)
        if position is None:
            raise PaperExecutionError("RECONCILED_POSITION_REQUIRED")
        if position.stop_price is None or not request.target_prices:
            raise PaperExecutionError("DURABLE_PROTECTION_REQUIRED")
        protection = seal(ProtectionPlan(
            protection_id="protect_" + hashlib.sha256(f"{position_id}|{authorization.authorization_id}".encode()).hexdigest()[:24],
            condition_id=condition_id, position_id=position_id,
            risk_grant_id=authorization.authorization_id,
            initial_hard_stop=request.stop_price, current_hard_stop=request.stop_price,
            natural_targets=request.target_prices, structural_invalidation_id=structural_invalidation_id,
            time_exit_at=time_exit_at, emergency_exit_on_stale_data=True,
            protected_quantity=position.remaining_quantity, created_at=self._now().isoformat(),
        ))
        path = self.protection_root / f"{protection.protection_id}.json"
        if path.exists():
            current = path.read_text(encoding="utf-8")
            import json
            if json.loads(current) != protection.to_dict():
                raise PaperExecutionError("IMMUTABLE_PROTECTION_CONFLICT")
        else:
            _atomic_write(path, protection.to_dict())
        self.protection_events.append("PROTECTION_ESTABLISHED", {
            "protection_id": protection.protection_id, "position_id": position_id,
            "current_hard_stop": protection.current_hard_stop, "status": "ACTIVE",
            "protection_hash": protection.content_hash,
        }, idempotency_key=f"protection-created:{protection.protection_id}")
        return protection

    def protection(self, protection_id: str) -> ProtectionPlan:
        import json
        try:
            value = ProtectionPlan(**json.loads((self.protection_root / f"{protection_id}.json").read_text(encoding="utf-8")))
        except FileNotFoundError as error:
            raise PaperExecutionError("PROTECTION_UNAVAILABLE") from error
        for row in self.protection_events.read():
            payload = row.get("payload") or {}
            if payload.get("protection_id") != protection_id:
                continue
            if payload.get("current_hard_stop") is not None:
                value = seal(ProtectionPlan(**{**value.to_dict(), "content_hash": "",
                    "current_hard_stop": float(payload["current_hard_stop"])}))
            if payload.get("status") and payload.get("status") != value.status:
                value = seal(ProtectionPlan(**{**value.to_dict(), "content_hash": "",
                    "status": str(payload["status"])}))
        return value

    def tighten_stop(self, protection: ProtectionPlan, new_stop: float, mark_price: float) -> ProtectionPlan:
        if new_stop < protection.current_hard_stop or new_stop >= mark_price:
            raise PaperExecutionError("STOP_LOOSENING_FORBIDDEN")
        position = next(row for row in self.paper_state.load().open_positions if row.position_id == protection.position_id)
        self.paper_state.update_mark(position.position_id, mark_price,
            f"guardian-tighten-{protection.protection_id}-{new_stop}", stop_price=new_stop,
            trailing_active=True)
        updated = seal(ProtectionPlan(**{
            **protection.to_dict(), "content_hash": "", "current_hard_stop": float(new_stop),
        }))
        self.protection_events.append("PROTECTION_TIGHTENED", {
            "protection_id": protection.protection_id, "position_id": protection.position_id,
            "current_hard_stop": float(new_stop), "status": "ACTIVE",
            "protection_hash": updated.content_hash,
        }, idempotency_key=f"protection-tighten:{protection.protection_id}:{new_stop}")
        return updated

    def mark_protection_exited(self, protection: ProtectionPlan, *, reason: str) -> None:
        self.protection_events.append("PROTECTION_EXITED", {
            "protection_id": protection.protection_id, "position_id": protection.position_id,
            "current_hard_stop": protection.current_hard_stop, "status": "EXITED",
            "reason_code": reason,
        }, idempotency_key=f"protection-exit:{protection.protection_id}:{reason}")

    def active_protections(self) -> tuple[ProtectionPlan, ...]:
        if not self.protection_root.exists():
            return ()
        values = []
        for path in sorted(self.protection_root.glob("*.json")):
            try:
                value = self.protection(path.stem)
            except PaperExecutionError:
                continue
            if value.status == "ACTIVE":
                values.append(value)
        return tuple(values)

    def cancel_order(self, order_id: str, *, reason: str, idempotency_key: str) -> dict[str, Any]:
        order = self.ledger.get_order(order_id)
        if order["state"] in {"CANCELLED", "REJECTED", "EXPIRED", "FILLED", "FAILED"}:
            return self.order(order_id)
        if order["filled_quantity"]:
            raise PaperExecutionError("FILLED_QUANTITY_CANNOT_BE_CANCELLED")
        self.ledger.request_cancel(order_id)
        self.ledger.append_order_event(order_id, "CANCELLED", str(reason), event_id=idempotency_key)
        return self.order(order_id)

    def record_authorized_modification(self, order_id: str, *, revised_request: PaperOrderRequest,
                                       authorization: ExactPaperAuthorizationDecision,
                                       idempotency_key: str) -> dict[str, Any]:
        order = self.ledger.get_order(order_id)
        original = order["intent"]
        if order["state"] not in {"SUBMITTED", "ACKNOWLEDGED"} or order["filled_quantity"]:
            raise PaperExecutionError("ONLY_UNFILLED_ACTIVE_ORDER_MAY_BE_MODIFIED")
        if not revised_request.verify_hash() or not authorization.allowed:
            raise PaperExecutionError("FRESH_EXACT_MODIFICATION_AUTHORIZATION_REQUIRED")
        if authorization.paper_order_request_hash != revised_request.content_hash:
            raise PaperExecutionError("MODIFICATION_AUTHORIZATION_HASH_MISMATCH")
        if (revised_request.contract_id != original["instrument_id"]
                or revised_request.quantity != original["requested_quantity"]):
            raise PaperExecutionError("MODIFICATION_SCOPE_MISMATCH")
        row = self.execution_events.append("PAPER_ORDER_MODIFICATION_AUTHORIZED", {
            "order_id": order_id, "revised_order_request_id": revised_request.order_request_id,
            "revised_order_request_hash": revised_request.content_hash,
            "risk_grant_id": authorization.authorization_id,
            "new_limit_price": revised_request.limit_price, "paper_only": True,
            "broker_submission": False,
        }, idempotency_key=idempotency_key)
        return {"status": "MODIFICATION_RECORDED", "order_id": order_id,
                "effective_limit_price": revised_request.limit_price,
                "event_hash": row["record_hash"], "requires_reconciliation": True,
                "broker_submission": False}

    def exit_position(self, position_id: str, *, price: float, reason: str,
                      event_key: str, close_quantity: int | None = None) -> dict[str, Any]:
        position = next((row for row in self.paper_state.load().open_positions if row.position_id == position_id), None)
        if position is None:
            closed = next((row for row in self.paper_state.load().closed_trades if row.position_id == position_id), None)
            return {"status": "CLOSED", "closed_trade": closed.to_dict() if closed else None}
        quantity = position.remaining_quantity if close_quantity is None else int(close_quantity)
        if quantity <= 0 or quantity > position.remaining_quantity:
            raise PaperExecutionError("INVALID_PAPER_EXIT_QUANTITY")
        intent_id = "p5exit_" + hashlib.sha256(f"{position_id}|{event_key}|{quantity}".encode()).hexdigest()[:24]
        now = self._now()
        intent = OrderIntent(
            intent_id=intent_id, created_at=now.isoformat(), symbol=position.symbol,
            instrument_id=str(position.instrument_id), exchange_segment="NSE_FNO", side="SELL",
            order_type="MARKET", time_in_force="IOC", requested_quantity=quantity,
            authorized_quantity=quantity, lot_size=None,
            limit_price=None, stop_price=None, reference_price=Decimal(str(price)), reference_price_source="CANONICAL_BID",
            strategy_id="ORACLE_PHASE5_GUARDIAN_EXIT", strategy_version="5.0.0",
            aegis_decision_id="RISK_REDUCING_EXIT", aegis_decision="ZERO_INFLUENCE",
            risk_decision_id="RISK_REDUCING_PAPER_EXIT", risk_decision="ALLOW",
            market_data_timestamp=now.isoformat(), session_state="OPEN", kill_switch_state="INACTIVE",
            live_trading_enabled=False, metadata={"paper_only": True, "position_id": position_id, "exit_reason": reason},
        )
        try:
            self.ledger.create_order_intent(intent)
            self.ledger.validate_order_intent(intent_id, True)
            self.ledger.append_order_event(intent_id, "AUTHORIZED", "RISK_REDUCING_PAPER_EXIT", {"authorized_quantity": quantity})
            self.ledger.append_order_event(intent_id, "QUEUED", "INTERNAL_PAPER_EXIT_QUEUED")
            self.ledger.append_order_event(intent_id, "SUBMITTED", "INTERNAL_SIMULATION_NO_BROKER")
            fill_id = f"fill_{hashlib.sha256(intent_id.encode()).hexdigest()[:24]}"
            self.ledger.append_fill(FillEvent(fill_id=fill_id, intent_id=intent_id, occurred_at=now.isoformat(),
                                             quantity=quantity, price=Decimal(str(price)), side="SELL",
                                             source="INTERNAL_PAPER_CANONICAL_QUOTE"))
            closed = self.paper_state.close_position(position_id, float(price), f"paper-close-{fill_id}",
                                                     close_quantity=quantity, exit_reason=reason)
            self.ledger.record_fill_application(fill_id, paper_event_id=f"paper-close-{fill_id}", applied_at=now.isoformat())
        except ValueError:
            order = self.ledger.get_order(intent_id)
            if order["state"] != "FILLED":
                raise
            closed = next(row for row in self.paper_state.load().closed_trades if row.position_id == position_id)
        remaining = next((row.remaining_quantity for row in self.paper_state.load().open_positions if row.position_id == position_id), 0)
        return {"status": "CLOSED" if remaining == 0 else "PARTIALLY_CLOSED", "order_id": intent_id,
                "closed_trade": closed.to_dict(), "remaining_quantity": remaining,
                "broker_submission": False, "live_trading_enabled": False}

    def order(self, order_id: str) -> dict[str, Any]:
        value = self.ledger.get_order(order_id)
        return {**value, "paper_only": True, "broker_submission": False,
                "costs": self.ledger.cost_summary(order_id),
                "slippage": self.ledger.slippage_summary(order_id)}

    def trade(self, position_id: str) -> dict[str, Any]:
        # GET projections must not invoke PaperStateService.load(), which may roll
        # the trading date. Read and validate the persisted document directly.
        try:
            document = json.loads(self.paper_state.path.read_text(encoding="utf-8"))
            state = PaperState.from_mapping(document["state"])
        except (FileNotFoundError, OSError, ValueError, TypeError, KeyError) as error:
            raise KeyError(position_id) from error
        open_position = next((row for row in state.open_positions if row.position_id == position_id), None)
        closed = next((row for row in state.closed_trades if row.position_id == position_id), None)
        if not open_position and not closed:
            raise KeyError(position_id)
        return {"status": "OPEN" if open_position else "CLOSED",
                "position": open_position.to_dict() if open_position else None,
                "closed_trade": closed.to_dict() if closed else None,
                "paper_only": True, "broker_submission": False}

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise PaperExecutionError("VERIFIED_TIME_UNAVAILABLE")
        return value
