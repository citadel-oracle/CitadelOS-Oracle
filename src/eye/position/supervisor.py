"""Position Supervisor & OpenAlgo Sandbox Idempotency Engine for Phase E6A.

Tracks active simulated sandbox positions and prevents duplicate Analyzer order submissions.
"""

import hashlib
import json
from dataclasses import fields
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Any, Mapping
from src.eye.position.contracts import PositionState, GuardianState
from src.broker.openalgo_client import OpenAlgoClient
from src.strategy_lab.storage import _atomic_write


class PositionSupervisor:
    """Authoritative tracker for active simulated OpenAlgo Analyzer positions."""

    _instance: Optional["PositionSupervisor"] = None

    @classmethod
    def get_instance(cls, openalgo_client: Optional[OpenAlgoClient] = None) -> "PositionSupervisor":
        if cls._instance is None:
            cls._instance = cls(openalgo_client=openalgo_client)
        return cls._instance

    def __init__(
        self,
        openalgo_client: Optional[OpenAlgoClient] = None,
        *,
        state_path: Optional[str | Path] = None,
    ):
        self.openalgo_client = openalgo_client or OpenAlgoClient()
        self.positions: Dict[str, PositionState] = {}
        self.submitted_idempotency_keys: set = set()
        self.unresolved_idempotency_keys: set = set()
        self.reconciliation_required: list[dict[str, Any]] = []
        self._lock = Lock()
        # Persistence is opt-in for a concrete runtime owner.  Unit callers and
        # legacy manual-only adapters remain isolated; the EYE runtime passes
        # its own canonical state path when execution is armed.
        self.state_path = Path(state_path) if state_path else None
        self._restore()
        self.reconcile_openalgo_positions()

    def _restore(self) -> None:
        """Restore only an exact previously-owned EYE position state.

        A broker/analyzer position does not contain enough provenance to invent
        expiry, strike, risk geometry, or a Guardian contract.  Corrupt or
        incomplete local state therefore fails closed rather than generating a
        synthetic position.
        """
        try:
            if self.state_path is None:
                return
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
                return
            allowed = {item.name for item in fields(PositionState)}
            for value in raw.get("positions") or []:
                if not isinstance(value, Mapping):
                    continue
                candidate = {key: value[key] for key in allowed if key in value}
                if isinstance(candidate.get("guardian_state"), str):
                    candidate["guardian_state"] = GuardianState(candidate["guardian_state"])
                position = PositionState(**candidate)
                self.positions[position.position_id] = position
            self.submitted_idempotency_keys = {
                str(value)
                for value in raw.get("submitted_idempotency_keys") or []
                if isinstance(value, str)
            }
            self.unresolved_idempotency_keys = {
                str(value)
                for value in raw.get("unresolved_idempotency_keys") or []
                if isinstance(value, str)
            }
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            # A bad recovery document must never create a best-effort position.
            self.positions = {}
            self.submitted_idempotency_keys = set()
            self.unresolved_idempotency_keys = set()

    def _persist(self) -> None:
        if self.state_path is None:
            return
        payload = {
            "schema_version": 1,
            "positions": [position.to_dict() for position in self.positions.values()],
            "submitted_idempotency_keys": sorted(self.submitted_idempotency_keys),
            "unresolved_idempotency_keys": sorted(self.unresolved_idempotency_keys),
        }
        _atomic_write(self.state_path, payload)

    def reconcile_openalgo_positions(self) -> None:
        """Reconcile only known EYE positions; never manufacture metadata.

        If Analyzer reports a position that cannot be tied to a persisted EYE
        record, it remains explicitly reconciliation-required.  It cannot enter
        the Guardian or Oracle as a synthetic valid position.
        """
        try:
            status = self.openalgo_client.get_analyzer_status()
            if not (isinstance(status, dict) and status.get("status") == "success" and status.get("data", {}).get("mode") == "analyze"):
                return

            pos_res = self.openalgo_client.get_positions()
            positions_list = pos_res.get("data", []) if isinstance(pos_res, dict) and isinstance(pos_res.get("data"), list) else []
            # Read the trade book only as reconciliation evidence.  It is not
            # sufficient to manufacture an EYE position when durable EYE
            # provenance is absent.
            self.openalgo_client.get_trades()

            for p in positions_list:
                sym = p.get("symbol")
                qty = int(p.get("quantity", 0))
                if sym and qty > 0:
                    known = next(
                        (
                            item
                            for item in self.positions.values()
                            if item.closed_at is None
                            and item.exact_contract == str(sym)
                            and item.quantity == qty
                        ),
                        None,
                    )
                    if known is None:
                        evidence = {
                            "symbol": str(sym),
                            "quantity": qty,
                            "reason": "EXTERNAL_POSITION_WITHOUT_EYE_PROVENANCE",
                        }
                        if evidence not in self.reconciliation_required:
                            self.reconciliation_required.append(evidence)

            from src.eye.oracle_projection.runtime_state import EyeRuntimeState
            active = self.get_active_positions()
            if active:
                EyeRuntimeState.get_instance().set_active_position(active[-1].to_dict())
            elif self.reconciliation_required:
                EyeRuntimeState.get_instance().set_active_position({
                    "status": "RECONCILIATION_REQUIRED",
                    "reason": self.reconciliation_required[0]["reason"],
                })
        except Exception:
            pass

    def generate_idempotency_key(
        self,
        setup_record_id: str,
        setup_revision: str,
        exact_contract: str,
        entry_time_str: str,
    ) -> str:
        raw = f"{setup_record_id}:{setup_revision}:{exact_contract}:{entry_time_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def has_decision_been_submitted(self, idempotency_key: str) -> bool:
        return (
            idempotency_key in self.submitted_idempotency_keys
            or idempotency_key in self.unresolved_idempotency_keys
        )

    def open_analyzer_position(
        self,
        decision_id: str,
        setup_key: str,
        setup_record_id: str,
        underlying: str,
        exact_contract: str,
        exchange: str,
        expiry: str,
        strike: float,
        option_type: str,
        side: str,
        quantity: int,
        ref_entry: float,
        sl_price: float,
        t1: float,
        t2: Optional[float],
        t3: Optional[float],
        timestamp_str: str,
        idempotency_key: str,
        product: str = "NRML",
    ) -> Optional[PositionState]:
        if side.upper() != "BUY":
            raise ValueError("Safety Violation: CITADEL is Option-Buying Only. Opening option order MUST be BUY.")

        with self._lock:
            if self.has_decision_been_submitted(idempotency_key):
                return None

        # Build OpenAlgo order payload for Analyzer sandbox
        order_payload = {
            "symbol": exact_contract,
            "action": side.upper(),
            "exchange": exchange.upper(),
            "quantity": quantity,
            "price": ref_entry,
            "product": product.upper(),
            "strategy": "CITADEL_EYE_E5_ORACLE",
        }

        # 1. Mandatory per-order safety gate: query live Analyzer status before EVERY request
        try:
            status = self.openalgo_client.get_analyzer_status()
            status_data = status.get("data", {})
            if status.get("status") != "success" or status_data.get("mode") != "analyze":
                raise RuntimeError("EXECUTION_BLOCKED_ANALYZER_NOT_PROVEN: OpenAlgo is NOT in analyze mode.")
        except Exception as e:
            raise RuntimeError(f"EXECUTION_BLOCKED_ANALYZER_NOT_PROVEN: {e}")

        with self._lock:
            if self.has_decision_been_submitted(idempotency_key):
                return None
            # An unacknowledged transport outcome is not safely retryable by
            # this legacy adapter because it has no broker-side correlation key.
            self.unresolved_idempotency_keys.add(idempotency_key)
            self._persist()

        # 2. Place order in OpenAlgo Analyzer sandbox
        try:
            res = self.openalgo_client.place_order(order_payload)
        except Exception:
            # The request could have reached Analyzer.  Retain its key and force
            # a manual/reconciled decision rather than blindly resubmitting.
            return None
        if res.get("status") != "success":
            with self._lock:
                self.unresolved_idempotency_keys.discard(idempotency_key)
                self._persist()
            return None

        order_id = res.get("orderid") or res.get("id")
        if not order_id:
            # Analyzer acknowledgement without an order ID is uncertain.  Do not
            # materialise a paper position or manufacture a reconciliation key.
            return None
        str_order_id = str(order_id)

        # 3. Query OpenAlgo TradeBook for fill authority evidence
        actual_fill_price = None
        try:
            trades_resp = self.openalgo_client.get_trades()
            if trades_resp and isinstance(trades_resp, dict) and isinstance(trades_resp.get("data"), list):
                for t in trades_resp["data"]:
                    if str(t.get("orderid")) == str_order_id:
                        value = t.get("price") or t.get("average_price")
                        if value is not None:
                            actual_fill_price = float(value)
                        break
        except Exception:
            actual_fill_price = None
        if actual_fill_price is None:
            # No tradebook fill is not a fill.  Recovery must reconcile the
            # acknowledged order; it is unsafe to substitute requested price.
            return None

        pos_id = f"POS:{decision_id}:{exact_contract}"
        risk_pts = round(abs(ref_entry - sl_price), 2)
        initial_rr = round(abs(t1 - ref_entry) / risk_pts, 2) if risk_pts > 0 else 0.0

        pos = PositionState(
            position_id=pos_id,
            decision_id=decision_id,
            setup_key=setup_key,
            setup_record_id=setup_record_id,
            underlying=underlying,
            exact_contract=exact_contract,
            exchange=exchange,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            side=side.upper(),
            quantity=quantity,
            product=product.upper(),
            expected_entry=ref_entry,
            actual_fill=actual_fill_price,
            fill_time=timestamp_str,
            structural_sl=sl_price,
            invalidation_level=sl_price,
            t1=t1,
            t2=t2,
            t3=t3,
            initial_risk_points=risk_pts,
            initial_rr=initial_rr,
            current_premium=actual_fill_price,
            current_underlying=None,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            current_r=0.0,
            mfe=0.0,
            mae=0.0,
            guardian_state=GuardianState.ARMED,
            thesis_state="VALID",
            openalgo_order_id=str_order_id,
            openalgo_mode="analyze",
            opened_at=timestamp_str,
            closed_at=None,
            exit_reason=None,
        )

        with self._lock:
            self.positions[pos_id] = pos
            self.unresolved_idempotency_keys.discard(idempotency_key)
            self.submitted_idempotency_keys.add(idempotency_key)
            self._persist()

        from src.eye.oracle_projection.runtime_state import EyeRuntimeState
        EyeRuntimeState.get_instance().set_active_position(pos.to_dict())

        return pos

    def get_active_positions(self) -> List[PositionState]:
        return [p for p in self.positions.values() if p.closed_at is None]

    def close_analyzer_position(
        self,
        position_id: str,
        close_price: float,
        timestamp_str: str,
        exit_reason: str,
    ) -> Optional[PositionState]:
        pos = self.positions.get(position_id)
        if not pos or pos.closed_at is not None:
            return pos

        close_side = "SELL" if pos.side == "BUY" else "BUY"
        order_payload = {
            "symbol": pos.exact_contract,
            "action": close_side,
            "exchange": pos.exchange,
            "quantity": pos.quantity,
            "price": close_price,
            "product": pos.product,
            "strategy": "CITADEL_EYE_GUARDIAN",
        }

        # Mandatory per-order safety gate before closing request
        try:
            status = self.openalgo_client.get_analyzer_status()
            status_data = status.get("data", {})
            if status.get("status") != "success" or status_data.get("mode") != "analyze":
                raise RuntimeError("EXECUTION_BLOCKED_ANALYZER_NOT_PROVEN: OpenAlgo is NOT in analyze mode.")
        except Exception as e:
            raise RuntimeError(f"EXECUTION_BLOCKED_ANALYZER_NOT_PROVEN: {e}")

        # Close position in OpenAlgo Analyzer sandbox
        res = self.openalgo_client.place_order(order_payload)
        if not isinstance(res, dict) or res.get("status") != "success":
            return None
        close_order_id = res.get("orderid") or res.get("id")
        str_close_order_id = str(close_order_id) if close_order_id else None
        if str_close_order_id:
            pos.close_openalgo_order_id = str_close_order_id

        # Query TradeBook for actual SELL fill price
        actual_sell_fill = None
        try:
            trades_resp = self.openalgo_client.get_trades()
            if trades_resp and isinstance(trades_resp, dict) and isinstance(trades_resp.get("data"), list):
                for t in trades_resp["data"]:
                    if str_close_order_id and str(t.get("orderid")) == str_close_order_id:
                        value = t.get("price") or t.get("average_price")
                        if value is not None:
                            actual_sell_fill = float(value)
                        break
        except Exception:
            actual_sell_fill = None
        if actual_sell_fill is None:
            return None

        # Update position state
        pos.closed_at = timestamp_str
        pos.exit_reason = exit_reason
        pos.guardian_state = GuardianState.CLOSED

        if pos.side == "BUY":
            pnl_pts = actual_sell_fill - pos.actual_fill
        else:
            pnl_pts = pos.actual_fill - actual_sell_fill

        pos.realized_pnl = round(pnl_pts * pos.quantity, 2)
        pos.unrealized_pnl = 0.0
        pos.current_r = round(pnl_pts / pos.initial_risk_points, 2) if pos.initial_risk_points > 0 else 0.0
        with self._lock:
            self._persist()

        from src.eye.oracle_projection.runtime_state import EyeRuntimeState
        EyeRuntimeState.get_instance().set_active_position(pos.to_dict())

        return pos
