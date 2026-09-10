from src.core.config import Config
from src.kronos.models import KronosScores


class KronosScoring:

    def score(
        self,
        indicators,
        structure=None,
        liquidity=None,
        fvg=None,
        order_block=None,
        structure_v2=None,
        timeframe=None,
    ):
        scores = KronosScores()

        ema21 = indicators.get("ema_21")
        ema38 = indicators.get("ema_38")
        rsi14 = indicators.get("rsi_14")
        close = indicators.get("close")
        vwap = indicators.get("vwap")
        atr14 = indicators.get("atr_14")
        adx14 = indicators.get("adx_14")

        if ema21 is None or ema38 is None or rsi14 is None:
            scores.neutral_score = 100
            scores.reasons.append("Not enough indicator data")
            return scores

        if ema21 > ema38:
            scores.bull_score += Config.WEIGHT_EMA
            scores.trend_score += Config.WEIGHT_EMA
            scores.reasons.append("EMA Bullish")
        elif ema21 < ema38:
            scores.bear_score += Config.WEIGHT_EMA
            scores.trend_score += Config.WEIGHT_EMA
            scores.reasons.append("EMA Bearish")
        else:
            scores.neutral_score += 10
            scores.reasons.append("EMA Flat")

        if rsi14 >= Config.RSI_BUY:
            scores.bull_score += Config.WEIGHT_RSI
            scores.momentum_score += Config.WEIGHT_RSI
            scores.reasons.append("RSI Strong")
        elif rsi14 <= Config.RSI_SELL:
            scores.bear_score += Config.WEIGHT_RSI
            scores.momentum_score += Config.WEIGHT_RSI
            scores.reasons.append("RSI Weak")
        else:
            scores.neutral_score += 15
            scores.reasons.append("RSI Neutral")

        if close is not None and vwap is not None:
            if close > vwap:
                scores.bull_score += Config.WEIGHT_VWAP
                scores.reasons.append("Above VWAP")
            elif close < vwap:
                scores.bear_score += Config.WEIGHT_VWAP
                scores.reasons.append("Below VWAP")
            else:
                scores.neutral_score += 10
                scores.reasons.append("At VWAP")

        if adx14 is not None:
            if adx14 >= 20:
                scores.trend_score += Config.WEIGHT_ADX
                scores.reasons.append("ADX Strong")
            else:
                scores.neutral_score += Config.WEIGHT_ADX
                scores.reasons.append("ADX Weak")

        if atr14 is not None and atr14 > 0:
            scores.volatility_score += Config.WEIGHT_ATR
            scores.reasons.append("ATR Active")

        self._apply_context_score(scores, structure, Config.WEIGHT_STRUCTURE, "Structure V1")
        self._apply_context_score(scores, liquidity, Config.WEIGHT_LIQUIDITY, "Liquidity")
        self._apply_context_score(scores, fvg, Config.WEIGHT_FVG, "FVG")
        self._apply_context_score(scores, order_block, Config.WEIGHT_ORDER_BLOCK, "Order Block")
        self._apply_context_score(scores, structure_v2, Config.WEIGHT_STRUCTURE_V2, "Structure V2")

        if timeframe:
            tf_bias = timeframe.get("bias")
            tf_conf = int(timeframe.get("confidence", 0))
            tf_points = int(Config.WEIGHT_TIMEFRAME * tf_conf / 100)

            if tf_bias == "BULLISH":
                scores.bull_score += tf_points
                scores.trend_score += tf_points
                scores.reasons.append(f"MTF Bullish +{tf_points}")
            elif tf_bias == "BEARISH":
                scores.bear_score += tf_points
                scores.trend_score += tf_points
                scores.reasons.append(f"MTF Bearish +{tf_points}")
            else:
                scores.neutral_score += int(Config.WEIGHT_TIMEFRAME * 0.4)
                scores.reasons.append("MTF Neutral")

        return scores

    def _apply_context_score(self, scores, context, weight, label):
        if not context:
            return

        bias = context.get("bias")
        raw_score = int(context.get("score", 0))
        points = int(weight * raw_score / 100)

        if points <= 0:
            return

        if bias == "BULLISH":
            scores.bull_score += points
            scores.trend_score += points
            scores.reasons.append(f"{label} Bullish +{points}")
        elif bias == "BEARISH":
            scores.bear_score += points
            scores.trend_score += points
            scores.reasons.append(f"{label} Bearish +{points}")
        else:
            neutral_points = int(weight * 0.4)
            scores.neutral_score += neutral_points
            scores.reasons.append(f"{label} Neutral +{neutral_points}")