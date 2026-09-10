"""
CitadelOS Liquidity Engine V1

Detects:
- Equal Highs
- Equal Lows
- Bullish Liquidity Sweep
- Bearish Liquidity Sweep
"""

class LiquidityEngine:

    def analyze(self, candles, lookback=30, tolerance=0.001):
        if not candles or len(candles) < 10:
            return self._empty("Not enough candles")

        recent = candles[-lookback:] if len(candles) >= lookback else candles

        highs = [float(c["high"]) for c in recent]
        lows = [float(c["low"]) for c in recent]
        closes = [float(c["close"]) for c in recent]

        last_high = highs[-1]
        last_low = lows[-1]
        last_close = closes[-1]

        previous_highs = highs[:-1]
        previous_lows = lows[:-1]

        equal_high_level = self._find_equal_level(previous_highs, tolerance)
        equal_low_level = self._find_equal_level(previous_lows, tolerance)

        bearish_sweep = False
        bullish_sweep = False

        if equal_high_level:
            if last_high > equal_high_level and last_close < equal_high_level:
                bearish_sweep = True

        if equal_low_level:
            if last_low < equal_low_level and last_close > equal_low_level:
                bullish_sweep = True

        if bullish_sweep:
            return {
                "bias": "BULLISH",
                "type": "BULLISH_SWEEP",
                "score": 85,
                "equal_high": equal_high_level,
                "equal_low": equal_low_level,
                "reason": "Price swept equal lows and closed back above liquidity",
            }

        if bearish_sweep:
            return {
                "bias": "BEARISH",
                "type": "BEARISH_SWEEP",
                "score": 85,
                "equal_high": equal_high_level,
                "equal_low": equal_low_level,
                "reason": "Price swept equal highs and closed back below liquidity",
            }

        if equal_high_level and equal_low_level:
            return {
                "bias": "NEUTRAL",
                "type": "RANGE_LIQUIDITY",
                "score": 50,
                "equal_high": equal_high_level,
                "equal_low": equal_low_level,
                "reason": "Equal highs and equal lows detected",
            }

        if equal_high_level:
            return {
                "bias": "BEARISH",
                "type": "EQUAL_HIGHS",
                "score": 55,
                "equal_high": equal_high_level,
                "equal_low": equal_low_level,
                "reason": "Equal highs detected; buy-side liquidity above",
            }

        if equal_low_level:
            return {
                "bias": "BULLISH",
                "type": "EQUAL_LOWS",
                "score": 55,
                "equal_high": equal_high_level,
                "equal_low": equal_low_level,
                "reason": "Equal lows detected; sell-side liquidity below",
            }

        return self._empty("No clear liquidity pool detected")

    def _find_equal_level(self, values, tolerance):
        if len(values) < 3:
            return None

        rounded = []

        for value in values:
            rounded.append(round(value, 2))

        for i in range(len(rounded)):
            level = rounded[i]
            matches = 0

            for j in range(len(rounded)):
                if i == j:
                    continue

                diff = abs(rounded[j] - level)
                allowed = max(level * tolerance, 1)

                if diff <= allowed:
                    matches += 1

            if matches >= 1:
                return level

        return None

    def _empty(self, reason):
        return {
            "bias": "NEUTRAL",
            "type": "NONE",
            "score": 0,
            "equal_high": None,
            "equal_low": None,
            "reason": reason,
        }