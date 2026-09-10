from src.analytics.oracle_reader import OracleReader
from src.analytics.performance_analyzer import PerformanceAnalyzer
from src.analytics.strategy_ranking import StrategyRanking


class AnalyticsReportBuilder:

    def __init__(self):
        self.reader = OracleReader()
        self.analyzer = PerformanceAnalyzer()
        self.ranker = StrategyRanking()

    def build(self):
        rows = self.reader.closed_trades()
        report = self.analyzer.analyze(rows)

        return {
            "summary": self._summary(report),
            "rankings": {
                "symbols": self.ranker.rank_groups(report.get("by_symbol", {})),
                "regimes": self.ranker.rank_groups(report.get("by_regime", {})),
                "liquidity": self.ranker.rank_groups(report.get("by_liquidity", {})),
                "fvg": self.ranker.rank_groups(report.get("by_fvg", {})),
                "order_blocks": self.ranker.rank_groups(report.get("by_order_block", {})),
                "bos": self.ranker.rank_groups(report.get("by_bos", {})),
            },
            "raw": report,
        }

    def _summary(self, report):
        total = report.get("total_trades", 0)
        win_rate = report.get("win_rate", 0)
        pf = report.get("profit_factor", 0)
        expectancy = report.get("expectancy", 0)

        if total < 100:
            verdict = "DATA_INSUFFICIENT"
            comment = "Sample size too small. Collect at least 100 paper trades."
        elif pf >= 1.5 and expectancy > 0 and win_rate >= 50:
            verdict = "PROMISING"
            comment = "System performance is promising. Continue forward testing."
        elif pf < 1 or expectancy <= 0:
            verdict = "WEAK"
            comment = "System is not ready for live trading."
        else:
            verdict = "NEUTRAL"
            comment = "Mixed performance. More filtering or optimization needed."

        return {
            "total_trades": total,
            "wins": report.get("wins"),
            "losses": report.get("losses"),
            "win_rate": win_rate,
            "net_points": report.get("net_points"),
            "profit_factor": pf,
            "expectancy": expectancy,
            "max_win_streak": report.get("max_win_streak"),
            "max_loss_streak": report.get("max_loss_streak"),
            "verdict": verdict,
            "comment": comment,
        }