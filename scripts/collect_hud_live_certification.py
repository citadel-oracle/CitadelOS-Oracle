#!/usr/bin/env python3
"""One-shot five-minute Oracle HUD/Flow Pulse live certification collector.

Open the real Oracle page with ``?hudAuditCollector=true`` before running this
script.  The collector consumes the existing Fast Lane SSE stream, receives
event-driven DOM commit beacons, samples recorder growth once at start/end,
writes one JSON summary, and terminates.  It never polls Codex or market APIs.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from src.oracle_certification.harness import RotatingJsonlFollower


DOM_EVENTS: list[dict[str, Any]] = []
BROWSER_EVENTS: list[dict[str, Any]] = []
DOM_LOCK = threading.Lock()


def record_browser_event(value: dict[str, Any], *, dom: bool = False) -> dict[str, Any]:
    recorded = dict(value)
    recorded["collector_receive_epoch_ms"] = time.time() * 1000.0
    with DOM_LOCK:
        (DOM_EVENTS if dom else BROWSER_EVENTS).append(recorded)
    return recorded


def parse_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    rows = sorted(values)
    index = max(0, min(len(rows) - 1, math.ceil(len(rows) * quantile) - 1))
    return round(rows[index], 3)


def stats(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "max_ms": round(max(values), 3) if values else None,
    }


class DomHandler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in {
            "http://127.0.0.1:3000", "http://127.0.0.1:3101",
            "http://localhost:3000", "http://localhost:3101",
        }:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path not in {"/dom-transition", "/browser-event"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(size))
            record_browser_event(value, dom=self.path == "/dom-transition")
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        return


class FastLaneCapture:
    def __init__(self, url: str, stop: threading.Event) -> None:
        self.url = url
        self.stop = stop
        self.events = 0
        self.reconnects = 0
        self.hud_source_updates = 0
        self.hud_raw_transitions = 0
        self.hud_display_transitions = 0
        self.focus_switches: list[dict[str, Any]] = []
        self.flow_headlines: list[dict[str, Any]] = []
        self.flow_semantics: list[dict[str, Any]] = []
        self.sse_receipt_ms: list[float] = []
        self.latest_hud: dict[str, Any] | None = None
        self.latest_pulse: dict[str, Any] | None = None

    @staticmethod
    def hud_raw_key(hud: dict[str, Any]) -> tuple:
        return tuple(
            (hud.get(side) or {}).get(field)
            for side in ("call", "put")
            for field in ("raw_edge_state", "raw_structure_state")
        )

    @staticmethod
    def hud_display_key(hud: dict[str, Any]) -> tuple:
        return (
            hud.get("display_revision"), hud.get("focus_strike"), hud.get("data_quality"),
            *(
                (hud.get(side) or {}).get(field)
                for side in ("call", "put")
                for field in ("display_edge_state", "display_structure_state")
            ),
        )

    def consume_hud(self, hud: dict[str, Any], received_ms: float) -> None:
        self.hud_source_updates += 1
        prior = self.latest_hud
        if prior and self.hud_raw_key(prior) != self.hud_raw_key(hud):
            self.hud_raw_transitions += 1
        if prior and self.hud_display_key(prior) != self.hud_display_key(hud):
            self.hud_display_transitions += 1
        if prior and prior.get("focus_strike") != hud.get("focus_strike"):
            self.focus_switches.append({
                "received_epoch_ms": received_ms,
                "before": prior.get("focus_strike"),
                "after": hud.get("focus_strike"),
                "before_revision": prior.get("revision"),
                "after_revision": hud.get("revision"),
                "call_contract": (hud.get("call") or {}).get("contract"),
                "put_contract": (hud.get("put") or {}).get("contract"),
            })
        self.latest_hud = hud

    def consume_pulse(self, pulse: dict[str, Any], received_ms: float) -> None:
        prior = self.latest_pulse or {}
        if prior.get("headline") != pulse.get("headline"):
            self.flow_headlines.append({
                "received_epoch_ms": received_ms,
                "source_timestamp": pulse.get("source_timestamp"),
                "before": prior.get("headline"), "after": pulse.get("headline"),
                "model": pulse.get("model"), "key_level": pulse.get("key_level"),
            })
        semantic = pulse.get("semantic") or {}
        prior_semantic = prior.get("semantic") or {}
        if semantic != prior_semantic:
            self.flow_semantics.append({
                "received_epoch_ms": received_ms,
                "source_timestamp": pulse.get("source_timestamp"),
                "market": semantic.get("market"), "pressure": semantic.get("pressure"),
                "result": semantic.get("result"), "speed": semantic.get("speed"),
            })
        self.latest_pulse = pulse

    def consume(self, event: dict[str, Any]) -> None:
        received_ms = time.time() * 1000.0
        self.events += 1
        published = parse_epoch(event.get("published_at"))
        if published is not None:
            self.sse_receipt_ms.append(max(0.0, received_ms - published * 1000.0))
        if event.get("flow_pulse"):
            self.consume_pulse(event["flow_pulse"], received_ms)
        feeds = event.get("feeds") or {}
        chart = ((feeds.get("futures_chart") or {}).get("data") or {})
        if chart.get("decision_hud"):
            self.consume_hud(chart["decision_hud"], received_ms)
        pulse = ((feeds.get("order_flow") or {}).get("data") or {}).get("flow_pulse")
        if pulse:
            self.consume_pulse(pulse, received_ms)

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                request = Request(self.url, headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"})
                with urlopen(request, timeout=15) as response:
                    for raw in response:
                        if self.stop.is_set():
                            break
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if event:
                            self.consume(event)
            except Exception:
                if not self.stop.is_set():
                    self.reconnects += 1


def appended_rows(path: Path, offset: int) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= offset:
        return []
    result = []
    with path.open("rb") as handle:
        handle.seek(offset)
        for raw in handle:
            try:
                result.append(json.loads(raw))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    return result


def raw_packet_payload(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("payload") if isinstance(row.get("payload"), dict) else row


def packet_dom_latency(raw_rows: list[dict[str, Any]], dom_rows: list[dict[str, Any]]) -> list[float]:
    by_strike: dict[float, list[float]] = {}
    for row in raw_rows:
        payload = raw_packet_payload(row)
        strike = payload.get("strike")
        timestamp = parse_epoch(payload.get("receive_wall_utc") or payload.get("receive_time_ist"))
        if isinstance(strike, (int, float)) and timestamp is not None:
            by_strike.setdefault(float(strike), []).append(timestamp * 1000.0)
    for values in by_strike.values():
        values.sort()
    result = []
    for row in dom_rows:
        strike = row.get("focus_strike")
        commit = row.get("commit_epoch_ms")
        values = by_strike.get(float(strike)) if isinstance(strike, (int, float)) else None
        if not values or not isinstance(commit, (int, float)):
            continue
        index = bisect.bisect_right(values, float(commit)) - 1
        if index >= 0:
            result.append(max(0.0, float(commit) - values[index]))
    return result


def initial_fast_lane(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def projection_hot_path(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stages = {"packet_to_raw": [], "raw_to_event": [], "event_to_payload": []}
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        stamps = payload.get("latency_timestamps") if isinstance(payload.get("latency_timestamps"), dict) else {}
        points = [stamps.get(key) for key in (
            "t0_packet_receive_ns", "t1_raw_feature_ready_ns",
            "t2_semantic_event_committed_ns", "t3_canonical_payload_ready_ns",
        )]
        if not all(isinstance(value, int) for value in points):
            continue
        for name, left, right in zip(stages, points, points[1:]):
            if right >= left:
                stages[name].append((right - left) / 1_000_000.0)
    return {name: stats(values) for name, values in stages.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=float, default=300.0)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--dom-port", type=int, default=8110)
    parser.add_argument("--raw-journal", type=Path, required=True)
    parser.add_argument("--projection-journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    projection_follower = RotatingJsonlFollower(
        args.projection_journal, required_projection_fields=True,
    )
    projection_follower.start(from_end=True)
    capture_attached_at_ns = projection_follower.attached_at_ns
    raw_offset = args.raw_journal.stat().st_size if args.raw_journal.exists() else 0
    baseline = initial_fast_lane(f"{args.api}/v1/oracle/fast-lane")
    recorder_at_t0 = initial_fast_lane(f"{args.api}/v1/oracle/fast-lane/health").get("recorder", {})
    stop = threading.Event()
    capture = FastLaneCapture(f"{args.api}/v1/oracle/fast-lane/stream", stop)
    dom_server = ThreadingHTTPServer(("127.0.0.1", args.dom_port), DomHandler)
    sse_thread = threading.Thread(target=capture.run, daemon=True)
    sse_thread.start()
    started_at_ns = time.perf_counter_ns()
    started_at = datetime.now(timezone.utc)
    deadline = time.monotonic() + args.duration_seconds
    dom_server.timeout = min(0.5, max(0.05, args.duration_seconds))
    while time.monotonic() < deadline:
        dom_server.handle_request()
    stop.set()
    dom_server.server_close()
    sse_thread.join(timeout=16)
    projection_follower.stop()
    health_at_end = initial_fast_lane(f"{args.api}/v1/oracle/fast-lane/health")

    raw_rows = appended_rows(args.raw_journal, raw_offset)
    projection_rows = list(projection_follower.rows)
    with DOM_LOCK:
        dom_rows = list(DOM_EVENTS)
        browser_rows = list(BROWSER_EVENTS)
    packet_rows = [raw_packet_payload(row) for row in raw_rows]
    packet_roles = Counter(str(row.get("instrument_role") or "UNKNOWN") for row in packet_rows)
    projection_types = Counter(str(row.get("event_type") or "UNKNOWN") for row in projection_rows)
    flow_revisions = [
        int(row["payload"]["revision"])
        for row in projection_rows
        if row.get("event_type") == "FLOW_PROJECTION"
        and isinstance(row.get("payload"), dict)
        and isinstance(row["payload"].get("revision"), int)
    ]
    browser_to_commit = [
        float(row["commit_epoch_ms"]) - float(row["browser_receive_epoch_ms"])
        for row in dom_rows
        if isinstance(row.get("commit_epoch_ms"), (int, float))
        and isinstance(row.get("browser_receive_epoch_ms"), (int, float))
    ]
    publish_to_commit = [
        float(row["commit_epoch_ms"]) - published * 1000.0
        for row in dom_rows
        if isinstance(row.get("commit_epoch_ms"), (int, float))
        and (published := parse_epoch(row.get("published_at"))) is not None
    ]
    chart = ((baseline.get("feeds") or {}).get("futures_chart") or {}).get("data") or {}
    order_flow = ((baseline.get("feeds") or {}).get("order_flow") or {}).get("data") or {}
    pulse = order_flow.get("flow_pulse") or {}
    result = {
        "certification": "GENUINE_LIVE_MEASUREMENT" if raw_rows and capture.events and dom_rows else "INSUFFICIENT_LIVE_EVIDENCE",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "requested_duration_seconds": args.duration_seconds,
        "collector_mode": "AUTO_TERMINATING_EVENT_DRIVEN_NO_POLLING",
        "dhan_packets": {"count": len(packet_rows), "roles": dict(packet_roles)},
        "recorder": {
            "raw_bytes_appended": max(0, (args.raw_journal.stat().st_size if args.raw_journal.exists() else 0) - raw_offset),
            "raw_rows": len(raw_rows), "projection_rows": len(projection_rows),
            "projection_event_types": dict(projection_types),
            "projection_capture": {
                "attached_before_t0": bool(capture_attached_at_ns and capture_attached_at_ns <= started_at_ns),
                "attached_at_monotonic_ns": capture_attached_at_ns,
                "certified_t0_monotonic_ns": started_at_ns,
                "first_row_at_monotonic_ns": projection_follower.first_row_at_ns,
                "errors": projection_follower.errors,
                "canonical_rotation_aware": True,
                "revisions_chronological": all(
                    right >= left for left, right in zip(flow_revisions, flow_revisions[1:])
                ),
                "first_revision": flow_revisions[0] if flow_revisions else None,
                "last_revision": flow_revisions[-1] if flow_revisions else None,
            },
        },
        "sse": {"events": capture.events, "reconnects": capture.reconnects, "receipt_latency": stats(capture.sse_receipt_ms)},
        "latency": {
            "schema": "ORACLE_CERTIFICATION_LATENCY_V2",
            "hot_path": {
                **projection_hot_path(projection_rows),
                "payload_to_sse": (health_at_end.get("event_to_sse_yield_ms") or {}),
                "sse_to_browser": stats(capture.sse_receipt_ms),
                "browser_to_dom": stats(browser_to_commit),
                "packet_to_dom": stats(packet_dom_latency(raw_rows, dom_rows)),
            },
            "persistence_path": {
                "at_t0": recorder_at_t0,
                "at_end": health_at_end.get("recorder", {}),
            },
            "old_persistence_age_is_decision_latency": False,
        },
        "hud": {
            "source_updates": capture.hud_source_updates,
            "raw_transitions": capture.hud_raw_transitions,
            "display_transitions": capture.hud_display_transitions,
            "focus_switches": capture.focus_switches,
            "dom_transitions": len(dom_rows),
            "dom_color_transitions": sum(
                1 for left, right in zip(dom_rows, dom_rows[1:])
                for side in ("call", "put") for field in ("edge_color", "structure_color")
                if (left.get(side) or {}).get(field) != (right.get(side) or {}).get(field)
            ),
            "browser_receive_to_dom": stats(browser_to_commit),
            "publish_to_dom": stats(publish_to_commit),
            "packet_to_dom_action": stats(packet_dom_latency(raw_rows, dom_rows)),
        },
        "flow_pulse": {"headline_transitions": capture.flow_headlines, "semantic_transitions": capture.flow_semantics},
        "levels": {
            "open_range": pulse.get("open_range"),
            "pdh": (pulse.get("levels") or {}).get("PDH"),
            "pdl": (pulse.get("levels") or {}).get("PDL"),
            "previous_close": (pulse.get("levels") or {}).get("PREVIOUS CLOSE"),
            "chart_decision_hud_focus": (chart.get("decision_hud") or {}).get("focus_strike"),
        },
        "dom_events": dom_rows,
        "browser_events": browser_rows,
        "browser": {
            "eventsource_connects": sum(row.get("event_type") == "EVENTSOURCE_CONNECTED" for row in browser_rows),
            "eventsource_disconnects": sum(row.get("event_type") == "EVENTSOURCE_DISCONNECTED" for row in browser_rows),
            "failed_fetch_count": sum(row.get("event_type") == "FETCH_FAILED" for row in browser_rows),
            "failed_fetches": [row for row in browser_rows if row.get("event_type") == "FETCH_FAILED"],
            "sse_revisions": [row.get("revision") for row in browser_rows if row.get("event_type") == "SSE_REVISION"],
        },
        "live_pass_claimed_by_collector": False,
        "note": "Review evidence before assigning PASS; collector never self-certifies trading behavior.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "certification": result["certification"], "dhan_packets": len(packet_rows), "sse_events": capture.events, "dom_transitions": len(dom_rows)}))


if __name__ == "__main__":
    main()
