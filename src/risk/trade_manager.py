"""
CitadelOS Trade Manager V1.1

Handles:
- One active trade only
- Unique trade IDs across restarts
- Entry
- SL
- Target
- Break-even
- Trailing SL
- PnL
- Exit reason

Works for both paper and future live execution.
"""

from datetime import datetime


class TradeManager:

    def __init__(self):
        self.active_trade = None

        # Restart-safe trade id seed
        # Example: 10:25:31 => 102531
        self.trade_id = int(datetime.now().strftime("%H%M%S"))

    def open_trade(self, signal, symbol="NIFTY"):
        if self.active_trade is not None:
            return {
                "opened": False,
                "reason": "Trade already active",
                "trade": self.active_trade,
            }

        if signal.get("signal") not in ["BUY", "SELL"]:
            return {
                "opened": False,
                "reason": "No valid trade signal",
                "trade": None,
            }

        if signal.get("entry") is None or signal.get("sl") is None or signal.get("target") is None:
            return {
                "opened": False,
                "reason": "Entry, SL or Target missing",
                "trade": None,
            }

        self.trade_id += 1

        self.active_trade = {
            "trade_id": self.trade_id,
            "symbol": symbol,
            "side": signal.get("signal"),
            "entry": float(signal.get("entry")),
            "sl": float(signal.get("sl")),
            "initial_sl": float(signal.get("sl")),
            "target": float(signal.get("target")),
            "confidence": signal.get("confidence", 0),
            "reason": signal.get("reason", ""),
            "status": "OPEN",
            "ltp": float(signal.get("entry")),
            "pnl_points": 0.0,
            "r_multiple": 0.0,
            "break_even_done": False,
            "trailing_active": False,
            "exit_reason": None,
            "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "closed_at": None,
        }

        return {
            "opened": True,
            "reason": "Trade opened",
            "trade": self.active_trade,
        }

    def update(self, ltp):
        if self.active_trade is None:
            return {
                "status": "NO_TRADE",
                "trade": None,
            }

        trade = self.active_trade
        ltp = float(ltp)

        side = trade["side"]
        entry = trade["entry"]
        initial_sl = trade["initial_sl"]
        target = trade["target"]

        risk = abs(entry - initial_sl)

        if risk <= 0:
            risk = 1

        if side == "BUY":
            pnl_points = ltp - entry
            r_multiple = pnl_points / risk

            if ltp <= trade["sl"]:
                trade["status"] = "CLOSED"
                trade["exit_reason"] = "SL HIT"
                trade["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            elif ltp >= target:
                trade["status"] = "CLOSED"
                trade["exit_reason"] = "TARGET HIT"
                trade["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            else:
                self._manage_buy_trade(trade, ltp, r_multiple)

        elif side == "SELL":
            pnl_points = entry - ltp
            r_multiple = pnl_points / risk

            if ltp >= trade["sl"]:
                trade["status"] = "CLOSED"
                trade["exit_reason"] = "SL HIT"
                trade["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            elif ltp <= target:
                trade["status"] = "CLOSED"
                trade["exit_reason"] = "TARGET HIT"
                trade["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            else:
                self._manage_sell_trade(trade, ltp, r_multiple)

        else:
            pnl_points = 0
            r_multiple = 0
            trade["status"] = "ERROR"
            trade["exit_reason"] = "Invalid trade side"

        trade["ltp"] = ltp
        trade["pnl_points"] = round(pnl_points, 2)
        trade["r_multiple"] = round(r_multiple, 2)

        result = {
            "status": trade["status"],
            "trade": trade.copy(),
        }

        if trade["status"] == "CLOSED":
            self.active_trade = None

        return result

    def _manage_buy_trade(self, trade, ltp, r_multiple):
        entry = trade["entry"]
        risk = abs(entry - trade["initial_sl"])

        if not trade["break_even_done"] and r_multiple >= 1.0:
            trade["sl"] = entry
            trade["break_even_done"] = True

        if r_multiple >= 1.5:
            trade["trailing_active"] = True
            new_sl = ltp - risk * 0.75

            if new_sl > trade["sl"]:
                trade["sl"] = round(new_sl, 2)

    def _manage_sell_trade(self, trade, ltp, r_multiple):
        entry = trade["entry"]
        risk = abs(entry - trade["initial_sl"])

        if not trade["break_even_done"] and r_multiple >= 1.0:
            trade["sl"] = entry
            trade["break_even_done"] = True

        if r_multiple >= 1.5:
            trade["trailing_active"] = True
            new_sl = ltp + risk * 0.75

            if new_sl < trade["sl"]:
                trade["sl"] = round(new_sl, 2)

    def has_active_trade(self):
        return self.active_trade is not None

    def get_active_trade(self):
        return self.active_trade

    def close_trade_manually(self, reason="MANUAL EXIT"):
        if self.active_trade is None:
            return {
                "closed": False,
                "reason": "No active trade",
                "trade": None,
            }

        trade = self.active_trade
        trade["status"] = "CLOSED"
        trade["exit_reason"] = reason
        trade["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.active_trade = None

        return {
            "closed": True,
            "reason": reason,
            "trade": trade,
        }


def print_trade_state(result):
    print("\n📌 Trade Manager")

    trade = result.get("trade")

    if not trade:
        print("Status : No active trade")
        return

    print(f"Trade ID     : {trade.get('trade_id')}")
    print(f"Symbol       : {trade.get('symbol')}")
    print(f"Side         : {trade.get('side')}")
    print(f"Entry        : {trade.get('entry')}")
    print(f"LTP          : {trade.get('ltp')}")
    print(f"SL           : {trade.get('sl')}")
    print(f"Target       : {trade.get('target')}")
    print(f"PnL Points   : {trade.get('pnl_points')}")
    print(f"R Multiple   : {trade.get('r_multiple')}")
    print(f"Break Even   : {trade.get('break_even_done')}")
    print(f"Trailing     : {trade.get('trailing_active')}")
    print(f"Status       : {trade.get('status')}")
    print(f"Exit Reason  : {trade.get('exit_reason')}")
    print(f"Opened At    : {trade.get('opened_at')}")
    print(f"Closed At    : {trade.get('closed_at')}")