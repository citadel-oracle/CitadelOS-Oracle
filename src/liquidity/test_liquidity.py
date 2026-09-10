from src.broker.dhan_client import DhanClient
from src.liquidity.liquidity_engine import LiquidityEngine

dhan = DhanClient()
engine = LiquidityEngine()

res = dhan.get_intraday_candles(
    segment="IDX_I",
    security_id="13",
    instrument="INDEX",
    interval="1",
)

candles = res.get("candles", [])

result = engine.analyze(candles)

print("========== LIQUIDITY TEST ==========")
print(result)