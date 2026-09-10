#!/usr/bin/env python3
"""Fail closed when the compiled Oracle frontend and reachable backend disagree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def inspect_contract(*, build: Path, expected_base: str, browser_evidence: Path | None) -> dict:
    expected_fast_lane = f"{expected_base}/v1/oracle/fast-lane"
    expected_stream = f"{expected_base}/v1/oracle/fast-lane/stream"
    compiled = ""
    for path in build.rglob("*.js"):
        try:
            compiled += path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    stale_ports = sorted({port for port in ("8102",) if f":{port}" in compiled})
    browser_rows = []
    if browser_evidence and browser_evidence.exists():
        value = json.loads(browser_evidence.read_text(encoding="utf-8"))
        browser_rows = value if isinstance(value, list) else value.get("browser_events", [])
    contracts = [row for row in browser_rows if row.get("event_type") == "BACKEND_CONTRACT"]
    fetch_ok = any(row.get("event_type") == "FETCH_OK" and row.get("url") == expected_fast_lane for row in browser_rows)
    sse_ok = any(row.get("event_type") == "EVENTSOURCE_CONNECTED" and row.get("url") == expected_stream for row in browser_rows)
    resolved_ok = any(
        row.get("fast_lane_url") == expected_fast_lane and row.get("eventsource_url") == expected_stream
        for row in contracts
    )
    reachable = False
    error = None
    try:
        with urlopen(Request(expected_fast_lane, headers={"Cache-Control": "no-cache"}), timeout=5) as response:
            reachable = response.status == 200
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    ready = not stale_ports and reachable and resolved_ok and fetch_ok and sse_ok
    return {
        "schema_version": 1,
        "compiled_runtime_backend_base": contracts[-1].get("backend_base_url") if contracts else None,
        "expected_backend_base": expected_base,
        "actual_reachable_backend": reachable,
        "browser_resolved_fast_lane_url": contracts[-1].get("fast_lane_url") if contracts else None,
        "browser_resolved_eventsource_url": contracts[-1].get("eventsource_url") if contracts else None,
        "browser_fast_lane_fetch": fetch_ok,
        "eventsource_connected": sse_ok,
        "stale_compiled_ports": stale_ports,
        "error": error,
        "oracle_ready": ready,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--browser-evidence", type=Path)
    args = parser.parse_args()
    result = inspect_contract(build=args.build, expected_base=args.expected_base, browser_evidence=args.browser_evidence)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["oracle_ready"] else 2)


if __name__ == "__main__":
    main()
