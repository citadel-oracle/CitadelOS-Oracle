"""Session-anchored resampling engine for Spot, Futures, and Option completed candles."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Mapping, Optional

IST = ZoneInfo("Asia/Kolkata")

class OracleDevDataStreamAggregator:
    """Aggregates 1m completed candles into session-anchored 3m and 5m completed candles."""

    def __init__(self, clock=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def session_open_time(date_val: datetime.date) -> datetime:
        """Get the exchange open time (09:15:00 IST) for a given date."""
        return datetime.combine(date_val, datetime.min.time()).replace(tzinfo=IST) + timedelta(hours=9, minutes=15)

    @classmethod
    def get_bucket_start(cls, candle_time: datetime, interval_minutes: int) -> datetime:
        """Calculate the session-anchored start time for a candle in the given interval."""
        # Convert candle time to IST
        tz_candle = candle_time.astimezone(IST)
        session_open = cls.session_open_time(tz_candle.date())
        
        if tz_candle < session_open:
            # Pre-market candle, anchor to session start
            return session_open

        elapsed_seconds = int((tz_candle - session_open).total_seconds())
        elapsed_minutes = elapsed_seconds // 60
        
        bucket_elapsed_minutes = (elapsed_minutes // interval_minutes) * interval_minutes
        return session_open + timedelta(minutes=bucket_elapsed_minutes)

    def resample(
        self,
        candles_1m: List[Dict[str, Any]],
        interval_minutes: int,
        now_dt: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Resample a list of 1m completed candles into completed interval_minutes candles."""
        if not candles_1m:
            return []
        
        if interval_minutes == 1:
            return [dict(c) for c in candles_1m]

        reference = now_dt or self.clock()
        reference_ist = reference.astimezone(IST)

        # Group 1m candles by their bucket start time
        buckets: Dict[int, List[Dict[str, Any]]] = {}
        for c in candles_1m:
            # Parse candle time (can be epoch timestamp or datetime)
            t_val = c.get("time") or c.get("timestamp")
            if isinstance(t_val, (int, float)):
                c_time = datetime.fromtimestamp(t_val, tz=IST)
            elif isinstance(t_val, str):
                c_time = datetime.fromisoformat(t_val.replace("Z", "+00:00")).astimezone(IST)
            elif isinstance(t_val, datetime):
                c_time = t_val.astimezone(IST)
            else:
                continue

            b_start = self.get_bucket_start(c_time, interval_minutes)
            b_key = int(b_start.timestamp())
            buckets.setdefault(b_key, []).append((c_time, c))

        resampled = []
        for b_key in sorted(buckets.keys()):
            # Sort the constituent candles chronologically
            candles_in_bucket = sorted(buckets[b_key], key=lambda x: x[0])
            b_start_dt = datetime.fromtimestamp(b_key, tz=IST)
            b_end_dt = b_start_dt + timedelta(minutes=interval_minutes)

            # A resampled candle is only completed if the current time is >= the bucket's end time
            if reference_ist >= b_end_dt:
                # Aggregate OHLCV
                c_list = [item[1] for item in candles_in_bucket]
                
                opens = [float(c["open"]) for c in c_list]
                highs = [float(c["high"]) for c in c_list]
                lows = [float(c["low"]) for c in c_list]
                closes = [float(c["close"]) for c in c_list]
                
                vol_sum = 0.0
                has_vol = False
                for c in c_list:
                    v = c.get("volume")
                    if v is not None:
                        vol_sum += float(v)
                        has_vol = True

                oi_val = None
                for c in reversed(c_list):
                    v = c.get("oi")
                    if v is not None:
                        oi_val = int(v)
                        break

                res_candle = {
                    "time": b_key,
                    "open": opens[0],
                    "high": max(highs),
                    "low": min(lows),
                    "close": closes[-1],
                    "volume": vol_sum if has_vol else None,
                    "authoritative": True,
                    "source": "ORACLE_DEV_RESAMPLED",
                    "input_candles_count": len(c_list)
                }
                if oi_val is not None:
                    res_candle["oi"] = oi_val
                resampled.append(res_candle)

        return resampled
