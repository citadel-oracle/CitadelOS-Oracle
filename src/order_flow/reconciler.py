"""Cumulative-volume anchored reconciliation; a packet is never assumed a trade."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    AggressorSide,
    DataQuality,
    MarketEvent,
    ReconciledTradeState,
)
from .signer import AggressorSigner


@dataclass(slots=True)
class _InstrumentState:
    cumulative_volume: int
    ltt: int
    ltp: float
    best_bid: float | None
    best_ask: float | None
    last_distinct_trade_price: float | None = None


class VolumeReconciler:
    """Reconcile observed event volume without manufacturing price assignment."""

    def __init__(self, signer: AggressorSigner | None = None):
        self.signer = signer or AggressorSigner()
        self._state: dict[tuple[str, int, str, str], _InstrumentState] = {}

    def reconcile(self, event: MarketEvent) -> ReconciledTradeState:
        key = (
            event.session_id,
            event.feed_generation,
            event.exchange_segment,
            event.security_id,
        )
        previous = self._state.get(key)
        bid, ask = _top(event)
        if previous is None:
            self._state[key] = _InstrumentState(
                event.cumulative_volume, event.exchange_ltt, event.ltp, bid, ask
            )
            return self._result(event, 0, 0, 0, 0, "BASELINE", 0.0, "BASELINE_ESTABLISHED")

        delta = event.cumulative_volume - previous.cumulative_volume
        if delta < 0:
            self._state[key] = _InstrumentState(
                event.cumulative_volume,
                event.exchange_ltt,
                event.ltp,
                bid,
                ask,
                previous.last_distinct_trade_price,
            )
            return self._result(
                event,
                0,
                0,
                0,
                0,
                "VOLUME_REGRESSION",
                0.0,
                "SESSION_RESET_OR_VOLUME_REGRESSION",
                quality=DataQuality.DEGRADED,
            )
        if delta == 0:
            self._update(previous, event, bid, ask)
            return self._result(event, 0, 0, 0, 0, "QUOTE_ONLY", 0.0, "NO_NEW_EXECUTED_VOLUME")

        observed_qty = 0
        trade_price = None
        side = AggressorSide.UNKNOWN
        method = "UNCLASSIFIED_AGGREGATE"
        confidence = 0.0
        ltt_advanced = event.exchange_ltt > previous.ltt
        if ltt_advanced and 0 < event.ltq <= delta:
            observed_qty = event.ltq
            trade_price = event.ltp
            signed = self.signer.sign(
                trade_price=trade_price,
                pre_bid=previous.best_bid,
                pre_ask=previous.best_ask,
                last_distinct_trade_price=previous.last_distinct_trade_price,
                quote_fresh=event.data_quality is not DataQuality.UNUSABLE,
            )
            side, method, confidence = signed.side, signed.method, signed.confidence

        buy = observed_qty if side is AggressorSide.BUY else 0
        sell = observed_qty if side is AggressorSide.SELL else 0
        unknown_observed = observed_qty if side is AggressorSide.UNKNOWN else 0
        residual = delta - observed_qty
        unclassified = residual + unknown_observed
        status = "RECONCILED"
        quality = event.data_quality
        if unclassified:
            status = "UNCLASSIFIED_AGGREGATE"
            if quality is DataQuality.GOOD:
                quality = DataQuality.DEGRADED
        if observed_qty and event.ltp != previous.last_distinct_trade_price:
            previous.last_distinct_trade_price = event.ltp
        self._update(previous, event, bid, ask)
        return self._result(
            event,
            delta,
            buy,
            sell,
            unclassified,
            method,
            confidence,
            status,
            side=side,
            observed_price=trade_price,
            observed_qty=observed_qty,
            quality=quality,
        )

    @staticmethod
    def _update(
        state: _InstrumentState,
        event: MarketEvent,
        bid: float | None,
        ask: float | None,
    ) -> None:
        state.cumulative_volume = event.cumulative_volume
        state.ltt = max(state.ltt, event.exchange_ltt)
        state.ltp = event.ltp
        state.best_bid = bid
        state.best_ask = ask

    @staticmethod
    def _result(
        event: MarketEvent,
        delta: int,
        buy: int,
        sell: int,
        unknown: int,
        method: str,
        confidence: float,
        status: str,
        *,
        side: AggressorSide = AggressorSide.UNKNOWN,
        observed_price: float | None = None,
        observed_qty: int = 0,
        quality: DataQuality | None = None,
    ) -> ReconciledTradeState:
        return ReconciledTradeState(
            event_id=event.event_id,
            delta_volume=delta,
            classified_buy_qty=buy,
            classified_sell_qty=sell,
            unclassified_qty=unknown,
            signer_method=method,
            signer_confidence=confidence,
            reconciliation_status=status,
            aggressor_side=side,
            observed_trade_price=observed_price,
            observed_trade_qty=observed_qty,
            data_quality=quality or event.data_quality,
        )


def _top(event: MarketEvent) -> tuple[float | None, float | None]:
    if not event.depth_5:
        return None, None
    first = event.depth_5[0]
    bid = first.bid_price if first.bid_price > 0 else None
    ask = first.ask_price if first.ask_price > 0 else None
    return bid, ask
