from src.structure.structure_engine_v2 import StructureEngineV2


engine = StructureEngineV2()

candles = []

price = 100

# Build bullish swing structure
for i in range(60):
    if i % 10 < 5:
        price += 1.5
    else:
        price -= 0.7

    candles.append({
        "time": i,
        "open": price - 0.5,
        "high": price + 1.0,
        "low": price - 1.0,
        "close": price,
        "volume": 1000,
    })

# Force bullish BOS
candles.append({
    "time": 61,
    "open": price,
    "high": price + 8,
    "low": price - 1,
    "close": price + 7,
    "volume": 2000,
})

result = engine.analyze(candles)

print("========== STRUCTURE V2 SYNTHETIC TEST ==========")
print(result)