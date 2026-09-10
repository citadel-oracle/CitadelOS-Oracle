from datetime import datetime

from src.brain.models import MarketContext


class ContextBuilder:

    def build(
        self,
        symbol,
        indicators,
        kronos,
        structure_v1,
        structure_v2,
        liquidity,
        fvg,
        order_block,
        timeframe,
    ):

        context = MarketContext(
            symbol=symbol,
            timestamp=datetime.now(),
        )

        context.indicators = indicators

        context.kronos = kronos.__dict__

        context.structure_v1 = structure_v1

        context.structure_v2 = structure_v2

        context.liquidity = liquidity

        context.fvg = fvg

        context.order_block = order_block

        context.timeframe = timeframe

        context.smart_score = self.calculate_score(context)

        context.confidence = kronos.confidence

        context.regime = kronos.regime

        context.features = self.build_features(context)

        return context

    def calculate_score(self, context):

        score = 0

        score += context.confidence * 0.50

        score += context.structure_v2.get("score", 0) * 0.20

        score += context.liquidity.get("score", 0) * 0.10

        score += context.fvg.get("score", 0) * 0.07

        score += context.order_block.get("score", 0) * 0.08

        score += context.timeframe.get("confidence", 0) * 0.05

        return round(score, 2)

    def build_features(self, context):

        return {

            "ema21": context.indicators.get("ema_21"),

            "ema38": context.indicators.get("ema_38"),

            "rsi": context.indicators.get("rsi_14"),

            "adx": context.indicators.get("adx_14"),

            "atr": context.indicators.get("atr_14"),

            "vwap": context.indicators.get("vwap"),

            "kronos_bias": context.kronos.get("bias"),

            "structure": context.structure_v2.get("structure"),

            "bos": context.structure_v2.get("bos"),

            "choch": context.structure_v2.get("choch"),

            "liquidity": context.liquidity.get("type"),

            "fvg": context.fvg.get("type"),

            "order_block": context.order_block.get("type"),

            "mtf": context.timeframe.get("bias"),

            "smart_score": context.smart_score,
        }