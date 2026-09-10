"""Fast, conservative trade-aggressor classification."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import AggressorSide


@dataclass(frozen=True, slots=True)
class SignResult:
    side: AggressorSide
    method: str
    confidence: float


class AggressorSigner:
    """Quote test first, tick test second, UNKNOWN otherwise."""

    def sign(
        self,
        *,
        trade_price: float,
        pre_bid: float | None,
        pre_ask: float | None,
        last_distinct_trade_price: float | None,
        quote_fresh: bool = True,
    ) -> SignResult:
        valid_quote = (
            quote_fresh
            and pre_bid is not None
            and pre_ask is not None
            and pre_bid > 0
            and pre_ask > pre_bid
        )
        if valid_quote and trade_price >= pre_ask:
            return SignResult(AggressorSide.BUY, "PRE_EVENT_ASK_TEST", 0.95)
        if valid_quote and trade_price <= pre_bid:
            return SignResult(AggressorSide.SELL, "PRE_EVENT_BID_TEST", 0.95)
        if last_distinct_trade_price is not None:
            if trade_price > last_distinct_trade_price:
                return SignResult(AggressorSide.BUY, "LAST_DISTINCT_TICK_UP", 0.65)
            if trade_price < last_distinct_trade_price:
                return SignResult(AggressorSide.SELL, "LAST_DISTINCT_TICK_DOWN", 0.65)
        reason = "STALE_OR_INVALID_PRE_EVENT_QUOTE" if not valid_quote else "AMBIGUOUS_INSIDE_SPREAD"
        return SignResult(AggressorSide.UNKNOWN, reason, 0.0)
