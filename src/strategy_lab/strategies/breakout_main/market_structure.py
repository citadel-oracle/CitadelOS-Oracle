"""BREAKOUT MAIN Market Structure engine defined by the Phase 3A contract."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class MarketStructureConfig:
    window_enabled: bool = True
    window_bars: int = 5000
    algorithmic_logic: str = "Adjusted Points"
    pivot_length: int = 5
    build_sweeps: bool = True
    max_bars_back: int = 5000

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None):
        raw = dict(value or {})
        config = cls(
            window_enabled=raw.get("window_enabled", True),
            window_bars=raw.get("window_bars", 5000),
            algorithmic_logic=raw.get("algorithmic_logic", "Adjusted Points"),
            pivot_length=raw.get("pivot_length", 5),
            build_sweeps=raw.get("build_sweeps", True),
            max_bars_back=raw.get("max_bars_back", 5000),
        )
        if not isinstance(config.window_enabled, bool) or not isinstance(config.build_sweeps, bool):
            raise ValueError("market-structure boolean configuration is invalid")
        if not isinstance(config.window_bars, int) or config.window_bars < 1000:
            raise ValueError("window_bars must be an integer >= 1000")
        if not isinstance(config.pivot_length, int) or config.pivot_length < 2:
            raise ValueError("pivot_length must be an integer >= 2")
        if config.algorithmic_logic not in {"Adjusted Points", "Extreme Points"}:
            raise ValueError("algorithmic_logic is invalid")
        if config.max_bars_back != 5000:
            raise ValueError("max_bars_back must preserve the Pine value 5000")
        return config


@dataclass
class StructureState:
    zn: Optional[int] = None
    zz: Optional[float] = None
    bos: Optional[float] = None
    choch: Optional[float] = None
    loc: Optional[int] = None
    temp: Optional[int] = None
    trend: int = 0
    start: int = 0
    main: Optional[float] = None
    xloc: Optional[int] = None
    upsweep: bool = False
    dnsweep: bool = False
    txt: Optional[str] = None


@dataclass(frozen=True)
class StructureEvent:
    event: str
    direction: str
    level: float
    bar_index: int


@dataclass
class _Bar:
    index: int
    open: float
    high: float
    low: float
    close: float
    timestamp: Any = None


class MarketStructureEngine:
    SCHEMA_VERSION = 1

    def __init__(self, config: Optional[Mapping[str, Any] | MarketStructureConfig] = None):
        self.config = config if isinstance(config, MarketStructureConfig) else MarketStructureConfig.from_mapping(config)
        self.state = StructureState()
        self.up: Optional[float] = None
        self.dn: Optional[float] = None
        self.phn: list[Optional[int]] = [None]
        self.pln: list[Optional[int]] = [None]
        self.php: list[Optional[float]] = [None]
        self.plp: list[Optional[float]] = [None]
        self.timer_start = False
        self.timer_count = 0
        self.events: list[StructureEvent] = []
        self._history: list[_Bar] = []

    def process_bars(self, bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows = [self._coerce_bar(value) for value in bars]
        last_bar_index = rows[-1].index if rows else None
        return [self._process(bar, last_bar_index) for bar in rows]

    def update(self, bar: Mapping[str, Any], *, last_bar_index: Optional[int] = None) -> dict[str, Any]:
        current = self._coerce_bar(bar)
        return self._process(current, current.index if last_bar_index is None else last_bar_index)

    def find(self, use_max: bool, *, sweep: bool = False) -> int:
        origin = self.state.xloc if sweep else self.state.loc
        if origin is None or not self._history:
            return 0
        distance = self._history[-1].index - origin
        end = distance - 1 if distance - 1 > 0 else distance
        maximum = 0.0
        minimum = 99_999_999.0
        selected = 0
        for offset in range(0, end + 1):
            bar = self._at(offset)
            if use_max:
                maximum = max(bar.high, maximum)
                if maximum == bar.high:
                    minimum = bar.low
                    selected = offset
            else:
                minimum = min(bar.low, minimum)
                if minimum == bar.low:
                    maximum = bar.high
                    selected = offset
        return selected

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": "MARKET_STRUCTURE_COMPLETE",
            "config": asdict(self.config),
            "state": asdict(self.state),
            "up": self.up,
            "dn": self.dn,
            "phn": list(self.phn),
            "pln": list(self.pln),
            "php": list(self.php),
            "plp": list(self.plp),
            "timer_start": self.timer_start,
            "timer_count": self.timer_count,
            "events": [asdict(event) for event in self.events],
            "history": [asdict(bar) for bar in self._history],
        }

    @classmethod
    def restore(cls, value: Mapping[str, Any]):
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("market-structure schema version is unsupported")
        engine = cls(value.get("config"))
        engine.state = StructureState(**dict(value.get("state") or {}))
        engine.up = value.get("up")
        engine.dn = value.get("dn")
        for name in ("phn", "pln", "php", "plp"):
            setattr(engine, name, list(value.get(name) or []))
        engine.timer_start = bool(value.get("timer_start"))
        engine.timer_count = int(value.get("timer_count") or 0)
        engine.events = [StructureEvent(**row) for row in value.get("events") or []]
        engine._history = [_Bar(**row) for row in value.get("history") or []]
        return engine

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self.snapshot(), handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: str | Path):
        return cls.restore(json.loads(Path(path).read_text(encoding="utf-8")))

    def _process(self, bar: _Bar, last_bar_index: Optional[int]) -> dict[str, Any]:
        if self._history and bar.index != self._history[-1].index + 1:
            raise ValueError("bar_index must be contiguous and increasing")
        self._history.append(bar)
        del self._history[: max(0, len(self._history) - (self.config.max_bars_back + 1))]
        if self.config.window_enabled and last_bar_index is not None and not (bar.index > last_bar_index - self.config.window_bars):
            return self._result(bar.index, processed=False)

        crossup = False
        crossdn = False
        self._update_pivots(bar)
        if self.up is None:
            self.up = bar.high
        if self.dn is None:
            self.dn = bar.low
        if bar.high > self.up:
            self.up = bar.high
            self.dn = bar.low
            crossup = True
        if bar.low < self.dn:
            self.up = bar.high
            self.dn = bar.low
            crossdn = True

        state = self.state
        if state.start == 0:
            state.zn = bar.index
            state.zz = None
            state.bos = bar.high
            state.choch = bar.low
            state.loc = bar.index
            state.temp = bar.index
            state.trend = 0
            state.start = 1
            state.main = None
            state.xloc = bar.index

        state.upsweep = False
        state.dnsweep = False
        if state.start == 1:
            self._bootstrap(bar)
        if state.start == 2:
            if state.trend == -1:
                self._bearish(bar, crossup)
            elif state.trend == 1:
                self._bullish(bar, crossdn)
        return self._result(bar.index, processed=True)

    def _bootstrap(self, bar: _Bar) -> None:
        state = self.state
        if self.config.build_sweeps and self._le(bar.low, state.choch) and self._ge(bar.close, state.choch):
            state.dnsweep = True
            state.choch = bar.low
            state.xloc = bar.index
        elif self.config.build_sweeps and self._ge(bar.high, state.bos) and self._le(bar.close, state.bos):
            state.upsweep = True
            state.bos = bar.high
            state.xloc = bar.index
        elif self._le(bar.close, state.choch):
            self._event("CHoCH", "BEARISH", state.choch, bar.index)
            state.trend = -1
            state.choch = state.bos
            state.bos = None
            state.start = 2
            state.loc = state.temp = state.xloc = bar.index
            state.main = bar.low
        elif self._ge(bar.close, state.bos):
            self._event("CHoCH", "BULLISH", state.bos, bar.index)
            state.trend = 1
            state.bos = None
            state.start = 2
            state.loc = state.temp = state.xloc = bar.index
            state.main = bar.high

    def _bearish(self, bar: _Bar, crossup: bool) -> None:
        state = self.state
        if self._le(bar.low, state.main):
            state.main = bar.low
            state.temp = bar.index
        if self._adjustment_bar(bar.index) and state.bos is not None and self.php:
            pivot = self.php[0]
            if pivot is not None and self._lt(pivot, state.choch):
                state.choch = pivot
                state.loc = state.xloc = state.temp = self.phn[0]
        if state.bos is None and crossup and self._bullish_candle(0) and self._bullish_candle(1):
            state.bos = state.main
            state.loc = state.temp
            state.xloc = state.loc

        if state.bos is not None and self.config.build_sweeps and self._le(bar.low, state.bos) and self._ge(bar.close, state.bos):
            state.dnsweep = True
            state.bos = bar.low
            state.xloc = bar.index
        elif state.bos is not None and self._le(bar.close, state.bos):
            level = state.bos
            self._event("BOS", "BEARISH", level, bar.index)
            selected = self.find(True)
            state.xloc = bar.index
            state.bos = None
            state.choch = self._at(selected).high
            state.loc = self._at(selected).index

        if self.config.build_sweeps and self._ge(bar.high, state.choch) and self._le(bar.close, state.choch):
            state.upsweep = True
            state.choch = bar.high
            state.xloc = bar.index
        elif self._ge(bar.close, state.choch):
            level = state.choch
            self._event("CHoCH", "BULLISH", level, bar.index)
            selected = self.find(False)
            next_choch = self._at(selected).low if state.bos is None else state.bos
            state.choch = next_choch
            state.bos = None
            state.main = bar.high
            state.trend = 1
            state.loc = state.xloc = state.temp = bar.index

    def _bullish(self, bar: _Bar, crossdn: bool) -> None:
        state = self.state
        if self._ge(bar.high, state.main):
            state.main = bar.high
            state.temp = bar.index
        if state.bos is None and crossdn and self._bearish_candle(0) and self._bearish_candle(1):
            state.bos = state.main
            state.loc = state.temp
            state.xloc = state.loc
        if self._adjustment_bar(bar.index) and state.bos is not None and self.plp:
            pivot = self.plp[0]
            if pivot is not None and self._gt(pivot, state.choch):
                state.choch = pivot
                state.loc = state.xloc = state.temp = self.pln[0]

        if state.bos is not None and self.config.build_sweeps and self._ge(bar.high, state.bos) and self._le(bar.close, state.bos):
            state.upsweep = True
            state.bos = bar.high
            state.xloc = bar.index
        elif state.bos is not None and self._ge(bar.close, state.bos):
            level = state.bos
            self._event("BOS", "BULLISH", level, bar.index)
            selected = self.find(False)
            state.xloc = bar.index
            state.bos = None
            state.choch = self._at(selected).low
            state.loc = self._at(selected).index

        if self.config.build_sweeps and self._le(bar.low, state.choch) and self._ge(bar.close, state.choch):
            state.dnsweep = True
            state.choch = bar.low
            state.xloc = bar.index
        elif self._le(bar.close, state.choch):
            level = state.choch
            self._event("CHoCH", "BEARISH", level, bar.index)
            selected = self.find(True)
            next_choch = self._at(selected).high if state.bos is None else state.bos
            state.choch = next_choch
            state.bos = None
            state.main = bar.low
            state.trend = -1
            state.loc = state.xloc = state.temp = bar.index

    def _update_pivots(self, bar: _Bar) -> None:
        length = self.config.pivot_length
        if len(self._history) >= length * 2 + 1:
            window = self._history[-(length * 2 + 1):]
            candidate = window[length]
            if candidate.high == max(item.high for item in window):
                self.phn.insert(0, candidate.index)
                self.php.insert(0, candidate.high)
            if candidate.low == min(item.low for item in window):
                self.pln.insert(0, candidate.index)
                self.plp.insert(0, candidate.low)
        if self.php and self.php[0] is not None and bar.high > self.php[0]:
            self.php.clear()
            self.phn.clear()
        if self.plp and self.plp[0] is not None and bar.low < self.plp[0]:
            self.plp.clear()
            self.pln.clear()

    def _event(self, event: str, direction: str, level: Optional[float], bar_index: int) -> None:
        if level is None:
            return
        self.state.txt = event.lower()
        self.state.zz = level
        self.state.zn = bar_index
        self.timer_start = True
        self.timer_count = 0
        self.events.append(StructureEvent(event, direction, level, bar_index))

    def _result(self, bar_index: int, *, processed: bool) -> dict[str, Any]:
        return {
            "status": "MARKET_STRUCTURE_COMPLETE",
            "processed": processed,
            "bar_index": bar_index,
            "state": asdict(self.state),
            "events": [asdict(event) for event in self.events],
        }

    def _at(self, offset: int) -> _Bar:
        if offset < 0 or offset >= len(self._history):
            raise IndexError("historical offset exceeds retained Pine history")
        return self._history[-1 - offset]

    def _bullish_candle(self, offset: int) -> bool:
        bar = self._at(offset)
        return bar.close > bar.open

    def _bearish_candle(self, offset: int) -> bool:
        bar = self._at(offset)
        return bar.close < bar.open

    def _adjustment_bar(self, bar_index: int) -> bool:
        return (bar_index % self.config.pivot_length) * 2 == 0

    @staticmethod
    def _coerce_bar(value: Mapping[str, Any]) -> _Bar:
        index = value.get("bar_index", value.get("index"))
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("bar_index must be an integer")
        numbers = {}
        for key in ("open", "high", "low", "close"):
            raw = value.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise ValueError(f"{key} must be a finite number")
            numbers[key] = float(raw)
        if numbers["high"] < max(numbers["open"], numbers["close"], numbers["low"]):
            raise ValueError("bar high is invalid")
        if numbers["low"] > min(numbers["open"], numbers["close"], numbers["high"]):
            raise ValueError("bar low is invalid")
        return _Bar(index=index, timestamp=value.get("timestamp"), **numbers)

    @staticmethod
    def _le(left: Optional[float], right: Optional[float]) -> bool:
        return left is not None and right is not None and left <= right

    @staticmethod
    def _ge(left: Optional[float], right: Optional[float]) -> bool:
        return left is not None and right is not None and left >= right

    @staticmethod
    def _lt(left: Optional[float], right: Optional[float]) -> bool:
        return left is not None and right is not None and left < right

    @staticmethod
    def _gt(left: Optional[float], right: Optional[float]) -> bool:
        return left is not None and right is not None and left > right
