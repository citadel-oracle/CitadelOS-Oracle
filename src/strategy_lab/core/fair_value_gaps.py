"""Canonical display-independent Fair Value Gap lifecycle engine."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ._state import encode_state, write_state
from .atr import TradingViewATR


@dataclass(frozen=True)
class FairValueGapConfig:
    mode: str = "FVG"
    mitigation_method: str = "Close"
    threshold: float = 0.0
    hide_overlap: bool = True
    track_raids: bool = False
    atr_length: int = 200
    max_history: int = 5000

    def __post_init__(self) -> None:
        if self.mode not in {"FVG", "Breakers"}:
            raise ValueError("FVG mode must be FVG or Breakers")
        if self.mitigation_method not in {"Close", "Wick", "Avg"}:
            raise ValueError("FVG mitigation must be Close, Wick, or Avg")
        if not 0.0 <= self.threshold <= 2.0:
            raise ValueError("FVG threshold must be between 0 and 2")
        if self.atr_length < 1 or self.max_history < 3:
            raise ValueError("invalid FVG history configuration")


@dataclass(frozen=True)
class FairValueGapBar:
    bar_index: int
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class FairValueGap:
    bull: bool
    top: float
    btm: float
    loc: int
    is_breaker: bool = False
    breaker_location: Optional[int] = None
    is_raid: bool = False
    raid_price: Optional[float] = None
    raid_location: Optional[int] = None
    raid_end: Optional[int] = None
    raid_active: bool = False


@dataclass(frozen=True)
class FairValueGapUpdate:
    created: Tuple[str, ...]
    bullish_count: int
    bearish_count: int


class FairValueGapEngine:
    SCHEMA_VERSION = 1

    def __init__(self, config: Optional[FairValueGapConfig] = None) -> None:
        self.config = config or FairValueGapConfig()
        self.bullish: List[FairValueGap] = []
        self.bearish: List[FairValueGap] = []
        self._history: List[Dict[str, Any]] = []
        self._pending: List[Dict[str, Any]] = []
        self._atr = TradingViewATR(self.config.atr_length)

    def update(
        self,
        bar: FairValueGapBar,
        *,
        timeframe_changed: bool = True,
    ) -> FairValueGapUpdate:
        created: List[str] = []
        for pending in self._pending:
            collection = self.bullish if pending["bull"] else self.bearish
            self._activate_previous_raid(collection)
            collection.insert(0, FairValueGap(**pending))
            created.append("BULLISH" if pending["bull"] else "BEARISH")
        self._pending = []

        atr = self._atr.update(bar.high, bar.low, bar.close)
        self._history.append({"bar": asdict(bar), "atr": atr})
        if len(self._history) > self.config.max_history:
            self._history.pop(0)

        next_pending: List[Dict[str, Any]] = []
        if len(self._history) >= 3 and timeframe_changed:
            two_back = FairValueGapBar(**self._history[-3]["bar"])
            previous = FairValueGapBar(**self._history[-2]["bar"])
            previous_atr = self._history[-2]["atr"]
            if previous_atr is not None:
                bullish_threshold = previous.low + previous_atr * self.config.threshold
                bearish_threshold = previous.high - previous_atr * self.config.threshold
                if bar.low > two_back.high and previous.close > bullish_threshold:
                    next_pending.append(
                        {"bull": True, "top": bar.low, "btm": two_back.high, "loc": two_back.time}
                    )
                if two_back.low > bar.high and previous.close < bearish_threshold:
                    next_pending.append(
                        {"bull": False, "top": two_back.low, "btm": bar.high, "loc": two_back.time}
                    )

        self._mitigate(self.bullish, bar)
        self._mitigate(self.bearish, bar)
        if self.config.hide_overlap:
            self._remove_overlaps()
        if self.config.track_raids:
            self._track_raids(self.bullish, bar)
            self._track_raids(self.bearish, bar)
        self._pending = next_pending
        return FairValueGapUpdate(tuple(created), len(self.bullish), len(self.bearish))

    def process_bars(self, bars: Iterable[FairValueGapBar]) -> List[FairValueGapUpdate]:
        return [self.update(bar) for bar in bars]

    @classmethod
    def replay(
        cls,
        bars: Iterable[FairValueGapBar],
        config: Optional[FairValueGapConfig] = None,
    ) -> "FairValueGapEngine":
        engine = cls(config)
        engine.process_bars(bars)
        return engine

    @staticmethod
    def _activate_previous_raid(collection: List[FairValueGap]) -> None:
        if not collection:
            return
        latest = collection[0]
        if latest.is_raid and not latest.raid_active:
            latest.raid_active = True
            latest.raid_location = None
            latest.raid_end = None
            latest.raid_price = None

    def _mitigate(self, collection: List[FairValueGap], bar: FairValueGapBar) -> None:
        for gap in tuple(collection):
            if not any(item is gap for item in collection):
                continue
            if not gap.is_breaker and self._normal_mitigated(gap, bar):
                gap.is_breaker = True
                gap.breaker_location = bar.time
                if self.config.mode == "FVG":
                    self._remove_identity(collection, gap)
            elif gap.is_breaker and self.config.mode == "Breakers" and self._breaker_mitigated(gap, bar):
                self._remove_identity(collection, gap)

    def _normal_mitigated(self, gap: FairValueGap, bar: FairValueGapBar) -> bool:
        level = (gap.top + gap.btm) / 2.0
        if gap.bull:
            value = min(bar.close, bar.open)
            if self.config.mitigation_method == "Wick":
                value = bar.low
            return value < (level if self.config.mitigation_method == "Avg" else gap.btm)
        value = max(bar.close, bar.open)
        if self.config.mitigation_method == "Wick":
            value = bar.high
        return value > (level if self.config.mitigation_method == "Avg" else gap.top)

    def _breaker_mitigated(self, gap: FairValueGap, bar: FairValueGapBar) -> bool:
        level = (gap.top + gap.btm) / 2.0
        if gap.bull:
            value = max(bar.close, bar.open)
            if self.config.mitigation_method == "Wick":
                value = bar.high
            return value > (level if self.config.mitigation_method == "Avg" else gap.top)
        value = min(bar.close, bar.open)
        if self.config.mitigation_method == "Wick":
            value = bar.low
        return value < (level if self.config.mitigation_method == "Avg" else gap.btm)

    def _remove_overlaps(self) -> None:
        self._remove_same_side(self.bullish)
        self._remove_same_side(self.bearish)
        self._remove_cross_side(self.bullish, self.bearish)
        self._remove_cross_side(self.bearish, self.bullish)

    def _remove_same_side(self, collection: List[FairValueGap]) -> None:
        for index in range(len(collection) - 1, 0, -1):
            if index < len(collection) and self._overlaps(collection[index], collection[0]):
                collection.pop(index)

    def _remove_cross_side(
        self, collection: List[FairValueGap], opposite: List[FairValueGap]
    ) -> None:
        if not collection or not opposite:
            return
        for index in range(len(collection) - 1, -1, -1):
            if index < len(collection) and collection and opposite:
                if self._overlaps(collection[index], opposite[0]):
                    collection.pop(index)

    @staticmethod
    def _overlaps(stuff: FairValueGap, current: FairValueGap) -> bool:
        return (
            current.btm < stuff.btm < current.top
            or (stuff.top < current.top and stuff.btm > current.btm)
            or (stuff.top > current.top and stuff.btm < current.btm)
            or current.btm < stuff.top < current.top
        )

    @staticmethod
    def _track_raids(collection: List[FairValueGap], bar: FairValueGapBar) -> None:
        for gap in collection:
            if not gap.is_raid and not gap.is_breaker:
                raided = (
                    bar.low < gap.top and bar.close > gap.top
                    if gap.bull
                    else bar.high > gap.btm and bar.close < gap.btm
                )
                if raided:
                    gap.is_raid = True
                    gap.raid_location = bar.time
                    gap.raid_end = bar.time
                    gap.raid_price = bar.low if gap.bull else bar.high
            elif gap.is_raid and not gap.raid_active and not gap.is_breaker:
                continued = (
                    bar.low <= gap.raid_price if gap.bull else bar.high >= gap.raid_price
                )
                if continued:
                    gap.raid_active = True
                gap.raid_end = bar.time

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "config": asdict(self.config),
            "bullish": [asdict(item) for item in self.bullish],
            "bearish": [asdict(item) for item in self.bearish],
            "history": list(self._history),
            "pending": list(self._pending),
            "atr": self._atr.snapshot(),
        }

    def serialize(self) -> str:
        return encode_state(self.snapshot())

    @classmethod
    def deserialize(cls, payload: str) -> "FairValueGapEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported FVG state schema")
        engine = cls(FairValueGapConfig(**value["config"]))
        engine.bullish = [FairValueGap(**item) for item in value.get("bullish", [])]
        engine.bearish = [FairValueGap(**item) for item in value.get("bearish", [])]
        engine._history = list(value.get("history", []))
        engine._pending = list(value.get("pending", []))
        engine._atr = TradingViewATR.restore(value["atr"])
        return engine

    def save(self, path: Path) -> None:
        write_state(path, self.serialize())

    @classmethod
    def load(cls, path: Path) -> "FairValueGapEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def _remove_identity(collection: List[FairValueGap], target: FairValueGap) -> None:
        for index, item in enumerate(collection):
            if item is target:
                collection.pop(index)
                return
