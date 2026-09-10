"""TradingView-compatible true range and RMA ATR state."""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class TradingViewATR:
    length: int
    previous_close: Optional[float] = None
    value: Optional[float] = None

    def __post_init__(self) -> None:
        if self.length < 1:
            raise ValueError("ATR length must be positive")
        self._seed: List[float] = []

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        high, low, close = float(high), float(low), float(close)
        true_range = high - low
        if self.previous_close is not None:
            true_range = max(true_range, abs(high - self.previous_close), abs(low - self.previous_close))
        if self.value is None:
            self._seed.append(float(true_range))
            if len(self._seed) == self.length:
                self.value = sum(self._seed) / self.length
        else:
            self.value = (self.value * (self.length - 1) + true_range) / self.length
        self.previous_close = close
        return self.value

    def snapshot(self) -> Dict[str, Any]:
        return {
            "length": self.length,
            "previous_close": self.previous_close,
            "seed": list(self._seed),
            "value": self.value,
        }

    @classmethod
    def restore(cls, value: Mapping[str, Any]) -> "TradingViewATR":
        atr = cls(int(value["length"]), previous_close=value.get("previous_close"), value=value.get("value"))
        atr._seed = [float(item) for item in value.get("seed", [])]
        return atr
