from src.kronos.kronos_engine import (
    KronosEngine,
    print_kronos,
)

engine = KronosEngine()

indicators = {

    "ema_21": 24500,

    "ema_38": 24400,

    "rsi_14": 63,

    "close": 24520,

    "vwap": 24480,

    "atr_14": 42,

    "adx_14": 26,

}

result = engine.analyze(indicators)

print_kronos(result)