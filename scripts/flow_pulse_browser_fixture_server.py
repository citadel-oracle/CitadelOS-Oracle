#!/usr/bin/env python3
"""Isolated SSE fixture for the Flow Pulse browser contract proof."""

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


CLIENTS: set[queue.Queue[dict]] = set()
CLIENTS_LOCK = threading.Lock()
CURRENT_PULSE: dict = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def baseline_pulse() -> dict:
    return {
        "revision": 1, "action_revision": 1, "semantic_revision": 1,
        "state": "WATCH", "headline": "WATCH", "model": "MODEL 2 · TREND",
        "story": "OR LOW APPROACHING", "side": None,
        "source_timestamp": "2026-08-11T03:45:48.803891+00:00",
        "data_quality": "GOOD", "flow_state": "MIXED",
        "futures": {"ltp": 24602.0, "trigger": 24601.5, "trigger_text": "FUT AT 24601.50", "invalidation": None, "target_1": None, "target_2": None},
        "option": None,
        "semantic": {"market": "BALANCED ↔", "pressure": "MIXED", "result": "FLOW NOT CLEAN ENOUGH", "speed": "NORMAL"},
        "flow": {"buy_volume": 20, "sell_volume": 22, "unknown_volume": 3, "buy_bursts": 1, "sell_bursts": 1, "unknown_bursts": 0},
        "tape": {"events_per_second": 4.0, "executed_volume_per_second": 45.0},
        "profile": {"revision": 1, "val": 24595.0, "poc": 24601.5, "vah": 24610.0},
        "levels": {"OR LOW": 24601.5, "OR HIGH": 24618.0, "PDL": 24641.19921875, "opening_range_available": True},
        "key_level": {"name": "OR LOW", "label": "OR LOW 24601.50", "price": 24601.5, "state": "APPROACHING"},
        "next_level": {"name": "OR LOW", "price": 24601.5, "distance_points": 0.5, "state": "APPROACHING"},
        "what_happened": "OR LOW APPROACHING",
        "open_range": {"status": "SET", "label": "OPEN RANGE 24601.50–24618.00 · SET"},
        "live_health": {"status": "LIVE", "last_packet_age_ms": 2.0, "last_semantic_revision": 1, "last_action_revision": 1},
        "paper_trades": [], "paper_episodes": [],
    }


def meter_pulse() -> dict:
    pulse = baseline_pulse()
    pulse.update({
        "revision": 2, "semantic_revision": 2,
        "source_timestamp": "2026-08-11T03:46:12.650208+00:00",
        "semantic": {"market": "ACCEPTING LOWER ↓", "pressure": "SELLERS STRONG", "result": "PRICE FALLING WITH SELLERS", "speed": "FAST"},
        "flow_state": "SELLING STRONG",
        "flow": {"buy_volume": 42, "sell_volume": 310, "unknown_volume": 17, "buy_bursts": 1, "sell_bursts": 7, "unknown_bursts": 1},
        "futures": {"ltp": 24600.099609375, "trigger": 24601.5, "trigger_text": "FUT BELOW 24601.50", "invalidation": None, "target_1": None, "target_2": None},
        "key_level": {"name": "OR LOW", "label": "OR LOW 24601.50", "price": 24601.5, "state": "BROKE BELOW"},
        "next_level": {"name": "VAL", "price": 24595.0, "distance_points": 5.1, "state": "APPROACHING"},
        "what_happened": "OR LOW BROKE BELOW",
        "live_health": {"status": "LIVE", "last_packet_age_ms": 1.0, "last_semantic_revision": 2, "last_action_revision": 1},
    })
    return pulse


def action_pulse() -> dict:
    return {
        "revision": 2, "semantic_revision": 2, "headline": "EARLY BUY PE",
        "model": "MODEL 2 · TREND", "story": "LOW BROKE → BUYERS FAILED → SELLERS BACK",
        "key_level": {"name": "OR LOW", "label": "OR LOW 24601.50", "price": 24601.5, "state": "BROKE BELOW"},
        "trigger": 24601.5,
        "option": {"strike": 24550.0, "option_type": "PE", "bid": 73.75, "ask": 73.80000305175781, "status": "AVAILABLE"},
        "stop": 24601.5, "target_1": None, "target_2": 24595.0,
        "episode_state": "EARLY BUY PE", "source_timestamp": "2026-08-11T03:46:13.319782+00:00",
        "packet_receive_ns": 4137319782, "action_ready_ns": 4137419782,
    }


class Handler(BaseHTTPRequestHandler):
    fixture: dict = {}

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:3101")
        self.send_header("Access-Control-Allow-Headers", "Last-Event-ID")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/oracle/fast-lane":
            document = deepcopy(self.fixture)
            document["generated_at"] = now_iso()
            order_flow = document["feeds"]["order_flow"]
            order_flow["ok"] = True
            order_flow["data"]["flow_pulse"] = deepcopy(CURRENT_PULSE)
            order_flow["meta"].update({
                "health": "HEALTHY", "readiness": "READY",
                "last_updated": document["generated_at"], "stale_reason": None,
            })
            return self._json(document)
        if path == "/v1/oracle/fast-lane/stream":
            return self._stream()
        if path == "/emit/meters":
            return self._emit("FLOW_PULSE_METERS", meter_pulse())
        if path == "/emit/action":
            return self._emit("FLOW_PULSE_ACTION", action_pulse())
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

    def _emit(self, event_type: str, pulse: dict) -> None:
        global CURRENT_PULSE
        if event_type == "FLOW_PULSE_METERS":
            CURRENT_PULSE = {**CURRENT_PULSE, **deepcopy(pulse)}
        else:
            futures = dict(CURRENT_PULSE.get("futures") or {})
            futures.update({
                "trigger": pulse.get("trigger"), "invalidation": pulse.get("stop"),
                "target_1": pulse.get("target_1"), "target_2": pulse.get("target_2"),
            })
            CURRENT_PULSE.update({
                "action_revision": pulse.get("revision"),
                "semantic_revision": pulse.get("semantic_revision"),
                "headline": pulse.get("headline"), "model": pulse.get("model"),
                "story": pulse.get("story"), "key_level": deepcopy(pulse.get("key_level")),
                "state": pulse.get("episode_state"), "side": "PE", "option": deepcopy(pulse.get("option")),
                "source_timestamp": pulse.get("source_timestamp"), "futures": futures,
            })
        published = now_iso()
        event = {
            "event_id": f"browser-proof-{time.time_ns()}", "event_type": event_type,
            "published_at": published, "generated_at": published, "trace_id": "flow-pulse-browser-proof",
            "symbol": "NIFTY", "flow_pulse": pulse, "full": False,
        }
        with CLIENTS_LOCK:
            clients = tuple(CLIENTS)
        for client in clients:
            client.put(event)
        self._json({"published": len(clients), "event": event})

    def _stream(self) -> None:
        client: queue.Queue[dict] = queue.Queue()
        with CLIENTS_LOCK:
            CLIENTS.add(client)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
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
    global CURRENT_PULSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8101)
    args = parser.parse_args()
    CURRENT_PULSE = baseline_pulse()
    Handler.fixture = json.loads(args.fixture.read_text())
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
