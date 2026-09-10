"""
CitadelOS FVG Engine V1

Detects simple 3-candle Fair Value Gaps:
- Bullish FVG: candle 1 high < candle 3 low
- Bearish FVG: candle 1 low > candle 3 high

This is V1 working logic.
V2 will add mitigation, strength, volume, ATR filtering, and premium/discount context.
"""


class FVGEngine:

    def analyze(self, candles, lookback=50):
        if not candles or len(candles) < 3:
            return self._empty("Not enough candles")

        recent = candles[-lookback:] if len(candles) >= lookback else candles

        fvgs = []

        for i in range(2, len(recent)):
            c1 = recent[i - 2]
            c2 = recent[i - 1]
            c3 = recent[i]

            c1_high = float(c1["high"])
            c1_low = float(c1["low"])
            c3_high = float(c3["high"])
            c3_low = float(c3["low"])
            c3_close = float(c3["close"])

            # Bullish FVG
            if c1_high < c3_low:
                gap_low = c1_high
                gap_high = c3_low
                filled = c3_close <= gap_low

                fvgs.append({
                    "type": "BULLISH_FVG",
                    "bias": "BULLISH",
                    "gap_low": round(gap_low, 2),
                    "gap_high": round(gap_high, 2),
                    "size": round(gap_high - gap_low, 2),
                    "filled": filled,
                    "index": i,
                })

            # Bearish FVG
            if c1_low > c3_high:
                gap_low = c3_high
                gap_high = c1_low
                filled = c3_close >= gap_high

                fvgs.append({
                    "type": "BEARISH_FVG",
                    "bias": "BEARISH",
                    "gap_low": round(gap_low, 2),
                    "gap_high": round(gap_high, 2),
                    "size": round(gap_high - gap_low, 2),
                    "filled": filled,
                    "index": i,
                })

        if not fvgs:
            return self._empty("No FVG detected")

        latest = fvgs[-1]

        score = 70
        if not latest["filled"]:
            score = 80

        return {
            "bias": latest["bias"],
            "type": latest["type"],
            "score": score,
            "gap_low": latest["gap_low"],
            "gap_high": latest["gap_high"],
            "size": latest["size"],
            "filled": latest["filled"],
            "total_fvgs": len(fvgs),
            "reason": f"Latest {latest['type']} detected",
        }

    def _empty(self, reason):
        return {
            "bias": "NEUTRAL",
            "type": "NONE",
            "score": 0,
            "gap_low": None,
            "gap_high": None,
            "size": 0,
            "filled": None,
            "total_fvgs": 0,
            "reason": reason,
        }