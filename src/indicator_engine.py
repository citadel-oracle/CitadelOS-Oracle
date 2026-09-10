"""
CitadelOS Indicator Engine
Calculates EMA, RSI, ATR, VWAP approximation, and Supertrend.
"""


class IndicatorEngine:

    def ema(self, values, period):
        if len(values) < period:
            return None

        multiplier = 2 / (period + 1)
        ema_value = sum(values[:period]) / period

        for price in values[period:]:
            ema_value = (price - ema_value) * multiplier + ema_value

        return round(ema_value, 2)

    def rsi(self, closes, period=14):
        if len(closes) <= period:
            return None

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    def atr(self, candles, period=14):
        if len(candles) <= period:
            return None

        true_ranges = []

        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_close = candles[i - 1]["close"]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )

            true_ranges.append(tr)

        return round(sum(true_ranges[-period:]) / period, 2)

    def vwap(self, candles):
        if not candles:
            return None

        total_price = 0

        for candle in candles:
            typical_price = (
                candle["high"] + candle["low"] + candle["close"]
            ) / 3
            total_price += typical_price

        return round(total_price / len(candles), 2)

    def supertrend(self, candles, period=10, multiplier=3):
        if len(candles) <= period:
            return None

        atr_value = self.atr(candles, period)

        if atr_value is None:
            return None

        latest = candles[-1]

        hl2 = (latest["high"] + latest["low"]) / 2

        upper_band = hl2 + (multiplier * atr_value)
        lower_band = hl2 - (multiplier * atr_value)

        close = latest["close"]

        if close > upper_band:
            trend = "BULLISH"
        elif close < lower_band:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"

        return {
            "trend": trend,
            "upper_band": round(upper_band, 2),
            "lower_band": round(lower_band, 2)
        }

    def calculate(self, candles):
        closes = [c["close"] for c in candles]

        return {
            "ema_21": self.ema(closes, 21),
            "ema_38": self.ema(closes, 38),
            "rsi_14": self.rsi(closes, 14),
            "atr_14": self.atr(candles, 14),
            "vwap": self.vwap(candles),
            "supertrend": self.supertrend(candles),
            "candles_count": len(candles)
        }