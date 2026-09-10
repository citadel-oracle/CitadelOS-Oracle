"""Session-Anchored 1m -> 3m/5m/15m Resampler with Zero Lookahead for CITADEL Eye."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class SessionResampler:
    """Aggregates 1m canonical bars into 3m, 5m, and 15m confirmed candles anchored at 09:15 IST."""

    @staticmethod
    def resample_1m_to_tf(
        bars_1m: List[Dict[str, Any]], timeframe_minutes: int = 3
    ) -> List[Dict[str, Any]]:
        if not bars_1m:
            return []

        aggregated_bars: List[Dict[str, Any]] = []
        current_bucket: Optional[Dict[str, Any]] = None
        current_bucket_index: Optional[int] = None

        for bar in bars_1m:
            dt_str = bar.get("timestamp") or bar.get("time") or "09:15:00"
            # Parse minute
            try:
                if ":" in dt_str:
                    parts = dt_str.split(":")
                    mins_since_open = (int(parts[0]) * 60 + int(parts[1])) - (9 * 60 + 15)
                else:
                    mins_since_open = 0
            except Exception:
                mins_since_open = 0

            bucket_idx = max(0, mins_since_open // timeframe_minutes)

            if current_bucket_index is None or bucket_idx != current_bucket_index:
                if current_bucket is not None:
                    current_bucket["is_confirmed"] = True
                    aggregated_bars.append(current_bucket)

                current_bucket_index = bucket_idx
                current_bucket = {
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar.get("volume", 0),
                    "timestamp": dt_str,
                    "is_confirmed": False,
                    "count": 1,
                }
            else:
                current_bucket["high"] = max(current_bucket["high"], bar["high"])
                current_bucket["low"] = min(current_bucket["low"], bar["low"])
                current_bucket["close"] = bar["close"]
                current_bucket["volume"] += bar.get("volume", 0)
                current_bucket["count"] += 1

        # Final bar is confirmed if it has timeframe_minutes constituent bars
        if current_bucket:
            if current_bucket["count"] >= timeframe_minutes:
                current_bucket["is_confirmed"] = True
                aggregated_bars.append(current_bucket)

        return aggregated_bars
