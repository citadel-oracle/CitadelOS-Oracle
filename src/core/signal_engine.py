"""
CitadelOS Signal Engine
Stateful EMA + RSI live paper strategy.
"""

class SignalEngine:
    def __init__(self):
        self.position_state = "FLAT"

    def check(self, indicators, candle=None):
        ema_21 = indicators.get("ema_21")
        ema_38 = indicators.get("ema_38")
        rsi_14 = indicators.get("rsi_14")

        if ema_21 is None or ema_38 is None or rsi_14 is None:
            return {
                "signal": "NO TRADE",
                "reason": "Not enough candle history",
                "confidence": 0,
                "entry": None,
                "sl": None,
                "target": None,
            }

        bullish = ema_21 > ema_38 and rsi_14 > 55
        bearish = ema_21 < ema_38 and rsi_14 < 45

        if bullish and self.position_state != "LONG":
            self.position_state = "LONG"
            return {
                "signal": "BUY",
                "reason": "New bullish regime: EMA21 > EMA38 and RSI > 55",
                "confidence": 70,
                "entry": candle.get("close") if isinstance(candle, dict) else None,
                "sl": None,
                "target": None,
            }

        if bearish and self.position_state != "SHORT":
            self.position_state = "SHORT"
            return {
                "signal": "SELL",
                "reason": "New bearish regime: EMA21 < EMA38 and RSI < 45",
                "confidence": 70,
                "entry": candle.get("close") if isinstance(candle, dict) else None,
                "sl": None,
                "target": None,
            }

        if self.position_state == "LONG":
            reason = "Already LONG; waiting for bearish reversal"
        elif self.position_state == "SHORT":
            reason = "Already SHORT; waiting for bullish reversal"
        else:
            reason = "EMA/RSI conditions not aligned"

        return {
            "signal": "NO TRADE",
            "reason": reason,
            "confidence": 0,
            "entry": None,
            "sl": None,
            "target": None,
        }

    def generate(self, indicators, candle=None):
        return self.check(indicators, candle)


def print_signal(signal):
    print("\n📡 Signal")
    print(f"Decision   : {signal.get('signal')}")
    print(f"Reason     : {signal.get('reason')}")
    print(f"Confidence : {signal.get('confidence')}%")
    print(f"Entry      : {signal.get('entry')}")
    print(f"SL         : {signal.get('sl')}")
    print(f"Target     : {signal.get('target')}")