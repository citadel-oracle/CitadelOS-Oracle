"""Canonical pivot-volume Liquidity Zone engine without drawing objects."""

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ._state import encode_state, write_state
from .atr import TradingViewATR
from .volume import VolumeFilter


@dataclass(frozen=True)
class LiquidityZoneConfig:
    left_bars: int = 10
    right_bars: Optional[int] = None
    max_zones: int = 10
    volume_strength: str = "Mid"
    dynamic_distance: bool = False
    atr_length: int = 200
    normalization_length: int = 500
    max_history: int = 5000

    def __post_init__(self) -> None:
        right = self.left_bars - 2 if self.right_bars is None else self.right_bars
        object.__setattr__(self, "right_bars", right)
        if self.left_bars < 2 or right < 1:
            raise ValueError("liquidity pivot lengths are invalid")
        if not 1 <= self.max_zones <= 50:
            raise ValueError("max_zones must be between 1 and 50")
        if self.volume_strength not in {"Low", "Mid", "High"}:
            raise ValueError("volume_strength must be Low, Mid, or High")
        if self.atr_length < 1 or self.normalization_length < 2:
            raise ValueError("liquidity indicator lengths are invalid")

    @property
    def volume_threshold(self) -> int:
        return {"Low": 1, "Mid": 2, "High": 3}[self.volume_strength]


@dataclass(frozen=True)
class LiquidityBar:
    bar_index: int
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class LiquidityZone:
    side: str
    pivot_index: int
    pivot_time: int
    base: float
    outer: float
    distance: float
    average_volume: float
    normalized_volume: float
    line_end_index: int
    grabbed: bool = False
    grabbed_index: Optional[int] = None
    grabbed_time: Optional[int] = None

    @property
    def level(self) -> float:
        return self.outer


@dataclass(frozen=True)
class LiquidityUpdate:
    created: Optional[str]
    grabbed: Tuple[str, ...]
    zone_count: int


class LiquidityZoneEngine:
    SCHEMA_VERSION = 1

    def __init__(self, config: Optional[LiquidityZoneConfig] = None) -> None:
        self.config = config or LiquidityZoneConfig()
        self.zones: List[LiquidityZone] = []
        self._history: List[Dict[str, Any]] = []
        self._atr = TradingViewATR(self.config.atr_length)
        self._average_volumes: List[Optional[float]] = []

    def update(self, bar: LiquidityBar) -> LiquidityUpdate:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        volumes = [item["bar"]["volume"] for item in self._history] + [bar.volume]
        average_volume = VolumeFilter.sma(volumes, self.config.right_bars)
        self._average_volumes.append(average_volume)
        normalized = self._normalized_volume()
        self._history.append(
            {
                "bar": asdict(bar),
                "atr": atr,
                "average_volume": average_volume,
                "normalized_volume": normalized,
            }
        )
        if len(self._history) > self.config.max_history:
            self._history.pop(0)
            self._average_volumes.pop(0)

        created = self._create_confirmed_zone(bar, atr)
        grabbed: List[str] = []
        for zone in self.zones:
            if zone.grabbed:
                continue
            if bar.bar_index == zone.line_end_index and not (bar.high > zone.level and bar.low < zone.level):
                zone.line_end_index = bar.bar_index + 1
            if bar.high > zone.level and bar.low < zone.level:
                zone.grabbed = True
                zone.grabbed_index = bar.bar_index
                zone.grabbed_time = bar.time
                grabbed.append(zone.side)
        while len(self.zones) > self.config.max_zones:
            self.zones.pop(0)
        return LiquidityUpdate(created, tuple(grabbed), len(self.zones))

    def process_bars(self, bars: Iterable[LiquidityBar]) -> List[LiquidityUpdate]:
        return [self.update(bar) for bar in bars]

    def _normalized_volume(self) -> Optional[float]:
        length = self.config.normalization_length
        available = [item for item in self._average_volumes[-length:] if item is not None]
        if len(available) < length:
            return None
        mean = sum(available) / length
        deviation = math.sqrt(sum((item - mean) ** 2 for item in available) / length)
        if deviation == 0.0:
            return None
        return available[-1] / deviation

    def _create_confirmed_zone(
        self, current: LiquidityBar, current_atr: Optional[float]
    ) -> Optional[str]:
        left, right = self.config.left_bars, self.config.right_bars
        if len(self._history) < left + right + 1:
            return None
        candidate_position = len(self._history) - 1 - right
        candidate = LiquidityBar(**self._history[candidate_position]["bar"])
        normalized = self._history[candidate_position]["normalized_volume"]
        average_volume = self._history[candidate_position]["average_volume"]
        if normalized is None or average_volume is None or normalized <= self.config.volume_threshold:
            return None
        window = [
            LiquidityBar(**item["bar"])
            for item in self._history[candidate_position - left : candidate_position + right + 1]
        ]
        left_window, right_window = window[:left], window[left + 1 :]
        pivot_high = (
            all(candidate.high >= item.high for item in left_window)
            and all(candidate.high > item.high for item in right_window)
        )
        pivot_low = (
            all(candidate.low <= item.low for item in left_window)
            and all(candidate.low < item.low for item in right_window)
        )
        pivot_atr = self._history[candidate_position]["atr"]
        if self.config.dynamic_distance:
            if pivot_atr is None:
                return None
            distance = normalized * pivot_atr / 2.0
        else:
            if current_atr is None:
                return None
            distance = current_atr
        if pivot_high:
            zone = LiquidityZone(
                "UPPER",
                candidate.bar_index,
                candidate.time,
                candidate.high,
                candidate.high + distance,
                distance,
                average_volume,
                normalized,
                current.bar_index,
            )
            created = "UPPER"
        elif pivot_low:
            zone = LiquidityZone(
                "LOWER",
                candidate.bar_index,
                candidate.time,
                candidate.low,
                candidate.low - distance,
                distance,
                average_volume,
                normalized,
                current.bar_index,
            )
            created = "LOWER"
        else:
            return None
        self.zones.append(zone)
        return created

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "config": asdict(self.config),
            "zones": [asdict(zone) for zone in self.zones],
            "history": list(self._history),
            "average_volumes": list(self._average_volumes),
            "atr": self._atr.snapshot(),
        }

    def serialize(self) -> str:
        return encode_state(self.snapshot())

    @classmethod
    def deserialize(cls, payload: str) -> "LiquidityZoneEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported Liquidity Zone state schema")
        engine = cls(LiquidityZoneConfig(**value["config"]))
        engine.zones = [LiquidityZone(**item) for item in value.get("zones", [])]
        engine._history = list(value.get("history", []))
        engine._average_volumes = list(value.get("average_volumes", []))
        engine._atr = TradingViewATR.restore(value["atr"])
        return engine

    def save(self, path: Path) -> None:
        write_state(path, self.serialize())

    @classmethod
    def load(cls, path: Path) -> "LiquidityZoneEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
