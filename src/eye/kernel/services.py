from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import collections

from src.eye.kernel.domain import MarketEvent, MarketEventType
from src.eye.personal_strategies.indicators import (
    compute_bollinger_bands, compute_rsi, compute_ema, compute_traditional_pivots
)

class BarService:
    """Canonical Bar Service. Aggregates 1m bars into higher timeframes without lookahead."""
    
    def __init__(self, bus):
        self.bus = bus
        # security_id -> timeframe -> list of completed bars
        self.history: Dict[str, Dict[int, List[Dict[str, float]]]] = collections.defaultdict(
            lambda: collections.defaultdict(list)
        )
        # security_id -> timeframe -> partial bar state
        self.partial_bars: Dict[str, Dict[int, Dict[str, float]]] = collections.defaultdict(
            lambda: collections.defaultdict(dict)
        )
        self._seen_1m: set[tuple[str, int]] = set()
        self.bus.subscribe(MarketEventType.TICK, self._on_tick)
        
    def _on_tick(self, event: MarketEvent):
        """Processes a 1m tick/bar and rolls up to higher timeframes."""
        bar = event.payload.get("bar")
        if not bar:
            return
            
        sec_id = event.security_id
        try:
            bar_time = int(bar["time"])
        except (KeyError, TypeError, ValueError):
            return
        dedup_key = (str(sec_id), bar_time)
        if dedup_key in self._seen_1m:
            return
        self._seen_1m.add(dedup_key)
        
        # Save the canonical source bar including its explicit contract and
        # bootstrap provenance.  Higher-timeframe bars inherit these fields so
        # routers cannot confuse a hydrated historical bar with live evidence.
        self.history[sec_id][1].append(dict(bar))
        
        # We need the bar's timestamp to do 09:15 anchoring.
        # Assuming bar['time'] is epoch timestamp of the bar's START.
        # NSE anchoring: 09:15 is the start. 
        # For simplicity, if we rely on fixed intervals since session open.
        self._aggregate(sec_id, 3, bar)
        self._aggregate(sec_id, 5, bar)
        self._aggregate(sec_id, 15, bar)

    def _aggregate(self, sec_id: str, tf_minutes: int, bar_1m: Dict[str, float]):
        """Deterministically aggregates a 1m bar into a larger timeframe."""
        # Standard NSE market open is 09:15 IST (03:45 UTC). 
        # A 1m bar at 09:15 starts at 03:45 UTC.
        # This naive aggregation just groups sequentially for now as an adapter stand-in.
        # In a real rigorous setup, it maps precisely to (ts - 03:45) % tf_minutes == 0
        
        ts = int(bar_1m["time"])
        # IST offset = +19800 seconds
        ist_ts = ts + 19800
        # Minutes since 00:00 IST
        minutes_since_midnight = (ist_ts % 86400) // 60
        # Market opens at 9:15 = 555 minutes
        market_minute = minutes_since_midnight - 555
        
        partial = self.partial_bars[sec_id][tf_minutes]
        
        if not partial:
            # Start new bar
            partial.update({
                "time": ts,
                "open": bar_1m["open"],
                "high": bar_1m["high"],
                "low": bar_1m["low"],
                "close": bar_1m["close"],
                "volume": bar_1m.get("volume", 0.0),
                "count": 1,
                "option_type": bar_1m.get("option_type"),
                "bootstrap": bool(bar_1m.get("bootstrap")),
                "source_timestamp": bar_1m.get("source_timestamp", ts),
                "ingest_timestamp": bar_1m.get("ingest_timestamp", ts),
            })
        else:
            # Update existing bar
            partial["time"] = ts  # Always update to latest bar's time
            partial["high"] = max(partial["high"], bar_1m["high"])
            partial["low"] = min(partial["low"], bar_1m["low"])
            partial["close"] = bar_1m["close"]
            partial["volume"] += bar_1m.get("volume", 0.0)
            partial["count"] += 1
            partial["bootstrap"] = bool(partial.get("bootstrap")) and bool(bar_1m.get("bootstrap"))
            partial["source_timestamp"] = bar_1m.get("source_timestamp", ts)
            partial["ingest_timestamp"] = bar_1m.get("ingest_timestamp", ts)
            
        # Check if the TF bar is complete.
        # E.g. at market_minute 2 (9:17), the 3rd 1m bar just arrived, so the 3m bar is complete.
        is_complete = ((market_minute + 1) % tf_minutes == 0)
        
        if is_complete:
            completed_bar = partial.copy()
            del completed_bar["count"]
            self.history[sec_id][tf_minutes].append(completed_bar)
            self.partial_bars[sec_id][tf_minutes].clear()
            
            # Emit event
            self.bus.publish(MarketEvent(
                event_id=f"BAR_{sec_id}_{tf_minutes}_{ts}",
                event_type=MarketEventType.BAR_CLOSED,
                source_timestamp=ts, # Use the close time
                ingest_timestamp=float(completed_bar.get("ingest_timestamp") or ts),
                security_id=sec_id,
                source="BarService",
                payload={"timeframe": tf_minutes, "bar": completed_bar, "completed": True}
            ))

    def get_bars(self, sec_id: str, tf_minutes: int, limit: int = 100) -> List[Dict[str, float]]:
        return self.history[sec_id][tf_minutes][-limit:]


