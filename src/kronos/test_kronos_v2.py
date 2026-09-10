from src.kronos.kronos_engine import KronosEngine, print_kronos

engine = KronosEngine()

indicators = {
    "close": 24500,
    "ema_21": 24480,
    "ema_38": 24420,
    "rsi_14": 62,
    "vwap": 24460,
    "atr_14": 25,
    "adx_14": 28,
}

structure = {
    "bias": "BULLISH",
    "score": 80,
}

liquidity = {
    "bias": "BULLISH",
    "score": 85,
}

fvg = {
    "bias": "BULLISH",
    "score": 80,
}

order_block = {
    "bias": "BULLISH",
    "score": 75,
}

structure_v2 = {
    "bias": "BULLISH",
    "score": 90,
}

timeframe = {
    "bias": "BULLISH",
    "confidence": 85,
}

result = engine.analyze(
    indicators=indicators,
    structure=structure,
    liquidity=liquidity,
    fvg=fvg,
    order_block=order_block,
    structure_v2=structure_v2,
    timeframe=timeframe,
)

print_kronos(result)

print()
print(result.scores)