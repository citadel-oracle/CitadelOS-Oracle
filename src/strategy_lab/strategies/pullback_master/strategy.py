"""PULLBACK MASTER strategy-specific lifecycle over the frozen shared core."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ...core import (
    FairValueGapEngine,
    LiquidityZoneEngine,
    OrderBlock,
    SessionConfig,
    SharedOrderBlockEngine,
    SharedRiskEngine,
    SharedSessionManager,
    SupertrendEngine,
    VWAPEngine,
    VolumeFilter,
)
from ...core.atr import TradingViewATR


@dataclass(frozen=True)
class PullbackMasterConfig:
    trading_mode: str = "Intraday"
    square_off_session: str = "1515-1530"
    pullback_mode: str = "V4"
    entry_mode: str = "OB Top"
    buy_touch_mode: str = "Wick Touch"
    sell_touch_mode: str = "Wick Touch"
    stop_trigger_mode: str = "Wick Below VOB"
    target_mode: str = "Bearish VOB"
    rr_target: float = 4.0
    require_target: bool = False
    use_min_target_room: bool = True
    min_target_room_rr: float = 3.5
    require_pullback: bool = False
    min_bars_after_ob: int = 1
    move_away_points: float = 0.0
    buy_on_close: bool = False
    broker_safe: bool = True
    trail_new_bull_ob: bool = True
    use_supertrend_trail: bool = True
    supertrend_factor: float = 2.8
    supertrend_atr_length: int = 8
    supertrend_only_bullish: bool = True
    use_bear_fvg_supply_target: bool = True
    bear_fvg_location: str = "Below Or Inside Supply"
    bear_fvg_supply_buffer: float = 20.0
    bear_fvg_min_gap: float = 0.0
    use_fvg_filter: bool = False
    fvg_filter_mode: str = "Touch Candle Or Previous"
    use_liquidity_filter: bool = False
    liquidity_lookback_bars: int = 5
    liquidity_after_ob_only: bool = True
    liquidity_same_vob_touch: bool = False
    use_pullback_type_filter: bool = False
    allow_sweeping: bool = True
    allow_corrective: bool = True
    allow_aggressive: bool = True
    aggressive_body_pct: float = 55.0
    aggressive_range_atr: float = 1.0
    use_htf_confirmation: bool = False
    use_ltf_confirmation: bool = False
    use_strength_filter: bool = False
    min_strength_score: float = 6.0
    visible_order_blocks: int = 5
    strong_volume_share_pct: float = 25.0
    retest_volume_length: int = 20
    retest_volume_multiplier: float = 1.25
    relative_volume_weight: float = 1.25
    spread_quality_weight: float = 1.25
    close_near_high_pct: float = 35.0
    first_touch_bonus: float = 1.25
    repeated_retest_penalty: float = 0.5
    deep_pierce_penalty: float = 1.25
    tiny_zone_penalty_points: float = 0.0
    chop_lookback: int = 20
    chop_atr_multiplier: float = 1.2
    context_lookback: int = 50
    context_atr_buffer: float = 1.0
    displacement_body_pct: float = 55.0
    displacement_atr_multiplier: float = 0.8
    fvg_confluence_bonus: float = 1.25
    use_obv_score: bool = False
    use_mfi_score: bool = False
    use_vwap_score: bool = False
    use_index_score: bool = False
    require_enabled_extra_confirmations: bool = False
    extra_score_weight: float = 0.75
    tick_size: float = 0.05
    alerts_enabled: bool = True
    alert_details: bool = True

    @classmethod
    def tradingview_v2_20260814(cls) -> "PullbackMasterConfig":
        """Active values shown in the supplied PULLBACK V2 settings.

        This is a configuration binding only.  Strategy formulas remain in
        the engine and are not specialized for the parity fixture.
        """

        return cls(
            trading_mode="Positional",
            pullback_mode="V2",
            stop_trigger_mode="Close Below VOB",
            use_min_target_room=False,
            supertrend_factor=3.5,
            supertrend_atr_length=10,
            use_bear_fvg_supply_target=False,
        )

    def __post_init__(self) -> None:
        choices = {
            "trading_mode": (self.trading_mode, {"Intraday", "Positional"}),
            "pullback_mode": (self.pullback_mode, {"V1", "V2", "V3", "V4", "Aggressive", "Conservative"}),
            "entry_mode": (self.entry_mode, {"OB Top", "Close"}),
            "buy_touch_mode": (self.buy_touch_mode, {"Wick Touch", "Close Inside VOB"}),
            "sell_touch_mode": (self.sell_touch_mode, {"Wick Touch", "Close Inside VOB"}),
            "stop_trigger_mode": (self.stop_trigger_mode, {"Close Below VOB", "Wick Below VOB"}),
            "target_mode": (self.target_mode, {"Bearish VOB", "Fixed RR", "Nearest: VOB or RR", "Farthest: VOB or RR", "No Target Trail Only"}),
            "bear_fvg_location": (self.bear_fvg_location, {"Below Supply Only", "Inside Supply Only", "Below Or Inside Supply"}),
            "fvg_filter_mode": (self.fvg_filter_mode, {"Touch Candle", "Previous Candle", "Touch Candle Or Previous"}),
        }
        for name, (value, allowed) in choices.items():
            if value not in allowed:
                raise ValueError(f"unsupported {name}: {value}")
        positive = (self.rr_target, self.min_target_room_rr, self.supertrend_factor,
                    self.tick_size, self.retest_volume_multiplier)
        if any(value <= 0 for value in positive) or self.min_bars_after_ob < 1:
            raise ValueError("invalid PULLBACK MASTER configuration")

    @property
    def profile_strength_filter(self) -> bool:
        if self.pullback_mode == "Conservative":
            return True
        return False if self.pullback_mode in {"Aggressive", "V1"} else self.use_strength_filter

    @property
    def profile_min_strength(self) -> float:
        if self.pullback_mode == "Conservative":
            return 7.5
        if self.pullback_mode in {"Aggressive", "V1"}:
            return 0.0
        return max(self.min_strength_score, 6.0) if self.pullback_mode == "V4" else self.min_strength_score

    @property
    def profile_require_pullback(self) -> bool:
        if self.pullback_mode == "Conservative":
            return True
        return False if self.pullback_mode in {"Aggressive", "V1"} else self.require_pullback

    @property
    def profile_min_target_room(self) -> bool:
        return False if self.pullback_mode in {"Aggressive", "V1"} else self.use_min_target_room

    @property
    def profile_min_target_rr(self) -> float:
        if self.pullback_mode == "Conservative":
            return max(self.min_target_room_rr, 3.5)
        if self.pullback_mode in {"Aggressive", "V1"}:
            return 2.0
        return max(self.min_target_room_rr, 3.0) if self.pullback_mode == "V4" else self.min_target_room_rr

    @property
    def profile_liquidity_filter(self) -> bool:
        if self.pullback_mode == "Conservative":
            return True
        return False if self.pullback_mode in {"Aggressive", "V1"} else self.use_liquidity_filter

    @property
    def profile_pullback_type_filter(self) -> bool:
        if self.pullback_mode == "Conservative":
            return True
        return False if self.pullback_mode in {"Aggressive", "V1"} else self.use_pullback_type_filter


@dataclass(frozen=True)
class PullbackBar:
    index: int
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PullbackBar":
        raw = value.get("timestamp", value.get("time"))
        if isinstance(raw, datetime):
            timestamp = raw
        elif isinstance(raw, (int, float)):
            timestamp = datetime.fromtimestamp(float(raw) / (1000 if raw > 10_000_000_000 else 1))
        else:
            timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        result = cls(
            index=int(value.get("index", value.get("bar_index"))), timestamp=timestamp,
            open=float(value["open"]), high=float(value["high"]), low=float(value["low"]),
            close=float(value["close"]), volume=float(value.get("volume", 0.0)),
            confirmed=bool(value.get("confirmed", value.get("is_closed", True))),
        )
        values = (result.open, result.high, result.low, result.close, result.volume)
        if not all(math.isfinite(item) for item in values):
            raise ValueError("non-finite PULLBACK MASTER bar")
        if result.high < max(result.open, result.close, result.low) or result.low > min(result.open, result.close, result.high):
            raise ValueError("invalid PULLBACK MASTER OHLC")
        return result

    @property
    def time_ms(self) -> int:
        return int(self.timestamp.timestamp() * 1000)


@dataclass
class PullbackPosition:
    entry: float
    stop: float
    target: Optional[float]
    target_top: Optional[float]
    ob_location: int
    base_top: float
    score: float
    trail_ob_location: int
    entry_time: int
    initial_risk: float
    max_high: float
    break_even_armed: bool = False
    profit_lock_armed: bool = False
    bear_fvg_target: Optional[float] = None
    bear_fvg_target_top: Optional[float] = None
    bear_fvg_target_time: Optional[int] = None


@dataclass
class PullbackMasterState:
    used_bull_ob_locations: list[int] = field(default_factory=list)
    position: Optional[PullbackPosition] = None
    last_action_bar: Optional[int] = None
    sequence: int = 0
    last_bar_index: Optional[int] = None


class PullbackMasterStrategyEngine:
    """Native long-only Pine lifecycle. Scheduling and execution remain external/off."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        config: Optional[PullbackMasterConfig] = None,
        *,
        order_blocks: Optional[SharedOrderBlockEngine] = None,
        fair_value_gaps: Optional[FairValueGapEngine] = None,
        liquidity: Optional[LiquidityZoneEngine] = None,
        risk: Optional[SharedRiskEngine] = None,
        vwap: Optional[VWAPEngine] = None,
        supertrend: Optional[SupertrendEngine] = None,
        morning_session: Optional[SharedSessionManager] = None,
        afternoon_session: Optional[SharedSessionManager] = None,
    ) -> None:
        self.config = config or PullbackMasterConfig()
        self.order_blocks = order_blocks or SharedOrderBlockEngine()
        self.fair_value_gaps = fair_value_gaps or FairValueGapEngine()
        self.liquidity = liquidity or LiquidityZoneEngine()
        self.risk = risk or SharedRiskEngine()
        self.vwap = vwap or VWAPEngine()
        self.supertrend = supertrend or SupertrendEngine(
            factor=self._profile_st_factor(), atr_length=self._profile_st_length()
        )
        self.morning_session = morning_session or SharedSessionManager(SessionConfig(
            mode=self.config.trading_mode,
            entry_session="0915-1200",
            square_off_session=self.config.square_off_session,
        ))
        self.afternoon_session = afternoon_session or SharedSessionManager(SessionConfig(
            mode=self.config.trading_mode,
            entry_session="1400-1515",
            square_off_session=self.config.square_off_session,
        ))
        self.atr = TradingViewATR(14)
        self.state = PullbackMasterState()
        self.history: list[Dict[str, Any]] = []
        self.volumes: list[float] = []
        self.canonical_supertrend_last_timestamp: Optional[int] = None

    def evaluate(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        raw_bar = context.get("bar")
        if not isinstance(raw_bar, Mapping):
            return self._wait("MARKET_CONTEXT_REQUIRED", status="NOT_IMPLEMENTED")
        bar = PullbackBar.from_mapping(raw_bar)
        if self.state.last_bar_index is not None and bar.index <= self.state.last_bar_index:
            return self._wait("BAR_ALREADY_EVALUATED")

        morning = self.morning_session.evaluate(bar.timestamp)
        afternoon = self.afternoon_session.evaluate(bar.timestamp)
        session_allowed = self._entry_session_allowed(morning.entry_allowed, afternoon.entry_allowed)
        session_square_off = morning.square_off or afternoon.square_off
        vwap = self.vwap.update(timestamp=bar.timestamp, high=bar.high, low=bar.low,
                                close=bar.close, volume=bar.volume, session_key=morning.session_date)
        st_status = self._advance_canonical_supertrend(context, bar)
        st_value = self.supertrend.value
        st_direction = self.supertrend.direction
        atr = self.atr.update(bar.high, bar.low, bar.close)
        self.volumes.append(bar.volume)
        self.volumes = self.volumes[-max(self.config.retest_volume_length, 1):]
        volume_average = VolumeFilter.sma(self.volumes, self.config.retest_volume_length)
        events: list[Dict[str, Any]] = []
        action, reason = "WAIT", "NO_PULLBACK_ACTION"
        exit_price: Optional[float] = None
        exit_reason: Optional[str] = None
        exited: Optional[PullbackPosition] = None

        # Pine order: target refresh, OB trail, ST trail, BE/MFE, FVG target,
        # target-before-stop exit, then candidate selection. Shared state mutation
        # (OB/FVG/liquidity creation and mitigation) is intentionally external.
        position = self.state.position
        if position and position.target is None and self.config.target_mode == "Bearish VOB":
            target = self._nearest_bearish_target(position.entry)
            if target:
                position.target, position.target_top = target
                events.append(self._event("TARGET_ASSIGNED", bar, target=target[0]))

        if position and self.config.trail_new_bull_ob and bar.confirmed:
            eligible = [block for block in self.order_blocks.bullish if not block.is_breaker
                        and block.loc > position.entry_time and block.loc > position.trail_ob_location
                        and block.btm > position.base_top and block.btm > position.stop
                        and bar.close > block.top]
            if eligible:
                candidate = max(eligible, key=lambda block: block.loc)
                old = position.stop
                position.stop, position.trail_ob_location = candidate.btm, candidate.loc
                events.append(self._event("STOP_TRAILED_ORDER_BLOCK", bar, previous_stop=old, stop=position.stop))

        if position and self._profile_use_supertrend() and bar.confirmed and st_value is not None:
            direction_ok = not self.config.supertrend_only_bullish or st_direction == -1
            if direction_ok and position.stop < st_value < bar.close:
                old = position.stop
                position.stop = st_value
                events.append(self._event("STOP_TRAILED_SUPERTREND", bar, previous_stop=old, stop=position.stop))

        if position and position.initial_risk > 0:
            position.max_high = max(position.max_high, bar.high)
            favorable = max(0.0, position.max_high - position.entry)
            protected = position.stop
            if self._use_break_even() and not position.break_even_armed and favorable >= position.initial_risk * self._break_even_r():
                position.break_even_armed = True
            if position.break_even_armed:
                protected = max(protected, position.entry)
            if self._use_mfe_trail() and favorable >= position.initial_risk * self._mfe_start_r():
                protected = max(protected, position.max_high - favorable * self._mfe_giveback_pct() / 100.0)
            if bar.confirmed and protected > position.stop:
                old = position.stop
                position.stop = protected
                events.append(self._event("STOP_TRAILED_PROTECTION", bar, previous_stop=old, stop=protected))

        if position and self._profile_use_bear_fvg() and position.target is not None and position.target_top is not None:
            fvg = self._bear_fvg_target(position)
            if fvg and (fvg[0] != position.bear_fvg_target or fvg[2] != position.bear_fvg_target_time):
                position.bear_fvg_target, position.bear_fvg_target_top, position.bear_fvg_target_time = fvg
                events.append(self._event("BEAR_FVG_TARGET_ASSIGNED", bar, target=fvg[0]))

        position = self.state.position
        safe = not self.config.broker_safe or bar.confirmed
        if position:
            fvg_hit = bool(self._profile_use_bear_fvg() and position.bear_fvg_target is not None
                           and bar.high >= position.bear_fvg_target)
            target_hit = fvg_hit or bool(safe and position.target is not None and (
                bar.high >= position.target if self.config.sell_touch_mode == "Wick Touch"
                else bar.close >= position.target and (position.target_top is None or bar.close <= position.target_top)
            ))
            trailed_to_new_ob = position.trail_ob_location != position.ob_location
            stop_hit = (bar.confirmed and bar.close < position.stop) if trailed_to_new_ob else bool(safe and (
                bar.close < position.stop if self.config.stop_trigger_mode == "Close Below VOB" else bar.low < position.stop
            ))
            if session_square_off:
                action, reason, exit_reason, exit_price = (
                    "SELL", "SESSION_SQUARE_OFF", "SESSION_SQUARE_OFF", bar.close,
                )
            elif target_hit:
                action, reason, exit_reason = "SELL", "TARGET_REACHED", "TARGET"
                exit_price = position.bear_fvg_target if fvg_hit else position.target
            elif stop_hit:
                action, reason, exit_reason, exit_price = "SELL", "STOP_LOSS_REACHED", "STOP", position.stop
            if action == "SELL":
                exited = position
                events.append(self._event(f"POSITION_EXIT_{exit_reason}", bar, price=exit_price))
                self.state.position = None
                self.state.last_action_bar = bar.index

        can_open = (self.state.position is None and
                    (self.state.last_action_bar is None or bar.index > self.state.last_action_bar))
        if action == "WAIT" and can_open and self.order_blocks.bullish:
            candidate = self._select_candidate(bar, context, atr, volume_average, session_allowed)
            if candidate:
                block, entry, target, target_top, score = candidate
                position = PullbackPosition(
                    entry=entry, stop=block.btm, target=target, target_top=target_top,
                    ob_location=block.loc, base_top=block.top, score=score,
                    trail_ob_location=block.loc, entry_time=bar.time_ms,
                    initial_risk=max(entry - block.btm, self.config.tick_size), max_high=bar.high,
                )
                self.state.position = position
                self.state.used_bull_ob_locations.insert(0, block.loc)
                del self.state.used_bull_ob_locations[100:]
                self.state.last_action_bar = bar.index
                action, reason = "BUY", "PULLBACK_CONFIRMED"
                events.append(self._event("POSITION_OPENED", bar, price=entry, setup_location=block.loc, score=score))

        self.history.append({"index": bar.index, "time": bar.time_ms, "open": bar.open,
                             "high": bar.high, "low": bar.low, "close": bar.close,
                             "volume": bar.volume, "bull_fvg": bool(context.get("bull_fvg")),
                             "bull_breakaway_fvg": bool(context.get("bull_breakaway_fvg"))})
        self.history = self.history[-500:]
        self.state.sequence += 1
        self.state.last_bar_index = bar.index
        active = self.state.position
        evidence = active if action != "SELL" else exited
        underlying_price = active.entry if action == "BUY" and active else exit_price
        paper_price = self._number(context.get("paper_price", context.get("option_price")))
        contract = context.get("option_contract", context.get("contract"))
        result: Dict[str, Any] = {
            "status": "EVALUATED", "reason": reason, "signal": action,
            "evaluation_id": f"pullback-master:{bar.timestamp.isoformat()}:{bar.index}:{self.state.sequence}",
            "bar_index": bar.index, "bar_timestamp": bar.timestamp.isoformat(), "side": "LONG",
            "position_effect": "OPEN" if action == "BUY" else "CLOSE" if action == "SELL" else None,
            "contract": contract, "entry": paper_price if action == "BUY" else None,
            "exit": paper_price if action == "SELL" else None, "execution_price": paper_price,
            "underlying_entry": underlying_price if action == "BUY" else None,
            "underlying_exit": underlying_price if action == "SELL" else None,
            "underlying_stop": evidence.stop if evidence else None,
            "underlying_target": evidence.target if evidence else None,
            "stop": self._number(context.get("paper_stop")), "target": self._number(context.get("paper_target")),
            "position_state": asdict(active) if active else None,
            "used_setup_locations": list(self.state.used_bull_ob_locations),
            "events": events, "journal_events": list(events), "replay_events": list(events),
            "evidence_events": list(events), "exit_reason": exit_reason,
            "alert": self._alert(action, context, paper_price or underlying_price, evidence, exit_reason) if action != "WAIT" else None,
            "paper_only": True, "paper_execution_enabled": False, "broker_submission": False,
            "live_trading_enabled": False,
            "shared_core": {"vwap": vwap.value, "supertrend": st_value,
                            "supertrend_direction": st_direction,
                            "supertrend_timeframe": "5m",
                            "supertrend_authority": "CANONICAL_OPTION_PREMIUM_5M",
                            "supertrend_source_status": st_status,
                            "supertrend_last_timestamp": self.canonical_supertrend_last_timestamp,
                            "atr": atr,
                            "session_allowed": session_allowed, "square_off": session_square_off,
                            "risk": self.risk.snapshot(),
                            "order_block_count": len(self.order_blocks.bullish) + len(self.order_blocks.bearish),
                            "fvg_count": len(self.fair_value_gaps.bullish) + len(self.fair_value_gaps.bearish),
                            "liquidity_zone_count": len(self.liquidity.zones)},
        }
        if action != "WAIT" and (not contract or paper_price is None):
            result["execution_readiness"] = "BLOCKED_AUTHORITATIVE_OPTION_REQUIRED"
        return result

    def _advance_canonical_supertrend(self, context: Mapping[str, Any], bar: PullbackBar) -> str:
        """Advance only legally available completed canonical 5m bars.

        ``request.security(..., lookahead_off)`` exposes a completed historical
        5m value on the lower-timeframe candle whose close reaches that 5m
        boundary.  The supplemental source is pre-filtered by the context
        provider; this second boundary and contract check makes replay
        independently no-future-safe.
        """

        raw_rows = context.get("canonical_5m_candles")
        if not isinstance(raw_rows, list):
            return "CANONICAL_5M_REQUIRED"
        raw_bar = context.get("bar")
        close_value = raw_bar.get("candle_closed_at") if isinstance(raw_bar, Mapping) else None
        try:
            evaluation_close = (
                close_value
                if isinstance(close_value, datetime)
                else datetime.fromisoformat(str(close_value).replace("Z", "+00:00"))
                if close_value
                else bar.timestamp + timedelta(minutes=self._context_interval_minutes(context))
            )
        except (TypeError, ValueError):
            return "CANONICAL_5M_CLOSE_INVALID"
        evaluation_close = self._align_timezone(evaluation_close, bar.timestamp)
        expected_contract = str(context.get("contract") or context.get("option_contract") or "")
        advanced = 0
        for raw in sorted(
            (row for row in raw_rows if isinstance(row, Mapping)),
            key=lambda row: str(row.get("timestamp") or row.get("time") or ""),
        ):
            try:
                opened = raw.get("timestamp", raw.get("time"))
                opened_at = opened if isinstance(opened, datetime) else datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
                opened_at = self._align_timezone(opened_at, bar.timestamp)
                closed = raw.get("candle_closed_at")
                closed_at = (
                    closed
                    if isinstance(closed, datetime)
                    else datetime.fromisoformat(str(closed).replace("Z", "+00:00"))
                    if closed
                    else opened_at + timedelta(minutes=5)
                )
                closed_at = self._align_timezone(closed_at, bar.timestamp)
                timestamp_ms = int(opened_at.timestamp() * 1000)
                row_contract = str(
                    raw.get("contract")
                    or (raw.get("chart_contract") or {}).get("security_id")
                    or ""
                )
                if closed_at > evaluation_close:
                    continue
                if expected_contract and row_contract and row_contract != expected_contract:
                    continue
                if self.canonical_supertrend_last_timestamp is not None and timestamp_ms <= self.canonical_supertrend_last_timestamp:
                    continue
                self.supertrend.update(
                    high=float(raw["high"]), low=float(raw["low"]), close=float(raw["close"])
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            self.canonical_supertrend_last_timestamp = timestamp_ms
            advanced += 1
        if advanced:
            return "ADVANCED_COMPLETED_5M"
        if self.canonical_supertrend_last_timestamp is not None:
            return "CARRIED_FORWARD_COMPLETED_5M"
        return "CANONICAL_5M_WARMUP_REQUIRED"

    @staticmethod
    def _context_interval_minutes(context: Mapping[str, Any]) -> int:
        value = str(context.get("timeframe") or "1m").strip().lower()
        return int(value[:-1]) if value.endswith("m") and value[:-1].isdigit() else 1

    @staticmethod
    def _align_timezone(value: datetime, reference: datetime) -> datetime:
        if value.tzinfo is None and reference.tzinfo is not None:
            return value.replace(tzinfo=reference.tzinfo)
        if value.tzinfo is not None and reference.tzinfo is not None:
            return value.astimezone(reference.tzinfo)
        return value

    def _select_candidate(self, bar: PullbackBar, context: Mapping[str, Any], atr: Optional[float],
                          volume_average: Optional[float], session_allowed: bool
                          ) -> Optional[tuple[OrderBlock, float, Optional[float], Optional[float], float]]:
        total = sum(block.vol for block in self.order_blocks.bullish[:self.config.visible_order_blocks])
        selected: Optional[tuple[OrderBlock, float, Optional[float], Optional[float], float]] = None
        for block in self.order_blocks.bullish:
            if block.is_breaker or block.loc in self.state.used_bull_ob_locations:
                continue
            touched = (bar.low <= block.top and bar.high >= block.btm) if self.config.buy_touch_mode == "Wick Touch" else (
                bar.confirmed and block.btm <= bar.close <= block.top)
            invalid = (bar.confirmed and bar.close < block.btm) if self.config.stop_trigger_mode == "Close Below VOB" else bar.low < block.btm
            prior = [item for item in self.history if item["time"] > block.loc]
            bars_since = next((offset for offset, item in enumerate(reversed(self.history), 1) if item["time"] == block.loc),
                              max(0, int((bar.time_ms - block.loc) / max(self._bar_interval_ms(), 1))))
            moved_away = any(item["high"] > block.top + self.config.move_away_points for item in prior)
            prior_touches = sum(item["low"] <= block.top and item["high"] >= block.btm for item in prior)
            real_pullback = not self.config.profile_require_pullback or (
                bars_since >= self.config.min_bars_after_ob and moved_away)
            higher_broken = any(other is not block and not other.is_breaker and other.btm > block.top
                                and bar.low <= other.top and bar.high >= other.btm and bar.low < other.btm
                                for other in self.order_blocks.bullish)
            entry = block.top if self.config.entry_mode == "OB Top" else bar.close
            raw_target = self._nearest_bearish_target(entry)
            risk = max(entry - block.btm, self.config.tick_size)
            rr_target = entry + risk * self.config.rr_target
            target, target_top = self._target(raw_target, rr_target)
            target_ok = self.config.target_mode == "No Target Trail Only" or not self.config.require_target or target is not None
            room = None if target is None else (target - entry) / risk
            room_ok = (not self.config.profile_min_target_room or self.config.target_mode == "No Target Trail Only"
                       or (room is not None and room >= self.config.profile_min_target_rr))
            bull_fvg_now = bool(context.get("bull_fvg"))
            bull_fvg_previous = bool(self.history and self.history[-1].get("bull_fvg"))
            fvg_ok = not self.config.use_fvg_filter or {
                "Touch Candle": bull_fvg_now, "Previous Candle": bull_fvg_previous,
                "Touch Candle Or Previous": bull_fvg_now or bull_fvg_previous,
            }[self.config.fvg_filter_mode]
            recent_sweeps = [zone for zone in self.liquidity.zones if zone.side == "LOWER" and zone.grabbed
                             and zone.grabbed_index is not None and bar.index - zone.grabbed_index <= self.config.liquidity_lookback_bars]
            recent_sweep = bool(recent_sweeps)
            sweep_after_ob = any(zone.grabbed_time is not None and zone.grabbed_time >= block.loc for zone in recent_sweeps)
            sweep_belongs = not self.config.liquidity_after_ob_only or sweep_after_ob
            sweep_on_touch = not self.config.liquidity_same_vob_touch or bool(
                recent_sweeps and recent_sweeps[-1].grabbed_index == bar.index and touched and bar.low <= block.top and bar.close > block.btm)
            liquidity_ok = not self.config.profile_liquidity_filter or recent_sweep and sweep_belongs and sweep_on_touch
            pb_range = max(bar.high - bar.low, self.config.tick_size)
            body_pct = abs(bar.close - bar.open) / pb_range * 100.0
            atr_base = atr if atr is not None else pb_range
            sweeping = touched and bar.close > block.btm and (recent_sweep or bar.low < block.btm or (bar.low < block.top and bar.close > block.top))
            aggressive = touched and not sweeping and bar.close < bar.open and body_pct >= self.config.aggressive_body_pct and pb_range >= atr_base * self.config.aggressive_range_atr
            corrective = touched and not sweeping and not aggressive
            allow_aggressive = False if self.config.pullback_mode == "Conservative" else self.config.allow_aggressive
            type_ok = not self.config.profile_pullback_type_filter or (
                self.config.allow_sweeping and sweeping or allow_aggressive and aggressive or self.config.allow_corrective and corrective)
            htf_ok = not self.config.use_htf_confirmation or context.get("htf_confirmation") is True
            ltf_ok = not self.config.use_ltf_confirmation or context.get("ltf_confirmation") is True
            optional = {"obv": self.config.use_obv_score, "mfi": self.config.use_mfi_score,
                        "vwap": self.config.use_vwap_score, "index": self.config.use_index_score}
            confirmation_values = {name: context.get(f"{name}_confirmation") is True for name in optional}
            extra_ok = not self.config.require_enabled_extra_confirmations or all(
                not enabled or confirmation_values[name] for name, enabled in optional.items())
            score = self._score(block, bar, atr_base, volume_average, total, prior_touches,
                                recent_sweep and sweep_belongs, sweeping, aggressive, corrective,
                                room is not None and room >= self.config.profile_min_target_rr,
                                bull_fvg_now or bull_fvg_previous, bool(context.get("bull_breakaway_fvg")),
                                confirmation_values)
            score_ok = not self.config.profile_strength_filter or score >= self.config.profile_min_strength
            buy_ok = (touched and real_pullback and fvg_ok and liquidity_ok and type_ok and htf_ok and ltf_ok
                      and extra_ok and score_ok and session_allowed and not invalid and not higher_broken
                      and target_ok and room_ok and (not self.config.buy_on_close or bar.confirmed)
                      and (not self.config.broker_safe or bar.confirmed))
            if not buy_ok:
                continue
            value = (block, entry, target, target_top, score)
            if selected is None or (score > selected[4] or score == selected[4] and block.top > selected[0].top
                                    if self.config.profile_strength_filter else block.top > selected[0].top):
                selected = value
        return selected

    def _score(self, block: OrderBlock, bar: PullbackBar, atr: float, volume_average: Optional[float],
               total_volume: float, prior_touches: int, recent_sweep: bool, sweeping: bool,
               aggressive: bool, corrective: bool, target_room: bool, bull_fvg: bool,
               breakaway: bool, confirmations: Mapping[str, bool]) -> float:
        pb_range = max(bar.high - bar.low, self.config.tick_size)
        body_pct = abs(bar.close - bar.open) / pb_range * 100.0
        close_pct = (bar.close - bar.low) / pb_range * 100.0
        close_near_high = close_pct >= 100.0 - self.config.close_near_high_pct
        share = block.vol / total_volume * 100.0 if total_volume > 0 else 0.0
        average = bar.volume if volume_average is None else volume_average
        ratio = bar.volume / max(average, 1.0)
        rel_volume = min(self.config.relative_volume_weight,
                         ratio / self.config.retest_volume_multiplier * self.config.relative_volume_weight)
        body_quality = min(1.0, body_pct / self.config.displacement_body_pct)
        close_quality = min(1.0, close_pct / max(100.0 - self.config.close_near_high_pct, 1.0))
        range_quality = min(1.0, pb_range / max(atr * self.config.displacement_atr_multiplier, self.config.tick_size))
        spread = ((body_quality * .4 + close_quality * .35 + range_quality * .25)
                  * self.config.spread_quality_weight if bar.close > bar.open else 0.0)
        lows = [item["low"] for item in self.history[-self.config.context_lookback:]] + [bar.low]
        recent = self.history[-self.config.chop_lookback:]
        chop_range = (max([item["high"] for item in recent] + [bar.high]) -
                      min([item["low"] for item in recent] + [bar.low]))
        zone_height = max(block.top - block.btm, self.config.tick_size)
        depth = max(0.0, min(1.0, (block.top - bar.low) / zone_height))
        score = 2.0 if share >= self.config.strong_volume_share_pct else 0.0
        score += rel_volume + (0.5 if bar.volume >= average * self.config.retest_volume_multiplier else 0.0) + spread
        score += sum(self.config.extra_score_weight for name, enabled in (
            ("obv", self.config.use_obv_score), ("mfi", self.config.use_mfi_score),
            ("vwap", self.config.use_vwap_score), ("index", self.config.use_index_score))
                     if enabled and confirmations[name])
        score += 1.5 if bar.close > bar.open and close_near_high and bar.close > block.btm else 0.0
        score += self.config.fvg_confluence_bonus if bull_fvg else 0.0
        score += 0.75 if breakaway else 0.0
        score += 1.25 if bar.close > bar.open and body_pct >= self.config.displacement_body_pct and pb_range >= atr * self.config.displacement_atr_multiplier and close_near_high else 0.0
        score += 1.0 if recent_sweep else 0.0
        score += 1.0 if target_room else 0.0
        score += 1.0 if sweeping else 0.5 if corrective else 0.0
        score += 0.5 if block.direction == 1 else 0.0
        score += self.config.first_touch_bonus if prior_touches == 0 else 0.0
        score += 1.0 if block.btm <= min(lows) + atr * self.config.context_atr_buffer else 0.0
        score -= 1.0 if aggressive else 0.0
        score -= min(2.0, prior_touches * self.config.repeated_retest_penalty)
        score -= 1.5 if chop_range <= atr * self.config.chop_atr_multiplier else 0.0
        score -= 1.0 if self.config.tiny_zone_penalty_points > 0 and zone_height < self.config.tiny_zone_penalty_points else 0.0
        score -= 1.5 if not target_room else 0.0
        score -= self.config.deep_pierce_penalty if depth > .65 and not (bar.close > block.top and close_near_high) else 0.0
        return max(0.0, min(10.0, score))

    def _target(self, raw: Optional[tuple[float, float]], rr: float) -> tuple[Optional[float], Optional[float]]:
        if self.config.target_mode == "No Target Trail Only":
            return None, None
        if self.config.target_mode == "Bearish VOB":
            return raw or (None, None)
        if self.config.target_mode == "Fixed RR":
            return rr, None
        if self.config.target_mode == "Nearest: VOB or RR":
            return raw if raw and raw[0] <= rr else (rr, None)
        return raw if raw and raw[0] >= rr else (rr, None)

    def _nearest_bearish_target(self, reference: float) -> Optional[tuple[float, float]]:
        candidates = [block for block in self.order_blocks.bearish if not block.is_breaker and block.btm > reference]
        if not candidates:
            return None
        block = min(candidates, key=lambda item: item.btm)
        return block.btm, block.top

    def _bear_fvg_target(self, position: PullbackPosition) -> Optional[tuple[float, float, int]]:
        best: Optional[tuple[float, float, int, float]] = None
        for gap in self.fair_value_gaps.bearish:
            if gap.is_breaker or gap.top - gap.btm < self.config.bear_fvg_min_gap or gap.btm <= position.entry:
                continue
            below = gap.top <= position.target and gap.top >= position.target - self._profile_fvg_buffer()
            inside = gap.top >= position.target and gap.btm <= position.target_top
            allowed = ((self.config.bear_fvg_location in {"Below Supply Only", "Below Or Inside Supply"} and below)
                       or (self.config.bear_fvg_location in {"Inside Supply Only", "Below Or Inside Supply"} and inside))
            if not allowed:
                continue
            distance = 0.0 if inside else position.target - gap.top
            value = (gap.btm, gap.top, gap.loc, distance)
            if best is None or distance < best[3] or distance == best[3] and gap.btm > best[0]:
                best = value
        return None if best is None else best[:3]

    def _entry_session_allowed(self, morning: bool, afternoon: bool) -> bool:
        if self.config.pullback_mode not in {"V4", "Conservative"}:
            return True
        return morning or (self.config.pullback_mode == "V4" and afternoon)

    def _profile_use_supertrend(self) -> bool:
        return self.config.use_supertrend_trail

    def _profile_st_length(self) -> int:
        return 8 if self.config.pullback_mode in {"V4", "Conservative"} else 10 if self.config.pullback_mode == "Aggressive" else self.config.supertrend_atr_length

    def _profile_st_factor(self) -> float:
        return 2.8 if self.config.pullback_mode in {"V4", "Conservative"} else 3.5 if self.config.pullback_mode == "Aggressive" else self.config.supertrend_factor

    def _profile_use_bear_fvg(self) -> bool:
        return self.config.pullback_mode not in {"V1", "V2"} and self.config.use_bear_fvg_supply_target

    def _profile_fvg_buffer(self) -> float:
        return 12.0 if self.config.pullback_mode == "Conservative" else 25.0 if self.config.pullback_mode == "Aggressive" else self.config.bear_fvg_supply_buffer

    def _use_break_even(self) -> bool:
        return self.config.pullback_mode in {"V4", "Aggressive", "Conservative"}

    def _use_mfe_trail(self) -> bool:
        return self._use_break_even()

    def _break_even_r(self) -> float:
        return 1.0 if self.config.pullback_mode == "Aggressive" else .75

    def _mfe_start_r(self) -> float:
        return 3.0 if self.config.pullback_mode == "Aggressive" else 2.0

    def _mfe_giveback_pct(self) -> float:
        return 35.0 if self.config.pullback_mode == "Conservative" else 55.0 if self.config.pullback_mode == "Aggressive" else 40.0

    def _bar_interval_ms(self) -> int:
        if len(self.history) < 2:
            return 180_000
        return max(1, self.history[-1]["time"] - self.history[-2]["time"])

    def _event(self, kind: str, bar: PullbackBar, **values: Any) -> Dict[str, Any]:
        return {"event": kind, "bar_index": bar.index, "timestamp": bar.timestamp.isoformat(), **values}

    def _alert(self, action: str, context: Mapping[str, Any], price: Optional[float],
               position: Optional[PullbackPosition], exit_reason: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.config.alerts_enabled:
            return None
        details = ""
        if self.config.alert_details:
            details = f"|price={self._fmt(price)}|sl={self._fmt(position.stop if position else None)}|target={self._fmt(position.target if position else None)}"
        return {"action": action, "exit_reason": exit_reason,
                "message": f"{action}|symbol={context.get('symbol', '')}|tf={context.get('timeframe', '')}{details}"}

    @staticmethod
    def _fmt(value: Optional[float]) -> str:
        return "na" if value is None else str(float(value))

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = float(value)
        return result if math.isfinite(result) else None

    @staticmethod
    def _wait(reason: str, *, status: str = "EVALUATED") -> Dict[str, Any]:
        return {"status": status, "reason": reason, "signal": "WAIT", "paper_only": True,
                "paper_execution_enabled": False, "broker_submission": False, "live_trading_enabled": False}

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION, "config": asdict(self.config),
            "state": {"used_bull_ob_locations": list(self.state.used_bull_ob_locations),
                      "position": asdict(self.state.position) if self.state.position else None,
                      "last_action_bar": self.state.last_action_bar, "sequence": self.state.sequence,
                      "last_bar_index": self.state.last_bar_index},
            "history": list(self.history), "volumes": list(self.volumes), "atr": self.atr.snapshot(),
            "canonical_supertrend_last_timestamp": self.canonical_supertrend_last_timestamp,
            "order_blocks": json.loads(self.order_blocks.serialize()),
            "fair_value_gaps": json.loads(self.fair_value_gaps.serialize()),
            "liquidity": json.loads(self.liquidity.serialize()), "risk": json.loads(self.risk.serialize()),
            "vwap": json.loads(self.vwap.serialize()), "supertrend": json.loads(self.supertrend.serialize()),
            "morning_session": json.loads(self.morning_session.serialize()),
            "afternoon_session": json.loads(self.afternoon_session.serialize()),
        }

    def serialize(self) -> str:
        return json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def deserialize(cls, payload: str) -> "PullbackMasterStrategyEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported PULLBACK MASTER state schema")
        engine = cls(
            PullbackMasterConfig(**value["config"]),
            order_blocks=SharedOrderBlockEngine.deserialize(json.dumps(value["order_blocks"])),
            fair_value_gaps=FairValueGapEngine.deserialize(json.dumps(value["fair_value_gaps"])),
            liquidity=LiquidityZoneEngine.deserialize(json.dumps(value["liquidity"])),
            risk=SharedRiskEngine.deserialize(json.dumps(value["risk"])),
            vwap=VWAPEngine.deserialize(json.dumps(value["vwap"])),
            supertrend=SupertrendEngine.deserialize(json.dumps(value["supertrend"])),
            morning_session=SharedSessionManager.deserialize(json.dumps(value["morning_session"])),
            afternoon_session=SharedSessionManager.deserialize(json.dumps(value["afternoon_session"])),
        )
        state = value["state"]
        engine.state = PullbackMasterState(
            used_bull_ob_locations=[int(item) for item in state.get("used_bull_ob_locations", [])],
            position=PullbackPosition(**state["position"]) if state.get("position") else None,
            last_action_bar=state.get("last_action_bar"), sequence=int(state.get("sequence", 0)),
            last_bar_index=state.get("last_bar_index"),
        )
        engine.history = list(value.get("history", []))
        engine.volumes = [float(item) for item in value.get("volumes", [])]
        engine.atr = TradingViewATR.restore(value["atr"])
        engine.canonical_supertrend_last_timestamp = value.get("canonical_supertrend_last_timestamp")
        return engine

    def save(self, path: Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(self.serialize(), encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: Path) -> "PullbackMasterStrategyEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
