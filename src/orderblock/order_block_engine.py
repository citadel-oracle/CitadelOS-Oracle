"""
CitadelOS Order Block Engine V1

Detects simple order blocks:
- Bullish OB: last bearish candle before strong bullish move
- Bearish OB: last bullish candle before strong bearish move

V1 working logic.
V2 will add mitigation, freshness, displacement strength, volume, and structure confirmation.
"""


class OrderBlockEngine:

    def analyze(self, candles, lookback=60):
        if not candles or len(candles) < 10:
            return self._empty("Not enough candles")

        recent = candles[-lookback:] if len(candles) >= lookback else candles

        bullish_ob = None
        bearish_ob = None

        for i in range(2, len(recent)):
            prev = recent[i - 1]
            curr = recent[i]

            prev_open = float(prev["open"])
            prev_close = float(prev["close"])
            prev_high = float(prev["high"])
            prev_low = float(prev["low"])

            curr_open = float(curr["open"])
            curr_close = float(curr["close"])
            curr_high = float(curr["high"])
            curr_low = float(curr["low"])

            curr_body = abs(curr_close - curr_open)
            curr_range = max(curr_high - curr_low, 1)

            displacement = curr_body / curr_range

            # Bullish OB: bearish candle followed by strong bullish displacement
            if prev_close < prev_open and curr_close > curr_open and displacement >= 0.6:
                bullish_ob = {
                    "type": "BULLISH_OB",
                    "bias": "BULLISH",
                    "low": round(prev_low, 2),
                    "high": round(prev_high, 2),
                    "score": 75,
                    "fresh": True,
                    "reason": "Bearish candle before bullish displacement",
                }

            # Bearish OB: bullish candle followed by strong bearish displacement
            if prev_close > prev_open and curr_close < curr_open and displacement >= 0.6:
                bearish_ob = {
                    "type": "BEARISH_OB",
                    "bias": "BEARISH",
                    "low": round(prev_low, 2),
                    "high": round(prev_high, 2),
                    "score": 75,
                    "fresh": True,
                    "reason": "Bullish candle before bearish displacement",
                }

        latest_close = float(recent[-1]["close"])

        if bullish_ob:
            if bullish_ob["low"] <= latest_close <= bullish_ob["high"]:
                bullish_ob["score"] = 85
                bullish_ob["reason"] += " + price inside OB"

        if bearish_ob:
            if bearish_ob["low"] <= latest_close <= bearish_ob["high"]:
                bearish_ob["score"] = 85
                bearish_ob["reason"] += " + price inside OB"

        if bullish_ob and bearish_ob:
            # Pick the block closer to current price
            bull_mid = (bullish_ob["low"] + bullish_ob["high"]) / 2
            bear_mid = (bearish_ob["low"] + bearish_ob["high"]) / 2

            if abs(latest_close - bull_mid) <= abs(latest_close - bear_mid):
                return bullish_ob
            return bearish_ob

        if bullish_ob:
            return bullish_ob

        if bearish_ob:
            return bearish_ob

        return self._empty("No order block detected")

    def _empty(self, reason):
        return {
            "type": "NONE",
            "bias": "NEUTRAL",
            "low": None,
            "high": None,
            "score": 0,
            "fresh": False,
            "reason": reason,
        }