from src.analytics.oracle_reader import OracleReader
from src.analytics.performance_analyzer import PerformanceAnalyzer


class OptimizerEngine:

    def __init__(self):
        self.reader = OracleReader()
        self.analyzer = PerformanceAnalyzer()

    def analyze_current_performance(self):
        rows = self.reader.closed_trades()
        return self.analyzer.analyze(rows)

    def suggest(self):
        report = self.analyze_current_performance()
        suggestions = []

        if report["total_trades"] < 100:
            suggestions.append({
                "priority": "HIGH",
                "type": "DATA",
                "message": "Collect at least 100 paper trades before trusting optimization.",
            })

        if report["win_rate"] < 45 and report["total_trades"] >= 20:
            suggestions.append({
                "priority": "HIGH",
                "type": "FILTER",
                "message": "Win rate is weak. Increase confidence threshold or reduce low-quality setups.",
            })

        if report["profit_factor"] < 1 and report["total_trades"] >= 20:
            suggestions.append({
                "priority": "HIGH",
                "type": "RISK",
                "message": "Profit factor below 1. Improve setup quality before live trading.",
            })

        best_symbol = self.best_group(report.get("by_symbol", {}))
        if best_symbol:
            suggestions.append({
                "priority": "MEDIUM",
                "type": "SYMBOL",
                "message": f"Best current symbol: {best_symbol}. Prioritize only after sample size improves.",
            })

        best_liquidity = self.best_group(report.get("by_liquidity", {}))
        if best_liquidity:
            suggestions.append({
                "priority": "MEDIUM",
                "type": "LIQUIDITY",
                "message": f"Best current liquidity condition: {best_liquidity}.",
            })

        return {"report": report, "suggestions": suggestions}

    def best_group(self, group):
        if not group:
            return None

        candidates = [
            (k, v) for k, v in group.items()
            if v.get("trades", 0) >= 2
        ]

        if not candidates:
            return None

        candidates.sort(
            key=lambda x: (x[1].get("win_rate", 0), x[1].get("pnl", 0)),
            reverse=True,
        )

        return candidates[0][0]