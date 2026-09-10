"""Quote & Market Data Quality Classifier Wrapper for Eye Engine Option Capture."""

from datetime import datetime
from typing import Optional, Dict, Any

from src.eye.option_evidence.quote_quality import classify_quote_quality, QuoteQualityMetrics
from src.eye.contracts import PriceAtom


def evaluate_capture_quote_quality(
    best_bid: Optional[PriceAtom],
    best_ask: Optional[PriceAtom],
    bid_quantity: int,
    ask_quantity: int,
    last_price: Optional[PriceAtom],
    observed_at: datetime,
    evaluation_as_of: datetime,
) -> QuoteQualityMetrics:
    """Evaluates quote metrics and quote states for a capture observation."""
    return classify_quote_quality(
        best_bid=best_bid,
        best_ask=best_ask,
        bid_quantity=bid_quantity,
        ask_quantity=ask_quantity,
        last_price=last_price,
        observed_at=observed_at,
        evaluation_as_of=evaluation_as_of,
    )
