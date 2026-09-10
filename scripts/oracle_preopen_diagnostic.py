#!/usr/bin/env python3
"""Read-only Oracle pre-open diagnostic; it never starts or controls services.

This command is deliberately observational.  It proves the already-running
launchd-owned runtime, Fast Lane cache, canonical basket, recorder, forecasts,
SSE admission, provenance and local storage without initiating a new Dhan
connection or mutating any Oracle state.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any, Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_BACKEND = "http://127.0.0.1:8000"
DEFAULT_FRONTEND = "http://127.0.0.1:3000"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _get(url: str, *, accept: str = "application/json") -> dict[str, Any]:
    started = perf_counter()
    try:
        request = Request(url, headers={"Accept": accept})
        with urlopen(request, timeout=5.0) as response:
            body = response.read() if accept == "application/json" else b""
            payload = json.loads(body) if body else None
            return {
                "http_status": int(response.status),
                "latency_ms": round((perf_counter() - started) * 1000.0, 3),
                "content_type": response.headers.get("Content-Type"),
                "valid_json": payload is not None if accept == "application/json" else None,
                "payload": payload,
                "error": None,
            }
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        return {
            "http_status": None,
            "latency_ms": round((perf_counter() - started) * 1000.0, 3),
            "content_type": None,
            "valid_json": False if accept == "application/json" else None,
            "payload": None,
            "error": f"{type(error).__name__}:{error}",
        }


def _sse(url: str) -> dict[str, Any]:
    """Verify SSE admission only; no long-lived subscriber is retained."""

    started = perf_counter()
    try:
        request = Request(url, headers={"Accept": "text/event-stream"})
        with urlopen(request, timeout=5.0) as response:
            return {
                "http_status": int(response.status),
                "latency_ms": round((perf_counter() - started) * 1000.0, 3),
                "content_type": response.headers.get("Content-Type"),
                "connected": "text/event-stream" in str(response.headers.get("Content-Type") or ""),
                "error": None,
            }
    except (URLError, TimeoutError) as error:
        return {
            "http_status": None,
            "latency_ms": round((perf_counter() - started) * 1000.0, 3),
            "content_type": None,
            "connected": False,
            "error": f"{type(error).__name__}:{error}",
        }


def _component(feed: Mapping[str, Any] | None, *, source: str) -> dict[str, Any]:
    value = _mapping(feed)
    data = _mapping(value.get("data"))
    meta = _mapping(value.get("meta"))
    return {
        "registered": bool(value),
        "initialized": value.get("ok") is not False,
        "available": value.get("ok"),
        "current_state": data.get("status") or data.get("state") or value.get("status"),
        "source": source,
        "freshness_truth": meta.get("freshness"),
        "last_good_timestamp": meta.get("source_timestamp") or data.get("source_timestamp") or data.get("generated_at"),
        "error": value.get("error") or data.get("reason"),
        "dependency": meta.get("module"),
    }


def _process_inventory() -> dict[str, Any]:
    output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    rows = [line.strip() for line in output.splitlines() if line.strip()]
    return {
        "backend_uvicorn": [row for row in rows if "uvicorn app.main:app" in row],
        "frontend_next": [row for row in rows if "next-server" in row],
        "gateway_owner_threads": [row for row in rows if "oracle-dhan-full-feed" in row],
    }


def _disk(path: Path) -> dict[str, Any]:
    stat = os.statvfs(path)
    available = stat.f_bavail * stat.f_frsize
    total = stat.f_blocks * stat.f_frsize
    return {
        "path": str(path),
        "available_bytes": available,
        "total_bytes": total,
        "available_percent": round(available / total * 100.0, 3) if total else None,
    }


def collect(backend: str, frontend: str) -> dict[str, Any]:
    backend = backend.rstrip("/")
    frontend = frontend.rstrip("/")
    live = _get(f"{backend}/health/live")
    ready = _get(f"{backend}/health/ready")
    fast_lane = _get(f"{backend}/v1/oracle/fast-lane")
    fast_health = _get(f"{backend}/v1/oracle/fast-lane/health")
    frontend_oracle = _get(f"{frontend}/oracle", accept="text/html")
    sse = _sse(f"{backend}/v1/oracle/fast-lane/stream")
    forecast_endpoints = {
        name: _get(f"{backend}{path}")
        for name, path in {
            "kronos": "/v1/kronos-alpha/status",
            "chronos_2": "/v1/chronos-2/status",
            "premium_intelligence": "/v1/premium-intelligence/status",
            "perception": "/v1/oracle/perception/diagnostics",
            "fusion_eod": "/v1/oracle/fusion-shadow/eod",
        }.items()
    }
    snapshot = _mapping(fast_lane.get("payload"))
    feeds = _mapping(snapshot.get("feeds"))
    order_flow = _mapping(_mapping(feeds.get("order_flow")).get("data"))
    transport = _mapping(order_flow.get("transport"))
    argus = _mapping(_mapping(_mapping(feeds.get("argus")).get("data")).get("data"))
    tactical = _mapping(argus.get("tactical_edge"))
    futures = _mapping(argus.get("futures"))
    instruments = [
        _mapping(item) for item in transport.get("instruments") or () if isinstance(item, Mapping)
    ]
    components = {
        name: _component(_mapping(feeds.get(feed)), source="ORACLE_FAST_LANE")
        for name, feed in {
            "argus_prime": "argus", "order_flow": "order_flow", "fusion_shadow": "fusion_shadow",
            "futures_chart": "futures_chart", "eye_perception": "eye_oracle_projection",
            "strategy_lab": "strategy_lab", "risk_status": "risk_status", "paper_status": "paper_status",
        }.items()
    }
    components.update({
        "flow_pulse": {
            "registered": "flow_pulse" in order_flow,
            "initialized": bool(order_flow.get("flow_pulse")),
            "available": order_flow.get("status") == "AVAILABLE",
            "current_state": _mapping(order_flow.get("flow_pulse")).get("directional_state") or order_flow.get("directional_state"),
            "source": "ORDER_FLOW_CANONICAL_PROJECTION",
            "freshness_truth": order_flow.get("data_quality"),
            "last_good_timestamp": _mapping(order_flow.get("flow_pulse")).get("source_timestamp"),
            "error": order_flow.get("reason"),
            "dependency": "CANONICAL_DHAN_FULL_PACKETS",
        },
        "ose": {"registered": True, "initialized": bool(tactical), "available": tactical.get("ose") is not None, "current_state": _mapping(tactical.get("ose")).get("state"), "source": "ARGUS_TACTICAL_EDGE", "freshness_truth": _mapping(tactical.get("ose")).get("freshness"), "last_good_timestamp": None, "error": None, "dependency": "ARGUS_OPTION_CHAIN"},
        "vob": {"registered": True, "initialized": bool(tactical), "available": tactical.get("vob") is not None, "current_state": _mapping(tactical.get("vob")).get("status"), "source": "ARGUS_TACTICAL_EDGE", "freshness_truth": _mapping(tactical.get("vob")).get("freshness"), "last_good_timestamp": None, "error": None, "dependency": "FINALIZED_CANDLES"},
        "gamma": {"registered": True, "initialized": bool(tactical), "available": tactical.get("gamma") is not None, "current_state": _mapping(tactical.get("gamma")).get("status"), "source": "ARGUS_TACTICAL_EDGE", "freshness_truth": _mapping(tactical.get("gamma")).get("freshness"), "last_good_timestamp": None, "error": None, "dependency": "OPTION_CHAIN"},
    })
    return {
        "diagnostic": "ORACLE_PREOPEN_READ_ONLY_V1",
        "backend": {key: {item: value for item, value in response.items() if item != "payload"} for key, response in {"live": live, "ready": ready, "fast_lane": fast_lane, "fast_lane_health": fast_health}.items()},
        "frontend": {"oracle": frontend_oracle},
        "sse": sse,
        "components": components,
        "forecast_and_research": {name: {key: value for key, value in response.items() if key != "payload"} | {"state": _mapping(response.get("payload")).get("status") or _mapping(response.get("payload")).get("model_status")} for name, response in forecast_endpoints.items()},
        "dhan": {
            "ws_owner_count": len(_process_inventory()["backend_uvicorn"]),
            "transport": {key: transport.get(key) for key in (
                "WS_CONNECTED", "EXPECTED_INSTRUMENTS", "REQUESTED_INSTRUMENTS", "ACK_STATUS",
                "BASKET_HEALTH", "FEED_GENERATION", "RECONNECT_COUNT", "CONNECTION_ATTEMPTS",
                "LAST_CONNECT_RESULT", "LAST_CONNECT_HTTP_STATUS", "LAST_SUCCESSFUL_CONNECTION_TS",
            )},
            "futures_contract": {key: futures.get(key) for key in ("symbol", "security_id", "expiry", "lot_size", "instrument_source")},
            "basket": {"count": len(instruments), "instruments": instruments},
        },
        "recorder": _mapping(_mapping(fast_health.get("payload")).get("recorder")),
        "runtime_provenance": _mapping(_mapping(ready.get("payload")).get("runtime_provenance") or _mapping(ready.get("payload")).get("provenance")),
        "process_inventory": _process_inventory(),
        "disk": _disk(Path.cwd()),
        "execution_safety": _mapping(snapshot.get("safety")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = collect(args.backend, args.frontend)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
