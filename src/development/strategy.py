"""Development clone of Simple Pullback; production strategy is untouched."""

from src.strategies.base_strategy import BaseStrategy


class SimplePullbackDevelopment(BaseStrategy):
    """Same bias, indicators, stop and 2R target with relaxed EMA ordering.

    Production requires ``close > EMA21 > EMA38`` (inverse for shorts).
    Development requires close beyond both EMAs but does not require the two
    averages to be ordered. No indicator or directional rule is added.
    """

    PROFILE_VERSION = "DEVELOPMENT_V1"

    def name(self):
        return "Simple Pullback (Development)"

    def config(self):
        return {
            "mode": "DEVELOPMENT_PAPER_ONLY",
            "profile_version": self.PROFILE_VERSION,
            "production_strategy_modified": False,
            "core_logic": "KRONOS_DIRECTION_PLUS_CLOSE_VS_EMA21_EMA38",
            "relaxation": "EMA21_EMA38_ORDER_NOT_REQUIRED",
            "target_r_multiple": 2.0,
            "live_trading_enabled": False,
        }

    def generate(self, context):
        indicators = context.indicators
        close, ema21, ema38 = indicators.get("close"), indicators.get("ema_21"), indicators.get("ema_38")
        if close is None or ema21 is None or ema38 is None:
            return self.wait("Missing indicator data")
        bias = context.kronos.get("bias")
        if bias == "BULLISH" and close > ema21 and close > ema38:
            return self._signal("BUY", close, ema21, context.confidence, "Development Pullback: bullish Kronos + close above EMA21 and EMA38")
        if bias == "BEARISH" and close < ema21 and close < ema38:
            return self._signal("SELL", close, ema21, context.confidence, "Development Pullback: bearish Kronos + close below EMA21 and EMA38")
        return self.wait("No development pullback setup")

    def _signal(self, side, close, ema21, confidence, reason):
        risk = abs(float(close) - float(ema21))
        if risk <= 0:
            return self.wait("Invalid risk")
        direction = 1 if side == "BUY" else -1
        return {
            "signal": side,
            "confidence": confidence,
            "entry": round(float(close), 2),
            "sl": round(float(ema21), 2),
            "target": round(float(close) + direction * risk * 2, 2),
            "reason": reason,
            "strategy": self.name(),
            "profile_version": self.PROFILE_VERSION,
        }

    def wait(self, reason):
        return {"signal": "WAIT", "confidence": 0, "entry": None, "sl": None, "target": None, "reason": reason, "strategy": self.name(), "profile_version": self.PROFILE_VERSION}
