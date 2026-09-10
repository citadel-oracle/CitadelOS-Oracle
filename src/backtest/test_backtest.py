from src.backtest.backtest_engine import BacktestEngine


def synthetic_candles():
    candles = []
    price = 100

    for i in range(250):
        if i < 120:
            price += 0.4
        elif i < 180:
            price -= 0.25
        else:
            price += 0.35

        candles.append({
            "time": i,
            "open": round(price - 0.2, 2),
            "high": round(price + 0.6, 2),
            "low": round(price - 0.6, 2),
            "close": round(price, 2),
            "volume": 1000,
        })

    return candles


engine = BacktestEngine()
result = engine.run("NIFTY", synthetic_candles())

print("=" * 70)
print("CITADEL BACKTEST ENGINE V1")
print("=" * 70)

print("Total Trades :", result["total_trades"])
print("Wins         :", result["wins"])
print("Losses       :", result["losses"])
print("Win Rate     :", result["win_rate"], "%")
print("Net Points   :", result["net_points"])

print()
print("Last Trades")
for trade in result["trades"][-5:]:
    print(trade)