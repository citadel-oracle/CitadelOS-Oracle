from src.optimizer.optimizer_engine import OptimizerEngine


optimizer = OptimizerEngine()
result = optimizer.suggest()
report = result["report"]

print("=" * 70)
print("CITADEL OPTIMIZER V1")
print("=" * 70)
print("Total Trades  :", report["total_trades"])
print("Win Rate      :", report["win_rate"], "%")
print("Profit Factor :", report["profit_factor"])
print("Expectancy    :", report["expectancy"])
print("Net Points    :", report["net_points"])

print()
print("SUGGESTIONS")
print("-" * 70)

for s in result["suggestions"]:
    print(f"[{s['priority']}] {s['type']} - {s['message']}")