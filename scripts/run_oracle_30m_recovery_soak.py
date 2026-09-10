#!/usr/bin/env python3
"""Detached exact-window wrapper for the browser-recovery Oracle soak."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path("/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9")
OUT = ROOT / "reports/oracle_live_soak/20260812_0930_1000_browser_recovery"
START = datetime.fromisoformat("2026-08-12T09:30:00+05:30")
END = datetime.fromisoformat("2026-08-12T10:00:00+05:30")
DOM_PORT = 8111


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def listener_pid(port: int) -> int | None:
    try:
        value = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], text=True
        ).strip().splitlines()
        return int(value[0]) if value else None
    except Exception:
        return None


def process_sample(pid: int | None) -> dict:
    if pid is None:
        return {"pid": None, "error": "LISTENER_NOT_FOUND"}
    try:
        row = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "pid=,%cpu=,rss=,thcount=,command="], text=True
        ).strip().split(None, 4)
        return {
            "pid": int(row[0]), "cpu_percent": float(row[1]), "rss_kb": int(row[2]),
            "threads": int(row[3]), "command": row[4],
        }
    except Exception as error:
        return {"pid": pid, "error": str(error)}


def main() -> None:
    if (OUT / "MANIFEST.json").exists():
        raise RuntimeError("FINALIZED_RUN_DIRECTORY_IMMUTABLE_USE_NEW_RUN_ID")
    OUT.mkdir(parents=True, exist_ok=True)
    for name in (
        "RAW_MARKET", "FLOW_PULSE", "HUD_EDGE_STRUCTURE", "LATENCY", "RECORDER",
        "SYSTEM", "TRANSPORT", "FAST_LANE", "FORECASTS", "ORACLE_COMPONENTS",
        "BROWSER", "PAPER",
    ):
        (OUT / name).mkdir(exist_ok=True)

    backend_pid = listener_pid(8000)
    frontend_pid = listener_pid(3000)
    pre = {
        "created_at": datetime.now(IST).isoformat(),
        "start": START.isoformat(),
        "end": END.isoformat(),
        "timezone": "Asia/Kolkata",
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "backend_pid": backend_pid,
        "frontend_pid": frontend_pid,
        "repository": str(ROOT),
        "dom_port": DOM_PORT,
        "original_collector_pid_preserved": 5922,
    }
    (OUT / "PRE_SOAK.json").write_text(json.dumps(pre, indent=2) + "\n")
    (OUT / "WRAPPER_PID").write_text(f"{os.getpid()}\n")

    time.sleep(max(0, START.timestamp() - time.time()))
    raw = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/order_flow/evidence/raw_full_packets/2026-08-12.jsonl")
    projections = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/order_flow/evidence/projections.jsonl")
    command = [
        "/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python",
        str(ROOT / "scripts/collect_hud_live_certification.py"),
        "--duration-seconds", "1800",
        "--api", "http://127.0.0.1:8000",
        "--dom-port", str(DOM_PORT),
        "--raw-journal", str(raw),
        "--projection-journal", str(projections),
        "--output", str(OUT / "SUMMARY.json"),
    ]
    with (OUT / "collector.stdout.log").open("w") as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
        (OUT / "COLLECTOR_PID").write_text(f"{child.pid}\n")
        samples = []
        while child.poll() is None:
            disk = subprocess.check_output(["df", "-k", str(ROOT)], text=True).splitlines()[-1].split()
            samples.append({
                "timestamp": datetime.now(IST).isoformat(),
                "backend": process_sample(backend_pid),
                "frontend": process_sample(frontend_pid),
                "original_collector": process_sample(5922),
                "free_disk_kb": int(disk[3]),
            })
            time.sleep(1)
        exit_code = child.returncode

    (OUT / "SYSTEM/system_1hz.json").write_text(json.dumps(samples, indent=2) + "\n")
    manifest = {
        "window": {"start": START.isoformat(), "end": END.isoformat(), "timezone": "Asia/Kolkata"},
        "collector_exit_code": exit_code,
        "files": [],
    }
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            manifest["files"].append({
                "path": str(path.relative_to(OUT)), "bytes": path.stat().st_size, "sha256": sha(path),
            })
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (OUT / "MANIFEST.json").open("rb") as handle:
        os.fsync(handle.fileno())


if __name__ == "__main__":
    main()