class FeatureStore:
    """Caches deterministic technical features to prevent duplicated recalculations."""
    
    def __init__(self, bus, bar_service: BarService):
        self.bus = bus
        self.bar_service = bar_service
        self.cache: Dict[str, Any] = {}
        
    def _generate_key(self, sec_id: str, tf: int, feature: str, params: str) -> str:
        # We need bar count/length as part of revision to avoid staleness across ticks
        bars = self.bar_service.get_bars(sec_id, tf, limit=1)
        revision = len(self.bar_service.history.get(sec_id, {}).get(tf, []))
        # If there's an ongoing partial bar, incorporate its tick count for intra-bar feature uniqueness
        partial = self.bar_service.partial_bars.get(sec_id, {}).get(tf, {})
        if partial:
            revision = f"{revision}.{partial.get('count', 0)}"
            
        return f"{sec_id}:{tf}:{feature}:{params}:{revision}"
        
    def get_feature(self, sec_id: str, tf: int, feature: str, params: str) -> Optional[Any]:
        """Gets a feature, calculating and caching if necessary."""
        key = self._generate_key(sec_id, tf, feature, params)
        if key in self.cache:
            return self.cache[key]
            
        bars = self.bar_service.get_bars(sec_id, tf, limit=100) # Fetch sufficient bars
        if not bars:
            return None
            
        closes = [b["close"] for b in bars]
        val = None
        
        if feature == "BB20":
            res = compute_bollinger_bands(closes, period=20, num_std=2.0)
            val = res[-1] if res else None
        elif feature == "RSI14":
            res = compute_rsi(closes, period=14)
            val = res[-1] if res else None
        elif feature == "EMA15":
            res = compute_ema(closes, period=15)
            val = res[-1] if res else None
            
        self.cache[key] = val
        return val

    def set_prev_day_stats(self, sec_id: str, high: float, low: float, close: float):
        self.cache[f"{sec_id}:PREV_HIGH"] = high
        self.cache[f"{sec_id}:PREV_LOW"] = low
        self.cache[f"{sec_id}:PREV_CLOSE"] = close

    def get_prev_day_stats(self, sec_id: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        return (
            self.cache.get(f"{sec_id}:PREV_HIGH"),
            self.cache.get(f"{sec_id}:PREV_LOW"),
            self.cache.get(f"{sec_id}:PREV_CLOSE"),
        )


class OptionUniverseService:
    """Manages active options contracts and expiry resolution."""
    
    def __init__(self, bus):
        self.bus = bus
        self.current_spot = 0.0
        self.active_chain: List[Dict[str, Any]] = []
        self.master_rows: List[Dict[str, Any]] = []
        self.current_date: str = ""
        
    def set_current_date(self, date_str: str):
        self.current_date = date_str
        
    def update_spot(self, spot: float):
        self.current_spot = spot
        
    def update_chain(self, chain: List[Dict[str, Any]]):
        self.active_chain = chain
        
    def set_master_rows(self, rows: List[Dict[str, Any]]):
        self.master_rows = rows
        
    def get_atm_strike(self, spot: float, strike_step: float = 50.0) -> float:
        return round(spot / strike_step) * strike_step
        
    def get_nifty_weekly_expiry(self, session_date_str: str) -> str:
        """Choose the first actual listed NIFTY expiry on/after the session.

        The instrument master is authoritative; weekday arithmetic is not, as
        exchange expiry calendars move for holidays and policy changes.
        """
        if not session_date_str:
            return ""
        try:
            session = datetime.strptime(session_date_str, "%Y-%m-%d").date()
        except ValueError:
            return ""
        expiries = set()
        for row in self.master_rows:
            if str(row.get("UNDERLYING_SYMBOL") or "").upper() != "NIFTY":
                continue
            raw = row.get("SM_EXPIRY_DATE")
            if not raw:
                continue
            parsed = self._parse_expiry(str(raw))
            if parsed is not None and parsed >= session:
                expiries.add((parsed, str(raw)))
        if not expiries:
            return ""
        return min(expiries, key=lambda item: item[0])[1]

    @staticmethod
    def _parse_expiry(value: str):
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _resolve_sec_id(self, strike: float, opt_type: str, exp_date: str) -> Tuple[Optional[str], Optional[str]]:
        for r in self.master_rows:
            if r.get("UNDERLYING_SYMBOL") == "NIFTY" and r.get("SM_EXPIRY_DATE") == exp_date:
                if float(r.get("STRIKE_PRICE", 0)) == strike and r.get("OPTION_TYPE") == opt_type:
                    return r.get("SECURITY_ID"), r.get("SYMBOL_NAME")
        return None, None
        
    def resolve_contract(self, spot: float, opt_type: str, offset: int = 0) -> Optional[str]:
        """Resolves e.g. OTM1 CE or ITM1 PE dynamically using canonical logic."""
        if not self.master_rows or not self.current_date:
            return None
            
        atm = self.get_atm_strike(spot)
        target_strike = atm
        
        # Simple step math (Nifty = 50)
        if opt_type == "CE":
            target_strike += (offset * 50)
        else:
            target_strike -= (offset * 50)
            
        exp_date = self.get_nifty_weekly_expiry(self.current_date)
        sec_id, _ = self._resolve_sec_id(target_strike, opt_type, exp_date)
        return str(sec_id) if sec_id else None
