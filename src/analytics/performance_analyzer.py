from collections import defaultdict


class PerformanceAnalyzer:

    def analyze(self, rows):
        if not rows:
            return self.empty()

        total = len(rows)
        wins = losses = breakeven = 0
        net_points = gross_profit = gross_loss = 0.0

        by_symbol = defaultdict(self.group)
        by_regime = defaultdict(self.group)
        by_liquidity = defaultdict(self.group)
        by_fvg = defaultdict(self.group)
        by_order_block = defaultdict(self.group)
        by_bos = defaultdict(self.group)

        streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        last_result = None

        for row in rows:
            result = row.get("result")
            pnl = float(row.get("pnl") or 0)

            net_points += pnl

            if pnl > 0:
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)

            if result == "WIN":
                wins += 1
            elif result == "LOSS":
                losses += 1
            else:
                breakeven += 1

            if result == last_result:
                streak += 1
            else:
                streak = 1
                last_result = result

            if result == "WIN":
                max_win_streak = max(max_win_streak, streak)
            elif result == "LOSS":
                max_loss_streak = max(max_loss_streak, streak)

            self.add(by_symbol, row.get("symbol"), result, pnl)
            self.add(by_regime, row.get("regime"), result, pnl)
            self.add(by_liquidity, row.get("liquidity"), result, pnl)
            self.add(by_fvg, row.get("fvg"), result, pnl)
            self.add(by_order_block, row.get("order_block"), result, pnl)
            self.add(by_bos, row.get("bos"), result, pnl)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": round((wins / total) * 100, 2),
            "net_points": round(net_points, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else round(gross_profit, 2),
            "expectancy": round(net_points / total, 2),
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "by_symbol": self.finalize(by_symbol),
            "by_regime": self.finalize(by_regime),
            "by_liquidity": self.finalize(by_liquidity),
            "by_fvg": self.finalize(by_fvg),
            "by_order_block": self.finalize(by_order_block),
            "by_bos": self.finalize(by_bos),
        }

    def group(self):
        return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}

    def add(self, group, key, result, pnl):
        key = key or "UNKNOWN"
        group[key]["trades"] += 1
        group[key]["pnl"] += pnl

        if result == "WIN":
            group[key]["wins"] += 1
        elif result == "LOSS":
            group[key]["losses"] += 1

    def finalize(self, group):
        output = {}

        for key, data in group.items():
            trades = data["trades"]
            wins = data["wins"]

            output[key] = {
                "trades": trades,
                "wins": wins,
                "losses": data["losses"],
                "win_rate": round((wins / trades) * 100, 2) if trades else 0,
                "pnl": round(data["pnl"], 2),
            }

        return output

    def empty(self):
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate": 0,
            "net_points": 0,
            "gross_profit": 0,
            "gross_loss": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "by_symbol": {},
            "by_regime": {},
            "by_liquidity": {},
            "by_fvg": {},
            "by_order_block": {},
            "by_bos": {},
        }