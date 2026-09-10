"""
CitadelOS Multi-Timeframe Engine V1

Purpose:
- Convert 1m candles into higher timeframes
- Analyze 15m trend, 5m setup, 1m trigger
"""

from src.scanner.indicator_builder import IndicatorBuilder
from src.kronos.kronos_engine import KronosEngine
from src.structure.structure_engine import StructureEngine
from src.data.data_engine import DataEngine


class TimeframeEngine:

    def __init__(self):
        self.indicator_builder = IndicatorBuilder()
        self.kronos = KronosEngine()
        self.structure_engine = StructureEngine()

    def build_timeframes(self, candles):
        return {
            "1m": candles[-500:] if candles else [],
            "5m": self._resample(candles, 5),
            "15m": self._resample(candles, 15),
        }

    def analyze(self, candles):
        timeframes = self.build_timeframes(candles)

        tf_results = {}

        for tf, tf_candles in timeframes.items():
            session_date = None
            if tf_candles:
                session_date = DataEngine.exchange_datetime(
                    tf_candles[-1]["time"]
                ).date()
            indicators = self.indicator_builder.build(
                tf_candles, session_date=session_date
            )
            structure = self.structure_engine.analyze(tf_candles)
            kronos = self.kronos.analyze(indicators, structure)

            tf_results[tf] = {
                "candles": tf_candles,
                "indicators": indicators,
                "structure": structure,
                "kronos": kronos,
            }

        return self._final_decision(tf_results)

    def _final_decision(self, tf_results):
        k15 = tf_results["15m"]["kronos"]
        k5 = tf_results["5m"]["kronos"]
        k1 = tf_results["1m"]["kronos"]

        bullish_votes = 0
        bearish_votes = 0
        reasons = []

        if k15.bias == "BULLISH":
            bullish_votes += 2
            reasons.append("15m bullish")
        elif k15.bias == "BEARISH":
            bearish_votes += 2
            reasons.append("15m bearish")

        if k5.bias == "BULLISH":
            bullish_votes += 1
            reasons.append("5m bullish")
        elif k5.bias == "BEARISH":
            bearish_votes += 1
            reasons.append("5m bearish")

        if k1.bias == "BULLISH":
            bullish_votes += 1
            reasons.append("1m bullish")
        elif k1.bias == "BEARISH":
            bearish_votes += 1
            reasons.append("1m bearish")

        if bullish_votes >= 3 and bullish_votes > bearish_votes:
            bias = "BULLISH"
            signal_mode = "LONG_ONLY"
            allow_trade = True
            confidence = min(100, 60 + bullish_votes * 10)

        elif bearish_votes >= 3 and bearish_votes > bullish_votes:
            bias = "BEARISH"
            signal_mode = "SHORT_ONLY"
            allow_trade = True
            confidence = min(100, 60 + bearish_votes * 10)

        else:
            bias = "NEUTRAL"
            signal_mode = "WAIT"
            allow_trade = False
            confidence = max(20, abs(bullish_votes - bearish_votes) * 20)

        return {
            "bias": bias,
            "mode": signal_mode,
            "allow_trade": allow_trade,
            "confidence": confidence,
            "bullish_votes": bullish_votes,
            "bearish_votes": bearish_votes,
            "reason": ", ".join(reasons) if reasons else "No timeframe alignment",
            "timeframes": tf_results,
        }

    def _resample(self, candles, interval):
        if not candles:
            return []

        buckets = {}
        for source in candles:
            try:
                bucket = DataEngine.bucket_timestamp(source.get("time"), interval)
                if bucket not in buckets:
                    raw_volume = source.get("volume")
                    buckets[bucket] = {
                        "time": bucket,
                        "open": float(source["open"]),
                        "high": float(source["high"]),
                        "low": float(source["low"]),
                        "close": float(source["close"]),
                        "volume": (
                            float(raw_volume)
                            if isinstance(raw_volume, (int, float))
                            else None
                        ),
                        "_source_ids": {int(source["time"])},
                    }
                    continue

                candle = buckets[bucket]
                candle["high"] = max(candle["high"], float(source["high"]))
                candle["low"] = min(candle["low"], float(source["low"]))
                candle["close"] = float(source["close"])
                raw_volume = source.get("volume")
                if (
                    candle["volume"] is None
                    or not isinstance(raw_volume, (int, float))
                ):
                    candle["volume"] = None
                else:
                    candle["volume"] += float(raw_volume)
                candle["_source_ids"].add(int(source["time"]))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue

        completed = []
        for bucket in sorted(buckets):
            candle = buckets[bucket]
            expected = {
                bucket + offset * 60
                for offset in range(interval)
            }
            if candle.pop("_source_ids") != expected:
                continue
            completed.append(candle)
        return completed[-500:]
