from src.strategies.strategy_manager import StrategyManager
from src.brain.context_builder import ContextBuilder
from src.kronos.kronos_engine import KronosEngine


engine = KronosEngine()
builder = ContextBuilder()
manager = StrategyManager()

indicators = {
    "close": 24500,
    "ema_21": 24480,
    "ema_38": 24420,
    "rsi_14": 62,
    "adx_14": 28,
    "atr_14": 25,
    "vwap": 24460,
}

kronos = engine.analyze(indicators)

context = builder.build(
    symbol="NIFTY",
    indicators=indicators,
    kronos=kronos,
    structure_v1={"score": 80},
    structure_v2={"score": 90, "structure": "BULLISH_STRUCTURE", "bos": "BULLISH_BOS", "choch": "NONE"},
    liquidity={"score": 85, "type": "BULLISH_SWEEP"},
    fvg={"score": 80, "type": "BULLISH_FVG"},
    order_block={"score": 75, "type": "BULLISH_OB"},
    timeframe={"confidence": 85, "bias": "BULLISH"},
)

signal = manager.generate(context)

print("=" * 60)
print("STRATEGY MANAGER TEST")
print("=" * 60)
print("Strategy :", manager.strategy_name())
print(signal)