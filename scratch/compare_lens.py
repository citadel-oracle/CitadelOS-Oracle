import json
from scripts.run_e8d_month_replay import load_candles, aggregate_1m_candles
def get_len(fp):
    with open(fp) as f:
        candles = load_candles(json.load(f))
    spot_3m = aggregate_1m_candles(candles, 3)
    return len(candles), len(spot_3m)

print("E8C 03-Aug:", get_len("reports/personal_strategy_replay/e8c_r1_20260803_20260807/raw/spot_1m_20260803.json"))
print("E8D 03-Aug:", get_len("reports/personal_strategy_replay/e8d_20260706_20260807/raw/spot_1m_20260803.json"))
print("E8C 04-Aug:", get_len("reports/personal_strategy_replay/e8c_r1_20260803_20260807/raw/spot_1m_20260804.json"))
print("E8D 04-Aug:", get_len("reports/personal_strategy_replay/e8d_20260706_20260807/raw/spot_1m_20260804.json"))
print("E8C 05-Aug:", get_len("reports/personal_strategy_replay/e8c_r1_20260803_20260807/raw/spot_1m_20260805.json"))
print("E8D 05-Aug:", get_len("reports/personal_strategy_replay/e8d_20260706_20260807/raw/spot_1m_20260805.json"))
