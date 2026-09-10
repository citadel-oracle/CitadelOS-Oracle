import csv
import os
from datetime import datetime


class CandleBuilder:
    def __init__(self):
        self.candles = []

    def load_csv(self, path):
        if not os.path.exists(path):
            self.candles = []
            return []

        candles = []
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ltp = float(row.get("close") or row.get("ltp") or 0)
                candles.append({
                    "time": row.get("time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(row.get("open") or ltp),
                    "high": float(row.get("high") or ltp),
                    "low": float(row.get("low") or ltp),
                    "close": ltp,
                    "ltp": ltp,
                })

        self.candles = candles
        return self.candles

    def update(self, tick):
        if isinstance(tick, dict):
            ltp = float(tick.get("ltp") or tick.get("close") or 0)
        else:
            ltp = float(tick or 0)

        candle = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "open": ltp,
            "high": ltp,
            "low": ltp,
            "close": ltp,
            "ltp": ltp,
        }

        self.candles.append(candle)
        return candle

    def get_candles(self):
        return self.candles

    def save_csv(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if not self.candles:
            return

        fieldnames = ["time", "open", "high", "low", "close", "ltp"]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.candles)