"""
CitadelOS Data Engine V1

Single source of truth for all market data.

Responsibilities:
- Download and normalize historical candles
- Maintain one live candle per exchange-time bucket
- Merge historical + live without rewriting closed candles
- Serve data to every engine
"""

import math
import time as time_module
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.broker.dhan_client import DhanClient


class MarketHistoryUnavailable(RuntimeError):
    """Raised when authoritative completed history cannot be loaded safely."""


class DataEngine:
    EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(self, dhan=None, max_candles=1000):
        self.dhan = dhan if dhan is not None else DhanClient()
        self.max_candles = max_candles
        self.cache = {}

    @classmethod
    def exchange_datetime(cls, value):
        """Convert supported provider timestamps to an exchange-aware datetime."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=cls.EXCHANGE_TIMEZONE)
            return value.astimezone(cls.EXCHANGE_TIMEZONE)

        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=cls.EXCHANGE_TIMEZONE)

        if isinstance(value, str):
            normalized = value.strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=cls.EXCHANGE_TIMEZONE)
            return parsed.astimezone(cls.EXCHANGE_TIMEZONE)

        raise ValueError("Candle timestamp is unavailable")

    @classmethod
    def bucket_start(cls, value, interval_minutes=1):
        interval = int(interval_minutes)
        if interval <= 0:
            raise ValueError("Candle interval must be positive")

        timestamp = cls.exchange_datetime(value)
        bucket_minute = (timestamp.minute // interval) * interval
        return timestamp.replace(minute=bucket_minute, second=0, microsecond=0)

    @classmethod
    def bucket_timestamp(cls, value, interval_minutes=1):
        return int(cls.bucket_start(value, interval_minutes).timestamp())

    def load_history(self, symbol, segment, security_id, interval="1"):
        response = self.dhan.get_intraday_candles(
            segment=segment,
            security_id=security_id,
            instrument="INDEX",
            interval=interval,
        )
        candles = response.get("candles", [])
        return self.set_history(symbol, candles, interval_minutes=int(interval))

    def load_completed_history(
        self,
        symbol,
        segment,
        security_id,
        *,
        from_date,
        to_date,
        interval="1",
        limit=120,
        now=None,
        calendar=None,
        attempts=3,
        sleeper=None,
    ):
        """Fetch, validate, and merge the latest authoritative closed candles.

        The provider request is retried at most twice after the initial attempt.
        Existing live buckets are retained, while authoritative provider rows
        replace matching closed buckets deterministically.
        """

        reference = self.exchange_datetime(now or datetime.now(self.EXCHANGE_TIMEZONE))
        interval_minutes = int(interval)
        retry_count = max(1, min(3, int(attempts)))
        sleep = sleeper or time_module.sleep
        response = None
        error = "DHAN_HISTORY_UNAVAILABLE"

        for attempt in range(retry_count):
            try:
                response = self.dhan.get_intraday_candles(
                    segment=segment,
                    security_id=security_id,
                    instrument="INDEX",
                    interval=str(interval_minutes),
                    from_date=str(from_date),
                    to_date=str(to_date),
                )
                if (
                    not isinstance(response, dict)
                    or response.get("success") is not True
                    or not isinstance(response.get("candles"), list)
                    or not response.get("candles")
                ):
                    raise MarketHistoryUnavailable(
                        str((response or {}).get("error") or "DHAN_HISTORY_UNAVAILABLE")
                    )
                break
            except Exception as exc:
                error = str(exc) or "DHAN_HISTORY_UNAVAILABLE"
                response = None
                if attempt + 1 < retry_count:
                    sleep(0.25 * (2 ** attempt))

        if response is None:
            raise MarketHistoryUnavailable(
                f"DHAN_HISTORY_UNAVAILABLE: {error}"
            )

        provider_rows = self._validated_completed_rows(
            response.get("candles") or [],
            reference=reference,
            interval_minutes=interval_minutes,
            calendar=calendar,
        )
        if not provider_rows:
            raise MarketHistoryUnavailable(
                "DHAN_HISTORY_UNAVAILABLE: no valid completed candles"
            )

        selected = provider_rows[-max(1, int(limit)):]
        current = {
            self.bucket_timestamp(item.get("time"), interval_minutes): dict(item)
            for item in self.cache.get(symbol, [])
            if isinstance(item, dict) and item.get("time") is not None
        }
        # Provider history is authoritative for any matching completed bucket.
        current.update({item["time"]: item for item in selected})
        ordered = [current[key] for key in sorted(current)]
        self.cache[symbol] = ordered[-self.max_candles:]
        return selected

    def completed_candles(self, symbol, *, now=None, interval_minutes=1):
        reference = self.exchange_datetime(now or datetime.now(self.EXCHANGE_TIMEZONE))
        interval = int(interval_minutes)
        completed = []
        for item in self.cache.get(symbol, []):
            try:
                # Quote polling can describe the current forming bucket, but it
                # is not an authoritative OHLCV candle.  Once that bucket
                # closes it must be replaced by Dhan history before any
                # indicator or strategy is allowed to consume it.
                if item.get("authoritative") is False:
                    continue
                opened = self.exchange_datetime(item["time"])
                if opened + timedelta(minutes=interval) <= reference:
                    completed.append(item)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return completed

    def _validated_completed_rows(
        self,
        rows,
        *,
        reference,
        interval_minutes,
        calendar,
    ):
        by_bucket = {}
        for source in rows:
            try:
                opened = self.bucket_start(source["time"], interval_minutes)
                closed_at = opened + timedelta(minutes=interval_minutes)
                if closed_at > reference:
                    continue
                if calendar is not None:
                    session = calendar.session_for_date(opened.date())
                    if session.get("session_state") not in {"OPEN", "SPECIAL_SESSION"}:
                        continue
                    scheduled_open = self.exchange_datetime(session["scheduled_open"])
                    scheduled_close = self.exchange_datetime(session["scheduled_close"])
                    if opened < scheduled_open or opened >= scheduled_close:
                        continue
                values = {
                    name: float(source[name])
                    for name in ("open", "high", "low", "close")
                }
                if not all(math.isfinite(value) and value > 0 for value in values.values()):
                    continue
                if values["high"] < max(values.values()) or values["low"] > min(values.values()):
                    continue
                raw_volume = source.get("volume")
                volume = (
                    float(raw_volume)
                    if isinstance(raw_volume, (int, float))
                    and not isinstance(raw_volume, bool)
                    else None
                )
                if volume is not None and (
                    not math.isfinite(volume) or volume < 0
                ):
                    volume = None
                bucket = int(opened.timestamp())
                by_bucket[bucket] = {
                    "time": bucket,
                    **values,
                    "volume": volume,
                    "authoritative": True,
                    "source": "DHAN_V2_INTRADAY",
                }
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return [by_bucket[key] for key in sorted(by_bucket)]

    def set_history(self, symbol, candles, interval_minutes=1):
        """Seed a symbol with chronological, unique provider candle buckets."""
        by_bucket = {}

        for source in candles:
            try:
                bucket = self.bucket_timestamp(source.get("time"), interval_minutes)
                candle = dict(source)
                candle["time"] = bucket
                candle["open"] = float(source["open"])
                candle["high"] = float(source["high"])
                candle["low"] = float(source["low"])
                candle["close"] = float(source["close"])
                candle["volume"] = source.get("volume", 0)
                by_bucket[bucket] = candle
            except (KeyError, TypeError, ValueError, OverflowError):
                continue

        ordered = [by_bucket[key] for key in sorted(by_bucket)]
        self.cache[symbol] = ordered[-self.max_candles:]
        return self.cache[symbol]

    def update_live_price(
        self,
        symbol,
        price,
        timestamp=None,
        interval_minutes=1,
    ):
        """Upsert a quote into its market-time candle without altering history."""
        live_price = float(price)
        observed_at = timestamp or datetime.now(self.EXCHANGE_TIMEZONE)
        bucket = self.bucket_timestamp(observed_at, interval_minutes)
        candles = self.cache.setdefault(symbol, [])

        if candles:
            latest_bucket = self.bucket_timestamp(
                candles[-1].get("time"), interval_minutes
            )

            if bucket < latest_bucket:
                return {"action": "ignored_stale", "candle": None}

            if bucket == latest_bucket:
                current = candles[-1]
                current["high"] = max(float(current["high"]), live_price)
                current["low"] = min(float(current["low"]), live_price)
                current["close"] = live_price
                current["ltp"] = live_price
                current.setdefault("volume", 0)
                return {"action": "updated", "candle": current}

        candle = {
            "time": bucket,
            "open": live_price,
            "high": live_price,
            "low": live_price,
            "close": live_price,
            "ltp": live_price,
            # Quote responses have no incremental volume. Keep that absence
            # explicit instead of fabricating accumulated volume.
            "volume": None,
            "authoritative": False,
            "source": "DHAN_QUOTE_PROVISIONAL",
        }
        candles.append(candle)
        if len(candles) > self.max_candles:
            del candles[:-self.max_candles]
        return {"action": "appended", "candle": candle}

    def append_live_candle(self, symbol, candle):
        """Compatibility wrapper; live input is still bucket-upserted."""
        price = candle.get("close", candle.get("ltp"))
        if price is None:
            return {"action": "ignored_invalid", "candle": None}
        return self.update_live_price(
            symbol=symbol,
            price=price,
            timestamp=candle.get("time"),
        )

    def get_candles(self, symbol):
        return self.cache.get(symbol, [])

    def get_last_price(self, symbol):
        candles = self.get_candles(symbol)
        if not candles:
            return None
        return candles[-1]["close"]

    def symbols(self):
        return list(self.cache.keys())
