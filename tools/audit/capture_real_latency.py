#!/usr/bin/env python3
"""Capture only directly timestamped, unique runtime latency intervals.

Missing stage boundaries stay UNPROVEN. This collector never reconstructs a
start timestamp from a duration and never turns repeated reads into samples.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

import requests

OUTPUT_DIR = Path("/tmp/citadel_final_latency")
FAST_LANE_URL = "http://127.0.0.1:8000/v1/oracle/fast-lane"
FAST_LANE_HEALTH_URL = "http://127.0.0.1:8000/v1/oracle/fast-lane/health"
SOL_STATE_URL = "http://127.0.0.1:8000/v1/oracle/sol/state"
STAGES = (
    "DHAN_RECEIVE_TO_DECODE",
    "DECODE_TO_CANONICAL",
    "CANONICAL_TO_ORDERFLOW",
    "DOMAIN_TO_FASTLANE",
    "FASTLANE_BUILD",
    "FASTLANE_SERIALIZATION",
    "FASTLANE_TO_IPC",
    "IPC_TO_API",
    "API_TO_SSE",
    "SSE_TO_BROWSER",
    "BROWSER_TO_RENDER",
    "GEMINI_PROVIDER",
)
ROW_FIELDS = (
    "sample_id",
    "runtime_generation",
    "session_generation",
    "revision",
    "security_id",
    "stage",
    "t0_source",
    "t1_source",
    "t0_ns",
    "t1_ns",
    "delta_ms",
)


def _direct_row(
    *,
    stage: str,
    sample_id: str,
    revision: Any,
    runtime_generation: Any,
    session_generation: Any,
    security_id: Any,
    source: dict[str, Any],
    t0_key: str,
    t1_key: str,
) -> dict[str, Any] | None:
    t0 = source.get(t0_key)
    t1 = source.get(t1_key)
    if isinstance(t0, bool) or isinstance(t1, bool):
        return None
    if not isinstance(t0, int) or not isinstance(t1, int) or t0 <= 0 or t1 < t0:
        return None
    return {
        "sample_id": sample_id,
        "runtime_generation": runtime_generation,
        "session_generation": session_generation,
        "revision": revision,
        "security_id": security_id,
        "stage": stage,
        "t0_source": t0_key,
        "t1_source": t1_key,
        "t0_ns": t0,
        "t1_ns": t1,
        "delta_ms": round((t1 - t0) / 1_000_000.0, 6),
    }


def collect_real_latency_samples(n_samples: int = 25) -> dict[str, list[dict[str, Any]]]:
    samples = {stage: [] for stage in STAGES}
    seen_revisions: set[tuple[Any, Any]] = set()
    seen_invocations: set[str] = set()

    for _ in range(n_samples * 4):
        if len(samples["FASTLANE_BUILD"]) >= n_samples:
            break
        try:
            response = requests.get(FAST_LANE_HEALTH_URL, timeout=5.0)
            response.raise_for_status()
            frame = response.json()
            polling = frame.get("latest_latency_stages") or {}
            runtime = frame.get("runtime_instance_id")
            revision = frame.get("revision")
            revision_key = (runtime, revision)
            if revision_key not in seen_revisions:
                seen_revisions.add(revision_key)
                metadata = frame.get("source_metadata") or {}
                common = {
                    "sample_id": f"{runtime or 'unknown'}:{revision}",
                    "revision": revision,
                    "runtime_generation": runtime,
                    "session_generation": metadata.get("session_generation"),
                    "security_id": metadata.get("security_id"),
                    "source": polling,
                }
                build = _direct_row(
                    stage="FASTLANE_BUILD",
                    t0_key="fastlane_build_start_ns",
                    t1_key="fastlane_value_tree_done_ns",
                    **common,
                )
                serialization = _direct_row(
                    stage="FASTLANE_SERIALIZATION",
                    t0_key="fastlane_serialization_start_ns",
                    t1_key="fastlane_serialized_ns",
                    **common,
                )
                if build:
                    samples["FASTLANE_BUILD"].append(build)
                if serialization:
                    samples["FASTLANE_SERIALIZATION"].append(serialization)
        except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
            pass

        try:
            response = requests.get(SOL_STATE_URL, timeout=5.0)
            response.raise_for_status()
            state = response.json()
            provider = state.get("provider_telemetry") or state.get("provider_health") or {}
            invocation_id = provider.get("invocation_id")
            if isinstance(invocation_id, str) and invocation_id and invocation_id not in seen_invocations:
                row = _direct_row(
                    stage="GEMINI_PROVIDER",
                    sample_id=invocation_id,
                    revision=state.get("state_revision"),
                    runtime_generation=state.get("runtime_instance_id"),
                    session_generation=state.get("session_generation"),
                    security_id=None,
                    source=provider,
                    t0_key="invocation_started_ns",
                    t1_key="invocation_completed_ns",
                )
                if row:
                    seen_invocations.add(invocation_id)
                    samples["GEMINI_PROVIDER"].append(row)
        except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
            pass
        time.sleep(0.3)
    return samples


def calculate_stats(deltas: list[float]) -> dict[str, Any]:
    if not deltas:
        return {"status": "UNPROVEN", "N": 0}
    ordered = sorted(deltas)
    n = len(ordered)

    def pick(fraction: float) -> float:
        return ordered[min(n - 1, int((n - 1) * fraction))]

    result: dict[str, Any] = {
        "status": "PROVEN",
        "N": n,
        "min_ms": round(ordered[0], 6),
        "p50_ms": round(pick(0.50), 6),
        "max_ms": round(ordered[-1], 6),
    }
    if n >= 20:
        result.update(p95_ms=round(pick(0.95), 6), p99_ms=round(pick(0.99), 6))
    else:
        result.update(p95_ms="INSUFFICIENT_N", p99_ms="INSUFFICIENT_N")
    return result


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    samples = collect_real_latency_samples()
    summary: list[dict[str, Any]] = []
    for stage, stage_samples in samples.items():
        if stage_samples:
            with (OUTPUT_DIR / f"{stage.casefold()}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
                writer.writeheader()
                writer.writerows(stage_samples)
        stats = calculate_stats([float(row["delta_ms"]) for row in stage_samples])
        summary.append({"stage": stage, **stats})
        print(f"{stage}: {stats}")
    (OUTPUT_DIR / "latency_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
