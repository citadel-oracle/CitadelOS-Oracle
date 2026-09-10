import csv
import os
from datetime import datetime


class OracleFeatureLogger:

    def __init__(self, filepath="logs/oracle_features.csv"):
        self.filepath = filepath
        self._initialize()

    def _initialize(self):
        os.makedirs("logs", exist_ok=True)

        if os.path.exists(self.filepath):
            return

        with open(self.filepath, "w", newline="") as f:
            writer = csv.writer(f)

            writer.writerow([
                "time",
                "trade_id",
                "symbol",
                "side",
                "entry",
                "sl",
                "target",
                "exit",
                "rr",
                "pnl",
                "result",
                "kronos_confidence",
                "market_quality",
                "regime",
                "structure",
                "bos",
                "choch",
                "liquidity",
                "fvg",
                "order_block",
                "mtf",
                "ema21",
                "ema38",
                "rsi",
                "adx",
                "atr",
                "vwap",
                "exit_reason",
            ])

    def log_trade(self, trade, context):
        features = context.features

        pnl = float(trade.get("pnl_points") or 0)
        exit_reason = trade.get("exit_reason")

        if exit_reason == "TARGET HIT":
            result = "WIN"
        elif exit_reason == "SL HIT":
            result = "LOSS"
        elif pnl > 0:
            result = "WIN"
        elif pnl < 0:
            result = "LOSS"
        else:
            result = "BREAKEVEN"

        with open(self.filepath, "a", newline="") as f:
            writer = csv.writer(f)

            writer.writerow([
                datetime.now(),
                trade.get("trade_id"),
                trade.get("symbol"),
                trade.get("side"),
                trade.get("entry"),
                trade.get("sl"),
                trade.get("target"),
                trade.get("ltp"),
                trade.get("r_multiple"),
                pnl,
                result,
                context.confidence,
                context.smart_score,
                context.regime,
                features.get("structure"),
                features.get("bos"),
                features.get("choch"),
                features.get("liquidity"),
                features.get("fvg"),
                features.get("order_block"),
                features.get("mtf"),
                features.get("ema21"),
                features.get("ema38"),
                features.get("rsi"),
                features.get("adx"),
                features.get("atr"),
                features.get("vwap"),
                exit_reason,
            ])

    def total_records(self):
        with open(self.filepath) as f:
            return max(sum(1 for _ in f) - 1, 0)