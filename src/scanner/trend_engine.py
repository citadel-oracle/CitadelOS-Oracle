"""
CitadelOS Trend Engine V1
Converts indicators into market trend + signal.
"""


class TrendEngine:

    def analyze(self, indicators):
        ema21 = indicators.get("ema_21")
        ema38 = indicators.get("ema_38")
        rsi14 = indicators.get("rsi_14")
        close = indicators.get("close")
        vwap = indicators.get("vwap")

        if ema21 is None or ema38 is None or rsi14 is None:
            return {
                "trend": "UNKNOWN",
                "signal": "WAIT",
                "strength": 0,
                "reason": "Not enough indicator data",
            }

        bull = 0
        bear = 0
        reasons = []

        if ema21 > ema38:
            bull += 35
            reasons.append("EMA bullish")
        elif ema21 < ema38:
            bear += 35
            reasons.append("EMA bearish")

        if rsi14 >= 55:
            bull += 30
            reasons.append("RSI bullish")
        elif rsi14 <= 45:
            bear += 30
            reasons.append("RSI bearish")

        if close is not None and vwap is not None:
            if close >= vwap:
                bull += 20
                reasons.append("Price above/equal VWAP")
            else:
                bear += 20
                reasons.append("Price below VWAP")

        if bull >= 60 and bull > bear:
            return {
                "trend": "BULLISH",
                "signal": "BUY",
                "strength": min(bull, 100),
                "reason": ", ".join(reasons),
            }

        if bear >= 60 and bear > bull:
            return {
                "trend": "BEARISH",
                "signal": "SELL",
                "strength": min(bear, 100),
                "reason": ", ".join(reasons),
            }

        return {
            "trend": "SIDEWAYS",
            "signal": "WAIT",
            "strength": max(bull, bear),
            "reason": ", ".join(reasons) if reasons else "No alignment",
        }