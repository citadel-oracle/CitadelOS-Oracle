from src.data.data_engine import DataEngine
from src.scanner.watchlist import WATCHLIST

engine = DataEngine()

print()

print("========== DATA ENGINE TEST ==========")

for symbol, info in WATCHLIST.items():

    candles = engine.load_history(
        symbol=symbol,
        segment=info["segment"],
        security_id=info["security_id"],
    )

    print(
        symbol,
        len(candles),
        candles[-1]["close"],
    )

print()

print("Cached Symbols")

print(engine.symbols())