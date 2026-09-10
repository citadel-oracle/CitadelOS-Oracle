"""
CitadelOS Market Data Loader

Loads saved candle history from CSV.
"""

import csv
import os
from datetime import datetime


class MarketData:

    def __init__(self, csv_file="logs/live_candles.csv"):
        self.csv_file = csv_file

    def load_saved_candles(self):
        candles = []

        if not os.path.exists(self.csv_file):
            return candles

        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file)

            for row in reader:
                try:
                    candles.append({
                        "time": datetime.fromisoformat(row["time"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                    })
                except Exception:
                    continue

        return candles