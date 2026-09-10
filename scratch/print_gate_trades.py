import json
from scripts.run_e8d_month_replay import REGRESSION_SESSIONS, run_replay
from pathlib import Path

with open("reports/personal_strategy_replay/e8d_20260706_20260807/raw/dhan_instrument_master.json") as f:
    master_rows = json.load(f)["rows"]

gate = run_replay(REGRESSION_SESSIONS, master_rows)
print(json.dumps(gate["all_s01"], indent=2))
