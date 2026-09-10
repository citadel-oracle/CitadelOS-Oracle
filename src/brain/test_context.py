from src.brain.context_builder import ContextBuilder
from src.kronos.kronos_engine import KronosEngine


builder = ContextBuilder()

engine = KronosEngine()

indicators = {
    "ema_21": 24480,
    "ema_38": 24420,
    "rsi_14": 62,
    "adx_14": 28,
    "atr_14": 25,
    "vwap": 24460,
}

kronos = engine.analyze(
    indicators={
        "close": 24500,
        **indicators,
    }
)

context = builder.build(
    symbol="NIFTY",
    indicators=indicators,
    kronos=kronos,
    structure_v1={"score":80},
    structure_v2={
        "score":90,
        "structure":"BULLISH_STRUCTURE",
        "bos":"BULLISH_BOS",
        "choch":"NONE",
    },
    liquidity={
        "score":85,
        "type":"BULLISH_SWEEP",
    },
    fvg={
        "score":80,
        "type":"BULLISH_FVG",
    },
    order_block={
        "score":75,
        "type":"BULLISH_OB",
    },
    timeframe={
        "confidence":85,
        "bias":"BULLISH",
    },
)

print("="*60)
print("CITADEL BRAIN TEST")
print("="*60)

print("Symbol      :", context.symbol)
print("Smart Score :", context.smart_score)
print("Confidence  :", context.confidence)
print("Regime      :", context.regime)

print()

print("Features")

for k,v in context.features.items():
    print(k,":",v)