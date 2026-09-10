import csv
import os


class OracleReader:

    def __init__(self, filepath="logs/oracle_features.csv"):
        self.filepath = filepath

    def read(self):
        if not os.path.exists(self.filepath):
            return []

        with open(self.filepath, "r") as f:
            return list(csv.DictReader(f))

    def closed_trades(self):
        rows = self.read()
        return [r for r in rows if r.get("result") in ["WIN", "LOSS", "BREAKEVEN"]]

    def total_records(self):
        return len(self.closed_trades())