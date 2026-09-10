"""Persistent session baselines for ARGUS intraday OI calculations."""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo


class BaselineStoreError(RuntimeError):
    """Raised when persisted baseline state cannot be trusted or saved."""


@dataclass(frozen=True)
class BaselineResolution:
    records: dict
    baseline_timestamp: str | None
    created: bool
    market_state: str
    trading_date: str


class ArgusBaselineStore:
    EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")
    MARKET_OPEN = time(9, 15)
    MARKET_CLOSE = time(15, 30)

    def __init__(self, path=None, now_provider=None):
        repository_root = Path(__file__).resolve().parents[2]
        self.path = Path(path or repository_root / "logs" / "argus_oi_baselines.json")
        self.now_provider = now_provider or (
            lambda: datetime.now(self.EXCHANGE_TIMEZONE)
        )
        self._lock = Lock()

    def resolve(self, symbol, expiry, observations, now=None):
        observed_at = self._exchange_time(now or self.now_provider())
        trading_date = observed_at.date().isoformat()
        market_state = self.market_state(observed_at)

        with self._lock:
            payload = self._load()
            records = payload.setdefault("records", {})
            created = False
            resolved = {}

            for observation in observations:
                strike = observation["strike"]
                side = observation["side"]
                key = self._identity_key(
                    trading_date, symbol, expiry, strike, side
                )
                existing = records.get(key)

                if existing is None and market_state == "OPEN":
                    oi = observation.get("oi")
                    ltp = observation.get("ltp")
                    if oi is not None and ltp is not None:
                        existing = {
                            "trading_date": trading_date,
                            "symbol": str(symbol),
                            "expiry": str(expiry),
                            "strike": float(strike),
                            "side": str(side),
                            "baseline_oi": int(oi),
                            "baseline_ltp": float(ltp),
                            "timestamp": observed_at.isoformat(),
                        }
                        records[key] = existing
                        created = True

                if existing is not None:
                    resolved[(float(strike), str(side))] = dict(existing)

            if created:
                self._atomic_write(payload)

        timestamps = [record["timestamp"] for record in resolved.values()]
        return BaselineResolution(
            records=resolved,
            baseline_timestamp=min(timestamps) if timestamps else None,
            created=created,
            market_state=market_state,
            trading_date=trading_date,
        )

    def reset(self, symbol=None, expiry=None, trading_date=None):
        """Internal/test-only reset; production API does not expose this method."""
        with self._lock:
            payload = self._load()
            records = payload.setdefault("records", {})
            retained = {}

            for key, record in records.items():
                matches = (
                    (symbol is None or record.get("symbol") == symbol)
                    and (expiry is None or record.get("expiry") == expiry)
                    and (
                        trading_date is None
                        or record.get("trading_date") == trading_date
                    )
                )
                if not matches:
                    retained[key] = record

            payload["records"] = retained
            self._atomic_write(payload)

    @classmethod
    def market_state(cls, value):
        observed_at = cls._exchange_time(value)
        if observed_at.weekday() >= 5:
            return "WEEKEND"
        if cls.MARKET_OPEN <= observed_at.time() <= cls.MARKET_CLOSE:
            return "OPEN"
        if observed_at.time() < cls.MARKET_OPEN:
            return "PRE_MARKET"
        return "CLOSED"

    @classmethod
    def _exchange_time(cls, value):
        if value.tzinfo is None:
            return value.replace(tzinfo=cls.EXCHANGE_TIMEZONE)
        return value.astimezone(cls.EXCHANGE_TIMEZONE)

    @staticmethod
    def _identity_key(trading_date, symbol, expiry, strike, side):
        return "|".join(
            [
                str(trading_date),
                str(symbol),
                str(expiry),
                f"{float(strike):g}",
                str(side),
            ]
        )

    def _load(self):
        if not self.path.exists():
            return {"version": 1, "records": {}}
        try:
            with self.path.open("r") as source:
                payload = json.load(source)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("records"), dict
            ):
                raise BaselineStoreError(
                    f"ARGUS baseline file has an invalid schema: {self.path}"
                )
            return payload
        except json.JSONDecodeError as error:
            raise BaselineStoreError(
                f"ARGUS baseline file is not valid JSON: {self.path}"
            ) from error
        except OSError as error:
            raise BaselineStoreError(
                f"ARGUS baseline file cannot be read: {self.path}"
            ) from error

    def _atomic_write(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, indent=2, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        except OSError as error:
            raise BaselineStoreError(
                f"ARGUS baseline file cannot be written: {self.path}"
            ) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
