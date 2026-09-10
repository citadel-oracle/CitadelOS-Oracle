import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


class NSESessionCalendar:
    EXCHANGE = "NSE"
    TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(self, calendar_dir=None, clock=None):
        self.calendar_dir = Path(calendar_dir or Path(__file__).resolve().parents[2] / "config" / "market_calendars")
        self.clock = clock or (lambda: datetime.now(self.TIMEZONE))
        self._documents = {}

    def status(self, at=None):
        now = self._aware(at or self.clock())
        document = self._load(now.year)
        base = {
            "exchange": self.EXCHANGE,
            "timezone": str(self.TIMEZONE),
            "session_date": now.date().isoformat(),
            "session_state": "UNKNOWN",
            "market_open": False,
            "scheduled_open": None,
            "scheduled_close": None,
            "reason": "CALENDAR_UNAVAILABLE",
            "next_valid_open": None,
            "calendar_source": None,
            "calendar_version": None,
            "calendar_checksum": None,
            "calendar_freshness_days": None,
            "warnings": ["NSE calendar unavailable; market fails closed."],
        }
        if document is None:
            return base

        open_time = self._parse_time(document["regular_open"])
        close_time = self._parse_time(document["regular_close"])
        pre_open = self._parse_time(document.get("pre_open", "09:00"))
        special = self._special_session(document, now.date())
        holidays = {item["date"]: item["name"] for item in document.get("holidays", [])}
        scheduled_open = datetime.combine(now.date(), open_time, self.TIMEZONE)
        scheduled_close = datetime.combine(now.date(), close_time, self.TIMEZONE)

        state, reason = "CLOSED", "OUTSIDE_REGULAR_SESSION"
        if special:
            scheduled_open = datetime.combine(now.date(), self._parse_time(special["open"]), self.TIMEZONE)
            scheduled_close = datetime.combine(now.date(), self._parse_time(special["close"]), self.TIMEZONE)
            state = "SPECIAL_SESSION" if scheduled_open <= now < scheduled_close else "CLOSED"
            reason = special.get("name", "NSE_SPECIAL_SESSION") if state == "SPECIAL_SESSION" else "OUTSIDE_SPECIAL_SESSION"
        elif now.weekday() >= 5:
            state, reason = "WEEKEND", "NSE_WEEKEND_CLOSED"
        elif now.date().isoformat() in holidays:
            state, reason = "HOLIDAY", holidays[now.date().isoformat()]
        elif datetime.combine(now.date(), pre_open, self.TIMEZONE) <= now < scheduled_open:
            state, reason = "PRE_OPEN", "NSE_PRE_OPEN"
        elif scheduled_open <= now < scheduled_close:
            state, reason = "OPEN", "NSE_REGULAR_SESSION"

        verified = date.fromisoformat(document["verified_at"])
        base.update({
            "session_state": state,
            "market_open": state in {"OPEN", "SPECIAL_SESSION"},
            "scheduled_open": scheduled_open.isoformat(),
            "scheduled_close": scheduled_close.isoformat(),
            "reason": reason,
            "next_valid_open": self._next_open(now, include_today=now < scheduled_open),
            "calendar_source": document["source"],
            "calendar_version": document["version"],
            "calendar_checksum": document["checksum"],
            "calendar_freshness_days": max(0, (now.date() - verified).days),
            "warnings": [],
        })
        return base

    def session_for_date(self, value):
        midday = datetime.combine(value, time(12), self.TIMEZONE)
        return self.status(midday)

    def _next_open(self, now, include_today=False):
        start = 0 if include_today else 1
        for offset in range(start, 370):
            candidate = now.date() + timedelta(days=offset)
            document = self._load(candidate.year)
            if document is None:
                continue
            special = self._special_session(document, candidate)
            if candidate.weekday() >= 5 and special is None:
                continue
            holidays = {item["date"] for item in document.get("holidays", [])}
            if candidate.isoformat() in holidays and special is None:
                continue
            opening = self._parse_time(special["open"] if special else document["regular_open"])
            return datetime.combine(candidate, opening, self.TIMEZONE).isoformat()
        return None

    def _load(self, year):
        if year in self._documents:
            return self._documents[year]
        path = self.calendar_dir / f"nse_{year}.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            required = {"exchange", "year", "timezone", "regular_open", "regular_close", "source", "verified_at", "version", "holidays"}
            if not required.issubset(document) or document["exchange"] != self.EXCHANGE or document["year"] != year:
                raise ValueError("invalid NSE calendar identity")
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            document["checksum"] = hashlib.sha256(canonical).hexdigest()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            document = None
        self._documents[year] = document
        return document

    @staticmethod
    def _special_session(document, value):
        return next((item for item in document.get("special_sessions", []) if item.get("date") == value.isoformat()), None)

    @classmethod
    def _aware(cls, value):
        if value.tzinfo is None:
            return value.replace(tzinfo=cls.TIMEZONE)
        return value.astimezone(cls.TIMEZONE)

    @staticmethod
    def _parse_time(value):
        return time.fromisoformat(value)
