"""
CitadelOS Paper Trader
Creates and monitors simulated paper orders only.
"""

import csv
import os
from datetime import datetime


class PaperTrader:
    def __init__(self, log_path="logs/paper_trades.csv"):
        self.trade_id = 0
        self.open_trade = None
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def execute(self, signal, ltp):
        if signal.get("signal") not in ["BUY", "SELL"]:
            return None

        if self.open_trade and self.open_trade.get("status") == "OPEN":
            return self.monitor(ltp)

        self.trade_id += 1

        side = signal.get("signal")
        entry = float(ltp)

        if side == "BUY":
            sl = entry - 20
            target = entry + 40
        else:
            sl = entry + 20
            target = entry - 40

        self.open_trade = {
            "trade_id": self.trade_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": "NIFTY",
            "side": side,
            "entry": entry,
            "sl": sl,
            "target": target,
            "confidence": signal.get("confidence"),
            "reason": signal.get("reason"),
            "status": "OPEN",
            "executed": True,
            "ltp": entry,
            "pnl": 0.0,
        }

        self._save_trade(self.open_trade)
        return self.open_trade

    def monitor(self, ltp):
        if not self.open_trade:
            return None

        trade = self.open_trade
        side = trade.get("side")
        ltp = float(ltp)

        if side == "BUY":
            pnl = ltp - trade["entry"]
            if ltp <= trade["sl"]:
                trade["status"] = "CLOSED_SL"
            elif ltp >= trade["target"]:
                trade["status"] = "CLOSED_TARGET"
        else:
            pnl = trade["entry"] - ltp
            if ltp >= trade["sl"]:
                trade["status"] = "CLOSED_SL"
            elif ltp <= trade["target"]:
                trade["status"] = "CLOSED_TARGET"

        trade["ltp"] = ltp
        trade["pnl"] = round(pnl, 2)

        if trade["status"] != "OPEN":
            self._save_trade(trade)
            self.open_trade = None

        return trade

    def _save_trade(self, trade):
        file_exists = os.path.exists(self.log_path)

        fieldnames = [
            "trade_id", "time", "symbol", "side", "entry", "sl", "target",
            "confidence", "reason", "status", "executed", "ltp", "pnl"
        ]

        row = {key: trade.get(key) for key in fieldnames}

        with open(self.log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)


def print_paper_order(order):
    print("\n📄 Paper Trader")

    if not order:
        print("Status : No paper order")
        return

    print(f"Executed : {order.get('executed')}")
    print(f"Reason   : {order.get('reason')}")
    print(f"Trade ID : {order.get('trade_id')}")
    print(f"Side     : {order.get('side')}")
    print(f"Entry    : {order.get('entry')}")
    print(f"SL       : {order.get('sl')}")
    print(f"Target   : {order.get('target')}")
    print(f"Status   : {order.get('status')}")
    print(f"LTP      : {order.get('ltp')}")
    print(f"PnL      : {order.get('pnl')}")