"""Shared, read-only completed-candle input for active Strategy Lab runtimes."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


class CompletedCandleContextProvider:
    """Build one authoritative context per cached candle for all strategies.

    Candle acquisition remains owned by the existing market-data scheduler.  This
    adapter only reads that cache and resolves one shared option-chain snapshot.
    """

    def __init__(
        self,
        *,
        candle_source: Any,
        argus_provider: Callable[[], Mapping[str, Any] | None],
        clock: Callable[[], datetime] | None = None,
        max_age_seconds: float = 600.0,
        held_security_id_provider: Callable[[], str | None] | None = None,
        canonical_5m_source: Any | None = None,
    ) -> None:
        self.candle_source = candle_source
        self.argus_provider = argus_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_age_seconds = max(1.0, float(max_age_seconds))
        self.held_security_id_provider = held_security_id_provider
        self.canonical_5m_source = canonical_5m_source
        self._lock = threading.Lock()
        self._candle_id: str | None = None
        self._context: dict[str, Any] | None = None

    def current_revision(self) -> str | None:
        """Return the source's cheap finalized-candle revision when supported.

        This is deliberately metadata-only.  It never substitutes for the
        full context validation performed by ``__call__``.
        """

        revision_provider = getattr(self.candle_source, "current_revision", None)
        if not callable(revision_provider):
            return None
        revision = revision_provider()
        return str(revision) if revision is not None else None

    def __call__(self) -> Mapping[str, Any]:
        candles = self.candle_source.load_cache()
        if not candles:
            return self._unavailable("CLOSED_CANDLE_CACHE_EMPTY")
        readiness_provider = getattr(self.candle_source, "readiness", None)
        readiness = readiness_provider() if callable(readiness_provider) else None
        if isinstance(readiness, Mapping) and readiness.get("DATA_READY") is False:
            return self._unavailable(
                str(readiness.get("not_ready_reason") or "HISTORY_LOADING"),
                readiness=readiness,
            )
        candle = dict(candles[-1])
        if candle.get("closed") is not True and candle.get("is_closed") is not True:
            return self._unavailable("INCOMPLETE_CANDLE")
        if candle.get("volume") is None:
            return self._unavailable("AUTHORITATIVE_VOLUME_REQUIRED")
        try:
            timestamp = self._aware(candle["timestamp"])
            closed_at = self._aware(candle.get("candle_closed_at") or candle["timestamp"])
        except (KeyError, TypeError, ValueError):
            return self._unavailable("CANDLE_TIMESTAMP_INVALID")
        now = self._aware(self.clock())
        age_seconds = (now - closed_at).total_seconds()
        if age_seconds < 0:
            return self._unavailable("CANDLE_NOT_CLOSED")
        if age_seconds > self.max_age_seconds:
            return self._unavailable(
                "CANDLE_STALE",
                timestamp=timestamp.isoformat(),
                readiness=readiness,
            )

        symbol = str(candle.get("symbol") or "").upper()
        timeframe = str(candle.get("timeframe") or "")
        candle_id = f"{symbol}:{timeframe}:{timestamp.isoformat()}"
        with self._lock:
            if candle_id == self._candle_id and self._context is not None:
                return deepcopy(self._context)
            try:
                argus = self.argus_provider()
            except Exception:
                return self._stale_chain_fallback(
                    candle, candles, candle_id, symbol, timeframe, timestamp, readiness,
                    reason="AUTHORITATIVE_OPTION_CHAIN_UNAVAILABLE",
                )
            if not isinstance(argus, Mapping) or not isinstance(argus.get("data"), Mapping):
                return self._stale_chain_fallback(
                    candle, candles, candle_id, symbol, timeframe, timestamp, readiness,
                    reason="AUTHORITATIVE_OPTION_CHAIN_UNAVAILABLE",
                )
            if not self._argus_is_fresh(argus, now):
                return self._stale_chain_fallback(
                    candle, candles, candle_id, symbol, timeframe, timestamp, readiness,
                    reason="AUTHORITATIVE_OPTION_CHAIN_STALE",
                )
            interval_seconds = self._interval_seconds(timeframe)
            context = {
                "candle_id": candle_id,
                "symbol": symbol,
                "underlying": symbol,
                "timeframe": timeframe,
                "timestamp": timestamp.isoformat(),
                "closed": True,
                "is_closed": True,
                "source": candle.get("source"),
                "source_health": "READY",
                "source_timestamp": candle.get("received_at"),
                "data_readiness": deepcopy(dict(readiness)) if isinstance(readiness, Mapping) else {
                    "DATA_READY": True, "loaded_bars": len(candles), "not_ready_reason": None,
                },
                "argus": deepcopy(dict(argus)),
                "bar": {
                    "index": int(timestamp.timestamp() // interval_seconds),
                    "timestamp": timestamp.isoformat(),
                    "candle_closed_at": candle.get("candle_closed_at"),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle["volume"]),
                    "confirmed": True,
                    "is_closed": True,
                },
            }
            chart_contract = candle.get("chart_contract")
            if isinstance(chart_contract, Mapping):
                context.update({
                    "underlying": str(candle.get("underlying") or "NIFTY").upper(),
                    "contract": str(candle.get("contract") or chart_contract.get("security_id") or ""),
                    "option_contract": str(candle.get("contract") or chart_contract.get("security_id") or ""),
                    "chart_contract": deepcopy(dict(chart_contract)),
                    "lot_size": int(candle["lot_size"]),
                    "current_price": float(candle["close"]),
                    "paper_price": float(candle["close"]),
                    "option_price": float(candle["close"]),
                })
            history = [self._history_bar(item) for item in candles if self._valid_history_candle(item)]
            context["completed_candles"] = history
            context["warmup_candle_count"] = len(history)
            context["canonical_5m_candles"] = self._canonical_5m_history(
                candle_closed_at=closed_at,
                security_id=str(context.get("contract") or ""),
            )
            self._candle_id = candle_id
            self._context = context
            return deepcopy(context)

    def _stale_chain_fallback(
        self,
        candle: dict[str, Any],
        candles: list[Any],
        candle_id: str,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        readiness: Any,
        *,
        reason: str,
    ) -> Mapping[str, Any]:
        """Allow evaluation only for the exact held security ID candle when chain is stale.

        Rules enforced:
        - Only the latest eligible completed candle of the EXACT held security ID is used.
        - New entry, contract selection, and rotation are always blocked.
        - Index candle price must never price an option exit.
        - Current ATM or any other contract is rejected.
        - Reason, security_id, candle_time, and price are persisted in the returned context.
        """
        chart_contract = candle.get("chart_contract")
        candle_security_id = str(
            candle.get("contract")
            or (chart_contract.get("security_id") if isinstance(chart_contract, Mapping) else None)
            or ""
        )

        # Resolve the held security ID from the caller-supplied provider (if any).
        held_security_id: str | None = None
        if callable(self.held_security_id_provider):
            try:
                held_security_id = self.held_security_id_provider()
            except Exception:
                held_security_id = None

        # The candle must be an option candle (has chart_contract) AND its security_id
        # must exactly match the held position's security_id.  Any mismatch is rejected.
        is_option_candle = isinstance(chart_contract, Mapping) and bool(candle_security_id)
        held_matches = (
            held_security_id is not None
            and bool(held_security_id)
            and candle_security_id == str(held_security_id)
        )

        if not is_option_candle or not held_matches:
            # Block new entry and any wrong-contract candle.
            return self._unavailable(reason, timestamp=timestamp.isoformat())

        # Confirm this is the latest completed candle (no replay / historical candle).
        # candles[-1] is the most recent candle in cache; `candle` is already resolved from it.
        # The candle timestamp must equal the last candle in the cache.
        if candles:
            last_raw = candles[-1]
            try:
                last_ts = self._aware(last_raw["timestamp"])
                if last_ts != timestamp:
                    return self._unavailable(
                        "CANDLE_FALLBACK_NOT_LATEST_COMPLETED",
                        timestamp=timestamp.isoformat(),
                    )
            except (KeyError, TypeError, ValueError):
                return self._unavailable(reason, timestamp=timestamp.isoformat())

        # Price must come exclusively from this option candle close — never index price.
        candle_price = float(candle["close"])
        interval_seconds = self._interval_seconds(timeframe)

        fallback_context: dict[str, Any] = {
            "candle_id": candle_id,
            "symbol": symbol,
            "underlying": str(candle.get("underlying") or "NIFTY").upper(),
            "timeframe": timeframe,
            "timestamp": timestamp.isoformat(),
            "closed": True,
            "is_closed": True,
            "source": candle.get("source"),
            "source_health": "STALE_CHAIN_CANDLE_FALLBACK",
            "source_reason": reason,
            "source_timestamp": candle.get("received_at"),
            "chain_stale": True,
            "chain_stale_reason": reason,
            "new_entry_blocked": True,
            "contract_rotation_blocked": True,
            "candle_fallback": True,
            "candle_fallback_reason": "QUOTE_UNAVAILABLE_CHAIN_STALE_CANDLE_FALLBACK",
            "candle_fallback_security_id": candle_security_id,
            "candle_fallback_timestamp": timestamp.isoformat(),
            "candle_fallback_price": candle_price,
            "data_readiness": deepcopy(dict(readiness)) if isinstance(readiness, Mapping) else {
                "DATA_READY": True, "loaded_bars": len(candles), "not_ready_reason": None,
            },
            "bar": {
                "index": int(timestamp.timestamp() // interval_seconds),
                "timestamp": timestamp.isoformat(),
                "candle_closed_at": candle.get("candle_closed_at"),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": candle_price,
                "volume": float(candle["volume"]),
                "confirmed": True,
                "is_closed": True,
            },
            "contract": candle_security_id,
            "option_contract": candle_security_id,
            "chart_contract": deepcopy(dict(chart_contract)),
            "lot_size": int(candle["lot_size"]) if candle.get("lot_size") else None,
            "current_price": candle_price,
            "paper_price": candle_price,
            "option_price": candle_price,
        }
        history = [self._history_bar(item) for item in candles if self._valid_history_candle(item)]
        fallback_context["completed_candles"] = history
        fallback_context["warmup_candle_count"] = len(history)
        fallback_context["canonical_5m_candles"] = self._canonical_5m_history(
            candle_closed_at=self._aware(candle.get("candle_closed_at") or candle["timestamp"]),
            security_id=candle_security_id,
        )
        return fallback_context

    def _canonical_5m_history(self, *, candle_closed_at: datetime, security_id: str) -> list[Mapping[str, Any]]:
        """Expose only canonical 5m bars Pine could know at this chart close."""

        if self.canonical_5m_source is None:
            return []
        try:
            rows = self.canonical_5m_source.load_cache()
        except Exception:
            return []
        legal: list[Mapping[str, Any]] = []
        for raw in rows:
            if not self._valid_history_candle(raw):
                continue
            try:
                closed_at = self._aware(raw.get("candle_closed_at") or raw["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            row_security_id = str(
                raw.get("contract")
                or (raw.get("chart_contract") or {}).get("security_id")
                or ""
            )
            if closed_at > candle_closed_at or (security_id and row_security_id != security_id):
                continue
            legal.append(self._history_bar(raw))
        return legal

    @staticmethod
    def _interval_seconds(timeframe: str) -> int:
        value = timeframe.strip().lower()
        if value.endswith("m") and value[:-1].isdigit():
            return max(60, int(value[:-1]) * 60)
        return 60

    @classmethod
    def _history_bar(cls, candle: Mapping[str, Any]) -> Mapping[str, Any]:
        timestamp = cls._aware(candle["timestamp"])
        timeframe = str(candle.get("timeframe") or "")
        result = {
            "index": int(timestamp.timestamp() // cls._interval_seconds(timeframe)),
            "timestamp": timestamp.isoformat(),
            "candle_closed_at": candle.get("candle_closed_at"),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle["volume"]),
            "confirmed": True,
            "is_closed": True,
        }
        chart_contract = candle.get("chart_contract")
        if isinstance(chart_contract, Mapping):
            result.update({
                "underlying": str(candle.get("underlying") or "NIFTY").upper(),
                "contract": str(candle.get("contract") or chart_contract.get("security_id") or ""),
                "chart_contract": deepcopy(dict(chart_contract)),
                "lot_size": candle.get("lot_size"),
            })
        return result

    @staticmethod
    def _valid_history_candle(candle: Any) -> bool:
        return (
            isinstance(candle, Mapping)
            and (candle.get("closed") is True or candle.get("is_closed") is True)
            and candle.get("volume") is not None
            and all(candle.get(key) is not None for key in ("timestamp", "open", "high", "low", "close"))
        )

    @staticmethod
    def _aware(value: Any) -> datetime:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    @staticmethod
    def _unavailable(reason: str, *, timestamp: str | None = None, readiness: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        data_readiness = deepcopy(dict(readiness)) if isinstance(readiness, Mapping) else {}
        data_readiness.update({
            "DATA_READY": False,
            "not_ready_reason": reason,
        })
        return {
            "closed": False,
            "is_closed": False,
            "source_health": "UNAVAILABLE",
            "source_reason": reason,
            "source_timestamp": timestamp,
            "data_readiness": data_readiness,
        }

    def _argus_is_fresh(self, argus: Mapping[str, Any], now: datetime) -> bool:
        if str(argus.get("status") or "").lower() in {"offline", "unavailable"}:
            return False
        data = argus.get("data")
        underlying = data.get("underlying") if isinstance(data, Mapping) else None
        if not isinstance(underlying, Mapping):
            return False
        market_state = str(underlying.get("market_state") or "").upper()
        if market_state and market_state != "OPEN":
            return False
        if not market_state and str(argus.get("status") or "").lower() != "available":
            return False
        try:
            fetched_at = self._aware(underlying["fetched_at"])
        except (KeyError, TypeError, ValueError):
            return False
        age = (now - fetched_at).total_seconds()
        if 0.0 <= age <= self.max_age_seconds:
            return True
        if str(argus.get("status") or "").lower() == "stale":
            return False
        if str(argus.get("freshness") or "").lower() == "stale":
            return False
        return False


def deployment_held_security_id_provider(service: Any, deployment_id: str) -> Callable[[], str | None]:
    """Return a lazy, deployment-scoped held-security-ID provider.

    Looks up the running StrategyRuntime for *deployment_id* in *service*
    at call time (never at construction time), reads its paper-engine
    projection and returns the ``held_security_id`` of the single open
    position, or ``None`` when:
    - no runtime is loaded yet,
    - no open position exists,
    - more than one open position exists (ambiguous — safer to block),
    - the projection raises any exception.

    The provider never returns an ATM/current-selected contract or the
    index instrument security ID.  It exclusively reflects what the paper
    engine already stamped as ``held_security_id`` at fill time.
    """

    def _provider() -> str | None:
        try:
            runtimes: dict[str, Any] = getattr(service, "_runtimes", {})
            runtime = runtimes.get(deployment_id)
            if runtime is None:
                return None
            projection_fn = getattr(getattr(runtime, "execution", None), "projection", None)
            if not callable(projection_fn):
                return None
            state = projection_fn()
            open_positions = [
                row for row in (state.get("positions") or [])
                if str(row.get("status") or "").upper() == "OPEN"
            ]
            if len(open_positions) != 1:
                return None
            held = str(open_positions[0].get("held_security_id") or "").strip()
            return held if held else None
        except Exception:
            return None

    return _provider
