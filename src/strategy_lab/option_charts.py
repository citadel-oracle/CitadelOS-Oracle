"""Shared completed-candle feed for Strategy Lab option-chart deployments."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.data.data_engine import DataEngine
from src.paper_trading.contracts import ContractResolutionError, DhanInstrumentMaster
from .state_truth import CandleIdentity, CanonicalCandleStore, HistoryRequirement


class OptionChartCandleFeed:
    """Ingest the existing ARGUS snapshot once and fan out CE/PE candles."""

    TIMEZONE = ZoneInfo("Asia/Kolkata")
    SIDES = ("CE", "PE")

    def __init__(
        self,
        *,
        dhan: Any,
        instrument_master: Any | None = None,
        projection_provider: Any | None = None,
        max_candles: int = 5000,
        canonical_store_root: str | None = None,
        history_days: int = 20,
        held_contract_provider: Any | None = None,
    ) -> None:
        self.dhan = dhan
        self.instrument_master = instrument_master or DhanInstrumentMaster()
        self.projection_provider = projection_provider
        self.max_candles = max(3, int(max_candles))
        self.canonical_store_root = canonical_store_root
        self.history_days = max(20, int(history_days))
        self.held_contract_provider = held_contract_provider
        self._lock = threading.RLock()
        self._states = {side: self._empty_state() for side in self.SIDES}
        self._last_snapshot: str | None = None
        self._last_payload: Mapping[str, Any] | None = None
        self._last_error: str | None = None
        self._last_gap_reconciliation: dict[str, datetime] = {}
        self._observers: list[Any] = []

    def subscribe(self, observer: Any) -> None:
        """Fan out the already-fetched ARGUS snapshot without adding polling."""

        if not callable(observer):
            raise TypeError("option-chart observer must be callable")
        with self._lock:
            self._observers.append(observer)
            cached = deepcopy(self._last_payload)
        if cached is not None:
            try:
                observer(cached)
            except Exception:
                pass
            return
        if self.projection_provider is not None:
            try:
                # The provider exposes ARGUS' existing cached projection.  This
                # primes late advisory subscribers after a restart; it does not
                # create another market-data poller or websocket.
                self.ingest(self.projection_provider())
            except Exception:
                self._last_error = "ARGUS_PROJECTION_UNAVAILABLE"

    def ingest(self, snapshot: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        if not isinstance(snapshot, Mapping):
            return snapshot
        snapshot_status = str(snapshot.get("status") or "").lower()
        if snapshot_status == "stale":
            # Post-market ARGUS cache remains authoritative historical context.
            # Restore persisted completed candles without treating the stale
            # option-chain quote as a live candle.
            self._restore_stale_snapshot(snapshot)
            with self._lock:
                observers = tuple(self._observers)
            for observer in observers:
                try:
                    observer(snapshot)
                except Exception:
                    continue
            return snapshot
        if snapshot_status != "available":
            return snapshot
        data = snapshot.get("data")
        underlying = data.get("underlying") if isinstance(data, Mapping) else None
        if not isinstance(underlying, Mapping) or str(underlying.get("symbol") or "").upper() != "NIFTY":
            return snapshot
        try:
            fetched_at = self._aware(underlying.get("fetched_at"))
        except (TypeError, ValueError):
            self._last_error = "ARGUS_TIMESTAMP_INVALID"
            return snapshot
        snapshot_id = f"{underlying.get('expiry')}:{fetched_at.isoformat()}"
        with self._lock:
            if snapshot_id == self._last_snapshot:
                return snapshot
            rows = [row for row in data.get("atm_window") or [] if isinstance(row, Mapping)]
            try:
                for side in self.SIDES:
                    self._ingest_side(side, underlying, rows, fetched_at)
            except ContractResolutionError:
                self._last_error = "OPTION_CONTRACT_RESOLUTION_UNAVAILABLE"
                return snapshot
            self._last_snapshot = snapshot_id
            self._last_payload = deepcopy(snapshot)
            self._last_error = None
            observers = tuple(self._observers)
        for observer in observers:
            try:
                observer(snapshot)
            except Exception:
                # Advisory consumers cannot degrade the strategy candle feed.
                continue
        return snapshot

    def _restore_stale_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        data = snapshot.get("data")
        underlying = data.get("underlying") if isinstance(data, Mapping) else None
        if not isinstance(underlying, Mapping) or str(underlying.get("symbol") or "").upper() != "NIFTY":
            return
        rows = [row for row in data.get("atm_window") or [] if isinstance(row, Mapping)]
        expiry = str(underlying.get("expiry") or "")
        trading_date = str(underlying.get("trading_date") or "")
        if not expiry or not rows:
            return
        snapshot_id = f"stale:{expiry}:{trading_date}"
        with self._lock:
            if self._last_snapshot == snapshot_id:
                return
            for side in self.SIDES:
                state = self._states[side]
                held = self.held_contract_provider(side) if callable(self.held_contract_provider) else None
                held_security_id = str(held.get("security_id") or "") if isinstance(held, Mapping) else ""
                leg_row = self._find_security(rows, side, held_security_id) if held_security_id else None
                leg_row = leg_row or self._atm_leg(rows, side, underlying.get("atm_strike"))
                if leg_row is None:
                    continue
                contract = (
                    deepcopy(dict(held))
                    if isinstance(held, Mapping) and held_security_id
                    else self._contract(side, expiry, leg_row)
                )
                store = self._store(contract, "1m")
                completed = store.load()[-self.max_candles :] if store is not None else []
                latest = self._aware(completed[-1]["candle_closed_at"]) if completed else None
                readiness = (
                    store.readiness(
                        HistoryRequirement.strategy_lab_default("1m"),
                        now=latest or datetime.now(self.TIMEZONE),
                    )
                    if store is not None
                    else None
                )
                state.update({
                    "contract": contract,
                    "trading_date": trading_date,
                    "completed_1m": completed,
                    "live": None,
                    "last_cumulative_volume": None,
                    "readiness": readiness,
                })
            self._last_snapshot = snapshot_id
            self._last_payload = deepcopy(snapshot)
            self._last_error = None

    def load_cache(self, side: str, timeframe: str) -> list[dict[str, Any]]:
        if self.projection_provider is not None:
            try:
                self.ingest(self.projection_provider())
            except Exception:
                self._last_error = "ARGUS_PROJECTION_UNAVAILABLE"
        normalized_side = str(side).upper()
        normalized_timeframe = str(timeframe).lower()
        if normalized_side not in self.SIDES or normalized_timeframe not in {"1m", "3m", "5m"}:
            raise ValueError("unsupported option-chart deployment")
        with self._lock:
            rows = self._states[normalized_side]["completed_1m"]
            selected = (
                rows
                if normalized_timeframe == "1m"
                else self._aggregate_three_minute(rows)
                if normalized_timeframe == "3m"
                else self._aggregate_five_minute(rows)
            )
            return deepcopy(selected[-self.max_candles :])

    def source(self, side: str, timeframe: str) -> "OptionChartCandleSource":
        return OptionChartCandleSource(self, side=side, timeframe=timeframe)

    def completed_candles(self, side: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Read the already-ingested canonical 1m cache without polling."""
        normalized_side = str(side).upper()
        if normalized_side not in self.SIDES:
            raise ValueError("unsupported option side")
        with self._lock:
            rows = self._states[normalized_side]["completed_1m"]
            selected = rows[-limit:] if limit is not None else rows
            return deepcopy(selected)

    def current_revision(self, side: str, timeframe: str) -> str | None:
        """Return one cheap immutable revision for the latest closed candle.

        The Strategy Lab scheduler uses this only to avoid rebuilding an
        already-processed finalized-candle context on timer wakes.  Contract
        identity is included so an ATM/held-contract rotation can never be
        coalesced with its predecessor.
        """

        normalized_side = str(side).upper()
        normalized_timeframe = str(timeframe).lower()
        if normalized_side not in self.SIDES or normalized_timeframe not in {"1m", "3m", "5m"}:
            return None
        with self._lock:
            state = self._states[normalized_side]
            contract = state.get("contract") or {}
            rows = state.get("completed_1m") or []
            if not rows:
                return None
            if normalized_timeframe == "1m":
                latest = rows[-1]
            else:
                # A small tail is sufficient to find the latest complete
                # higher-timeframe bucket and avoids aggregating session
                # history merely to answer a scheduler wake.
                aggregated = (
                    self._aggregate_three_minute(rows[-6:])
                    if normalized_timeframe == "3m"
                    else self._aggregate_five_minute(rows[-10:])
                )
                if not aggregated:
                    return None
                latest = aggregated[-1]
            timestamp = latest.get("timestamp") or latest.get("candle_closed_at")
            security_id = (
                latest.get("contract")
                or (latest.get("chart_contract") or {}).get("security_id")
                or contract.get("security_id")
            )
            if timestamp is None:
                return None
            return f"{normalized_side}:{normalized_timeframe}:{security_id}:{timestamp}"

    def status(self) -> dict[str, Any]:
        with self._lock:
            ready = bool(self._last_snapshot) and all(
                state.get("completed_1m") for state in self._states.values()
            )
            return {
                "status": "READY" if ready else "WAITING_FOR_ARGUS",
                "single_ingestion": True,
                "additional_polling": False,
                "websocket_count": 0,
                "last_error": self._last_error,
                "sides": {
                    side: {
                        "contract": deepcopy(state["contract"]),
                        "completed_1m": len(state["completed_1m"]),
                        "readiness": deepcopy(state.get("readiness")),
                    }
                    for side, state in self._states.items()
                },
            }

    def _ingest_side(
        self,
        side: str,
        underlying: Mapping[str, Any],
        rows: list[Mapping[str, Any]],
        fetched_at: datetime,
    ) -> None:
        state = self._states[side]
        expiry = str(underlying.get("expiry") or "")
        trading_date = str(underlying.get("trading_date") or fetched_at.date().isoformat())
        current_contract = state.get("contract")
        leg_row = None
        if current_contract and current_contract.get("expiry") == expiry and state.get("trading_date") == trading_date:
            leg_row = self._find_security(rows, side, current_contract["security_id"])
            if leg_row is None:
                leg_row = self._locked_contract_quote_row(side, current_contract)
        if leg_row is None and current_contract and state.get("trading_date") == trading_date:
            return
        if leg_row is None:
            held = self.held_contract_provider(side) if callable(self.held_contract_provider) else None
            held_security_id = str(held.get("security_id") or "") if isinstance(held, Mapping) else ""
            leg_row = self._find_security(rows, side, held_security_id) if held_security_id else None
            if leg_row is None and isinstance(held, Mapping) and held_security_id:
                leg_row = self._locked_contract_quote_row(side, held)
            leg_row = leg_row or self._atm_leg(rows, side, underlying.get("atm_strike"))
            if leg_row is None:
                return
            contract = (
                deepcopy(dict(held))
                if isinstance(held, Mapping) and held_security_id
                else self._contract(side, expiry, leg_row)
            )
            self._reset_side(state, contract, trading_date, fetched_at)
        leg = leg_row[side.lower()]
        price = self._positive(leg.get("ltp"))
        if price is None:
            return
        self._update_live(state, price, leg.get("volume"), fetched_at)
        self._reconcile_missing_history(state, fetched_at)

    def _locked_contract_quote_row(
        self,
        side: str,
        contract: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        quote_provider = getattr(self.dhan, "get_quote", None)
        if not callable(quote_provider):
            return None
        security_id = str(contract.get("security_id") or "")
        if not security_id:
            return None
        try:
            quote = quote_provider("NSE_FNO", security_id)
            price = self._positive(quote.get("ltp")) if isinstance(quote, Mapping) else None
        except Exception:
            return None
        if price is None:
            return None
        leg = {
            "security_id": security_id,
            "ltp": price,
            "volume": (quote.get("raw") or {}).get("volume") if isinstance(quote, Mapping) else None,
        }
        return {
            "strike": contract.get("strike"),
            side.lower(): leg,
        }

    def _reset_side(
        self,
        state: dict[str, Any],
        contract: dict[str, Any],
        trading_date: str,
        fetched_at: datetime,
    ) -> None:
        store = self._store(contract, "1m")
        missing_before = list(store.audit().get("missing_timestamps") or []) if store is not None else []
        history = []
        for from_date, to_date in self._history_ranges(fetched_at, store):
            response = self.dhan.get_intraday_candles(
                segment="NSE_FNO", security_id=contract["security_id"], instrument="OPTIDX",
                interval="1", from_date=from_date, to_date=to_date,
            )
            if isinstance(response, Mapping) and response.get("success") is True:
                for row in response.get("candles") or []:
                    normalized = self._history_candle(row, contract, fetched_at)
                    if normalized is not None:
                        history.append(normalized)
        if store is not None:
            store.merge(history, fetch_timestamp=fetched_at.isoformat())
            provider_times = {row["timestamp"] for row in history}
            if missing_before:
                store.record_gap_classifications({
                    "timestamp": timestamp,
                    "classification": "FETCH_RANGE_MISSING" if timestamp in provider_times else "PROVIDER_MISSING",
                    "reason": "PROVIDER_CANDLE_RECOVERED_DURING_RESTART_OVERLAP" if timestamp in provider_times else "AUTHORITATIVE_PROVIDER_DID_NOT_RETURN_INTERVAL",
                    "provider": "DHAN_DATA_API",
                    "reconciled_at": fetched_at.isoformat(),
                    "repaired": timestamp in provider_times,
                } for timestamp in missing_before)
            history = store.load()
        by_time = {row["timestamp"]: row for row in history}
        readiness = (
            store.readiness(HistoryRequirement.strategy_lab_default("1m"), now=fetched_at)
            if store is not None else None
        )
        state.update({
            "contract": contract,
            "trading_date": trading_date,
            "completed_1m": [by_time[key] for key in sorted(by_time)][-self.max_candles :],
            "live": None,
            "last_cumulative_volume": None,
            "readiness": readiness,
        })

    def _update_live(self, state: dict[str, Any], price: float, cumulative_volume: Any, observed_at: datetime) -> None:
        bucket = observed_at.replace(second=0, microsecond=0)
        volume = self._nonnegative(cumulative_volume)
        previous_volume = state.get("last_cumulative_volume")
        incremental_volume = max(0.0, volume - previous_volume) if volume is not None and previous_volume is not None else 0.0
        if volume is not None:
            state["last_cumulative_volume"] = volume
        live = state.get("live")
        if live is not None and self._aware(live["timestamp"]) < bucket:
            closed = dict(live)
            closed.update({
                "closed": True,
                "is_closed": True,
                "candle_closed_at": (self._aware(closed["timestamp"]) + timedelta(minutes=1)).isoformat(),
            })
            rows = {row["timestamp"]: row for row in state["completed_1m"]}
            rows[closed["timestamp"]] = closed
            state["completed_1m"] = [rows[key] for key in sorted(rows)][-self.max_candles :]
            store = self._store(state["contract"], "1m")
            if store is not None:
                store.merge([closed], fetch_timestamp=observed_at.isoformat())
                state["completed_1m"] = store.load()[-self.max_candles :]
                state["readiness"] = store.readiness(
                    HistoryRequirement.strategy_lab_default("1m"), now=observed_at
                )
            live = None
        if live is None:
            contract = state["contract"]
            state["live"] = {
                "symbol": f"NIFTY_{contract['option_type']}",
                "underlying": "NIFTY",
                "timeframe": "1m",
                "timestamp": bucket.isoformat(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": incremental_volume,
                "source": "DHAN_OPTION_CHAIN",
                "received_at": observed_at.isoformat(),
                "contract": contract["security_id"],
                "chart_contract": deepcopy(contract),
                "lot_size": contract["lot_size"],
            }
            return
        live["high"] = max(float(live["high"]), price)
        live["low"] = min(float(live["low"]), price)
        live["close"] = price
        live["volume"] = float(live.get("volume") or 0.0) + incremental_volume
        live["received_at"] = observed_at.isoformat()

    def _reconcile_missing_history(self, state: dict[str, Any], observed_at: datetime) -> None:
        """Repair only provider-confirmed missing buckets in the canonical reservoir."""

        contract = state.get("contract")
        store = self._store(contract, "1m") if isinstance(contract, Mapping) else None
        readiness = state.get("readiness")
        missing = list(readiness.get("missing_timestamps") or []) if isinstance(readiness, Mapping) else []
        if store is None or not missing:
            return
        security_id = str(contract["security_id"])
        last = self._last_gap_reconciliation.get(security_id)
        if last is not None and (observed_at - last).total_seconds() < 60:
            return
        self._last_gap_reconciliation[security_id] = observed_at
        missing_set = {self._aware(value).replace(second=0, microsecond=0).isoformat() for value in missing}
        dates = sorted({self._aware(value).date().isoformat() for value in missing})
        recovered: list[dict[str, Any]] = []
        classifications: list[dict[str, Any]] = []
        for date in dates:
            response = self.dhan.get_intraday_candles(
                segment="NSE_FNO", security_id=security_id, instrument="OPTIDX",
                interval="1", from_date=date, to_date=date,
            )
            provider_rows: dict[str, dict[str, Any]] = {}
            if isinstance(response, Mapping) and response.get("success") is True:
                for row in response.get("candles") or []:
                    normalized = self._history_candle(row, contract, observed_at)
                    if normalized is not None:
                        provider_rows[normalized["timestamp"]] = normalized
            for timestamp in sorted(value for value in missing_set if value.startswith(date)):
                candle = provider_rows.get(timestamp)
                if candle is not None:
                    recovered.append(candle)
                    classification = "FETCH_RANGE_MISSING"
                    reason = "PROVIDER_CANDLE_RECOVERED_FROM_EXACT_DATE_RANGE"
                else:
                    stamp = self._aware(timestamp)
                    in_session = stamp.weekday() < 5 and (stamp.hour, stamp.minute) >= (9, 15) and (stamp.hour, stamp.minute) <= (15, 29)
                    classification = "PROVIDER_MISSING" if in_session else "SESSION_CLOSED"
                    reason = "AUTHORITATIVE_PROVIDER_DID_NOT_RETURN_INTERVAL" if in_session else "OUTSIDE_REGULAR_SESSION"
                classifications.append({
                    "timestamp": timestamp,
                    "classification": classification,
                    "reason": reason,
                    "provider": "DHAN_DATA_API",
                    "reconciled_at": observed_at.isoformat(),
                    "repaired": candle is not None,
                })
        store.record_gap_classifications(classifications)
        if recovered:
            store.merge(recovered, fetch_timestamp=observed_at.isoformat())
            state["completed_1m"] = store.load()[-self.max_candles :]
        state["readiness"] = store.readiness(
            HistoryRequirement.strategy_lab_default("1m"), now=observed_at
        )

    def _contract(self, side: str, expiry: str, row: Mapping[str, Any]) -> dict[str, Any]:
        leg = row[side.lower()]
        security_id = str(leg["security_id"])
        strike = float(row["strike"])
        try:
            master = self.instrument_master.resolve(
                security_id=security_id,
                expiry=expiry,
                strike=strike,
                option_type=side,
                underlying="NIFTY",
            )
        except TypeError:
            master = self.instrument_master.resolve(
                security_id=security_id, expiry=expiry, strike=strike, option_type=side
            )
        except ContractResolutionError:
            raise
        return {
            "security_id": str(master["security_id"]),
            "exchange_segment": str(master["exchange_segment"]),
            "underlying": "NIFTY",
            "option_type": side,
            "strike": strike,
            "expiry": expiry,
            "lot_size": int(master["lot_size"]),
            "instrument_source": str(master["source"]),
            "quote_source": "DHAN_OPTION_CHAIN",
        }

    def _history_candle(
        self, row: Mapping[str, Any], contract: Mapping[str, Any], fetched_at: datetime
    ) -> dict[str, Any] | None:
        try:
            timestamp = DataEngine.exchange_datetime(row.get("time"))
            if timestamp + timedelta(minutes=1) > fetched_at:
                return None
            return {
                "symbol": f"NIFTY_{contract['option_type']}",
                "underlying": "NIFTY",
                "timeframe": "1m",
                "timestamp": timestamp.replace(second=0, microsecond=0).isoformat(),
                "candle_closed_at": (timestamp.replace(second=0, microsecond=0) + timedelta(minutes=1)).isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0.0),
                "source": "DHAN_DATA_API",
                "received_at": fetched_at.isoformat(),
                "closed": True,
                "is_closed": True,
                "contract": contract["security_id"],
                "chart_contract": deepcopy(dict(contract)),
                "lot_size": contract["lot_size"],
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def _aggregate_three_minute(self, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            timestamp = self._aware(row["timestamp"])
            bucket = timestamp.replace(minute=(timestamp.minute // 3) * 3, second=0, microsecond=0)
            grouped.setdefault(bucket.isoformat(), []).append(row)
        result = []
        for bucket_key in sorted(grouped):
            group = sorted(grouped[bucket_key], key=lambda item: item["timestamp"])
            bucket = self._aware(bucket_key)
            expected = [(bucket + timedelta(minutes=index)).isoformat() for index in range(3)]
            if [self._aware(item["timestamp"]).isoformat() for item in group] != expected:
                continue
            first, last = group[0], group[-1]
            result.append({
                **{key: deepcopy(first[key]) for key in (
                    "symbol", "underlying", "source", "contract", "chart_contract", "lot_size"
                )},
                "timeframe": "3m",
                "timestamp": bucket.isoformat(),
                "candle_closed_at": (bucket + timedelta(minutes=3)).isoformat(),
                "received_at": last.get("received_at"),
                "open": float(first["open"]),
                "high": max(float(item["high"]) for item in group),
                "low": min(float(item["low"]) for item in group),
                "close": float(last["close"]),
                "volume": sum(float(item.get("volume") or 0.0) for item in group),
                "closed": True,
                "is_closed": True,
            })
        return result

    def _aggregate_five_minute(self, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Reuse the accepted VOB 1m->5m resampler for option-premium bars.

        The VOB engine is the existing canonical 5m bucket authority.  This
        adapter adds contract lineage and an explicit close timestamp; it does
        not implement another OHLC formula.
        """

        if not rows:
            return []
        from src.vob.engine import NiftyVOBEngine

        resampled = NiftyVOBEngine()._resample_1m(list(rows), 5)
        by_timestamp = {self._aware(row["timestamp"]).isoformat(): row for row in rows}
        result: list[dict[str, Any]] = []
        for item in resampled:
            bucket = self._aware(item["timestamp"])
            group = [
                by_timestamp.get((bucket + timedelta(minutes=offset)).isoformat())
                for offset in range(5)
            ]
            group = [row for row in group if row is not None]
            if not group:
                continue
            first, last = group[0], group[-1]
            enriched = dict(item)
            enriched.update({
                **{key: deepcopy(first.get(key)) for key in (
                    "symbol", "underlying", "source", "contract", "chart_contract", "lot_size"
                )},
                "timeframe": "5m",
                "candle_closed_at": (bucket + timedelta(minutes=5)).isoformat(),
                "received_at": last.get("received_at"),
                "closed": True,
                "is_closed": True,
            })
            result.append(enriched)
        return result

    @staticmethod
    def _atm_leg(rows: list[Mapping[str, Any]], side: str, atm: Any) -> Mapping[str, Any] | None:
        try:
            return next(
                row for row in rows
                if abs(float(row.get("strike")) - float(atm)) < 0.001
                and isinstance(row.get(side.lower()), Mapping)
            )
        except (StopIteration, TypeError, ValueError):
            return None

    @staticmethod
    def _find_security(rows: list[Mapping[str, Any]], side: str, security_id: str) -> Mapping[str, Any] | None:
        return next((
            row for row in rows
            if isinstance(row.get(side.lower()), Mapping)
            and str(row[side.lower()].get("security_id")) == str(security_id)
        ), None)

    @classmethod
    def _aware(cls, value: Any) -> datetime:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=cls.TIMEZONE) if parsed.tzinfo is None else parsed.astimezone(cls.TIMEZONE)

    @staticmethod
    def _positive(value: Any) -> float | None:
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _nonnegative(value: Any) -> float | None:
        try:
            number = float(value)
            return number if number >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "contract": None,
            "trading_date": None,
            "completed_1m": [],
            "live": None,
            "last_cumulative_volume": None,
            "readiness": None,
        }

    def _store(self, contract: Mapping[str, Any], timeframe: str) -> CanonicalCandleStore | None:
        if not self.canonical_store_root:
            return None
        return CanonicalCandleStore(
            self.canonical_store_root,
            CandleIdentity(
                instrument=f"NIFTY_{contract['option_type']}",
                security_id=str(contract["security_id"]), timeframe=timeframe,
                expiry=str(contract.get("expiry") or "") or None,
            ),
            max_candles=max(self.max_candles, 12000),
        )

    def _history_ranges(self, fetched_at: datetime, store: CanonicalCandleStore | None) -> list[tuple[str, str]]:
        if store is None:
            return [((fetched_at.date() - timedelta(days=20)).isoformat(), fetched_at.date().isoformat())]
        required = HistoryRequirement.strategy_lab_default("1m").required_bars
        days = self.history_days if len(store.load()) < required else 3
        start = fetched_at.date() - timedelta(days=days)
        result = []
        while start < fetched_at.date():
            end = min(start + timedelta(days=30), fetched_at.date())
            result.append((start.isoformat(), end.isoformat()))
            start = end
        return result or [((fetched_at.date() - timedelta(days=1)).isoformat(), fetched_at.date().isoformat())]

    def readiness(self, side: str, timeframe: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._states[str(side).upper()]
            contract = state.get("contract")
            if not contract:
                return {"DATA_READY": False, "not_ready_reason": "EXPIRY_UNRESOLVED", "loaded_bars": 0}
            normalized_timeframe = str(timeframe).lower()
            if normalized_timeframe == "1m":
                return deepcopy(state.get("readiness"))
            rows = (
                self._aggregate_three_minute(state["completed_1m"])
                if normalized_timeframe == "3m"
                else self._aggregate_five_minute(state["completed_1m"])
            )
            if normalized_timeframe == "5m":
                return {
                    "DATA_READY": bool(rows),
                    "not_ready_reason": None if rows else "HISTORY_LOADING",
                    "loaded_bars": len(rows),
                }
            store = self._store(contract, "3m")
            if store is None:
                return {"DATA_READY": bool(rows), "not_ready_reason": None if rows else "HISTORY_LOADING", "loaded_bars": len(rows)}
            before = store.readiness(HistoryRequirement.strategy_lab_default("3m"))
            missing_before = list(before.get("missing_timestamps") or [])
            now = None
            if state.get("readiness") and state["readiness"].get("latest_completed_candle"):
                try:
                    now = datetime.fromisoformat(state["readiness"]["latest_completed_candle"])
                except Exception:
                    pass
            if now is None:
                now = datetime.now(self.TIMEZONE)
            store.merge(rows, fetch_timestamp=now.isoformat())
            after = store.readiness(HistoryRequirement.strategy_lab_default("3m"), now=now)
            if missing_before:
                remaining = set(after.get("missing_timestamps") or [])
                store.record_gap_classifications({
                    "timestamp": timestamp,
                    "classification": "MERGE_DROPPED",
                    "reason": "INCOMPLETE_THREE_MINUTE_GROUP_RESTORED_FROM_AUTHORITATIVE_ONE_MINUTE_CANDLES" if timestamp not in remaining else "INCOMPLETE_THREE_MINUTE_GROUP",
                    "provider": "CANONICAL_1M_AGGREGATION",
                    "reconciled_at": now.isoformat(),
                    "repaired": timestamp not in remaining,
                } for timestamp in missing_before)
                after = store.readiness(HistoryRequirement.strategy_lab_default("3m"), now=now)
            return after


class OptionChartCandleSource:
    def __init__(self, feed: OptionChartCandleFeed, *, side: str, timeframe: str) -> None:
        self.feed = feed
        self.side = side
        self.timeframe = timeframe

    def load_cache(self) -> list[dict[str, Any]]:
        return self.feed.load_cache(self.side, self.timeframe)

    def readiness(self):
        return self.feed.readiness(self.side, self.timeframe)

    def current_revision(self) -> str | None:
        return self.feed.current_revision(self.side, self.timeframe)
