#!/usr/bin/env python3
"""Launch a supplied Oracle collector once; never registers a keepalive job."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from src.oracle_certification.harness import (
    DynamicProcessMonitor, create_run_directory, evaluate_pre_soak_gate,
    finalize_run, launch_one_shot, resolve_process, write_once,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--certified", action="store_true")
    parser.add_argument("--preflight-evidence", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("collector command required")
    preflight = None
    if args.certified:
        if not args.preflight_evidence:
            parser.error("--certified requires --preflight-evidence")
        preflight = json.loads(args.preflight_evidence.read_text(encoding="utf-8"))
        gate = evaluate_pre_soak_gate(preflight)
        if not gate["certified_clock_armed"]:
            print(json.dumps(gate, indent=2, sort_keys=True))
            raise SystemExit(2)
    run_id, output = create_run_directory(args.runs_root, prefix="oracle_cert")
    started = datetime.now(timezone.utc).isoformat()
    child = launch_one_shot(args.command, cwd=args.cwd, stdout=output / "collector.stdout.log")
    write_once(output / "PID.json", {
        "run_id": run_id, "wrapper_pid": os.getpid(), "collector_pid": child.pid,
        "started_at": started,
    })
    resolvers = {
        "backend": lambda: resolve_process("backend", port=args.backend_port),
        "frontend": lambda: resolve_process("frontend", port=args.frontend_port),
        "collector": lambda: resolve_process("collector", pid=child.pid),
    }
    if preflight and isinstance(preflight.get("WS_OWNER_PID"), int):
        resolvers["ws_owner"] = lambda: resolve_process("ws_owner", pid=preflight["WS_OWNER_PID"])
    monitor = DynamicProcessMonitor(resolvers)
    samples = []
    while child.poll() is None:
        samples.append(monitor.sample())
        time.sleep(1.0)
    exit_code = child.returncode
    samples.append(monitor.sample())
    write_once(output / "SYSTEM.json", {"samples": samples, "pid_transitions": monitor.transitions})
    ended = datetime.now(timezone.utc).isoformat()
    finalize_run(output, run_id=run_id, started_at=started, ended_at=ended, pid=child.pid, exit_code=exit_code)
    print(output)


if __name__ == "__main__":
    main()
