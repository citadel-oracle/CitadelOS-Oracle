"""Exchange-session-safe model time for finalized NSE Futures bars."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from src.market.session_calendar import NSESessionCalendar


class ForecastTimeError(ValueError):
    """Raised when valid exchange forecast timestamps cannot be produced."""


class NSEForecastTimeMapper:
    """Map contiguous model positions onto real, valid NSE bar starts.

    Models see a regular integer/5-minute index. Only the final projections are
    mapped back to exchange timestamps, so no weekend or overnight OHLC candle
    is ever manufactured.
    """

    def __init__(self, calendar: NSESessionCalendar | None = None):
        self.calendar = calendar or NSESessionCalendar()

    def future_timestamps(
        self,
        source_timestamp: str | int | float | datetime,
        *,
        steps: int,
        interval_minutes: int = 5,
    ) -> tuple[str, ...]:
        if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
            raise ForecastTimeError("FORECAST_STEPS_INVALID")
        if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or interval_minutes <= 0:
            raise ForecastTimeError("FORECAST_INTERVAL_INVALID")
        current = self._parse(source_timestamp)
        result: list[str] = []
        while len(result) < steps:
            current = self._next_bar(current, interval_minutes)
            result.append(current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
        return tuple(result)

    def is_valid_bar_start(self, value: str | int | float | datetime, interval_minutes: int = 5) -> bool:
        instant = self._parse(value)
        session = self.calendar.session_for_date(instant.date())
        if session.get("session_state") in {"UNKNOWN", "WEEKEND", "HOLIDAY"}:
            return False
        opened, closed = self._bounds(instant.date(), session)
        if not opened <= instant < closed:
            return False
        return int((instant - opened).total_seconds()) % (interval_minutes * 60) == 0

    def assert_valid(self, values: Iterable[str], interval_minutes: int = 5) -> None:
        if any(not self.is_valid_bar_start(value, interval_minutes) for value in values):
            raise ForecastTimeError("FORECAST_TIMESTAMP_OUTSIDE_NSE_SESSION")

    def _next_bar(self, current: datetime, interval_minutes: int) -> datetime:
        candidate = current + timedelta(minutes=interval_minutes)
        for _ in range(370):
            session = self.calendar.session_for_date(candidate.date())
            state = session.get("session_state")
            if state not in {"UNKNOWN", "WEEKEND", "HOLIDAY"}:
                opened, closed = self._bounds(candidate.date(), session)
                if candidate < opened:
                    return opened
                if opened <= candidate < closed:
                    elapsed = max(0, int((candidate - opened).total_seconds()))
                    bucket = (elapsed // (interval_minutes * 60)) * interval_minutes * 60
                    aligned = opened + timedelta(seconds=bucket)
                    if aligned < candidate:
                        aligned += timedelta(minutes=interval_minutes)
                    if aligned < closed:
                        return aligned
            candidate = datetime.combine(candidate.date() + timedelta(days=1), time.min, self.calendar.TIMEZONE)
        raise ForecastTimeError("NSE_CALENDAR_HAS_NO_FUTURE_SESSION")

    def _bounds(self, value: date, session: dict) -> tuple[datetime, datetime]:
        opened = session.get("scheduled_open")
        closed = session.get("scheduled_close")
        if not opened or not closed:
            raise ForecastTimeError(f"NSE_CALENDAR_UNAVAILABLE:{value.isoformat()}")
        return self._parse(opened), self._parse(closed)

    def _parse(self, value: str | int | float | datetime) -> datetime:
        if isinstance(value, bool):
            raise ForecastTimeError("FORECAST_TIMESTAMP_INVALID")
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ForecastTimeError("FORECAST_TIMESTAMP_INVALID") from exc
        else:
            raise ForecastTimeError("FORECAST_TIMESTAMP_INVALID")
        if parsed.tzinfo is None:
            raise ForecastTimeError("FORECAST_TIMESTAMP_TIMEZONE_MISSING")
        return parsed.astimezone(self.calendar.TIMEZONE)
