"""
CitadelOS Kronos Engine
Market regime + trade permission filter.
Returns dict for RiskEngine compatibility.
"""


class KronosEngine:

    def analyze(self, indicators, candle=None):
        ema21 = indicators.get("ema_21")
        ema38 = indicators.get("ema_38")
        rsi14 = indicators.get("rsi_14")
        vwap = indicators.get("vwap")

        close = None
        if candle:
            close = candle.get("close")

        if ema21 is None or ema38 is None or rsi14 is None:
            return {
                "regime": "UNKNOWN",
                "bias": "NEUTRAL",
                "trade_mode": "WAIT",
                "risk_mode": "LOW",
                "confidence": 0,
                "allow_trade": False,
                "reason": "Not enough indicator data",
            }

        bullish_score = 0
        bearish_score = 0

        if ema21 > ema38:
            bullish_score += 40
        elif ema21 < ema38:
            bearish_score += 40

        if rsi14 >= 55:
            bullish_score += 30
        elif rsi14 <= 45:
            bearish_score += 30

        if close is not None and vwap is not None:
            if close >= vwap:
                bullish_score += 20
            elif close <= vwap:
                bearish_score += 20

        if bullish_score >= 60 and bullish_score > bearish_score:
            return {
                "regime": "TRENDING",
                "bias": "BULLISH",
                "trade_mode": "LONG_ONLY",
                "risk_mode": "NORMAL",
                "confidence": min(bullish_score, 100),
                "allow_trade": True,
                "reason": "Bullish regime confirmed by EMA/RSI/VWAP",
            }

        if bearish_score >= 60 and bearish_score > bullish_score:
            return {
                "regime": "TRENDING",
                "bias": "BEARISH",
                "trade_mode": "SHORT_ONLY",
                "risk_mode": "NORMAL",
                "confidence": min(bearish_score, 100),
                "allow_trade": True,
                "reason": "Bearish regime confirmed by EMA/RSI/VWAP",
            }

        return {
            "regime": "SIDEWAYS",
            "bias": "NEUTRAL",
            "trade_mode": "AVOID",
            "risk_mode": "LOW",
            "confidence": max(bullish_score, bearish_score),
            "allow_trade": False,
            "reason": "Sideways/choppy regime: conditions not aligned",
        }


def print_kronos(result):
    print("🧠 Kronos")
    print(f"Regime      : {result.get('regime')}")
    print(f"Bias        : {result.get('bias')}")
    print(f"Trade Mode  : {result.get('trade_mode')}")
    print(f"Risk Mode   : {result.get('risk_mode')}")
    print(f"Confidence  : {result.get('confidence')}%")
    print(f"Allow Trade : {result.get('allow_trade')}")
    print(f"Reason      : {result.get('reason')}")