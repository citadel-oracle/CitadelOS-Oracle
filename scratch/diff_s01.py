import ast
with open("scripts/run_e8c_r1_one_week_replay.py") as f:
    c1 = f.read()
with open("scripts/run_e8d_month_replay.py") as f:
    c2 = f.read()

import ast
def get_func(src, fname):
    mod = ast.parse(src)
    for node in mod.body:
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            return ast.unparse(node)
    return ""

with open("scratch/s01_e8c.py", "w") as f:
    f.write(get_func(c1, "replay_day_s01"))
with open("scratch/s01_e8d.py", "w") as f:
    f.write(get_func(c2, "replay_day_s01"))
