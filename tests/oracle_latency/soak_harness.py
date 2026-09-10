#!/usr/bin/env python3
"""
CITADEL ORACLE — Market-Hours Soak Harness
==========================================
Run during live NSE session (09:15–15:30 IST) to measure actual end-to-end
latency for every Oracle provider path.

Usage:
    python tests/oracle_latency/soak_harness.py [--duration 3600] [--out results.json]

Label semantics:
    AFTER-HOURS SYNTHETIC VERIFICATION  — no live quotes, inter-event gaps ~5–13s
    MARKET-HOURS VALIDATION PENDING     — must remain until real session data exists

Market-hours targets (NOT claimable tonight):
    quote p95 <= 300ms after backend receipt
    Decision Envelope fast path p95 <= 250ms
    ARGUS/OSE p95 <= 750ms after canonical backend output
    VOB visible <= 1000ms after authoritative completed 5m candle
    chart identity switch p95 <= 500ms
    SSE-to-visible-paint p95 <= 100ms
    zero wrong-contract events
    zero duplicate WebSockets
    zero old-revision overwrites
    zero broker/order/position mutations
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


ORACLE_BASE_URL = "http://127.0.0.1:8000"
SSE_STREAM_URL = f"{ORACLE_BASE_URL}/v1/oracle/live-workspace/stream"
PROJECTION_URL = f"{ORACLE_BASE_URL}/v1/oracle/live-workspace"

REQUIRED_SAFETY = {
    "advisory_only": True,
    "broker_submission": False,
    "execution_authority": False,
    "execution_influence": "ZERO",
    "live_trading_enabled": False,
    "paper_only": True,
}

TARGETS = {
    "quote_p95_ms": 300,
    "decision_fast_path_p95_ms": 250,
    "argus_ose_p95_ms": 750,
    "vob_candle_ms": 1000,
    "identity_switch_p95_ms": 500,
    "sse_to_paint_p95_ms": 100,
}


@dataclass
class EventRecord:
    # Identity
    symbol: str
    security_id: str | None
    identity_epoch: int | None
    provider: str
    # Timestamps (ISO strings from payload where available)
    source_ts: str | None
    gateway_received_ts: str | None
    calculation_started_ts: str | None
    calculation_completed_ts: str | None
    sse_published_ts: str | None
    browser_received_ts: str  # wall-clock ISO at this process
    # Derived latency (ms)
    backend_receipt_to_sse_ms: float | None = None
    sse_to_browser_ms: float | None = None
    end_to_end_ms: float | None = None
    # Stream metadata
    event_revision: int | None = None
    queue_depth: int | None = None
    dropped_count: int | None = None
    coalesced_count: int | None = None
    reconnect_count: int = 0
    freshness: str | None = None
    active_subscriptions: int | None = None
    wrong_contract_rejection_count: int = 0
    # Safety
    safety: dict = field(default_factory=dict)
    safety_ok: bool = True
    futures_forecast: dict = field(default_factory=dict)


def _parse_epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _detect_provider(proj: dict, prev_symbol: str | None) -> str:
    chart = proj.get("chart_state") or {}
    symbol = (chart.get("symbol") or {}).get("raw_symbol", "")
    if prev_symbol and symbol and symbol != prev_symbol:
        return "identity_switch"
    phase5 = proj.get("phase5", {})
    if phase5.get("guardian_action") or phase5.get("paper_order_state"):
        return "guardian_ledger"
    decision = proj.get("decision", {})
    tel = proj.get("health", {}).get("telemetry", {})
    if decision.get("decision_id") and decision.get("freshness") == "LIVE":
        return "decision_fast_path"
    if tel.get("argus_retrieval", {}).get("latest_ms", 0):
        return "argus"
    if tel.get("ose_retrieval", {}).get("latest_ms", 0):
        return "ose"
    if tel.get("vob_retrieval", {}).get("latest_ms", 0):
        return "vob_candle"
    if tel.get("exact_premium_candle_retrieval", {}).get("sample_count", 0) > 0:
        return "quote"
    return "decision"


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[max(0, int(len(s) * p) - 1)]


def run_soak(duration_seconds: float, output_path: str, label: str) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    t_deadline = time.perf_counter() + duration_seconds
    reconnects = 0
    last_revision = -1
    prev_symbol: str | None = None
    total_events = 0
    safety_violations: list[str] = []
    provider_latencies: dict[str, list[float]] = defaultdict(list)
    records: list[dict] = []

    print(f"[SOAK] {label}", flush=True)
    print(f"[SOAK] Duration={duration_seconds:.0f}s  URL={SSE_STREAM_URL}", flush=True)
    print(f"[SOAK] Targets: {TARGETS}", flush=True)
    print("=" * 72, flush=True)

    # Safety pre-flight
    try:
        raw = urllib.request.urlopen(PROJECTION_URL, timeout=5).read()
        proj = json.loads(raw)
        safety = proj.get("safety", {})
        for k, expected in REQUIRED_SAFETY.items():
            if safety.get(k) != expected:
                print(f"ABORT: safety pre-flight {k}={safety.get(k)!r} != {expected!r}")
                return 1
        print("[SOAK] Safety pre-flight: PASS", flush=True)
    except Exception as exc:
        print(f"ABORT: cannot reach {PROJECTION_URL}: {exc}")
        return 1

    while time.perf_counter() < t_deadline:
        try:
            req = urllib.request.Request(
                SSE_STREAM_URL,
                headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
            )
            remaining = t_deadline - time.perf_counter()
            with urllib.request.urlopen(req, timeout=min(remaining, 60.0)) as resp:
                for raw_line in resp:
                    if time.perf_counter() >= t_deadline:
                        break
                    # IMPORTANT: use time.time() (Unix epoch) not perf_counter() (uptime)
                    browser_epoch = time.time()
                    browser_iso = datetime.now(timezone.utc).isoformat()
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue

                    proj = payload.get("projection", payload)
                    health = proj.get("health", {})
                    safety = proj.get("safety", {})

                    # Skip SSE control/heartbeat events: no safety block means
                    # this is a stream keepalive or internal control event, not a projection.
                    if not safety:
                        continue

                    revision = health.get("changes") or 0
                    tel = health.get("telemetry", {})
                    chart = proj.get("chart_state") or {}
                    decision = proj.get("decision", {})
                    forecast = proj.get("futures_forecast") or {}

                    # Only flag old-revision overwrites on real projection events
                    if last_revision >= 0 and revision < last_revision:
                        msg = f"OLD_REVISION: got {revision} after {last_revision}"
                        safety_violations.append(msg)
                        print(f"  !! {msg}", flush=True)
                    if revision > last_revision:
                        last_revision = revision

                    symbol = (chart.get("symbol") or {}).get("raw_symbol", "UNKNOWN")
                    provider = _detect_provider(proj, prev_symbol)
                    if symbol != "UNKNOWN":
                        prev_symbol = symbol

                    wrong_contract = 1 if decision.get("current_contract_rejected") else 0

                    gen_epoch = _parse_epoch(proj.get("generated_timestamp"))
                    src_epoch = _parse_epoch(proj.get("source_timestamp"))
                    e2e_ms: float | None = None
                    sse_ms: float | None = None
                    if gen_epoch:
                        sse_ms = (browser_epoch - gen_epoch) * 1000
                    if src_epoch:
                        e2e_ms = (browser_epoch - src_epoch) * 1000

                    rec = EventRecord(
                        symbol=symbol,
                        security_id=(chart.get("instrument") or {}).get("security_id"),
                        identity_epoch=revision,
                        provider=provider,
                        source_ts=proj.get("source_timestamp"),
                        gateway_received_ts=proj.get("received_timestamp"),
                        calculation_started_ts=health.get("last_success_at"),
                        calculation_completed_ts=proj.get("generated_timestamp"),
                        sse_published_ts=browser_iso,  # proxy — no separate server publish stamp in payload
                        browser_received_ts=browser_iso,
                        backend_receipt_to_sse_ms=sse_ms,
                        sse_to_browser_ms=sse_ms,
                        end_to_end_ms=e2e_ms,
                        event_revision=revision,
                        dropped_count=health.get("duplicates"),
                        reconnect_count=reconnects,
                        freshness=decision.get("freshness"),
                        wrong_contract_rejection_count=wrong_contract,
                        safety=safety,
                        futures_forecast={
                            "forecast_revision": forecast.get("forecast_revision"),
                            "forecast_id": forecast.get("forecast_id"),
                            "source_bar_timestamp": forecast.get("source_bar_timestamp"),
                            "instrument": forecast.get("instrument"),
                            "future_timestamps": forecast.get("future_timestamps", []),
                            "status": forecast.get("status"),
                            "kronos": forecast.get("kronos"),
                            "chronos": forecast.get("chronos"),
                            "tirex": forecast.get("tirex"),
                            "orchestrator": forecast.get("orchestrator"),
                        },
                    )

                    # Safety check per event
                    for k, expected in REQUIRED_SAFETY.items():
                        if safety.get(k) != expected:
                            msg = f"SAFETY_VIOLATION: {k}={safety.get(k)!r} rev={revision}"
                            safety_violations.append(msg)
                            rec.safety_ok = False

                    # Accumulate latencies
                    if sse_ms is not None:
                        provider_latencies[provider].append(sse_ms)
                    # Server-side telemetry latencies for each sub-provider
                    for tel_key, prov in [
                        ("argus_retrieval", "tel:argus"),
                        ("ose_retrieval", "tel:ose"),
                        ("vob_retrieval", "tel:vob_candle"),
                        ("decision_envelope", "tel:decision_fast_path"),
                        ("exact_premium_candle_retrieval", "tel:quote"),
                    ]:
                        lms = tel.get(tel_key, {}).get("latest_ms")
                        if lms and lms > 0:
                            provider_latencies[prov].append(lms)

                    total_events += 1
                    records.append(asdict(rec))

                    eta = t_deadline - time.perf_counter()
                    lat = f"sse={sse_ms:.0f}ms" if sse_ms else "sse=?"
                    e2e = f"e2e={e2e_ms:.0f}ms" if e2e_ms else "e2e=?"
                    print(
                        f"[{total_events:04d}] rev={revision:<4} provider={provider:<18} "
                        f"{lat}  {e2e}  freshness={rec.freshness}  eta={eta:.0f}s",
                        flush=True,
                    )

        except Exception as exc:
            reconnects += 1
            print(f"[SOAK] RECONNECT #{reconnects}: {exc}", flush=True)
            time.sleep(min(2.0, max(0, t_deadline - time.perf_counter())))

    finished_at = datetime.now(timezone.utc).isoformat()

    # Final report
    print("\n" + "=" * 72, flush=True)
    print(f"SOAK COMPLETE — {label}", flush=True)
    print("=" * 72, flush=True)

    all_pass = True
    checks = [
        ("quote",              "quote_p95_ms",              "Quote visible p95"),
        ("decision_fast_path", "decision_fast_path_p95_ms", "Decision Envelope fast path p95"),
        ("argus",              "argus_ose_p95_ms",          "ARGUS p95"),
        ("ose",                "argus_ose_p95_ms",          "OSE p95"),
        ("vob_candle",         "vob_candle_ms",             "VOB 5m candle p95"),
        ("identity_switch",    "identity_switch_p95_ms",    "Identity switch p95"),
    ]
    for provider, target_key, lbl in checks:
        samples = provider_latencies.get(provider, [])
        target = TARGETS[target_key]
        if not samples:
            print(f"  {lbl}: NO DATA  [{label}]", flush=True)
            continue
        p95_val = pct(samples, 0.95)
        p50_val = pct(samples, 0.50)
        ok = p95_val <= target
        if not ok:
            all_pass = False
        status = "PASS" if ok else "FAIL"
        print(
            f"  {lbl}: p95={p95_val:.0f}ms  p50={p50_val:.0f}ms  target≤{target}ms  "
            f"n={len(samples)}  [{status}]",
            flush=True,
        )

    print(f"\n  Total events      : {total_events}", flush=True)
    print(f"  Reconnects        : {reconnects}", flush=True)
    print(f"  Safety violations : {len(safety_violations)}", flush=True)
    for v in safety_violations:
        print(f"    !! {v}", flush=True)
        all_pass = False

    verdict = "PASS" if (all_pass and total_events > 0 and not safety_violations) else "FAIL"
    if "PENDING" in label:
        verdict = "MARKET-HOURS VALIDATION PENDING"

    print(f"\n  VERDICT: {verdict}", flush=True)

    output = {
        "label": label,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "total_events": total_events,
        "reconnects": reconnects,
        "targets": TARGETS,
        "safety_violations": safety_violations,
        "provider_p95_ms": {k: round(pct(v, 0.95), 1) for k, v in provider_latencies.items() if v},
        "provider_p50_ms": {k: round(pct(v, 0.50), 1) for k, v in provider_latencies.items() if v},
        "provider_sample_counts": {k: len(v) for k, v in provider_latencies.items()},
        "verdict": verdict,
        "records": records,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"[SOAK] Results written → {output_path}", flush=True)
    return 0 if verdict == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=3600.0,
                        help="Soak duration seconds (default 3600 = 1 market hour)")
    parser.add_argument("--out", default="tests/oracle_latency/soak_results.json")
    parser.add_argument("--synthetic", action="store_true",
                        help="Label as AFTER-HOURS SYNTHETIC VERIFICATION (no latency PASS claims)")
    args = parser.parse_args()
    label = (
        "AFTER-HOURS SYNTHETIC VERIFICATION"
        if args.synthetic
        else "MARKET-HOURS VALIDATION PENDING"
    )
    return run_soak(args.duration, args.out, label)


if __name__ == "__main__":
    sys.exit(main())
