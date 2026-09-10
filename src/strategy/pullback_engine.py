"""
CitadelOS Pullback Engine V1

Goal:
- Take trades only when Kronos allows.
- Use simple EMA + VWAP + RSI pullback logic.
- This is not final Pullback V3 yet.
"""


class PullbackEngine:

    def generate(self, indicators, kronos):
        close = indicators.get("close")
        ema21 = indicators.get("ema_21")
        ema38 = indicators.get("ema_38")
        rsi14 = indicators.get("rsi_14")
        vwap = indicators.get("vwap")
        atr14 = indicators.get("atr_14")

        if close is None or ema21 is None or ema38 is None or rsi14 is None or vwap is None:
            return self._wait("Not enough indicator data")

        if not kronos.allow_trade:
            return self._wait(f"Kronos rejected: {kronos.reason}")

        atr = atr14 if atr14 and atr14 > 0 else 10
        near_ema21 = abs(close - ema21) <= atr * 0.8
        near_vwap = abs(close - vwap) <= atr * 1.2

        if kronos.bias == "BULLISH":
            trend_ok = ema21 > ema38
            rsi_ok = rsi14 >= 50
            pullback_ok = near_ema21 or near_vwap

            if trend_ok and rsi_ok and pullback_ok:
                sl = close - atr
                target = close + (atr * 2)

                return {
                    "signal": "BUY",
                    "reason": "Bullish Kronos + EMA trend + pullback near EMA/VWAP",
                    "confidence": kronos.confidence,
                    "entry": close,
                    "sl": round(sl, 2),
                    "target": round(target, 2),
                }

        if kronos.bias == "BEARISH":
            trend_ok = ema21 < ema38
            rsi_ok = rsi14 <= 50
            pullback_ok = near_ema21 or near_vwap

            if trend_ok and rsi_ok and pullback_ok:
                sl = close + atr
                target = close - (atr * 2)

                return {
                    "signal": "SELL",
                    "reason": "Bearish Kronos + EMA trend + pullback near EMA/VWAP",
                    "confidence": kronos.confidence,
                    "entry": close,
                    "sl": round(sl, 2),
                    "target": round(target, 2),
                }

        return self._wait("Pullback conditions not aligned")

    def _wait(self, reason):
        return {
            "signal": "WAIT",
            "reason": reason,
            "confidence": 0,
            "entry": None,
            "sl": None,
            "target": None,
        }