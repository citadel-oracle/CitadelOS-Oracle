#!/usr/bin/env python3
"""Benchmark exact lightweight Flow Pulse payloads on the existing SSE lane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.oracle_fast_lane import OracleFastLane


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10_000)
    args = parser.parse_args()
    replay = json.loads(args.replay.read_text())
    entry = replay["opening_replay"]["first_early"]
    final = replay["final"]
    action = {
        "revision": 2, "semantic_revision": final["semantic_revision"],
        "headline": entry["headline"], "model": entry["model"], "story": entry["story"],
        "key_level": entry["key_level"], "trigger": entry["futures_trigger"],
        "option": {
            "strike": 24550.0, "option_type": "PE", "bid": 73.5999984741211,
            "ask": entry["option_ask"], "status": "AVAILABLE",
        },
        "stop": entry["stop"], "target_1": entry["target_1"], "target_2": entry["target_2"],
        "episode_state": entry["state"], "source_timestamp": entry["time"],
        "action_ready_ns": 0, "packet_receive_ns": 0,
    }
    meters = {
        key: final.get(key)
        for key in (
            "revision", "semantic_revision", "source_timestamp", "packet_receive_ns",
            "futures", "semantic", "flow", "tape", "profile", "levels", "key_level",
            "next_level", "what_happened", "open_range", "live_health", "data_quality",
            "paper_trades", "paper_episodes",
        )
    }
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={})
    for _ in range(args.count):
        packet_ns = perf_counter_ns()
        action["packet_receive_ns"] = packet_ns
        action["action_ready_ns"] = packet_ns
        lane.publish_flow_pulse("FLOW_PULSE_ACTION", action)
        [event] = lane.wait_for_events(None, 0)
        frame_bytes = len(event["_encoded"]) + len(str(event["event_id"])) + 43
        lane.record_sse_yield(event, frame_bytes)
    for _ in range(args.count):
        lane._publish_compact("FLOW_PULSE_METERS", meters)
    health = lane.health()
    print(json.dumps({
        "count_per_lane": args.count,
        "serializer": "stdlib-json",
        "new_dependencies": [],
        "action_serialization_ms": health["action_serialization_ms"],
        "meter_serialization_ms": health["meter_serialization_ms"],
        "packet_to_action_event_ms": health["packet_to_action_event_ms"],
        "event_to_sse_yield_ms": health["event_to_sse_yield_ms"],
        "action_payload_bytes": health["action_payload_bytes"],
        "meter_payload_bytes": health["meter_payload_bytes"],
        "sse_frame_bytes": health["sse_frame_bytes"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
