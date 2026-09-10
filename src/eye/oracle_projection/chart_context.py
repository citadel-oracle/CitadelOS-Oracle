"""TradingView Chart Context & Epoch Manager for Eye Oracle Projection."""

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Mapping, Optional

from src.eye.oracle_projection.contracts import EyeChartContext, ChartIdentityStatus


SUPPORTED_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
SUPPORTED_TIMEFRAMES = {"1m", "3m", "5m", "15m", "1h", "4h", "1d"}


class ChartContextManager:
    """Manages active chart context and identity epoch transitions."""

    def __init__(self):
        self._lock = Lock()
        self._current_symbol: Optional[str] = None
        self._current_timeframe: Optional[str] = None
        self._current_identity: Optional[str] = None
        self._current_epoch: int = 0
        self._active_context: Optional[EyeChartContext] = None

    def active_context(
        self,
        *,
        underlying: str,
        timeframe: str,
    ) -> Optional[EyeChartContext]:
        """Return the current canonical chart identity without re-resolving it.

        An exact-option identity is an operator selection.  A projection read
        for its underlying must retain that selection rather than collapsing it
        into a generic index context.
        """
        normalized_underlying = str(underlying or "").strip().upper()
        normalized_timeframe = str(timeframe or "").strip().lower()
        with self._lock:
            active = self._active_context
            if (
                active is not None
                and active.underlying == normalized_underlying
                and active.chart_timeframe == normalized_timeframe
            ):
                return active
        return None

    def resolve_tradingview_context(self, chart_state: Mapping[str, Any]) -> EyeChartContext:
        """Resolve an already-authenticated TradingView identity without market I/O."""
        symbol = chart_state.get("symbol") if isinstance(chart_state.get("symbol"), Mapping) else {}
        instrument = chart_state.get("instrument") if isinstance(chart_state.get("instrument"), Mapping) else {}
        option = chart_state.get("option") if isinstance(chart_state.get("option"), Mapping) else None
        normalized = str(symbol.get("normalized_symbol") or symbol.get("raw_symbol") or "").strip().upper()
        timeframe = str(chart_state.get("timeframe") or "").strip().lower()
        route = str(symbol.get("route") or instrument.get("route") or "").upper()
        if route == "EXACT_OPTION":
            if not option or not option.get("security_id") or str(option.get("option_side") or "").upper() not in {"CE", "PE"}:
                return self._unresolved(normalized, timeframe, "TRADINGVIEW_EXACT_OPTION_UNRESOLVED")
            identity = ":".join(("NSE", str(option.get("underlying") or normalized), str(option.get("expiry")), str(option.get("strike")), str(option.get("option_side")).upper(), timeframe))
            return self._activate(normalized, timeframe, identity, f"DHAN:OPTION:{option['security_id']}", underlying=str(option.get("underlying") or normalized).upper())
        return self.resolve_context(normalized, timeframe)

    def resolve_context(self, symbol: str, timeframe: str) -> EyeChartContext:
        normalized_symbol = str(symbol).strip().upper()
        normalized_tf = str(timeframe).strip().lower()

        with self._lock:
            if normalized_symbol not in SUPPORTED_SYMBOLS:
                return EyeChartContext(
                    normalized_symbol=normalized_symbol,
                    exchange="NSE",
                    underlying=normalized_symbol,
                    chart_timeframe=normalized_tf,
                    tradingview_identity=f"NSE:{normalized_symbol}",
                    identity_epoch=self._current_epoch,
                    resolved_market_data_identity="UNRESOLVED",
                    resolved_at_utc=datetime.now(timezone.utc).isoformat(),
                    source="TRADINGVIEW_CONTEXT",
                    status=ChartIdentityStatus.UNSUPPORTED_INSTRUMENT,
                )

            return self._activate_locked(normalized_symbol, normalized_tf, f"NSE:{normalized_symbol}:{normalized_tf}", f"DHAN:INDEX:{normalized_symbol}")

    def _unresolved(self, symbol: str, timeframe: str, identity: str) -> EyeChartContext:
        return EyeChartContext(normalized_symbol=symbol or "UNKNOWN", exchange="NSE", underlying=symbol or "UNKNOWN", chart_timeframe=timeframe, tradingview_identity=identity, identity_epoch=self._current_epoch, resolved_market_data_identity="UNRESOLVED", resolved_at_utc=datetime.now(timezone.utc).isoformat(), source="TRADINGVIEW_CONTEXT", status=ChartIdentityStatus.IDENTITY_UNRESOLVED)

    def _activate(self, symbol: str, timeframe: str, identity: str, resolved: str, *, underlying: Optional[str] = None) -> EyeChartContext:
        with self._lock:
            return self._activate_locked(symbol, timeframe, identity, resolved, underlying=underlying)

    def _activate_locked(self, symbol: str, timeframe: str, identity: str, resolved: str, *, underlying: Optional[str] = None) -> EyeChartContext:
        if identity != self._current_identity or timeframe != self._current_timeframe:
            self._current_symbol = symbol
            self._current_timeframe = timeframe
            self._current_identity = identity
            self._current_epoch += 1
        self._active_context = EyeChartContext(normalized_symbol=symbol, exchange="NSE", underlying=underlying or symbol, chart_timeframe=timeframe, tradingview_identity=identity, identity_epoch=self._current_epoch, resolved_market_data_identity=resolved, resolved_at_utc=datetime.now(timezone.utc).isoformat(), source="TRADINGVIEW_CONTEXT", status=ChartIdentityStatus.ACTIVE)
        return self._active_context
