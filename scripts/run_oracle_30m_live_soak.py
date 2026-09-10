#!/usr/bin/env python3
"""Detached exact-window wrapper for the 12-Aug Oracle genuine-live soak."""
from __future__ import annotations

import hashlib, json, os, subprocess, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path("/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9")
OUT = ROOT / "reports/oracle_live_soak/20260812_0915_0945"
START = datetime.fromisoformat("2026-08-12T09:15:00+05:30")
END = datetime.fromisoformat("2026-08-12T09:45:00+05:30")

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def proc(pid: int) -> dict:
    try:
        out=subprocess.check_output(["ps","-p",str(pid),"-o","pid=,%cpu=,rss=,thcount=,command="],text=True).strip().split(None,4)
        return {"pid":int(out[0]),"cpu_percent":float(out[1]),"rss_kb":int(out[2]),"threads":int(out[3]),"command":out[4]}
    except Exception as e: return {"pid":pid,"error":str(e)}

def main():
    if (OUT / "MANIFEST.json").exists():
        raise RuntimeError("FINALIZED_RUN_DIRECTORY_IMMUTABLE_USE_NEW_RUN_ID")
    OUT.mkdir(parents=True,exist_ok=True)
    for name in ("RAW_MARKET","FLOW_PULSE","HUD_EDGE_STRUCTURE","LATENCY","RECORDER","SYSTEM","TRANSPORT","FAST_LANE","FORECASTS","ORACLE_COMPONENTS","BROWSER","PAPER"):
        (OUT/name).mkdir(exist_ok=True)
    pre={"created_at":datetime.now(IST).isoformat(),"start":START.isoformat(),"end":END.isoformat(),"timezone":"Asia/Kolkata","head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"backend_pid":3546,"frontend_pid":3549,"repository":str(ROOT)}
    (OUT/"PRE_SOAK.json").write_text(json.dumps(pre,indent=2)+"\n")
    delay=max(0, START.timestamp()-time.time())
    time.sleep(delay)
    raw=Path("/Users/ayushmudgal/Developer/CitadelOS/logs/order_flow/evidence/raw_full_packets/2026-08-12.jsonl")
    projections=Path("/Users/ayushmudgal/Developer/CitadelOS/logs/order_flow/evidence/projections.jsonl")
    cmd=[str(Path("/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python")),str(ROOT/"scripts/collect_hud_live_certification.py"),"--duration-seconds","1800","--api","http://127.0.0.1:8000","--raw-journal",str(raw),"--projection-journal",str(projections),"--output",str(OUT/"SUMMARY.json")]
    with (OUT/"collector.stdout.log").open("w") as log:
        child=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,text=True)
        samples=[]
        while child.poll() is None:
            now=datetime.now(IST)
            disk=subprocess.check_output(["df","-k",str(ROOT)],text=True).splitlines()[-1].split()
            samples.append({"timestamp":now.isoformat(),"backend":proc(3546),"frontend":proc(3549),"free_disk_kb":int(disk[3])})
            time.sleep(1)
        rc=child.returncode
    (OUT/"SYSTEM/system_1hz.json").write_text(json.dumps(samples,indent=2)+"\n")
    manifest={"window":{"start":START.isoformat(),"end":END.isoformat(),"timezone":"Asia/Kolkata"},"collector_exit_code":rc,"files":[]}
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and p.name!="MANIFEST.json": manifest["files"].append({"path":str(p.relative_to(OUT)),"bytes":p.stat().st_size,"sha256":sha(p)})
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n")
    with (OUT/"MANIFEST.json").open("rb") as f: os.fsync(f.fileno())

if __name__=="__main__": main()
