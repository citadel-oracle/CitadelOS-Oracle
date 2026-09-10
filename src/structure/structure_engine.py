"""
CitadelOS Market Structure Engine V1

Detects:
- Higher High / Higher Low
- Lower High / Lower Low
- Bullish / Bearish / Range structure
- Simple BOS signal
"""


class StructureEngine:

    def analyze(self, candles, lookback=50):
        if not candles or len(candles) < 10:
            return self._unknown("Not enough candle data")

        recent = candles[-lookback:] if len(candles) >= lookback else candles

        highs = [float(c["high"]) for c in recent]
        lows = [float(c["low"]) for c in recent]
        closes = [float(c["close"]) for c in recent]

        prev_high = max(highs[:-1])
        prev_low = min(lows[:-1])
        last_high = highs[-1]
        last_low = lows[-1]
        last_close = closes[-1]

        higher_high = last_high > prev_high
        lower_low = last_low < prev_low

        mid = len(recent) // 2

        first_half_high = max(highs[:mid])
        second_half_high = max(highs[mid:])

        first_half_low = min(lows[:mid])
        second_half_low = min(lows[mid:])

        making_higher_highs = second_half_high > first_half_high
        making_higher_lows = second_half_low > first_half_low

        making_lower_highs = second_half_high < first_half_high
        making_lower_lows = second_half_low < first_half_low

        if making_higher_highs and making_higher_lows:
            structure = "BULLISH"
            bias = "BULLISH"
            score = 80
            reason = "Higher highs and higher lows"

        elif making_lower_highs and making_lower_lows:
            structure = "BEARISH"
            bias = "BEARISH"
            score = 80
            reason = "Lower highs and lower lows"

        else:
            structure = "RANGE"
            bias = "NEUTRAL"
            score = 40
            reason = "Mixed highs/lows; range or transition"

        bos = "NONE"

        if higher_high and last_close > prev_high:
            bos = "BULLISH_BOS"
            structure = "BULLISH"
            bias = "BULLISH"
            score = max(score, 90)
            reason = "Bullish break of structure"

        elif lower_low and last_close < prev_low:
            bos = "BEARISH_BOS"
            structure = "BEARISH"
            bias = "BEARISH"
            score = max(score, 90)
            reason = "Bearish break of structure"

        return {
            "structure": structure,
            "bias": bias,
            "score": score,
            "bos": bos,
            "last_close": last_close,
            "previous_high": prev_high,
            "previous_low": prev_low,
            "reason": reason,
        }

    def _unknown(self, reason):
        return {
            "structure": "UNKNOWN",
            "bias": "NEUTRAL",
            "score": 0,
            "bos": "NONE",
            "last_close": None,
            "previous_high": None,
            "previous_low": None,
            "reason": reason,
        }