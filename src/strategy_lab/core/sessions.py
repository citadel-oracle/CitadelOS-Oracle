"""Strategy-neutral TradingView session permission state."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from ._state import encode_state, write_state


def _parse_session(value: str) -> Tuple[time, time]:
    try:
        start, end = value.split("-", 1)
        return time(int(start[:2]), int(start[2:])), time(int(end[:2]), int(end[2:]))
    except (TypeError, ValueError) as exc:
        raise ValueError("session must use HHMM-HHMM") from exc


@dataclass(frozen=True)
class SessionConfig:
    mode: str = "Intraday"
    entry_session: str = "0915-1515"
    square_off_session: str = "1515-1530"
    reset_each_day: bool = True
    timezone: str = "Asia/Kolkata"

    def __post_init__(self) -> None:
        if self.mode not in {"Intraday", "Positional"}:
            raise ValueError("session mode must be Intraday or Positional")
        _parse_session(self.entry_session)
        _parse_session(self.square_off_session)
        ZoneInfo(self.timezone)


@dataclass(frozen=True)
class SessionPermission:
    entry_allowed: bool
    square_off: bool
    daily_reset: bool
    mode: str
    session_date: str


class SharedSessionManager:
    SCHEMA_VERSION = 1

    def __init__(self, config: Optional[SessionConfig] = None) -> None:
        self.config = config or SessionConfig()
        self.last_session_date: Optional[str] = None

    def evaluate(self, timestamp: datetime) -> SessionPermission:
        zone = ZoneInfo(self.config.timezone)
        local = timestamp.replace(tzinfo=zone) if timestamp.tzinfo is None else timestamp.astimezone(zone)
        session_date = local.date().isoformat()
        daily_reset = (
            self.config.mode == "Intraday"
            and self.config.reset_each_day
            and self.last_session_date is not None
            and self.last_session_date != session_date
        )
        self.last_session_date = session_date
        if self.config.mode == "Positional":
            return SessionPermission(True, False, False, self.config.mode, session_date)
        entry = self._contains(local.time(), *_parse_session(self.config.entry_session))
        square_off = self._contains(local.time(), *_parse_session(self.config.square_off_session))
        return SessionPermission(entry, square_off, daily_reset, self.config.mode, session_date)

    @staticmethod
    def _contains(current: time, start: time, end: time) -> bool:
        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "config": asdict(self.config),
            "last_session_date": self.last_session_date,
        }

    def serialize(self) -> str:
        return encode_state(self.snapshot())

    @classmethod
    def deserialize(cls, payload: str) -> "SharedSessionManager":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported session state schema")
        manager = cls(SessionConfig(**value["config"]))
        manager.last_session_date = value.get("last_session_date")
        return manager

    def save(self, path: Path) -> None:
        write_state(path, self.serialize())

    @classmethod
    def load(cls, path: Path) -> "SharedSessionManager":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
