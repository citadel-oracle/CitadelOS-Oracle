"""Session-anchored TradingView VWAP calculation."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ._state import encode_state, write_state


@dataclass(frozen=True)
class VWAPPoint:
    value: Optional[float]
    session_key: str
    reset: bool


class VWAPEngine:
    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.session_key: Optional[str] = None
        self.cumulative_price_volume = 0.0
        self.cumulative_volume = 0.0

    def update(
        self,
        *,
        timestamp: datetime,
        high: float,
        low: float,
        close: float,
        volume: float,
        session_key: Optional[str] = None,
    ) -> VWAPPoint:
        key = session_key or timestamp.date().isoformat()
        reset = key != self.session_key
        if reset:
            self.session_key = key
            self.cumulative_price_volume = 0.0
            self.cumulative_volume = 0.0
        source = (float(high) + float(low) + float(close)) / 3.0
        self.cumulative_price_volume += source * float(volume)
        self.cumulative_volume += float(volume)
        value = None
        if self.cumulative_volume != 0.0:
            value = self.cumulative_price_volume / self.cumulative_volume
        return VWAPPoint(value, key, reset)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "session_key": self.session_key,
            "cumulative_price_volume": self.cumulative_price_volume,
            "cumulative_volume": self.cumulative_volume,
        }

    def serialize(self) -> str:
        return encode_state(self.snapshot())

    @classmethod
    def deserialize(cls, payload: str) -> "VWAPEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported VWAP state schema")
        engine = cls()
        engine.session_key = value.get("session_key")
        engine.cumulative_price_volume = float(value["cumulative_price_volume"])
        engine.cumulative_volume = float(value["cumulative_volume"])
        return engine

    def save(self, path: Path) -> None:
        write_state(path, self.serialize())

    @classmethod
    def load(cls, path: Path) -> "VWAPEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
