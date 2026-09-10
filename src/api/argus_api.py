"""Read-only API service for ARGUS option-chain intelligence."""

from datetime import date, datetime
from threading import Event, Lock, Thread
from time import monotonic, perf_counter
from zoneinfo import ZoneInfo

from src.argus import (
    BaselineStoreError,
    InvalidOptionExpiryError,
    OptionChainDataError,
    OptionChainEngine,
)
from src.argus.baseline_store import ArgusBaselineStore
from src.scanner.watchlist import WATCHLIST


class ArgusAPIError(RuntimeError):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.detail = {
            "status": "unavailable",
            "error": {
                "code": code,
                "message": message,
            },
        }


class ArgusAPI:
    CACHE_TTL_SECONDS = 3.0
    PROJECTION_FRESHNESS_SECONDS = 20.0
    EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        engine=None,
        cache_ttl_seconds=None,
        projection_freshness_seconds=None,
        clock=None,
        now_provider=None,
    ):
        self.engine = engine if engine is not None else OptionChainEngine()
        self.cache_ttl_seconds = (
            float(cache_ttl_seconds)
            if cache_ttl_seconds is not None
            else self.CACHE_TTL_SECONDS
        )
        self.projection_freshness_seconds = (
            float(projection_freshness_seconds)
            if projection_freshness_seconds is not None
            else self.PROJECTION_FRESHNESS_SECONDS
        )
        if self.projection_freshness_seconds <= self.cache_ttl_seconds:
            raise ValueError(
                "projection freshness must exceed fetch-dedup TTL"
            )
        self.clock = clock or monotonic
        self.now_provider = now_provider or (
            lambda: datetime.now(self.EXCHANGE_TIMEZONE)
        )
        self._cache = {}
        self._lock = Lock()
        self._producer_lock = Lock()
        self._producer_stop = Event()
        self._producer_thread = None
        self._producer_telemetry = {
            "last_success_at": None,
            "last_error_at": None,
            "last_error_type": None,
            "consecutive_failures": 0,
            "recovery_count": 0,
            "last_error_details": None,
        }

    def get_producer_telemetry(self) -> dict:
        with self._producer_lock:
            return dict(self._producer_telemetry)

    def get_oi(self, symbol, expiry=None):
        return self._get_oi(symbol, expiry=expiry, process_worker=None)

    def get_oi_isolated(self, symbol, process_worker, expiry=None):
        """Fetch Dhan in-process, then build only the CPU projection in the worker."""

        return self._get_oi(symbol, expiry=expiry, process_worker=process_worker)

    def start_cache_producer(
        self,
        process_worker,
        *,
        symbol="NIFTY",
        interval_seconds=None,
        on_snapshot=None,
        on_stage=None,
    ):
        """Keep one authoritative cache warm without coupling it to V2 rebuilds."""

        interval = (
            self.cache_ttl_seconds
            if interval_seconds is None
            else max(0.01, float(interval_seconds))
        )
        with self._producer_lock:
            if (
                self._producer_thread is not None
                and self._producer_thread.is_alive()
            ):
                return False
            self._producer_stop.clear()
            thread = Thread(
                target=self._cache_producer_loop,
                args=(
                    process_worker,
                    str(symbol).upper(),
                    interval,
                    on_snapshot,
                    on_stage,
                ),
                name="citadel-argus-cache-producer",
                daemon=True,
            )
            self._producer_thread = thread
            thread.start()
            return True

    def stop_cache_producer(self):
        self._producer_stop.set()
        with self._producer_lock:
            thread = self._producer_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.cache_ttl_seconds + 1.0))

    def _cache_producer_loop(
        self, process_worker, symbol, interval, on_snapshot, on_stage
    ):
        while not self._producer_stop.is_set():
            now_iso = datetime.now(self.EXCHANGE_TIMEZONE).isoformat()
            try:
                request_started = perf_counter()
                if callable(on_stage):
                    on_stage("ARGUS_REQUEST_START")
                projection = self._get_oi(
                    symbol,
                    expiry=None,
                    process_worker=process_worker,
                )
                if callable(on_stage):
                    source_timestamp = None
                    try:
                        source_timestamp = str((projection.get("data") or {}).get("underlying", {}).get("fetched_at") or "") or None
                    except AttributeError:
                        source_timestamp = None
                    on_stage(
                        "ARGUS_SOURCE_RESPONSE",
                        source_timestamp=source_timestamp,
                        duration_ms=(perf_counter() - request_started) * 1_000.0,
                    )
                if callable(on_snapshot):
                    try:
                        on_snapshot(projection)
                    except Exception as fanout_error:
                        with self._producer_lock:
                            if self._producer_telemetry["consecutive_failures"] > 0:
                                self._producer_telemetry["recovery_count"] += 1
                            self._producer_telemetry["consecutive_failures"] = 0
                            self._producer_telemetry["last_success_at"] = now_iso
                            self._producer_telemetry["last_error_at"] = now_iso
                            self._producer_telemetry["last_error_type"] = type(fanout_error).__name__
                            self._producer_telemetry["last_error_details"] = f"FANOUT_ERROR: {str(fanout_error)}"
                        self._producer_stop.wait(interval)
                        continue

                with self._producer_lock:
                    if self._producer_telemetry["consecutive_failures"] > 0:
                        self._producer_telemetry["recovery_count"] += 1
                    self._producer_telemetry["consecutive_failures"] = 0
                    self._producer_telemetry["last_success_at"] = now_iso

            except Exception as error:
                with self._producer_lock:
                    self._producer_telemetry["consecutive_failures"] += 1
                    self._producer_telemetry["last_error_at"] = now_iso
                    self._producer_telemetry["last_error_type"] = type(error).__name__
                    self._producer_telemetry["last_error_details"] = str(error)

            self._producer_stop.wait(interval)

    def _get_oi(self, symbol, *, expiry=None, process_worker=None):
        normalized_symbol = str(symbol).strip().upper()
        if normalized_symbol not in WATCHLIST:
            raise ArgusAPIError(
                404,
                "UNSUPPORTED_SYMBOL",
                f"ARGUS does not support symbol {normalized_symbol or '<empty>'}",
            )

        normalized_expiry = self._validate_expiry(expiry)
        cache_key = (normalized_symbol, normalized_expiry or "current")
        now = self.clock()
        cached = self._cache.get(cache_key)
        current_market_state = ArgusBaselineStore.market_state(self.now_provider())

        if cached is not None and self._cached_expiry_is_active(cached):
            age = max(0.0, now - cached["cached_at"])
            if age < self.cache_ttl_seconds or current_market_state != "OPEN":
                freshness = "cached" if current_market_state == "OPEN" else "stale"
                return self._response(
                    cached["data"],
                    cache_hit=True,
                    age_seconds=age,
                    freshness=freshness,
                )

        with self._lock:
            now = self.clock()
            cached = self._cache.get(cache_key)
            current_market_state = ArgusBaselineStore.market_state(
                self.now_provider()
            )
            if cached is not None and self._cached_expiry_is_active(cached):
                age = max(0.0, now - cached["cached_at"])
                if age < self.cache_ttl_seconds or current_market_state != "OPEN":
                    freshness = (
                        "cached" if current_market_state == "OPEN" else "stale"
                    )
                    return self._response(
                        cached["data"],
                        cache_hit=True,
                        age_seconds=age,
                        freshness=freshness,
                    )

            info = WATCHLIST[normalized_symbol]
            try:
                if process_worker is None:
                    snapshot = self.engine.fetch_current_snapshot(
                        symbol=normalized_symbol, segment=info["segment"],
                        security_id=info["security_id"], expiry=normalized_expiry,
                    )
                    snapshot_dict = snapshot.to_dict()
                else:
                    selected_expiry, response, source = self.engine.fetch_raw_option_chain(
                        segment=info["segment"],
                        security_id=info["security_id"],
                        expiry=normalized_expiry,
                    )
                    prepared = self.engine.prepare_snapshot_input(
                        normalized_symbol,
                        info["segment"],
                        info["security_id"],
                        selected_expiry,
                        response,
                        source=source,
                    )
                    snapshot_dict = process_worker.run("argus_snapshot", prepared)
            except InvalidOptionExpiryError as error:
                raise ArgusAPIError(422, "INVALID_EXPIRY", str(error)) from error
            except BaselineStoreError as error:
                raise ArgusAPIError(
                    503, "BASELINE_STORE_UNAVAILABLE", str(error)
                ) from error
            except OptionChainDataError as error:
                raise ArgusAPIError(502, "DHAN_UNAVAILABLE", str(error)) from error
            except RuntimeError as error:
                raise ArgusAPIError(503, "PROJECTION_WORKER_UNAVAILABLE", str(error)) from error

            compact = self._compact_snapshot(snapshot_dict)
            self._cache[cache_key] = {
                "data": compact,
                "cached_at": self.clock(),
            }
            return self._response(
                compact,
                cache_hit=False,
                age_seconds=0.0,
                freshness=(
                    "fresh" if compact["underlying"]["market_state"] == "OPEN" else "stale"
                ),
            )

    def projection(self, symbol, expiry=None):
        """Return only an existing in-process cache; never refresh Dhan on read."""
        normalized = str(symbol).strip().upper()
        normalized_expiry = self._validate_expiry(expiry)
        candidates = [
            (key, value) for key, value in self._cache.items()
            if key[0] == normalized
            and (normalized_expiry is None or key[1] == normalized_expiry)
            and (normalized_expiry is not None or self._cached_expiry_is_active(value))
        ]
        if not candidates:
            return None
        _, cached = max(candidates, key=lambda item: item[1]["cached_at"])
        age = max(0.0, self.clock() - cached["cached_at"])
        market_state = ArgusBaselineStore.market_state(self.now_provider())
        freshness = (
            "stale"
            if market_state != "OPEN"
            or age >= self.projection_freshness_seconds
            else "cached"
        )
        return self._response(cached["data"], cache_hit=True, age_seconds=age, freshness=freshness)

    def _cached_expiry_is_active(self, cached) -> bool:
        """Never let a closed-market cache pin CURRENT to a finished expiry."""

        try:
            expiry = cached["data"]["underlying"]["expiry"]
        except (KeyError, TypeError):
            return False
        return self.engine.is_active_expiry(expiry)

    def _response(self, data, cache_hit, age_seconds, freshness):
        source_reason = self._source_reason(data)
        reason = source_reason
        if reason is None and freshness == "stale":
            reason = "ARGUS_CACHE_UNAVAILABLE"
        available = freshness != "stale" and source_reason is None
        return {
            "status": "available" if available else "stale",
            "freshness": freshness if available else "stale",
            "reason": reason,
            "cache": {
                "hit": cache_hit,
                "age_seconds": round(age_seconds, 3),
                "ttl_seconds": self.cache_ttl_seconds,
                "projection_freshness_seconds": self.projection_freshness_seconds,
            },
            "data": data,
        }

    def _source_reason(self, data):
        try:
            underlying = data["underlying"]
            fetched_at = datetime.fromisoformat(
                str(underlying["fetched_at"]).replace("Z", "+00:00")
            )
            if fetched_at.tzinfo is None:
                return "ARGUS_CACHE_UNAVAILABLE"
            source_age = (
                self.now_provider().astimezone(self.EXCHANGE_TIMEZONE)
                - fetched_at.astimezone(self.EXCHANGE_TIMEZONE)
            ).total_seconds()
            if source_age < -2.0 or source_age > self.projection_freshness_seconds:
                return "ARGUS_SOURCE_STALE"
            if str(underlying.get("market_state") or "").upper() != "OPEN":
                return "ARGUS_SOURCE_STALE"
        except (KeyError, TypeError, ValueError, AttributeError):
            return "ARGUS_CACHE_UNAVAILABLE"
        return None

    @staticmethod
    def _compact_snapshot(snapshot):
        return {
            "underlying": {
                "symbol": snapshot["symbol"],
                "security_id": snapshot["underlying_security_id"],
                "segment": snapshot["underlying_segment"],
                "ltp": snapshot["underlying_ltp"],
                "expiry": snapshot["expiry"],
                "atm_strike": snapshot["atm_strike"],
                "fetched_at": snapshot["fetched_at"],
                "market_state": snapshot["market_state"],
                "session_name": snapshot["session_name"],
                "trading_date": snapshot["trading_date"],
                "baseline_timestamp": snapshot["baseline_timestamp"],
                "baseline_status": snapshot["baseline_status"],
            },
            "totals": snapshot["totals"],
            "atm_window": snapshot["atm_window"],
            "walls": snapshot["walls"],
            "dominance": snapshot["dominance"],
            "verdict": snapshot["verdict"],
            "provenance": {
                "day_change_oi_basis": "previous_day",
                "intraday_change_oi_basis": "session_baseline",
                "activity_basis": "intraday_price_change_and_intraday_change_oi",
                "minimum_price_change": OptionChainEngine.MIN_PRICE_CHANGE,
                "minimum_oi_change": OptionChainEngine.MIN_OI_CHANGE,
            },
            "missing_fields": snapshot["missing_fields"],
        }

    @staticmethod
    def _validate_expiry(expiry):
        if expiry is None or str(expiry).strip() == "":
            return None
        value = str(expiry).strip()
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ArgusAPIError(
                422,
                "INVALID_EXPIRY_FORMAT",
                "Expiry must use YYYY-MM-DD format",
            ) from error
        return value
