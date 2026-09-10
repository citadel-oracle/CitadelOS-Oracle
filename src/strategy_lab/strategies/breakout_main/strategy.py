"""BREAKOUT MAIN strategy-specific lifecycle around the frozen shared core."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ...core import (
    OrderBlock,
    SessionConfig,
    SharedOrderBlockEngine,
    SharedSessionManager,
    SupertrendEngine,
    VWAPEngine,
    VolumeFilter,
)


@dataclass(frozen=True)
class BreakoutMainConfig:
    trading_mode: str = "Intraday"
    entry_session: str = "0915-1515"
    square_off_session: str = "1515-1530"
    reset_used_setups_each_day: bool = True
    reentry_after_stop: bool = True
    require_next_bearish_target: bool = False
    entry_mode: str = "Signal High"
    trigger_mode: str = "Wick Cross Signal High"
    target_method: str = "Wick Touch"
    stop_buffer: float = 1.0
    cancel_signal_on_stop: bool = True
    stop_mode: str = "Fixed SL"
    supertrend_factor: float = 3.0
    supertrend_atr_length: int = 10
    volume_filter_enabled: bool = False
    volume_sma_length: int = 20
    volume_multiplier: float = 1.5
    trend_filter: str = "None"
    alerts_enabled: bool = True
    alert_details: bool = True

    def __post_init__(self) -> None:
        choices = {
            "trading_mode": (self.trading_mode, {"Intraday", "Positional"}),
            "entry_mode": (self.entry_mode, {"Signal High", "Breakout Close"}),
            "trigger_mode": (self.trigger_mode, {"Wick Cross Signal High", "Close Above Signal High"}),
            "target_method": (self.target_method, {"Wick Touch", "Close Inside VOB"}),
            "stop_mode": (self.stop_mode, {"Fixed SL", "Supertrend Trail"}),
            "trend_filter": (self.trend_filter, {"None", "VWAP", "Supertrend", "VWAP+Supertrend"}),
        }
        for name, (value, allowed) in choices.items():
            if value not in allowed:
                raise ValueError(f"unsupported {name}: {value}")
        if self.stop_buffer < 0 or self.supertrend_factor <= 0 or self.supertrend_atr_length < 1:
            raise ValueError("invalid stop or Supertrend configuration")
        if self.volume_sma_length < 1 or self.volume_multiplier < 0:
            raise ValueError("invalid volume configuration")


@dataclass(frozen=True)
class BreakoutBar:
    index: int
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BreakoutBar":
        raw_time = value.get("timestamp", value.get("time"))
        if isinstance(raw_time, datetime):
            timestamp = raw_time
        elif isinstance(raw_time, (int, float)):
            timestamp = datetime.fromtimestamp(float(raw_time) / (1000 if raw_time > 10_000_000_000 else 1))
        else:
            timestamp = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        bar = cls(
            index=int(value.get("index", value.get("bar_index"))),
            timestamp=timestamp,
            open=float(value["open"]), high=float(value["high"]),
            low=float(value["low"]), close=float(value["close"]),
            volume=float(value.get("volume", 0.0)),
            confirmed=bool(value.get("confirmed", value.get("is_closed", True))),
        )
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(math.isfinite(item) for item in values) or bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            raise ValueError("invalid BREAKOUT MAIN bar")
        return bar


@dataclass
class PendingSignal:
    high: float
    low: float
    stop: float
    target: Optional[float]
    target_top: Optional[float]
    setup_location: int
    signal_bar: int


@dataclass
class LongPosition:
    entry: float
    stop: float
    target: Optional[float]
    target_top: Optional[float]
    setup_location: int
    entry_bar: int


@dataclass
class BreakoutMainState:
    used_setup_locations: list[int] = field(default_factory=list)
    pending: Optional[PendingSignal] = None
    position: Optional[LongPosition] = None
    sequence: int = 0
    last_bar_index: Optional[int] = None


class BreakoutMainStrategyEngine:
    """Long-only, bar-close BREAKOUT MAIN lifecycle; scheduling remains external/off."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        config: Optional[BreakoutMainConfig] = None,
        *,
        order_blocks: Optional[SharedOrderBlockEngine] = None,
        sessions: Optional[SharedSessionManager] = None,
        vwap: Optional[VWAPEngine] = None,
        supertrend: Optional[SupertrendEngine] = None,
    ) -> None:
        self.config = config or BreakoutMainConfig()
        self.order_blocks = order_blocks or SharedOrderBlockEngine()
        self.sessions = sessions or SharedSessionManager(SessionConfig(
            mode=self.config.trading_mode,
            entry_session=self.config.entry_session,
            square_off_session=self.config.square_off_session,
            reset_each_day=self.config.reset_used_setups_each_day,
        ))
        self.vwap = vwap or VWAPEngine()
        self.supertrend = supertrend or SupertrendEngine(
            factor=self.config.supertrend_factor,
            atr_length=self.config.supertrend_atr_length,
        )
        self.state = BreakoutMainState()
        self.volumes: list[float] = []

    def evaluate(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        raw_bar = context.get("bar")
        if not isinstance(raw_bar, Mapping):
            return self._wait("MARKET_CONTEXT_REQUIRED", status="NOT_IMPLEMENTED")
        bar = BreakoutBar.from_mapping(raw_bar)
        if self.state.last_bar_index is not None and bar.index <= self.state.last_bar_index:
            return self._wait("BAR_ALREADY_EVALUATED")

        permission = self.sessions.evaluate(bar.timestamp)
        vwap = self.vwap.update(
            timestamp=bar.timestamp, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume, session_key=permission.session_date,
        )
        trend = self.supertrend.update(high=bar.high, low=bar.low, close=bar.close)
        self.volumes.append(bar.volume)
        self.volumes = self.volumes[-max(self.config.volume_sma_length, 1):]
        volume = VolumeFilter.evaluate(
            self.volumes, length=self.config.volume_sma_length,
            multiplier=self.config.volume_multiplier, enabled=self.config.volume_filter_enabled,
        )
        events: list[Dict[str, Any]] = []
        action = "WAIT"
        reason = "NO_BREAKOUT_ACTION"
        exit_underlying: Optional[float] = None
        exit_reason: Optional[str] = None
        exited_position: Optional[LongPosition] = None

        # Pine execution order: reset, target refresh, trail, exits, new signal,
        # cancellation, target refresh, confirmation/entry. OB mitigation is external.
        if permission.daily_reset:
            self.state.used_setup_locations.clear()
            self.state.pending = None
            events.append(self._event("DAILY_RESET", bar))

        if self.state.position and self.state.position.target is None:
            target = self._nearest_target(self.state.position.entry)
            if target:
                self.state.position.target, self.state.position.target_top = target
                events.append(self._event("TARGET_ASSIGNED", bar, target=target[0]))

        if self.state.position and self.config.stop_mode == "Supertrend Trail":
            if trend.value is not None and trend.value < bar.close and trend.value > self.state.position.stop:
                old = self.state.position.stop
                self.state.position.stop = trend.value
                events.append(self._event("STOP_TRAILED", bar, previous_stop=old, stop=trend.value))

        position = self.state.position
        if position:
            target_hit = bool(position.target is not None and (
                bar.high >= position.target if self.config.target_method == "Wick Touch"
                else bar.confirmed and bar.close >= position.target and (position.target_top is None or bar.close <= position.target_top)
            ))
            stop_hit = bar.low <= position.stop
            if permission.square_off:
                action, reason, exit_underlying, exit_reason = "SELL", "SESSION_SQUARE_OFF", bar.close, "SQUARE_OFF"
            elif target_hit:
                action, reason, exit_underlying, exit_reason = "SELL", "TARGET_REACHED", position.target, "TARGET"
            elif stop_hit:
                action, reason, exit_underlying, exit_reason = "SELL", "STOP_LOSS_REACHED", position.stop, "STOP"
            if action == "SELL":
                exited_position = position
                if exit_reason == "STOP" and self.config.reentry_after_stop:
                    self._remove_last_used(position.setup_location)
                events.append(self._event(f"POSITION_EXIT_{exit_reason}", bar, price=exit_underlying))
                self.state.position = None

        can_enter = permission.entry_allowed
        if not self.state.position and not self.state.pending and can_enter and bar.confirmed:
            for candidate in self.order_blocks.bearish:  # canonical arrays are newest first
                if candidate.is_breaker or candidate.loc in self.state.used_setup_locations or bar.close <= candidate.top:
                    continue
                target = self._nearest_target(bar.high)
                if self.config.require_next_bearish_target and target is None:
                    continue
                self.state.pending = PendingSignal(
                    high=bar.high, low=bar.low, stop=bar.low - self.config.stop_buffer,
                    target=target[0] if target else None,
                    target_top=target[1] if target else None,
                    setup_location=candidate.loc, signal_bar=bar.index,
                )
                events.append(self._event("SIGNAL_CREATED", bar, setup_location=candidate.loc))
                if action == "WAIT":
                    reason = "PENDING_SIGNAL_CREATED"
                break

        pending = self.state.pending
        if not self.state.position and pending:
            failed = self.config.cancel_signal_on_stop and bar.low <= pending.stop
            expired = self.config.trading_mode == "Intraday" and not permission.entry_allowed
            if failed or expired:
                cancellation_reason = "SIGNAL_CANCELLED_STOP" if failed else "SIGNAL_CANCELLED_SESSION"
                if action == "WAIT":
                    reason = cancellation_reason
                events.append(self._event(cancellation_reason, bar, setup_location=pending.setup_location))
                self.state.pending = None

        pending = self.state.pending
        if pending and pending.target is None:
            target = self._nearest_target(pending.high)
            if target:
                pending.target, pending.target_top = target
                events.append(self._event("PENDING_TARGET_ASSIGNED", bar, target=target[0]))

        pending = self.state.pending
        trend_allowed = self._trend_allowed(bar.close, vwap.value, trend.direction)
        if action == "WAIT" and pending and can_enter and bar.index > pending.signal_bar:
            breakout = bar.high > pending.high if self.config.trigger_mode == "Wick Cross Signal High" else bar.confirmed and bar.close > pending.high
            target_allowed = not self.config.require_next_bearish_target or pending.target is not None
            if breakout and volume.confirmed and trend_allowed and target_allowed:
                entry = pending.high if self.config.entry_mode == "Signal High" else bar.close
                self.state.position = LongPosition(
                    entry=entry, stop=pending.stop, target=pending.target,
                    target_top=pending.target_top, setup_location=pending.setup_location,
                    entry_bar=bar.index,
                )
                self.state.used_setup_locations.insert(0, pending.setup_location)
                del self.state.used_setup_locations[100:]
                self.state.pending = None
                if self.state.position.target is None:
                    target = self._nearest_target(entry)
                    if target:
                        self.state.position.target, self.state.position.target_top = target
                action, reason = "BUY", "BREAKOUT_CONFIRMED"
                events.append(self._event("POSITION_OPENED", bar, price=entry, setup_location=pending.setup_location))
            elif breakout:
                reason = self._confirmation_block(volume.confirmed, trend_allowed, target_allowed)

        self.state.sequence += 1
        self.state.last_bar_index = bar.index
        evaluation_id = f"breakout-main:{bar.timestamp.isoformat()}:{bar.index}:{self.state.sequence}"
        position = self.state.position
        evidence_position = position if action != "SELL" else exited_position
        underlying_price = position.entry if action == "BUY" and position else exit_underlying
        paper_price = self._number(context.get("paper_price", context.get("option_price")))
        contract = context.get("option_contract", context.get("contract"))
        alert = self._alert(action, context, paper_price or underlying_price, evidence_position, exit_reason) if action != "WAIT" else None
        output = {
            "status": "EVALUATED", "reason": reason, "signal": action,
            "evaluation_id": evaluation_id, "bar_index": bar.index,
            "bar_timestamp": bar.timestamp.isoformat(), "position_effect": "OPEN" if action == "BUY" else "CLOSE" if action == "SELL" else None,
            "side": "LONG", "contract": contract,
            "entry": paper_price if action == "BUY" else None,
            "exit": paper_price if action == "SELL" else None,
            "execution_price": paper_price,
            "underlying_entry": underlying_price if action == "BUY" else None,
            "underlying_exit": underlying_price if action == "SELL" else None,
            "underlying_stop": evidence_position.stop if evidence_position else None,
            "underlying_target": evidence_position.target if evidence_position else None,
            "stop": self._number(context.get("paper_stop")),
            "target": self._number(context.get("paper_target")),
            "pending_signal": asdict(self.state.pending) if self.state.pending else None,
            "position_state": asdict(self.state.position) if self.state.position else None,
            "used_setup_locations": list(self.state.used_setup_locations),
            "exit_reason": exit_reason,
            "events": events, "journal_events": list(events), "replay_events": list(events), "evidence_events": list(events),
            "alert": alert, "paper_only": True, "broker_submission": False,
            "live_trading_enabled": False,
            "shared_core": {"vwap": vwap.value, "supertrend": trend.value, "supertrend_direction": trend.direction,
                            "volume_average": volume.average, "volume_confirmed": volume.confirmed,
                            "entry_allowed": permission.entry_allowed, "square_off": permission.square_off},
        }
        if action != "WAIT" and (not contract or paper_price is None):
            output["execution_readiness"] = "BLOCKED_AUTHORITATIVE_OPTION_REQUIRED"
        return output

    def _wait(self, reason: str, *, status: str = "EVALUATED") -> Dict[str, Any]:
        return {"status": status, "reason": reason, "signal": "WAIT", "paper_only": True,
                "broker_submission": False, "live_trading_enabled": False}

    def _nearest_target(self, reference: float) -> Optional[tuple[float, float]]:
        candidates = [block for block in self.order_blocks.bearish if not block.is_breaker and block.btm > reference]
        if not candidates:
            return None
        target = min(candidates, key=lambda block: block.btm)
        return target.btm, target.top

    def _trend_allowed(self, close: float, vwap: Optional[float], direction: Optional[int]) -> bool:
        vwap_ok = vwap is not None and close > vwap
        supertrend_ok = direction == -1
        return {"None": True, "VWAP": vwap_ok, "Supertrend": supertrend_ok,
                "VWAP+Supertrend": vwap_ok and supertrend_ok}[self.config.trend_filter]

    @staticmethod
    def _confirmation_block(volume: bool, trend: bool, target: bool) -> str:
        if not volume:
            return "VOLUME_FILTER_BLOCKED"
        if not trend:
            return "TREND_FILTER_BLOCKED"
        if not target:
            return "TARGET_REQUIRED"
        return "BREAKOUT_NOT_CONFIRMED"

    def _remove_last_used(self, location: int) -> None:
        matches = [index for index, value in enumerate(self.state.used_setup_locations) if value == location]
        if matches:
            self.state.used_setup_locations.pop(matches[-1])

    def _event(self, kind: str, bar: BreakoutBar, **values: Any) -> Dict[str, Any]:
        return {"event": kind, "bar_index": bar.index, "timestamp": bar.timestamp.isoformat(), **values}

    def _alert(self, action: str, context: Mapping[str, Any], price: Optional[float], position: Optional[LongPosition], exit_reason: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.config.alerts_enabled:
            return None
        stop = position.stop if position else None
        target = position.target if position else None
        details = f"|price={self._fmt(price)}|sl={self._fmt(stop)}|target={self._fmt(target)}" if self.config.alert_details else ""
        symbol, timeframe = context.get("symbol", ""), context.get("timeframe", "")
        return {"action": action, "exit_reason": exit_reason,
                "message": f"{action}|symbol={symbol}|tf={timeframe}{details}"}

    @staticmethod
    def _fmt(value: Optional[float]) -> str:
        return "na" if value is None else str(float(value))

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = float(value)
        return result if math.isfinite(result) else None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION, "config": asdict(self.config),
            "state": {"used_setup_locations": list(self.state.used_setup_locations),
                      "pending": asdict(self.state.pending) if self.state.pending else None,
                      "position": asdict(self.state.position) if self.state.position else None,
                      "sequence": self.state.sequence, "last_bar_index": self.state.last_bar_index},
            "volumes": list(self.volumes), "order_blocks": json.loads(self.order_blocks.serialize()),
            "sessions": json.loads(self.sessions.serialize()), "vwap": json.loads(self.vwap.serialize()),
            "supertrend": json.loads(self.supertrend.serialize()),
        }

    def serialize(self) -> str:
        return json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def deserialize(cls, payload: str) -> "BreakoutMainStrategyEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported BREAKOUT MAIN state schema")
        engine = cls(
            BreakoutMainConfig(**value["config"]),
            order_blocks=SharedOrderBlockEngine.deserialize(json.dumps(value["order_blocks"])),
            sessions=SharedSessionManager.deserialize(json.dumps(value["sessions"])),
            vwap=VWAPEngine.deserialize(json.dumps(value["vwap"])),
            supertrend=SupertrendEngine.deserialize(json.dumps(value["supertrend"])),
        )
        state = value["state"]
        engine.state = BreakoutMainState(
            used_setup_locations=[int(item) for item in state.get("used_setup_locations", [])],
            pending=PendingSignal(**state["pending"]) if state.get("pending") else None,
            position=LongPosition(**state["position"]) if state.get("position") else None,
            sequence=int(state.get("sequence", 0)), last_bar_index=state.get("last_bar_index"),
        )
        engine.volumes = [float(item) for item in value.get("volumes", [])]
        return engine

    def save(self, path: Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(self.serialize(), encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: Path) -> "BreakoutMainStrategyEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
