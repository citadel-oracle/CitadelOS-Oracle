from src.kronos.models import KronosResult
from src.kronos.scoring import KronosScoring
from src.kronos.probability import KronosProbability
from src.kronos.regime import KronosRegime


class KronosEngine:

    def __init__(self):
        self.scoring = KronosScoring()
        self.probability = KronosProbability()
        self.regime = KronosRegime()

    def analyze(
        self,
        indicators,
        structure=None,
        liquidity=None,
        fvg=None,
        order_block=None,
        structure_v2=None,
        timeframe=None,
    ):
        scores = self.scoring.score(
            indicators=indicators,
            structure=structure,
            liquidity=liquidity,
            fvg=fvg,
            order_block=order_block,
            structure_v2=structure_v2,
            timeframe=timeframe,
        )

        probabilities = self.probability.calculate(scores)
        regime = self.regime.classify(probabilities)

        return KronosResult(
            regime=regime["regime"],
            bias=regime["bias"],
            trade_mode=regime["trade_mode"],
            risk_mode=regime["risk_mode"],
            confidence=regime["confidence"],
            allow_trade=regime["allow_trade"],
            bull_probability=probabilities["bull_probability"],
            bear_probability=probabilities["bear_probability"],
            neutral_probability=probabilities["neutral_probability"],
            scores={
                "bull_score": scores.bull_score,
                "bear_score": scores.bear_score,
                "neutral_score": scores.neutral_score,
                "trend_score": scores.trend_score,
                "momentum_score": scores.momentum_score,
                "volatility_score": scores.volatility_score,
            },
            reason=", ".join(scores.reasons),
        )


def print_kronos(result):
    print()
    print("🧠 KRONOS X / V2")
    print(f"Regime       : {result.regime}")
    print(f"Bias         : {result.bias}")
    print(f"Trade Mode   : {result.trade_mode}")
    print(f"Risk Mode    : {result.risk_mode}")
    print(f"Confidence   : {result.confidence}%")
    print()
    print(f"Bull Prob    : {result.bull_probability}%")
    print(f"Bear Prob    : {result.bear_probability}%")
    print(f"Neutral Prob : {result.neutral_probability}%")
    print()
    print(f"Trade        : {result.allow_trade}")
    print(f"Reason       : {result.reason}")