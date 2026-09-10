"""Quote Quality Classifier & Microstructure Metrics for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.contracts import QuoteState, PriceReference


@dataclass(frozen=True)
class QuoteQualityMetrics:
    quote_state: QuoteState
    spread_absolute: Optional[float]
    spread_ticks: Optional[int]
    proportional_spread: Optional[float]
    midpoint: Optional[float]
    microprice_research: Optional[float]
    bid_size: Optional[int]
    ask_size: Optional[int]
    size_imbalance: Optional[float]
    ltp_distance_from_midpoint: Optional[float]
    quote_age_seconds: Optional[float]
    is_executable: bool


def classify_quote_quality(
    best_bid: Optional[PriceAtom],
    best_ask: Optional[PriceAtom],
    bid_quantity: Optional[int] = None,
    ask_quantity: Optional[int] = None,
    last_price: Optional[PriceAtom] = None,
    observed_at: Optional[datetime] = None,
    evaluation_time: Optional[datetime] = None,
    stale_threshold_seconds: float = 30.0,
    tick_size_ticks: int = 5,
) -> QuoteQualityMetrics:
    """Classify quote state and compute microstructure metrics."""
    if best_bid is None and best_ask is None:
        return QuoteQualityMetrics(
            quote_state=QuoteState.NO_QUOTE, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if best_bid is not None and (best_bid.ticks < 0):
        return QuoteQualityMetrics(
            quote_state=QuoteState.INVALID_PRICE, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if best_ask is not None and (best_ask.ticks < 0):
        return QuoteQualityMetrics(
            quote_state=QuoteState.INVALID_PRICE, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if best_bid is not None and best_bid.ticks == 0 and best_ask is None:
        return QuoteQualityMetrics(
            quote_state=QuoteState.ZERO_BID, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if best_ask is not None and best_ask.ticks == 0 and best_bid is None:
        return QuoteQualityMetrics(
            quote_state=QuoteState.ZERO_ASK, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if best_bid is not None and best_ask is None:
        return QuoteQualityMetrics(
            quote_state=QuoteState.BID_ONLY, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if best_ask is not None and best_bid is None:
        return QuoteQualityMetrics(
            quote_state=QuoteState.ASK_ONLY, spread_absolute=None, spread_ticks=None,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    # Both best_bid and best_ask present
    bid_p = best_bid.ticks / 100.0
    ask_p = best_ask.ticks / 100.0

    if ask_p < bid_p:
        return QuoteQualityMetrics(
            quote_state=QuoteState.CROSSED, spread_absolute=ask_p - bid_p, spread_ticks=(best_ask.ticks - best_bid.ticks) // tick_size_ticks,
            proportional_spread=None, midpoint=None, microprice_research=None,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    if ask_p == bid_p:
        return QuoteQualityMetrics(
            quote_state=QuoteState.LOCKED, spread_absolute=0.0, spread_ticks=0,
            proportional_spread=0.0, midpoint=bid_p, microprice_research=bid_p,
            bid_size=bid_quantity, ask_size=ask_quantity, size_imbalance=None,
            ltp_distance_from_midpoint=None, quote_age_seconds=None, is_executable=False,
        )

    # Valid two-sided quote (ask > bid)
    spread_abs = ask_p - bid_p
    spread_ticks = (best_ask.ticks - best_bid.ticks) // tick_size_ticks
    mid = (bid_p + ask_p) / 2.0
    prop_spread = spread_abs / mid if mid > 0 else 0.0

    # Calculate Microprice Research Value
    microprice = None
    size_imbal = None
    if bid_quantity is not None and ask_quantity is not None and (bid_quantity + ask_quantity) > 0:
        total_qty = bid_quantity + ask_quantity
        microprice = (bid_p * ask_quantity + ask_p * bid_quantity) / total_qty
        size_imbal = (bid_quantity - ask_quantity) / total_qty

    ltp_dist = None
    if last_price is not None:
        ltp_p = last_price.ticks / 100.0
        ltp_dist = abs(ltp_p - mid)

    quote_age = None
    is_fresh = True
    if observed_at is not None and evaluation_time is not None:
        quote_age = (evaluation_time - observed_at).total_seconds()
        if quote_age > stale_threshold_seconds:
            is_fresh = False

    q_state = QuoteState.TWO_SIDED_VALID if is_fresh else QuoteState.STALE_TWO_SIDED

    return QuoteQualityMetrics(
        quote_state=q_state,
        spread_absolute=round(spread_abs, 4),
        spread_ticks=spread_ticks,
        proportional_spread=round(prop_spread, 6),
        midpoint=round(mid, 4),
        microprice_research=round(microprice, 4) if microprice is not None else None,
        bid_size=bid_quantity,
        ask_size=ask_quantity,
        size_imbalance=round(size_imbal, 4) if size_imbal is not None else None,
        ltp_distance_from_midpoint=round(ltp_dist, 4) if ltp_dist is not None else None,
        quote_age_seconds=quote_age,
        is_executable=(q_state == QuoteState.TWO_SIDED_VALID),
    )
