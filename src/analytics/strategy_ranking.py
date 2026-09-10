class StrategyRanking:

    def rank_groups(self, group_data, min_trades=2):
        rankings = []

        for name, stats in group_data.items():
            trades = stats.get("trades", 0)

            if trades < min_trades:
                continue

            win_rate = stats.get("win_rate", 0)
            pnl = stats.get("pnl", 0)

            score = self._score(win_rate, pnl, trades)

            rankings.append({
                "name": name,
                "trades": trades,
                "win_rate": win_rate,
                "pnl": pnl,
                "score": score,
            })

        rankings.sort(key=lambda x: x["score"], reverse=True)
        return rankings

    def _score(self, win_rate, pnl, trades):
        return round(
            (win_rate * 0.55) +
            (min(trades, 100) * 0.20) +
            (max(min(pnl, 500), -500) * 0.25 / 10),
            2
        )