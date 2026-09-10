import json
from scripts.eye_golden_replay_harness import run_golden_replay

r1 = run_golden_replay()
r2 = run_golden_replay()

import difflib
s1 = json.dumps(r1["raw_journal"], sort_keys=True, indent=2, default=str).splitlines()
s2 = json.dumps(r2["raw_journal"], sort_keys=True, indent=2, default=str).splitlines()

for line in difflib.context_diff(s1, s2):
    print(line)
