"""
CitadelOS Structure Engine V2

Detects:
- Swing highs / swing lows
- BOS: Break of Structure
- CHOCH: Change of Character

Adaptive version for live intraday data.
"""


class StructureEngineV2:

    def analyze(self, candles, swing_window=2, lookback=60):
        if not candles or len(candles) < 12:
            return self._empty("Not enough candles")

        recent = candles[-lookback:] if len(candles) >= lookback else candles

        if len(recent) < swing_window * 2 + 5:
            return self._empty("Not enough candles for swing detection")

        swings = self._detect_swings(recent, swing_window)

        swing_highs = swings["swing_highs"]
        swing_lows = swings["swing_lows"]

        last_close = float(recent[-1]["close"])

        if len(swing_highs) < 1 or len(swing_lows) < 1:
            return {
                "structure": "RANGE",
                "bias": "NEUTRAL",
                "score": 30,
                "bos": "NONE",
                "choch": "NONE",
                "last_close": last_close,
                "last_swing_high": None,
                "previous_swing_high": None,
                "last_swing_low": None,
                "previous_swing_low": None,
                "swing_high_count": len(swing_highs),
                "swing_low_count": len(swing_lows),
                "reason": "Not enough swing points; range/early session",
            }

        last_high = swing_highs[-1]
        prev_high = swing_highs[-2] if len(swing_highs) >= 2 else None

        last_low = swing_lows[-1]
        prev_low = swing_lows[-2] if len(swing_lows) >= 2 else None

        bias = "NEUTRAL"
        structure = "RANGE"
        bos = "NONE"
        choch = "NONE"
        score = 40
        reason = "Mixed swing structure"

        if prev_high and prev_low:
            higher_high = last_high["price"] > prev_high["price"]
            higher_low = last_low["price"] > prev_low["price"]

            lower_high = last_high["price"] < prev_high["price"]
            lower_low = last_low["price"] < prev_low["price"]

            if higher_high and higher_low:
                bias = "BULLISH"
                structure = "BULLISH_STRUCTURE"
                score = 75
                reason = "Swing structure making higher high and higher low"

            elif lower_high and lower_low:
                bias = "BEARISH"
                structure = "BEARISH_STRUCTURE"
                score = 75
                reason = "Swing structure making lower high and lower low"
        else:
            higher_high = False
            higher_low = False
            lower_high = False
            lower_low = False
            reason = "Only one swing high/low detected"

        if last_close > last_high["price"]:
            bos = "BULLISH_BOS"
            bias = "BULLISH"
            structure = "BULLISH_BREAKOUT"
            score = 90
            reason = "Close broke above last swing high"

            if lower_high or lower_low:
                choch = "BULLISH_CHOCH"
                reason = "Bullish CHOCH: close broke above bearish swing high"

        elif last_close < last_low["price"]:
            bos = "BEARISH_BOS"
            bias = "BEARISH"
            structure = "BEARISH_BREAKDOWN"
            score = 90
            reason = "Close broke below last swing low"

            if higher_high or higher_low:
                choch = "BEARISH_CHOCH"
                reason = "Bearish CHOCH: close broke below bullish swing low"

        return {
            "structure": structure,
            "bias": bias,
            "score": score,
            "bos": bos,
            "choch": choch,
            "last_close": last_close,
            "last_swing_high": last_high,
            "previous_swing_high": prev_high,
            "last_swing_low": last_low,
            "previous_swing_low": prev_low,
            "swing_high_count": len(swing_highs),
            "swing_low_count": len(swing_lows),
            "reason": reason,
        }

    def _detect_swings(self, candles, window):
        swing_highs = []
        swing_lows = []

        for i in range(window, len(candles) - window):
            current_high = float(candles[i]["high"])
            current_low = float(candles[i]["low"])

            left = candles[i - window:i]
            right = candles[i + 1:i + window + 1]

            left_highs = [float(c["high"]) for c in left]
            right_highs = [float(c["high"]) for c in right]

            left_lows = [float(c["low"]) for c in left]
            right_lows = [float(c["low"]) for c in right]

            if current_high >= max(left_highs) and current_high >= max(right_highs):
                swing_highs.append({
                    "index": i,
                    "price": round(current_high, 2),
                })

            if current_low <= min(left_lows) and current_low <= min(right_lows):
                swing_lows.append({
                    "index": i,
                    "price": round(current_low, 2),
                })

        return {
            "swing_highs": swing_highs,
            "swing_lows": swing_lows,
        }

    def _empty(self, reason):
        return {
            "structure": "UNKNOWN",
            "bias": "NEUTRAL",
            "score": 0,
            "bos": "NONE",
            "choch": "NONE",
            "last_close": None,
            "last_swing_high": None,
            "previous_swing_high": None,
            "last_swing_low": None,
            "previous_swing_low": None,
            "swing_high_count": 0,
            "swing_low_count": 0,
            "reason": reason,
        }