from src.analytics.report_builder import AnalyticsReportBuilder


builder = AnalyticsReportBuilder()
report = builder.build()

print("=" * 70)
print("CITADEL ANALYTICS REPORT")
print("=" * 70)

summary = report["summary"]

for key, value in summary.items():
    print(f"{key:<18}: {value}")

print()
print("=" * 70)
print("RANKINGS")
print("=" * 70)

for section, rows in report["rankings"].items():
    print()
    print(section.upper())
    print("-" * 70)

    if not rows:
        print("Not enough data")
        continue

    for row in rows[:5]:
        print(
            f"{row['name']:<20} "
            f"Trades: {row['trades']:<5} "
            f"WR: {row['win_rate']:<7}% "
            f"PnL: {row['pnl']:<10} "
            f"Score: {row['score']}"
        )