from src.oracle.feature_logger import OracleFeatureLogger
from src.brain.context_builder import ContextBuilder
from src.kronos.kronos_engine import KronosEngine


engine = KronosEngine()

builder = ContextBuilder()

logger = OracleFeatureLogger()

indicators = {
    "close":24500,
    "ema_21":24480,
    "ema_38":24420,
    "rsi_14":62,
    "adx_14":28,
    "atr_14":25,
    "vwap":24460,
}

kronos = engine.analyze(indicators)

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

trade = {

    "trade_id":1,

    "symbol":"NIFTY",

    "side":"BUY",

    "entry":24500,

    "sl":24470,

    "target":24560,

    "ltp":24560,

    "r_multiple":2.4,

    "pnl_points":60,

    "exit_reason":"TARGET HIT",
}

logger.log_trade(trade, context)

print()

print("="*60)

print("ORACLE LOGGER TEST")

print("="*60)

print()

print("Total Records :", logger.total_records())

print()

print("Saved Successfully")