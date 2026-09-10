"""Canonical PULLBACK MASTER / BREAKOUT MAIN Order Block state engine.

Only display-independent Order Block mechanics live here. Strategy signals,
scoring, execution, labels, alerts and scheduling remain outside this module.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class OrderBlockConfig:
    mitigation_method: str = "Close"
    show_breakers: bool = False
    hide_overlap: bool = True
    overlap_preference: str = "Recent"

    def __post_init__(self) -> None:
        if self.mitigation_method not in {"Close", "Wick", "Avg"}:
            raise ValueError("mitigation_method must be Close, Wick, or Avg")
        if self.overlap_preference not in {"Recent", "Previous"}:
            raise ValueError("overlap_preference must be Recent or Previous")

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "OrderBlockConfig":
        source = dict(value or {})
        allowed = {"mitigation_method", "show_breakers", "hide_overlap", "overlap_preference"}
        unknown = sorted(set(source) - allowed)
        if unknown:
            raise ValueError(f"unsupported Order Block configuration: {', '.join(unknown)}")
        return cls(**source)


@dataclass(frozen=True)
class OrderBlockBar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OrderBlockBar":
        bar = cls(
            time=int(value["time"]),
            open=float(value["open"]),
            high=float(value["high"]),
            low=float(value["low"]),
            close=float(value["close"]),
            volume=float(value["volume"]),
        )
        if not all(math.isfinite(item) for item in (bar.open, bar.high, bar.low, bar.close, bar.volume)):
            raise ValueError("Order Block bar values must be finite")
        if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            raise ValueError("invalid Order Block OHLC values")
        return bar


@dataclass
class OrderBlock:
    bull: bool
    top: float
    btm: float
    avg: float
    loc: int
    vol: float
    direction: int
    move: int = 1
    bull_position: int = 1
    bear_position: int = 1
    xloc_bull: Optional[int] = None
    xloc_bear: Optional[int] = None
    is_breaker: bool = False
    breaker_location: Optional[int] = None

    def __post_init__(self) -> None:
        if self.top < self.btm:
            raise ValueError("Order Block top must be greater than or equal to bottom")
        if self.direction not in {-1, 1}:
            raise ValueError("Order Block direction must be -1 or 1")
        if self.move not in {1, 2, 3}:
            raise ValueError("Order Block move must be 1, 2, or 3")
        if self.xloc_bull is None:
            self.xloc_bull = self.loc
        if self.xloc_bear is None:
            self.xloc_bear = self.loc

    def to_mapping(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OrderBlock":
        return cls(**dict(value))


@dataclass
class _EnteredState:
    normal: bool = False
    breaker: bool = False


class SharedOrderBlockEngine:
    """One persistent Order Block implementation shared by both strategies."""

    SCHEMA_VERSION = 1

    def __init__(self, config: Optional[OrderBlockConfig] = None) -> None:
        self.config = config or OrderBlockConfig()
        self.bullish: List[OrderBlock] = []
        self.bearish: List[OrderBlock] = []
        self.bull_entered = _EnteredState()
        self.bear_entered = _EnteredState()

    def create_block(self, *, bull: bool, boundary: float, origin: OrderBlockBar) -> OrderBlock:
        """Create and unshift the canonical bull or bear block."""

        if bull:
            top, btm = float(boundary), origin.low
            entered, blocks = self.bull_entered, self.bullish
        else:
            top, btm = origin.high, float(boundary)
            entered, blocks = self.bear_entered, self.bearish
        block = OrderBlock(
            bull=bull,
            top=top,
            btm=btm,
            avg=(top + btm) / 2.0,
            loc=origin.time,
            vol=origin.volume,
            direction=1 if origin.close > origin.open else -1,
            xloc_bull=origin.time,
            xloc_bear=origin.time,
        )
        entered.normal = False
        entered.breaker = False
        blocks.insert(0, block)
        return block

    def observe_latest_states(self) -> Tuple[str, ...]:
        """Persist canonical one-shot normal/breaker observation flags."""

        transitions: List[str] = []
        for side, blocks, entered in (
            ("BULL", self.bullish, self.bull_entered),
            ("BEAR", self.bearish, self.bear_entered),
        ):
            if not blocks:
                continue
            latest = blocks[0]
            if not latest.is_breaker and not entered.normal:
                entered.normal = True
                transitions.append(f"{side}_NORMAL")
            if latest.is_breaker and not entered.breaker:
                entered.breaker = True
                transitions.append(f"{side}_BREAKER")
        return tuple(transitions)

    def mitigate(self, bar: OrderBlockBar, *, confirmed: bool) -> None:
        if not confirmed:
            return
        self._mitigate_side(self.bullish, bar)
        self._mitigate_side(self.bearish, bar)

    def _mitigate_side(self, blocks: List[OrderBlock], bar: OrderBlockBar) -> None:
        for block in tuple(blocks):
            if not self._contains_identity(blocks, block):
                continue
            if not block.is_breaker:
                if self._normal_mitigated(block, bar):
                    block.is_breaker = True
                    block.breaker_location = bar.time
                    if not self.config.show_breakers:
                        self._remove_identity(blocks, block)
            elif self._breaker_mitigated(block, bar):
                self._remove_identity(blocks, block)

    def _normal_mitigated(self, block: OrderBlock, bar: OrderBlockBar) -> bool:
        if block.bull:
            if self.config.mitigation_method == "Close":
                return min(bar.close, bar.open) < block.btm
            if self.config.mitigation_method == "Wick":
                return bar.low < block.btm
            return bar.low < block.avg
        if self.config.mitigation_method == "Close":
            return max(bar.close, bar.open) > block.top
        if self.config.mitigation_method == "Wick":
            return bar.high > block.top
        return bar.high > block.avg

    def _breaker_mitigated(self, block: OrderBlock, bar: OrderBlockBar) -> bool:
        if block.bull:
            if self.config.mitigation_method == "Close":
                return max(bar.close, bar.open) > block.top
            if self.config.mitigation_method == "Wick":
                return bar.high > block.top
            return bar.high > block.avg
        if self.config.mitigation_method == "Close":
            return min(bar.close, bar.open) < block.btm
        if self.config.mitigation_method == "Wick":
            return bar.low < block.btm
        return bar.low < block.avg

    def remove_overlaps(self) -> None:
        if not self.config.hide_overlap:
            return
        self._remove_same_side(self.bullish)
        self._remove_same_side(self.bearish)
        self._remove_cross_side(self.bullish, self.bearish)
        self._remove_cross_side(self.bearish, self.bullish)

    def _remove_same_side(self, blocks: List[OrderBlock]) -> None:
        if len(blocks) <= 1:
            return
        for index in range(len(blocks) - 1, 0, -1):
            if index >= len(blocks) or not blocks:
                continue
            stuff, current = blocks[index], blocks[0]
            if self._overlaps(stuff, current):
                blocks.pop(index if self.config.overlap_preference == "Recent" else 0)

    def _remove_cross_side(self, blocks: List[OrderBlock], opposite: List[OrderBlock]) -> None:
        if not blocks or not opposite:
            return
        for index in range(len(blocks) - 1, -1, -1):
            if index >= len(blocks) or not blocks or not opposite:
                continue
            if self._overlaps(blocks[index], opposite[0]):
                blocks.pop(0 if self.config.overlap_preference == "Recent" else index)

    @staticmethod
    def _overlaps(stuff: OrderBlock, current: OrderBlock) -> bool:
        return (
            current.btm < stuff.btm < current.top
            or (stuff.top < current.top and stuff.btm > current.btm)
            or (stuff.top > current.top and stuff.btm < current.btm)
            or current.btm < stuff.top < current.top
        )

    def update_activity(self, current_time: int, previous_time: int, prior_time: int) -> None:
        for block in (*self.bullish, *self.bearish):
            if block.direction == 1:
                if block.move == 1:
                    block.bull_position += 1
                    block.move = 2
                elif block.move == 2:
                    block.bull_position += 1
                    block.move = 3
                else:
                    block.bear_position += 1
                    block.move = 1
            else:
                if block.move == 1:
                    block.bear_position += 1
                    block.move = 2
                elif block.move == 2:
                    block.bear_position += 1
                    block.move = 3
                else:
                    block.bull_position += 1
                    block.move = 1
            if current_time - previous_time == previous_time - prior_time:
                delta = current_time - previous_time
                block.xloc_bull = block.loc + delta * block.bull_position
                block.xloc_bear = block.loc + delta * block.bear_position

    def clear_blocks(self) -> None:
        self.bullish.clear()
        self.bearish.clear()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "config": asdict(self.config),
            "bullish": [block.to_mapping() for block in self.bullish],
            "bearish": [block.to_mapping() for block in self.bearish],
            "entered": {
                "bull": asdict(self.bull_entered),
                "bear": asdict(self.bear_entered),
            },
        }

    def serialize(self) -> str:
        return json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def deserialize(cls, payload: str) -> "SharedOrderBlockEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported Order Block state schema")
        engine = cls(OrderBlockConfig.from_mapping(value.get("config")))
        engine.bullish = [OrderBlock.from_mapping(item) for item in value.get("bullish", [])]
        engine.bearish = [OrderBlock.from_mapping(item) for item in value.get("bearish", [])]
        entered = value.get("entered", {})
        engine.bull_entered = _EnteredState(**dict(entered.get("bull", {})))
        engine.bear_entered = _EnteredState(**dict(entered.get("bear", {})))
        return engine

    def save(self, path: Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(self.serialize(), encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: Path) -> "SharedOrderBlockEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def _contains_identity(blocks: Sequence[OrderBlock], target: OrderBlock) -> bool:
        return any(item is target for item in blocks)

    @staticmethod
    def _remove_identity(blocks: List[OrderBlock], target: OrderBlock) -> None:
        for index, item in enumerate(blocks):
            if item is target:
                blocks.pop(index)
                return
