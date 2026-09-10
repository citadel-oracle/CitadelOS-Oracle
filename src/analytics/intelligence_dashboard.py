from src.analytics.report_builder import AnalyticsReportBuilder
from src.optimizer.optimizer_engine import OptimizerEngine


class IntelligenceDashboard:

    def __init__(self):
        self.report_builder = AnalyticsReportBuilder()
        self.optimizer = OptimizerEngine()

    def render(self):
        report = self.report_builder.build()
        optimizer_result = self.optimizer.suggest()

        summary = report["summary"]
        rankings = report["rankings"]

        print("=" * 90)
        print("CITADEL INTELLIGENCE DASHBOARD — PHASE 3")
        print("=" * 90)

        print()
        print("SUMMARY")
        print("-" * 90)
        print(f"Total Trades     : {summary.get('total_trades')}")
        print(f"Win Rate         : {summary.get('win_rate')}%")
        print(f"Net Points       : {summary.get('net_points')}")
        print(f"Profit Factor    : {summary.get('profit_factor')}")
        print(f"Expectancy       : {summary.get('expectancy')}")
        print(f"Max Win Streak   : {summary.get('max_win_streak')}")
        print(f"Max Loss Streak  : {summary.get('max_loss_streak')}")
        print(f"Verdict          : {summary.get('verdict')}")
        print(f"Comment          : {summary.get('comment')}")

        self._print_ranking("BEST SYMBOLS", rankings.get("symbols", []))
        self._print_ranking("BEST REGIMES", rankings.get("regimes", []))
        self._print_ranking("BEST LIQUIDITY", rankings.get("liquidity", []))
        self._print_ranking("BEST FVG", rankings.get("fvg", []))
        self._print_ranking("BEST ORDER BLOCKS", rankings.get("order_blocks", []))
        self._print_ranking("BEST BOS", rankings.get("bos", []))

        print()
        print("OPTIMIZER SUGGESTIONS")
        print("-" * 90)

        for suggestion in optimizer_result.get("suggestions", []):
            print(
                f"[{suggestion.get('priority')}] "
                f"{suggestion.get('type')} — "
                f"{suggestion.get('message')}"
            )

        print("=" * 90)

    def _print_ranking(self, title, rows):
        print()
        print(title)
        print("-" * 90)

        if not rows:
            print("Not enough data")
            return

        for row in rows[:5]:
            print(
                f"{row.get('name'):<22} "
                f"Trades: {row.get('trades'):<5} "
                f"WR: {row.get('win_rate'):<7}% "
                f"PnL: {row.get('pnl'):<10} "
                f"Score: {row.get('score')}"
            )


if __name__ == "__main__":
    IntelligenceDashboard().render()