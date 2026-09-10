from src.broker.dhan_client import DhanClient
from src.orderblock.order_block_engine import OrderBlockEngine


dhan = DhanClient()
engine = OrderBlockEngine()

res = dhan.get_intraday_candles(
    segment="IDX_I",
    security_id="13",
    instrument="INDEX",
    interval="1",
)

candles = res.get("candles", [])

result = engine.analyze(candles)

print("========== ORDER BLOCK TEST ==========")
print(result)