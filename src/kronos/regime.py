from src.core.config import Config


class KronosRegime:

    def classify(self, probabilities):

        bull = probabilities["bull_probability"]
        bear = probabilities["bear_probability"]
        neutral = probabilities["neutral_probability"]

        if neutral >= 50:

            return {

                "regime": "SIDEWAYS",

                "bias": "NEUTRAL",

                "trade_mode": "AVOID",

                "risk_mode": "LOW",

                "confidence": neutral,

                "allow_trade": False,

            }

        if bull >= Config.KRONOS_MIN_SCORE and bull > bear:

            return {

                "regime": "TRENDING",

                "bias": "BULLISH",

                "trade_mode": "LONG_ONLY",

                "risk_mode": "NORMAL",

                "confidence": bull,

                "allow_trade": True,

            }

        if bear >= Config.KRONOS_MIN_SCORE and bear > bull:

            return {

                "regime": "TRENDING",

                "bias": "BEARISH",

                "trade_mode": "SHORT_ONLY",

                "risk_mode": "NORMAL",

                "confidence": bear,

                "allow_trade": True,

            }

        return {

            "regime": "MIXED",

            "bias": "NEUTRAL",

            "trade_mode": "WAIT",

            "risk_mode": "LOW",

            "confidence": max(bull, bear),

            "allow_trade": False,

        }