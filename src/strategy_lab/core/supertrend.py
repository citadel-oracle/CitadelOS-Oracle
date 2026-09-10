"""Deterministic TradingView ``ta.supertrend`` equivalent."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ._state import encode_state, write_state
from .atr import TradingViewATR


@dataclass(frozen=True)
class SupertrendPoint:
    value: Optional[float]
    direction: Optional[int]
    atr: Optional[float]
    upper_band: Optional[float]
    lower_band: Optional[float]


class SupertrendEngine:
    SCHEMA_VERSION = 1

    def __init__(self, *, factor: float = 3.0, atr_length: int = 10) -> None:
        if factor <= 0:
            raise ValueError("Supertrend factor must be positive")
        self.factor = float(factor)
        self.atr = TradingViewATR(atr_length)
        self.upper_band: Optional[float] = None
        self.lower_band: Optional[float] = None
        self.value: Optional[float] = None
        self.direction: Optional[int] = None

    def update(self, *, high: float, low: float, close: float) -> SupertrendPoint:
        previous_close = self.atr.previous_close
        previous_atr = self.atr.value
        previous_upper = self.upper_band
        previous_lower = self.lower_band
        previous_value = self.value
        atr = self.atr.update(float(high), float(low), float(close))
        if atr is None:
            return SupertrendPoint(None, None, None, None, None)

        midpoint = (float(high) + float(low)) / 2.0
        lower = midpoint - self.factor * atr
        upper = midpoint + self.factor * atr
        prior_lower = lower if previous_lower is None else previous_lower
        prior_upper = upper if previous_upper is None else previous_upper
        prior_close = float(close) if previous_close is None else previous_close
        lower = lower if lower > prior_lower or prior_close < prior_lower else prior_lower
        upper = upper if upper < prior_upper or prior_close > prior_upper else prior_upper

        if previous_atr is None:
            direction = 1
        elif previous_value == prior_upper:
            direction = -1 if float(close) > upper else 1
        else:
            direction = 1 if float(close) < lower else -1
        value = lower if direction == -1 else upper

        self.upper_band = upper
        self.lower_band = lower
        self.direction = direction
        self.value = value
        return SupertrendPoint(value, direction, atr, upper, lower)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "factor": self.factor,
            "atr": self.atr.snapshot(),
            "upper_band": self.upper_band,
            "lower_band": self.lower_band,
            "value": self.value,
            "direction": self.direction,
        }

    def serialize(self) -> str:
        return encode_state(self.snapshot())

    @classmethod
    def deserialize(cls, payload: str) -> "SupertrendEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported Supertrend state schema")
        engine = cls(factor=float(value["factor"]), atr_length=int(value["atr"]["length"]))
        engine.atr = TradingViewATR.restore(value["atr"])
        engine.upper_band = value.get("upper_band")
        engine.lower_band = value.get("lower_band")
        engine.value = value.get("value")
        engine.direction = value.get("direction")
        return engine

    def save(self, path: Path) -> None:
        write_state(path, self.serialize())

    @classmethod
    def load(cls, path: Path) -> "SupertrendEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
