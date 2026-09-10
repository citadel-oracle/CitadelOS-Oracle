"""Pure, incremental order-flow features for the packet hot path."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from functools import partial
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import DataQuality, MarketEvent, ReconciledTradeState


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True, slots=True)
class BookMetrics:
    l1_ofi: float
    mlofi: float
    microprice: float | None
    microprice_edge: float
    bid_depletion: int
    ask_depletion: int
    bid_refill: int
    ask_refill: int
    signed_aggression: float
    book_pressure: float
    book_confidence: float
    spread: float | None
    status: str


class BookPressureEngine:
    """Price-level-aware five-level book state; no rank-to-rank aliasing."""

    def __init__(self):
        self._previous: dict[tuple[str, str], MarketEvent] = {}

    def update(self, event: MarketEvent, trade: ReconciledTradeState) -> BookMetrics:
        key = (event.exchange_segment, event.security_id)
        previous = self._previous.get(key)
        self._previous[key] = event
        top = event.depth_5[0]
        spread = top.ask_price - top.bid_price
        valid = top.bid_price > 0 and top.ask_price > top.bid_price and spread > 0
        if not valid:
            return BookMetrics(0, 0, None, 0, 0, 0, 0, 0, 0, 0, 0, None, "INVALID_OR_CROSSED_BOOK")
        micro = safe_ratio(
            top.ask_price * top.bid_quantity + top.bid_price * top.ask_quantity,
            top.bid_quantity + top.ask_quantity,
        )
        mid = (top.bid_price + top.ask_price) / 2.0
        micro_edge = clamp((micro - mid) / (spread / 2.0)) if micro else 0.0
        aggression = clamp(
            safe_ratio(
                trade.classified_buy_qty - trade.classified_sell_qty,
                trade.classified_buy_qty + trade.classified_sell_qty,
            )
        )
        if previous is None:
            return BookMetrics(0, 0, micro, micro_edge, 0, 0, 0, 0, aggression, micro_edge * 0.2, 0.25, spread, "BASELINE")

        prev_top = previous.depth_5[0]
        bid_event = _side_event(
            previous_price=prev_top.bid_price,
            previous_qty=prev_top.bid_quantity,
            current_price=top.bid_price,
            current_qty=top.bid_quantity,
            is_bid=True,
        )
        ask_event = _side_event(
            previous_price=prev_top.ask_price,
            previous_qty=prev_top.ask_quantity,
            current_price=top.ask_price,
            current_qty=top.ask_quantity,
            is_bid=False,
        )
        l1_raw = bid_event - ask_event
        l1_scale = max(1.0, prev_top.bid_quantity + prev_top.ask_quantity)
        l1 = clamp(l1_raw / l1_scale)

        prev_bids = {level.bid_price: level.bid_quantity for level in previous.depth_5 if level.bid_price > 0}
        prev_asks = {level.ask_price: level.ask_quantity for level in previous.depth_5 if level.ask_price > 0}
        cur_bids = {level.bid_price: level.bid_quantity for level in event.depth_5 if level.bid_price > 0}
        cur_asks = {level.ask_price: level.ask_quantity for level in event.depth_5 if level.ask_price > 0}
        bid_changes = sum(cur_bids.get(price, 0) - prev_bids.get(price, 0) for price in set(prev_bids) | set(cur_bids))
        ask_changes = sum(cur_asks.get(price, 0) - prev_asks.get(price, 0) for price in set(prev_asks) | set(cur_asks))
        depth_scale = max(1.0, sum(prev_bids.values()) + sum(prev_asks.values()))
        mlofi = clamp((bid_changes - ask_changes) / depth_scale)

        bid_depletion, bid_refill = _depletion_refill(prev_bids, cur_bids)
        ask_depletion, ask_refill = _depletion_refill(prev_asks, cur_asks)
        confidence = 1.0 if event.data_quality is DataQuality.GOOD else 0.55
        pressure = clamp(
            (0.35 * l1 + 0.25 * mlofi + 0.20 * micro_edge + 0.20 * aggression)
            * confidence
        )
        return BookMetrics(
            l1,
            mlofi,
            micro,
            micro_edge,
            bid_depletion,
            ask_depletion,
            bid_refill,
            ask_refill,
            aggression,
            pressure,
            confidence,
            spread,
            "AVAILABLE",
        )


@dataclass(frozen=True, slots=True)
class ResponseMetrics:
    response_quality: float
    state: str
    price_response_efficiency: float
    buyer_absorption: float
    seller_absorption: float
    failed_aggression: float
    liquidity_refill: float
    resiliency: float
    continuation_efficiency: float
    confidence: float


class ResponseQualityEngine:
    """Bounded response window linking known aggression to price and refill."""

    def __init__(self, window: int = 64):
        self._windows: dict[tuple[str, str], deque[tuple[float, int, int, BookMetrics]]] = defaultdict(
            partial(deque, maxlen=window)
        )

    def update(
        self, event: MarketEvent, trade: ReconciledTradeState, book: BookMetrics
    ) -> ResponseMetrics:
        key = (event.exchange_segment, event.security_id)
        values = self._windows[key]
        values.append((event.ltp, trade.classified_buy_qty, trade.classified_sell_qty, book))
        if len(values) < 2:
            return ResponseMetrics(0, "MIXED", 0, 0, 0, 0, 0, 0, 0, 0.2)
        start_price = values[0][0]
        price_change = event.ltp - start_price
        buys = sum(row[1] for row in values)
        sells = sum(row[2] for row in values)
        signed = buys - sells
        known = buys + sells
        spread = book.spread or max(abs(price_change), 1e-9)
        normalized_progress = clamp(price_change / max(spread * 3.0, 1e-9))
        signed_direction = clamp(safe_ratio(signed, known))
        efficiency = clamp(normalized_progress * signed_direction, 0.0, 1.0)
        ask_refill = sum(row[3].ask_refill for row in values)
        bid_refill = sum(row[3].bid_refill for row in values)
        refill_total = ask_refill + bid_refill
        refill = clamp(safe_ratio(bid_refill - ask_refill, refill_total))
        poor_progress = max(0.0, 1.0 - abs(normalized_progress))
        buyer_absorption = max(0.0, signed_direction) * poor_progress * max(0.25, safe_ratio(ask_refill, refill_total))
        seller_absorption = max(0.0, -signed_direction) * poor_progress * max(0.25, safe_ratio(bid_refill, refill_total))
        failed = max(buyer_absorption, seller_absorption)
        resiliency = clamp(abs(refill))
        continuation = clamp(signed_direction * normalized_progress, -1.0, 1.0)
        quality = clamp(0.65 * normalized_progress + 0.20 * signed_direction + 0.15 * refill)
        if buyer_absorption >= 0.45:
            state = "BUYERS_ABSORBED"
            quality = -max(quality, buyer_absorption)
        elif seller_absorption >= 0.45:
            state = "SELLERS_ABSORBED"
            quality = max(quality, seller_absorption)
        elif quality >= 0.25:
            state = "CLEAN_BULL"
        elif quality <= -0.25:
            state = "CLEAN_BEAR"
        else:
            state = "MIXED"
        confidence = min(1.0, known / 100.0) * book.book_confidence
        return ResponseMetrics(
            quality,
            state,
            efficiency,
            buyer_absorption,
            seller_absorption,
            failed,
            refill,
            resiliency,
            continuation,
            confidence,
        )


@dataclass(frozen=True, slots=True)
class OptionConfirmation:
    value: float
    confidence: float
    status: str
    ce_known_buy: int
    ce_known_sell: int
    pe_known_buy: int
    pe_known_sell: int
    nearby_agreement: float
    greeks_mode: str


class OptionConfirmationEngine:
    """ATM/nearby option confirmation; Futures remains directional owner."""

    def __init__(self, ttl_seconds: float = 3.0):
        self.ttl_ns = int(ttl_seconds * 1_000_000_000)
        self._latest: dict[str, tuple[MarketEvent, ReconciledTradeState, BookMetrics]] = {}
        self._greeks: dict[str, tuple[float, int]] = {}

    def register_delta(self, security_id: str, delta: float, *, receive_ns: int) -> None:
        if isinstance(delta, bool) or not math.isfinite(delta) or not -1.0 <= delta <= 1.0:
            raise ValueError("canonical option delta outside [-1,1]")
        self._greeks[str(security_id)] = (float(delta), int(receive_ns))

    def update(
        self,
        event: MarketEvent,
        trade: ReconciledTradeState,
        book: BookMetrics,
        *,
        now_ns: int,
    ) -> OptionConfirmation:
        if event.option_type in {"CE", "PE"}:
            self._latest[event.instrument_role] = (event, trade, book)
        return self.snapshot(now_ns)

    def snapshot(self, now_ns: int) -> OptionConfirmation:
        totals = {"CE": [0, 0], "PE": [0, 0]}
        directional_rows: list[float] = []
        confidences: list[float] = []
        stale = 0
        wide = 0
        greek_rows = 0
        for event, trade, book in self._latest.values():
            if now_ns - event.feed_receive_ns > self.ttl_ns:
                stale += 1
                continue
            side = event.option_type
            if side not in totals:
                continue
            totals[side][0] += trade.classified_buy_qty
            totals[side][1] += trade.classified_sell_qty
            known = trade.classified_buy_qty + trade.classified_sell_qty
            if known:
                raw = (trade.classified_buy_qty - trade.classified_sell_qty) / known
                greek = self._greeks.get(event.security_id)
                if greek is not None and now_ns - greek[1] <= self.ttl_ns:
                    # Signed premium aggression times canonical option delta.
                    directional_rows.append(raw * greek[0])
                    greek_rows += 1
                else:
                    # CE buying/selling and PE selling/buying are opposite confirmations.
                    directional_rows.append(raw if side == "CE" else -raw)
                spread_ratio = (book.spread or 0.0) / max(event.ltp, 1e-9)
                spread_factor = 0.25 if spread_ratio > 0.02 else 1.0
                wide += int(spread_factor < 1.0)
                confidences.append(trade.signer_confidence * book.book_confidence * spread_factor)
        if not directional_rows:
            status = "STALE_OPTIONS" if stale else "INSUFFICIENT_SIGNED_OPTION_FLOW"
            return OptionConfirmation(0, 0, status, *totals["CE"], *totals["PE"], 0, "RAW_QUOTE_AWARE")
        positive = sum(value > 0 for value in directional_rows)
        negative = sum(value < 0 for value in directional_rows)
        agreement = abs(positive - negative) / len(directional_rows)
        value = clamp(sum(directional_rows) / len(directional_rows))
        confidence = (sum(confidences) / len(confidences)) * (0.5 + 0.5 * agreement)
        mode = "DELTA_EQUIVALENT" if greek_rows == len(directional_rows) else "RAW_QUOTE_AWARE"
        status = "WIDE_SPREAD_DEGRADED" if wide else (
            "AVAILABLE_WITH_GREEKS" if mode == "DELTA_EQUIVALENT" else "AVAILABLE_WITHOUT_GREEKS"
        )
        return OptionConfirmation(
            value,
            confidence,
            status,
            *totals["CE"],
            *totals["PE"],
            agreement,
            mode,
        )


@dataclass(frozen=True, slots=True)
class ProfileDiagnostics:
    poc: float | None
    vah: float | None
    val: float | None
    status: str
    coverage: float
    cvd: int
    cvd_state: str
    cvd_coverage: float
    divergence_state: str
    footprint_state: str
    stacked_levels: int
    imbalance_ratio_max: float
    imbalance_quality: float
    location_state: str


class SessionProfileEngine:
    """Known-price volume profile, CVD, footprint and location diagnostics."""

    def __init__(
        self,
        *,
        value_area_fraction: float = 0.70,
        minimum_profile_coverage: float = 0.60,
        imbalance_ratio: float = 3.0,
        minimum_level_volume: int = 10,
        tick_size: float = 0.05,
        max_price_bins: int = 4096,
    ):
        if not 0.5 <= value_area_fraction <= 0.95:
            raise ValueError("value area fraction outside configured bounds")
        self.value_area_fraction = value_area_fraction
        self.minimum_profile_coverage = minimum_profile_coverage
        self.imbalance_ratio = imbalance_ratio
        self.minimum_level_volume = minimum_level_volume
        self.tick_size = tick_size
        self.max_price_bins = max(128, int(max_price_bins))
        self.session_id: str | None = None
        self.profile: dict[float, int] = defaultdict(int)
        self.buys: dict[float, int] = defaultdict(int)
        self.sells: dict[float, int] = defaultdict(int)
        self.total_delta = 0
        self.assigned = 0
        self.cvd = 0
        self._last_cvd = 0
        self._last_price: float | None = None
        self._location_candidate: tuple[str, int] | None = None
        self._confirmed_location: str | None = None
        self.profile_truncated = False

    def update(
        self,
        event: MarketEvent,
        trade: ReconciledTradeState,
        *,
        response_state: str = "MIXED",
    ) -> ProfileDiagnostics:
        if self.session_id != event.session_id:
            self.__init__(
                value_area_fraction=self.value_area_fraction,
                minimum_profile_coverage=self.minimum_profile_coverage,
                imbalance_ratio=self.imbalance_ratio,
                minimum_level_volume=self.minimum_level_volume,
                tick_size=self.tick_size,
                max_price_bins=self.max_price_bins,
            )
            self.session_id = event.session_id
        self.total_delta += trade.delta_volume
        known = trade.classified_buy_qty + trade.classified_sell_qty
        if known and trade.observed_trade_price is not None:
            price = self._bin(trade.observed_trade_price)
            self.profile[price] += known
            self.buys[price] += trade.classified_buy_qty
            self.sells[price] += trade.classified_sell_qty
            self.assigned += known
            self._bound_price_bins(event.ltp)
        prior_cvd = self.cvd
        self.cvd += trade.classified_buy_qty - trade.classified_sell_qty
        coverage = safe_ratio(self.assigned, self.total_delta)
        cvd_coverage = safe_ratio(
            sum(self.buys.values()) + sum(self.sells.values()), self.total_delta
        )
        cvd_state = "RISING" if self.cvd > prior_cvd else "FALLING" if self.cvd < prior_cvd else "FLAT"
        price_change = 0.0 if self._last_price is None else event.ltp - self._last_price
        cvd_change = self.cvd - self._last_cvd
        if cvd_change > 0 and price_change <= 0:
            divergence = "PRICE_NOT_RESPONDING" if price_change == 0 else "BEARISH_DIVERGENCE"
        elif cvd_change < 0 and price_change >= 0:
            divergence = "PRICE_NOT_RESPONDING" if price_change == 0 else "BULLISH_DIVERGENCE"
        else:
            divergence = "NONE"
        self._last_cvd, self._last_price = self.cvd, event.ltp
        footprint, stacked, ratio_max, imbalance_quality = self._footprint(
            absorbed=response_state in {"BUYERS_ABSORBED", "SELLERS_ABSORBED"}
        )
        if coverage < self.minimum_profile_coverage or not self.profile or self.profile_truncated:
            return ProfileDiagnostics(
                None, None, None, "PROFILE_DEGRADED", coverage, self.cvd,
                cvd_state, cvd_coverage, divergence, footprint, stacked,
                ratio_max, imbalance_quality * coverage, "UNAVAILABLE",
            )
        poc, vah, val = self._value_area()
        location = self._location(event.ltp, poc, vah, val)
        return ProfileDiagnostics(
            poc, vah, val, "AVAILABLE", coverage, self.cvd, cvd_state,
            cvd_coverage, divergence, footprint, stacked, ratio_max,
            imbalance_quality * coverage, location,
        )

    def _bin(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, 8)

    def _bound_price_bins(self, current_price: float) -> None:
        excess = len(self.profile) - self.max_price_bins
        if excess <= 0:
            return
        self.profile_truncated = True
        removable = sorted(
            self.profile,
            key=lambda price: (self.profile[price], -abs(price - current_price), price),
        )[:excess]
        for price in removable:
            del self.profile[price]
            self.buys.pop(price, None)
            self.sells.pop(price, None)

    def _value_area(self) -> tuple[float, float, float]:
        poc = max(sorted(self.profile), key=lambda price: self.profile[price])
        target = sum(self.profile.values()) * self.value_area_fraction
        selected = {poc}
        running = self.profile[poc]
        ordered = sorted(self.profile)
        index = ordered.index(poc)
        left, right = index - 1, index + 1
        while running < target and (left >= 0 or right < len(ordered)):
            left_volume = self.profile[ordered[left]] if left >= 0 else -1
            right_volume = self.profile[ordered[right]] if right < len(ordered) else -1
            if right_volume > left_volume:
                price = ordered[right]
                right += 1
            else:
                price = ordered[left]
                left -= 1
            selected.add(price)
            running += self.profile[price]
        return poc, max(selected), min(selected)

    def _footprint(self, *, absorbed: bool) -> tuple[str, int, float, float]:
        prices = sorted(set(self.buys) | set(self.sells))
        side = None
        current = maximum = 0
        maximum_side = None
        ratio_max = 0.0
        significant_volume = 0
        for index, price in enumerate(prices):
            buy = self.buys.get(price, 0)
            lower_sell = self.sells.get(prices[index - 1], 0) if index else 0
            sell = self.sells.get(price, 0)
            upper_buy = self.buys.get(prices[index + 1], 0) if index + 1 < len(prices) else 0
            candidate = None
            if buy >= self.minimum_level_volume and buy >= self.imbalance_ratio * max(1, lower_sell):
                candidate = "BUY"
                ratio_max = max(ratio_max, buy / max(1, lower_sell))
                significant_volume += buy
            elif sell >= self.minimum_level_volume and sell >= self.imbalance_ratio * max(1, upper_buy):
                candidate = "SELL"
                ratio_max = max(ratio_max, sell / max(1, upper_buy))
                significant_volume += sell
            if candidate == side:
                current += 1
            elif candidate:
                side, current = candidate, 1
            else:
                side, current = None, 0
            if current > maximum:
                maximum = current
                maximum_side = side
        if maximum < 2 or maximum_side is None:
            return "NO_STACKED_IMBALANCE", maximum, ratio_max, 0.0
        quality = min(1.0, maximum / 4.0) * min(1.0, significant_volume / 250.0)
        return (
            f"{maximum_side} {maximum}x STACKED · {'ABSORBED' if absorbed else 'CLEAN'}",
            maximum,
            ratio_max,
            quality,
        )

    def _location(self, ltp: float, poc: float, vah: float, val: float) -> str:
        tolerance = self.tick_size * 2
        raw = (
            "AT_POC" if abs(ltp - poc) <= tolerance
            else "ABOVE_VALUE" if ltp > vah
            else "BELOW_VALUE" if ltp < val
            else "VAH_TEST" if abs(ltp - vah) <= tolerance
            else "VAL_TEST" if abs(ltp - val) <= tolerance
            else "INSIDE_VALUE"
        )
        previous = self._location_candidate
        count = previous[1] + 1 if previous and previous[0] == raw else 1
        self._location_candidate = (raw, count)
        if count < 2:
            return f"{raw}_PENDING"
        prior_confirmed = self._confirmed_location
        if raw == "ABOVE_VALUE":
            interpreted = "VAH_ACCEPTED"
        elif raw == "BELOW_VALUE":
            interpreted = "VAL_BROKEN"
        elif raw == "INSIDE_VALUE" and prior_confirmed in {"ABOVE_VALUE", "VAH_ACCEPTED"}:
            interpreted = "VAH_REJECTED"
        elif raw == "INSIDE_VALUE" and prior_confirmed in {"BELOW_VALUE", "VAL_BROKEN"}:
            interpreted = "VAL_RECLAIMED"
        else:
            interpreted = raw
        self._confirmed_location = interpreted
        return interpreted


def _side_event(
    *, previous_price: float, previous_qty: int, current_price: float,
    current_qty: int, is_bid: bool,
) -> int:
    if current_price == previous_price:
        return current_qty - previous_qty
    if is_bid:
        return current_qty if current_price > previous_price else -previous_qty
    return current_qty if current_price < previous_price else -previous_qty


def _depletion_refill(previous: dict[float, int], current: dict[float, int]) -> tuple[int, int]:
    depletion = refill = 0
    for price in set(previous) & set(current):
        change = current[price] - previous[price]
        if change < 0:
            depletion += -change
        elif change > 0:
            refill += change
    return depletion, refill
