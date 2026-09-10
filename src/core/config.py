"""
Citadel Configuration
Single source of truth for all tunable parameters.
"""


class Config:

    EMA_FAST = 21
    EMA_SLOW = 38

    RSI_PERIOD = 14
    RSI_BUY = 55
    RSI_SELL = 45

    ATR_PERIOD = 14
    ADX_PERIOD = 14
    VWAP_ENABLED = True

    MIN_CANDLES = 100

    KRONOS_MIN_SCORE = 70

    WEIGHT_EMA = 20
    WEIGHT_RSI = 15
    WEIGHT_VWAP = 15
    WEIGHT_ADX = 15
    WEIGHT_ATR = 10
    WEIGHT_STRUCTURE = 15
    WEIGHT_VOLUME = 10

    WEIGHT_LIQUIDITY = 15
    WEIGHT_FVG = 12
    WEIGHT_ORDER_BLOCK = 12
    WEIGHT_STRUCTURE_V2 = 18
    WEIGHT_TIMEFRAME = 18

    MAX_RISK_PERCENT = 1.0
    ONE_TRADE_ONLY = True
    BREAK_EVEN_AT_R = 1.0
    TRAIL_AFTER_R = 1.5

    DEFAULT_TARGET_R = 2.0
    PARTIAL_EXIT = True
    PARTIAL_PERCENT = 50

    SAVE_TRADES = True
    SAVE_SIGNALS = True
    SAVE_KRONOS = True
    SAVE_ANALYTICS = True