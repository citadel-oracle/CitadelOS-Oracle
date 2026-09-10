"""Genuine Futures observation repair and finalized 5-minute context gates."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from src.market.session_calendar import NSESessionCalendar


class FuturesHistoryError(ValueError):
    pass


def _timestamp(row: Mapping[str, Any]) -> int:
    value = row.get("time", row.get("timestamp"))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FuturesHistoryError("FUTURES_1M_TIMESTAMP_INVALID")
    return int(value)


def normalize_genuine_1m(
    rows: Iterable[Mapping[str, Any]], *, as_of: datetime, calendar: NSESessionCalendar
) -> list[dict[str, Any]]:
    """Validate/dedupe observed Futures minutes and exclude forming/off-session rows."""
    as_of_utc = as_of.astimezone(timezone.utc)
    unique: dict[int, dict[str, Any]] = {}
    for raw in rows:
        if raw.get("forecast") or raw.get("predicted") or raw.get("synthetic") is True:
            raise FuturesHistoryError("PREDICTION_DERIVED_OBSERVATION_REJECTED")
        stamp = _timestamp(raw)
        instant = datetime.fromtimestamp(stamp, tz=timezone.utc)
        session = calendar.session_for_date(instant.astimezone(calendar.TIMEZONE).date())
        opening = session.get("scheduled_open")
        closing = session.get("scheduled_close")
        if not opening or not closing:
            continue
        open_at = datetime.fromisoformat(opening).astimezone(timezone.utc)
        close_at = datetime.fromisoformat(closing).astimezone(timezone.utc)
        if not (open_at <= instant < close_at) or instant + timedelta(minutes=1) > as_of_utc:
            continue
        values: dict[str, float] = {}
        for field in ("open", "high", "low", "close", "volume"):
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise FuturesHistoryError(f"FUTURES_1M_{field.upper()}_INVALID")
            values[field] = float(value)
        if values["volume"] < 0 or values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
            raise FuturesHistoryError("FUTURES_1M_OHLCV_INVALID")
        if raw.get("open_interest") is not None:
            try:
                values["open_interest"] = float(raw["open_interest"])
            except (ValueError, TypeError):
                pass
        elif raw.get("oi") is not None:
            try:
                values["open_interest"] = float(raw["oi"])
            except (ValueError, TypeError):
                pass
        unique[stamp] = {"time": stamp, **values}
    return [unique[key] for key in sorted(unique)]


def expected_current_session_minutes(*, as_of: datetime, calendar: NSESessionCalendar) -> tuple[int, ...]:
    status = calendar.status(as_of)
    if status.get("session_state") not in {"OPEN", "SPECIAL_SESSION"}:
        return ()
    opening = datetime.fromisoformat(status["scheduled_open"]).astimezone(timezone.utc)
    closing = datetime.fromisoformat(status["scheduled_close"]).astimezone(timezone.utc)
    latest = min(as_of.astimezone(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1), closing - timedelta(minutes=1))
    if latest < opening:
        return ()
    count = int((latest - opening).total_seconds() // 60) + 1
    return tuple(int((opening + timedelta(minutes=index)).timestamp()) for index in range(count))


def missing_current_session_minutes(rows: Iterable[Mapping[str, Any]], *, as_of: datetime, calendar: NSESessionCalendar) -> tuple[int, ...]:
    observed = {_timestamp(row) for row in rows}
    return tuple(stamp for stamp in expected_current_session_minutes(as_of=as_of, calendar=calendar) if stamp not in observed)


def finalized_five_minute_bars(
    rows: Iterable[Mapping[str, Any]], *, as_of: datetime, calendar: NSESessionCalendar
) -> list[dict[str, Any]]:
    """Build only exact five-observation, exchange-session-anchored bars."""
    observations = normalize_genuine_1m(rows, as_of=as_of, calendar=calendar)
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in observations:
        instant = datetime.fromtimestamp(row["time"], tz=timezone.utc)
        session = calendar.session_for_date(instant.astimezone(calendar.TIMEZONE).date())
        opening = datetime.fromisoformat(session["scheduled_open"]).astimezone(timezone.utc)
        elapsed = int((instant - opening).total_seconds() // 60)
        start = int((opening + timedelta(minutes=(elapsed // 5) * 5)).timestamp())
        buckets.setdefault(start, []).append(row)
    result = []
    as_of_utc = as_of.astimezone(timezone.utc)
    for start in sorted(buckets):
        rows_in_bucket = sorted(buckets[start], key=lambda row: row["time"])
        required = [start + offset * 60 for offset in range(5)]
        if [row["time"] for row in rows_in_bucket] != required:
            continue
        if datetime.fromtimestamp(start + 300, tz=timezone.utc) > as_of_utc:
            continue
        bar = {
            "time": start,
            "open": rows_in_bucket[0]["open"],
            "high": max(row["high"] for row in rows_in_bucket),
            "low": min(row["low"] for row in rows_in_bucket),
            "close": rows_in_bucket[-1]["close"],
            "volume": sum(row["volume"] for row in rows_in_bucket),
            "authoritative": True,
            "source": rows_in_bucket[-1].get("source", "UPSTOX_FUTIDX_CANONICAL_1M"),
            "input_candles_count": 5,
        }
        if "open_interest" in rows_in_bucket[-1]:
            bar["open_interest"] = rows_in_bucket[-1]["open_interest"]
        result.append(bar)
    return result


def context_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    canonical = [
        {key: row[key] for key in ("time", "open", "high", "low", "close", "volume")}
        for row in rows
    ]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
