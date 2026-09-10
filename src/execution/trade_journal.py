"""
CitadelOS Trade Journal V1

Saves paper/live trade events to CSV.
"""

import csv
import os
from datetime import datetime


class TradeJournal:

    def __init__(self, path="logs/paper_trades.csv"):
        self.path = path
        self.headers = [
            "time",
            "event",
            "trade_id",
            "symbol",
            "side",
            "entry",
            "ltp",
            "sl",
            "target",
            "pnl_points",
            "r_multiple",
            "status",
            "exit_reason",
            "confidence",
            "reason",
        ]

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.headers)
                writer.writeheader()

    def log_trade(self, event, trade):
        if not trade:
            return

        row = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "entry": trade.get("entry"),
            "ltp": trade.get("ltp"),
            "sl": trade.get("sl"),
            "target": trade.get("target"),
            "pnl_points": trade.get("pnl_points"),
            "r_multiple": trade.get("r_multiple"),
            "status": trade.get("status"),
            "exit_reason": trade.get("exit_reason"),
            "confidence": trade.get("confidence"),
            "reason": trade.get("reason"),
        }

        with open(self.path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writerow(row)

    def read_last(self, limit=10):
        if not os.path.exists(self.path):
            return []

        with open(self.path, "r") as f:
            rows = list(csv.DictReader(f))

        return rows[-limit:]

    def summary(self):
        if not os.path.exists(self.path):
            return {
                "total_closed": 0,
                "wins": 0,
                "losses": 0,
                "net_points": 0,
            }

        with open(self.path, "r") as f:
            rows = list(csv.DictReader(f))

        closed = [
            r for r in rows
            if r.get("event") == "CLOSE"
        ]

        wins = 0
        losses = 0
        net_points = 0.0

        for r in closed:
            pnl = float(r.get("pnl_points") or 0)
            net_points += pnl

            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1

        return {
            "total_closed": len(closed),
            "wins": wins,
            "losses": losses,
            "net_points": round(net_points, 2),
        }