#!/usr/bin/env python3
"""Bounded recorder proof at genuine peak packet rate and 1.5x."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.order_flow.recorder import OrderFlowEvidenceRecorder


PEAK_EVENTS_PER_SECOND = 278
SECONDS = 3


def run(multiplier: float) -> dict:
    target_rate = PEAK_EVENTS_PER_SECOND * multiplier
    event_count = round(target_rate * SECONDS)
    with tempfile.TemporaryDirectory(prefix="flow-pulse-recorder-") as directory:
        recorder = OrderFlowEvidenceRecorder(Path(directory))
        recorder.start()
        started = monotonic()
        for index in range(event_count):
            deadline = started + (index + 1) / target_rate
            accepted = recorder.submit(
                "FLOW_PROJECTION",
                {
                    "snapshot_id": f"recorder-{multiplier}-{index}",
                    "flow_pulse": {
                        "revision": index, "semantic_revision": index // 20,
                        "headline": "WATCH", "execution_influence": "ZERO",
                    },
                },
                f"recorder-{multiplier}-{index}",
            )
            if not accepted:
                break
            remaining = deadline - monotonic()
            if remaining > 0:
                sleep(remaining)
        producer_elapsed = monotonic() - started
        recorder._queue.join()
        recorder.stop()
        health = recorder.health()
        rows = recorder.projections.read()
        return {
            "multiplier": multiplier,
            "target_rate_per_s": target_rate,
            "submitted": event_count,
            "producer_elapsed_seconds": round(producer_elapsed, 6),
            "actual_producer_rate_per_s": round(event_count / producer_elapsed, 3),
            "written": len(rows),
            "health": health,
            "pass": (
                len(rows) == event_count
                and health["queue_depth"] == 0
                and health["dropped"] == 0
                and health["writer_rate_per_s"] >= health["producer_rate_per_s"]
            ),
        }


def main() -> None:
    results = [run(1.0), run(1.5)]
    print(json.dumps({
        "genuine_peak_rate_per_s": PEAK_EVENTS_PER_SECOND,
        "results": results,
        "pass": all(item["pass"] for item in results),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
