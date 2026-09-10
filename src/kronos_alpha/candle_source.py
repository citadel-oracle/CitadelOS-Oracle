import json
import os
import time as time_module
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data.dhan_market_data import DhanMarketDataClient
from src.market.session_calendar import NSESessionCalendar
from src.strategy_lab.state_truth import CandleIdentity, CanonicalCandleStore, HistoryRequirement


class CandleSourceError(RuntimeError):
    pass


class RealNiftyCandleSource:
    SYMBOL = "NIFTY"
    EXCHANGE = "NSE"
    SEGMENT = "IDX_I"
    SECURITY_ID = "13"
    INSTRUMENT = "INDEX"
    TIMEFRAME = "5m"
    INTERVAL_MINUTES = 5
    TIMEZONE = ZoneInfo("Asia/Kolkata")
    SCHEMA_VERSION = 1

    def __init__(self, provider=None, calendar=None, cache_path="logs/kronos_alpha_candles.json", clock=None, sleeper=None, retries=3,
                 canonical_store_root=None, history_days=20, required_bars=None):
        self._provider = provider
        self.calendar = calendar or NSESessionCalendar()
        self.cache_path = Path(cache_path)
        self.clock = clock or (lambda: datetime.now(self.TIMEZONE))
        self.sleeper = sleeper or time_module.sleep
        self.retries = max(1, min(3, int(retries)))
        self.history_days = max(20, int(history_days))
        self.required_bars = int(required_bars or HistoryRequirement.strategy_lab_default(self.TIMEFRAME).required_bars)
        self.canonical_store = (
            CanonicalCandleStore(
                canonical_store_root,
                CandleIdentity(self.SYMBOL, self.SECURITY_ID, self.TIMEFRAME),
            )
            if canonical_store_root else None
        )
        self.last_status = self._empty_status()

    @property
    def provider(self):
        if self._provider is None:
            self._provider = DhanMarketDataClient()
        return self._provider

    def backfill(self, limit=256, now=None):
        reference = self._aware(now or self.clock())
        limit = max(64, min(512, int(limit)))
        result, error = None, None
        requests = self._history_ranges(reference)
        fetched = []
        raw_volumes = []
        for from_date, to_date in requests:
            result = None
            for attempt in range(self.retries):
                try:
                    result = self.provider.get_intraday_candles(
                        segment=self.SEGMENT, security_id=self.SECURITY_ID,
                        instrument=self.INSTRUMENT, interval=str(self.INTERVAL_MINUTES),
                        from_date=from_date, to_date=to_date,
                    )
                    if not result.get("success"):
                        raise CandleSourceError(result.get("error") or "Dhan candle backfill failed")
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt + 1 < self.retries:
                        self.sleeper(0.5 * (2 ** attempt))
            if result is None or not result.get("success"):
                break
            fetched.extend(result.get("candles") or [])
            raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
            raw_volumes.extend(raw.get("volume") if isinstance(raw.get("volume"), list) else [])
        if result is None or not result.get("success"):
            cached = self.load_cache()
            self.last_status = {
                **self._empty_status(),
                "health": "DEGRADED" if cached else "UNAVAILABLE",
                "error": error,
                "cache_status": "CACHED" if cached else "MISSING",
                "candle_count": len(cached),
                "last_candle_at": cached[-1]["timestamp"] if cached else None,
                "volume_available": any(item.get("volume") is not None for item in cached) if cached else None,
            }
            return cached[-limit:]

        candles = []
        for index, item in enumerate(fetched):
            try:
                timestamp = self._provider_time(item["time"])
                closed_at = timestamp + timedelta(minutes=self.INTERVAL_MINUTES)
                session = self.calendar.session_for_date(timestamp.date())
                values = {name: float(item[name]) for name in ("open", "high", "low", "close")}
                if not all(value == value and abs(value) != float("inf") for value in values.values()):
                    continue
                if values["high"] < max(values.values()) or values["low"] > min(values.values()):
                    continue
                is_market_close = False
                scheduled_close_str = session.get("scheduled_close")
                if scheduled_close_str:
                    try:
                        scheduled_close_dt = datetime.fromisoformat(scheduled_close_str)
                        if closed_at == scheduled_close_dt:
                            is_market_close = True
                    except ValueError:
                        pass
                close_tolerance = timedelta(minutes=1) if is_market_close else timedelta(0)
                if timestamp > reference or (closed_at - close_tolerance > reference) or session["session_state"] not in {"OPEN", "SPECIAL_SESSION"}:
                    continue
                volume = None
                if index < len(raw_volumes) and isinstance(raw_volumes[index], (int, float)):
                    volume = float(raw_volumes[index])
                candles.append({
                    "symbol": self.SYMBOL,
                    "exchange": self.EXCHANGE,
                    "provider_segment": self.SEGMENT,
                    "provider_security_id": self.SECURITY_ID,
                    "instrument": self.INSTRUMENT,
                    "timeframe": self.TIMEFRAME,
                    "timestamp": timestamp.isoformat(),
                    **values,
                    "volume": volume,
                    "source": "DHAN_DATA_API",
                    "received_at": reference.isoformat(),
                    "candle_closed_at": closed_at.isoformat(),
                    "closed": True,
                    "is_closed": True,
                    "freshness": "FRESH" if (reference - closed_at).total_seconds() <= 600 else "HISTORICAL",
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        by_timestamp = {item["timestamp"]: item for item in candles}
        ordered = [by_timestamp[key] for key in sorted(by_timestamp)]
        if self.canonical_store is not None:
            self.canonical_store.merge(ordered, fetch_timestamp=reference.isoformat())
            ordered = self.canonical_store.load()
        else:
            ordered = ordered[-512:]
        if len(ordered) < 64:
            raise CandleSourceError("fewer than 64 valid closed NIFTY 5-minute candles")
        self._write_cache(ordered[-512:])
        selected = ordered[-limit:]
        self.last_status = {
            "health": "READY" if len(selected) >= 256 else "DEGRADED",
            "error": None,
            "cache_status": "UPDATED",
            "candle_count": len(ordered),
            "last_candle_at": selected[-1]["timestamp"],
            "source": "DHAN_DATA_API",
            "instrument": {"symbol": self.SYMBOL, "exchange": self.EXCHANGE, "segment": self.SEGMENT, "security_id": self.SECURITY_ID, "instrument": self.INSTRUMENT, "timeframe": self.TIMEFRAME},
            "volume_available": any(item["volume"] is not None for item in selected),
        }
        return selected

    def load_cache(self):
        if self.canonical_store is not None:
            canonical = self.canonical_store.load()
            if canonical:
                return canonical
        try:
            document = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if document.get("schema_version") != self.SCHEMA_VERSION or not isinstance(document.get("candles"), list):
                return []
            return document["candles"][-512:]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def readiness(self, now=None):
        if self.canonical_store is None:
            rows = self.load_cache()
            return {
                "DATA_READY": bool(rows), "loaded_bars": len(rows), "required_bars": None,
                "not_ready_reason": None if rows else "HISTORY_LOADING",
            }
        return self.canonical_store.readiness(
            HistoryRequirement.strategy_lab_default(self.TIMEFRAME), now=self._aware(now or self.clock())
        )

    def _history_ranges(self, reference):
        if self.canonical_store is None:
            return [((reference.date() - timedelta(days=20)).isoformat(), reference.date().isoformat())]
        loaded = self.canonical_store.load()
        days = self.history_days if len(loaded) < self.required_bars else 3
        start = reference.date() - timedelta(days=days)
        ranges = []
        while start < reference.date():
            end = min(start + timedelta(days=30), reference.date())
            ranges.append((start.isoformat(), end.isoformat()))
            start = end
        return ranges or [((reference.date() - timedelta(days=1)).isoformat(), reference.date().isoformat())]

    def _write_cache(self, candles):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"schema_version": self.SCHEMA_VERSION, "candles": candles}, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.cache_path)

    def _provider_time(self, value):
        if isinstance(value, (int, float)):
            timestamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(timestamp, tz=self.TIMEZONE)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return self._aware(parsed)

    def _aware(self, value):
        return value.replace(tzinfo=self.TIMEZONE) if value.tzinfo is None else value.astimezone(self.TIMEZONE)

    @staticmethod
    def _empty_status():
        return {"health": "NOT_STARTED", "error": None, "cache_status": "MISSING", "candle_count": 0, "last_candle_at": None, "source": "DHAN_DATA_API", "instrument": {"symbol": "NIFTY", "exchange": "NSE", "segment": "IDX_I", "security_id": "13", "instrument": "INDEX", "timeframe": "5m"}, "volume_available": None}
