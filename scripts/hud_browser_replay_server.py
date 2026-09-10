#!/usr/bin/env python3
"""Deterministic SSE replay for the real Oracle chart-top decision HUD.

The server reuses a cached Oracle fast-lane document for the surrounding page
and publishes genuine 11-Aug DECISION_HUD_TRANSITION records through the same
futures_chart feed used in production.  It is an isolated browser contract
fixture; it does not synthesize market decisions or alter replayed raw fields.
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


CLIENTS: set[queue.Queue[dict]] = set()
CLIENTS_LOCK = threading.Lock()
CURRENT_DOCUMENT: dict = {}
REPLAY_ROWS: list[dict] = []
REPLAY_STATUS: dict = {"running": False, "source_updates": 0, "display_revisions": 0}
AUTO_STARTED = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def semantic_key(hud: dict) -> tuple:
    return (
        hud.get("focus_strike"),
        hud.get("data_quality"),
        tuple(
            (
                hud.get(side, {}).get("contract"),
                hud.get(side, {}).get("display_edge_state"),
                hud.get(side, {}).get("display_structure_state"),
                hud.get(side, {}).get("action"),
                hud.get(side, {}).get("hero_state"),
            )
            for side in ("call", "put")
        ),
    )


def atomic_display_rows(rows: list[dict]) -> list[dict]:
    """Apply only the repaired publication invariants to recorded snapshots."""
    result: list[dict] = []
    prior: tuple | None = None
    display_revision = 0
    for source in rows:
        hud = deepcopy(source)
        locked = hud.get("data_quality") != "GOOD"
        if locked:
            hud["data_quality"] = "LOCKED"
            for side in ("call", "put"):
                value = hud[side]
                value.update(
                    display_edge_state="DATA LOCKED",
                    display_structure_state="DATA LOCKED",
                    edge_state="DATA LOCKED",
                    structure_state="DATA LOCKED",
                    edge_strength=0.0,
                    structure_strength=0.0,
                    action="WAIT",
                    hero_state="DATA_LOCKED",
                )
        key = semantic_key(hud)
        if key != prior:
            display_revision += 1
            prior = key
        hud["raw_revision"] = hud.get("revision", 0)
        hud["display_revision"] = display_revision
        result.append(hud)
    return result


def event_for(hud: dict, index: int) -> dict:
    published = now_iso()
    chart_feed = deepcopy(CURRENT_DOCUMENT["feeds"]["futures_chart"])
    chart_feed["data"]["decision_hud"] = hud
    chart_feed["data"]["source_timestamp"] = hud.get("source_timestamp")
    chart_feed["data"]["age_seconds"] = 0.0
    chart_feed["data"]["freshness"] = "FRESH"
    chart_feed["meta"].update(
        health="HEALTHY", readiness="READY", last_updated=published, stale_reason=None
    )
    return {
        "event_id": f"hud-browser-replay-{index}-{time.time_ns()}",
        "event_type": "ORACLE_FAST_LANE_UPDATED",
        "published_at": published,
        "generated_at": published,
        "trace_id": "hud-browser-replay-2026-08-11",
        "symbol": "NIFTY",
        "feeds": {"futures_chart": chart_feed},
        "full": False,
    }


def publish(event: dict) -> int:
    with CLIENTS_LOCK:
        clients = tuple(CLIENTS)
    for client in clients:
        client.put(event)
    return len(clients)


def run_replay(interval_ms: float) -> None:
    global REPLAY_STATUS
    REPLAY_STATUS = {"running": True, "source_updates": 0, "display_revisions": 0}
    prior_revision = None
    for index, hud in enumerate(REPLAY_ROWS):
        CURRENT_DOCUMENT["feeds"]["futures_chart"]["data"]["decision_hud"] = deepcopy(hud)
        publish(event_for(hud, index))
        REPLAY_STATUS["source_updates"] += 1
        if hud["display_revision"] != prior_revision:
            REPLAY_STATUS["display_revisions"] += 1
            prior_revision = hud["display_revision"]
        time.sleep(interval_ms / 1000.0)
    REPLAY_STATUS["running"] = False


def delayed_replay(delay_ms: float, interval_ms: float) -> None:
    time.sleep(delay_ms / 1000.0)
    run_replay(interval_ms)


class Handler(BaseHTTPRequestHandler):
    interval_ms = 15.0
    auto_start_delay_ms = 0.0

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:3101")
        self.send_header("Access-Control-Allow-Headers", "Last-Event-ID")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/oracle/fast-lane":
            document = deepcopy(CURRENT_DOCUMENT)
            document["generated_at"] = now_iso()
            return self._json(document)
        if path == "/v1/oracle/fast-lane/stream":
            return self._stream()
        if path == "/replay/start":
            if not REPLAY_STATUS["running"]:
                threading.Thread(target=run_replay, args=(self.interval_ms,), daemon=True).start()
            return self._json({"started": True, "rows": len(REPLAY_ROWS)})
        if path == "/replay/status":
            return self._json(deepcopy(REPLAY_STATUS))
        if path.startswith("/v1/oracle/flow-pulse/paper-history"):
            return self._json({"sessions": [], "selected_session": None, "entry_legs": []})
        self.send_error(HTTPStatus.NOT_FOUND)

    def _json(self, value: dict) -> None:
        encoded = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _stream(self) -> None:
        global AUTO_STARTED
        client: queue.Queue[dict] = queue.Queue()
        with CLIENTS_LOCK:
            CLIENTS.add(client)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        if self.auto_start_delay_ms > 0 and not AUTO_STARTED:
            AUTO_STARTED = True
            threading.Thread(
                target=delayed_replay,
                args=(self.auto_start_delay_ms, self.interval_ms),
                daemon=True,
            ).start()
        try:
            self.wfile.write(b"event: oracle_fast_heartbeat\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = client.get(timeout=10.0)
                    encoded = json.dumps(event, separators=(",", ":")).encode()
                    self.wfile.write(b"event: oracle_fast_lane\ndata: " + encoded + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with CLIENTS_LOCK:
                CLIENTS.discard(client)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    global CURRENT_DOCUMENT, REPLAY_ROWS
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--baseline-url", default="http://127.0.0.1:8000/v1/oracle/fast-lane")
    parser.add_argument("--port", type=int, default=8102)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument("--interval-ms", type=float, default=15.0)
    parser.add_argument("--auto-start-delay-ms", type=float, default=0.0)
    args = parser.parse_args()
    with urlopen(args.baseline_url, timeout=10) as response:
        CURRENT_DOCUMENT = json.load(response)
    evidence = json.loads(args.evidence.read_text())
    rows = evidence["recorded_canonical_hud"]["ledger"]
    REPLAY_ROWS = atomic_display_rows(rows[args.start : args.start + args.count])
    if not REPLAY_ROWS:
        raise SystemExit("selected replay range contains no HUD rows")
    CURRENT_DOCUMENT["feeds"]["futures_chart"]["data"]["decision_hud"] = deepcopy(REPLAY_ROWS[0])
    Handler.interval_ms = args.interval_ms
    Handler.auto_start_delay_ms = args.auto_start_delay_ms
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
