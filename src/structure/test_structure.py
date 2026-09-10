from src.broker.dhan_client import DhanClient
from src.structure.structure_engine import StructureEngine

dhan = DhanClient()
engine = StructureEngine()

res = dhan.get_intraday_candles(
    segment="IDX_I",
    security_id="13",
    instrument="INDEX",
    interval="1",
)

candles = res.get("candles", [])

result = engine.analyze(candles)

print(result)