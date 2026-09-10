"""Execution-provider boundary; only a paper provider is implemented."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Protocol


@dataclass(frozen=True)
class ExecutionReport:
    status: str
    reason: str
    price: Optional[float]
    quantity: int
    fees: float
    slippage: float
    slippage_per_unit: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionProvider(Protocol):
    """Future providers implement this boundary without changing Lab modules."""

    provider_name: str
    paper_only: bool
    broker_submission: bool

    def execute(
        self,
        *,
        order: Mapping[str, Any],
        market_context: Mapping[str, Any],
        reference_price: float,
        fee_rate_bps: float,
        flat_fee_per_fill: float,
        slippage_bps: float,
    ) -> ExecutionReport:
        ...


class PaperExecutionProvider:
    """Deterministic paper fills; contains no broker client or mutation surface."""

    provider_name = "CITADEL_STRATEGY_LAB_PAPER"
    paper_only = True
    broker_submission = False

    def execute(
        self,
        *,
        order: Mapping[str, Any],
        market_context: Mapping[str, Any],
        reference_price: float,
        fee_rate_bps: float,
        flat_fee_per_fill: float,
        slippage_bps: float,
    ) -> ExecutionReport:
        if not self._marketable(order, market_context):
            return ExecutionReport("PENDING", "ORDER_AWAITING_PRICE", None, 0, 0.0, 0.0, 0.0)
        remaining = int(order.get("remaining_quantity") or 0)
        available = market_context.get("available_quantity")
        if isinstance(available, bool) or not isinstance(available, (int, float)):
            fill_quantity = remaining
        else:
            fill_quantity = min(remaining, max(0, int(available)))
        if fill_quantity <= 0:
            return ExecutionReport("PENDING", "NO_FILL_LIQUIDITY", None, 0, 0.0, 0.0, 0.0)
        direction = 1.0 if order.get("side") == "BUY" else -1.0
        slippage_per_unit = reference_price * slippage_bps / 10000.0
        fill_price = reference_price + direction * slippage_per_unit
        fees = abs(fill_price * fill_quantity) * fee_rate_bps / 10000.0 + flat_fee_per_fill
        status = "FILLED" if fill_quantity == remaining else "PARTIAL"
        return ExecutionReport(
            status=status,
            reason="PAPER_FILL_RECORDED",
            price=round(fill_price, 8),
            quantity=fill_quantity,
            fees=round(fees, 8),
            slippage=round(slippage_per_unit * fill_quantity, 8),
            slippage_per_unit=round(slippage_per_unit, 8),
        )

    @staticmethod
    def _marketable(order: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
        order_type = str(order.get("order_type") or "MARKET").upper()
        if order_type == "MARKET":
            return True
        high = context.get("high")
        low = context.get("low")
        if not isinstance(high, (int, float)) or isinstance(high, bool):
            high = None
        if not isinstance(low, (int, float)) or isinstance(low, bool):
            low = None
        if order_type == "LIMIT":
            limit = order.get("limit_price")
            return isinstance(limit, (int, float)) and (
                (order.get("side") == "BUY" and low is not None and low <= limit)
                or (order.get("side") == "SELL" and high is not None and high >= limit)
            )
        if order_type == "STOP":
            stop = order.get("stop_price")
            return isinstance(stop, (int, float)) and (
                (order.get("side") == "BUY" and high is not None and high >= stop)
                or (order.get("side") == "SELL" and low is not None and low <= stop)
            )
        return False
