from datetime import time
from src.strategies.base_strategy import BaseStrategy


class SimplePullbackStrategy(BaseStrategy):

    def name(self):
        return "Simple Pullback"

    def config(self):
        return {
            "mode": "INTRADAY",
            "allow_overnight": False,
            "auto_square_off": True,
            "last_entry_time": time(15, 15),
            "square_off_time": time(15, 28),
        }

    def generate(self, context):
        indicators = context.indicators

        close = indicators.get("close")
        ema21 = indicators.get("ema_21")
        ema38 = indicators.get("ema_38")

        if close is None or ema21 is None or ema38 is None:
            return self.wait("Missing indicator data")

        if context.kronos.get("bias") == "BULLISH":
            if close > ema21 > ema38:
                risk = abs(close - ema21)

                if risk <= 0:
                    return self.wait("Invalid risk")

                return {
                    "signal": "BUY",
                    "confidence": context.confidence,
                    "entry": round(close, 2),
                    "sl": round(ema21, 2),
                    "target": round(close + risk * 2, 2),
                    "reason": "Simple Pullback: bullish Kronos + close above EMA21/EMA38",
                    "strategy": self.name(),
                }

        if context.kronos.get("bias") == "BEARISH":
            if close < ema21 < ema38:
                risk = abs(ema21 - close)

                if risk <= 0:
                    return self.wait("Invalid risk")

                return {
                    "signal": "SELL",
                    "confidence": context.confidence,
                    "entry": round(close, 2),
                    "sl": round(ema21, 2),
                    "target": round(close - risk * 2, 2),
                    "reason": "Simple Pullback: bearish Kronos + close below EMA21/EMA38",
                    "strategy": self.name(),
                }

        return self.wait("No simple pullback setup")

    def wait(self, reason):
        return {
            "signal": "WAIT",
            "confidence": 0,
            "entry": None,
            "sl": None,
            "target": None,
            "reason": reason,
            "strategy": self.name(),
        }