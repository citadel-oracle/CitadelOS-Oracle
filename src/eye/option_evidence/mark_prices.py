"""Price Reference Policy & Reference Price Calculations for Eye Engine Phase E4A."""

from typing import Optional
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.contracts import PriceReference, QuoteState
from src.eye.option_evidence.quote_quality import classify_quote_quality, QuoteQualityMetrics


def get_reference_price(
    best_bid: Optional[PriceAtom],
    best_ask: Optional[PriceAtom],
    last_price: Optional[PriceAtom],
    price_reference: PriceReference,
    bid_quantity: Optional[int] = None,
    ask_quantity: Optional[int] = None,
) -> Optional[float]:
    """Calculate specific reference price under price policy."""
    metrics = classify_quote_quality(best_bid, best_ask, bid_quantity, ask_quantity, last_price)

    if price_reference == PriceReference.BEST_ASK:
        return (best_ask.ticks / 100.0) if best_ask is not None else None

    if price_reference == PriceReference.BEST_BID:
        return (best_bid.ticks / 100.0) if best_bid is not None else None

    if price_reference == PriceReference.LAST_TRADED_PRICE:
        return (last_price.ticks / 100.0) if last_price is not None else None

    if price_reference == PriceReference.MIDPOINT:
        if metrics.quote_state in (QuoteState.TWO_SIDED_VALID, QuoteState.STALE_TWO_SIDED):
            return metrics.midpoint
        return None

    if price_reference == PriceReference.MICROPRICE_RESEARCH:
        if metrics.quote_state in (QuoteState.TWO_SIDED_VALID, QuoteState.STALE_TWO_SIDED):
            return metrics.microprice_research
        return None

    return None
