#!/usr/bin/env python3
"""Deterministic browser-to-backend Oracle field parity audit."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.oracle_sol.field_registry import SOL_SURFACE_FIELD_REGISTRY  # noqa: E402


def nested(payload: Any, path: str) -> Any:
    value = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def expected_display(value: Any, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "PRICE_2":
        return f"{float(value):.2f}"
    if kind == "SIGNED_2":
        return f"{float(value):+.2f}" if float(value) != 0 else "0.00"
    if kind == "PERCENT_1":
        return f"{float(value):.1f}%"
    if kind == "INTEGER":
        return str(int(value))
    if kind == "STATUS_DOT":
        return f"● {value}"
    if kind == "MONEY_2":
        return f"₹{float(value):.2f}"
    if kind == "SIGNED_MONEY_2":
        return f"+₹{float(value):.2f}" if float(value) > 0 else f"₹{float(value):.2f}"
    if kind == "QTY":
        s = str(int(value))
        if len(s) > 3:
            s, res = s[:-3], s[-3:]
            while s:
                res = s[-2:] + "," + res
                s = s[:-2]
            return res
        return s
    if kind == "LEVEL":
        p = f"₹{float(value['price']):.2f}"
        q = str(int(value['quantity']))
        if len(q) > 3:
            s, res = q[:-3], q[-3:]
            while s:
                res = s[-2:] + "," + res
                s = s[:-2]
            q = res
        o = value.get("orders")
        return f"{p} · {q}" + (f" · {int(o)} {'order' if int(o) == 1 else 'orders'}" if o is not None else "")
    if kind == "PCT_2":
        return f"{float(value):.2f}%"
    plain = {
        "OFF_MARKET": "MARKET CLOSED",
        "UNAVAILABLE": "UNAVAILABLE",
        "SUSPENDED": "PAUSED",
    }
    if kind == "PLAIN_STATUS":
        return plain.get(str(value), str(value).replace("_", " "))
    return str(value)


def verdict(value: Any, rendered: str, availability: Any, equal: bool) -> str:
    intentional_unavailable = rendered in {"—", "UNAVAILABLE", "NONE", "● UNAVAILABLE"}
    if value is None:
        return "PASS_UNAVAILABLE" if intentional_unavailable else "UNPROVEN"
    if not equal:
        return "FAIL_VALUE_MISMATCH"
    if availability in {"STALE", "LAST_KNOWN"}:
        return "PASS_LAST_KNOWN"
    return "PASS_LIVE"


def run_dom_probe(url: str, timeout_seconds: float, screenshot: Path | None = None) -> list[dict[str, Any]]:
    probe = REPO_ROOT / "tools/audit/oracle_dom_probe.cjs"
    command = ["node", str(probe), url, str(int(timeout_seconds * 1000))]
    if screenshot is not None:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        command.append(str(screenshot.resolve()))
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout_seconds + 30)
    if result.returncode:
        raise RuntimeError(f"Playwright DOM probe failed: {result.stderr[-1000:]}")
    return list(json.loads(result.stdout).get("fields") or [])


def audit(*, ui_url: str, backend_url: str, output_dir: Path, timeout_seconds: float, screenshot: Path | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    endpoint_cache: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for leaf in run_dom_probe(ui_url, timeout_seconds, screenshot):
        field_id = str(leaf.get("field_id") or "")
        contract = SOL_SURFACE_FIELD_REGISTRY.get(field_id)
        if contract is None:
            rows.append({**leaf, "verdict": "UNPROVEN", "backend_value": None, "reason": "FIELD_ID_NOT_REGISTERED"})
            continue
        if contract.endpoint not in endpoint_cache:
            response = requests.get(backend_url.rstrip("/") + contract.endpoint, timeout=timeout_seconds)
            response.raise_for_status()
            endpoint_cache[contract.endpoint] = response.json()
        payload = endpoint_cache[contract.endpoint]
        backend_value = nested(payload, contract.backend_path)
        availability = nested(payload, contract.availability_path) if contract.availability_path else leaf.get("status")
        expected = expected_display(backend_value, contract.display_kind)
        rendered = str(leaf.get("rendered_value") or "")
        row_verdict = verdict(backend_value, rendered, availability, rendered == expected)
        rows.append({
            **leaf,
            "backend_value": backend_value,
            "expected_display": expected,
            "availability": availability,
            "backend_path": contract.backend_path,
            "vob_free": contract.vob_free,
            "verdict": row_verdict,
            "reason": None if row_verdict.startswith("PASS_") else "EXACT_LEAF_MISMATCH",
        })

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    summary = {
        "ui_url": ui_url,
        "total_visible_dynamic_fields": len(rows),
        "mapped": sum(1 for row in rows if row.get("backend_path")),
        "unmapped": sum(1 for row in rows if not row.get("backend_path")),
        "counts": counts,
        "rows": rows,
    }
    (output_dir / "ORACLE_TRUTH_AUDIT.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    with (output_dir / "ORACLE_TRUTH_AUDIT.csv").open("w", newline="") as handle:
        fieldnames = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-url", default="http://127.0.0.1:3000/oracle")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    summary = audit(**vars(args))
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, indent=2))
    return 1 if any(key.startswith("FAIL_") for key in summary["counts"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
