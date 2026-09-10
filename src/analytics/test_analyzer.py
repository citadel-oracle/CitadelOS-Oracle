from src.analytics.oracle_reader import OracleReader
from src.analytics.performance_analyzer import PerformanceAnalyzer


reader = OracleReader()
analyzer = PerformanceAnalyzer()

rows = reader.closed_trades()
report = analyzer.analyze(rows)

print("=" * 70)
print("CITADEL PERFORMANCE ANALYZER")
print("=" * 70)
print("Total Trades     :", report["total_trades"])
print("Wins             :", report["wins"])
print("Losses           :", report["losses"])
print("Win Rate         :", report["win_rate"], "%")
print("Net Points       :", report["net_points"])
print("Profit Factor    :", report["profit_factor"])
print("Expectancy       :", report["expectancy"])
print("Max Win Streak   :", report["max_win_streak"])
print("Max Loss Streak  :", report["max_loss_streak"])
print()
print("BY SYMBOL        :", report["by_symbol"])
print("BY REGIME        :", report["by_regime"])
print("BY LIQUIDITY     :", report["by_liquidity"])
print("BY FVG           :", report["by_fvg"])
print("BY ORDER BLOCK   :", report["by_order_block"])
print("BY BOS           :", report["by_bos"])