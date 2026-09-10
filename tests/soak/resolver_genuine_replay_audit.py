"""Citadel Oracle — Resolver R1 Genuine Replay Audit (Zero Synthetic Data).

Executes strictly genuine recorded historical market data through the production ResolverEngine.
ZERO synthetic flow, ZERO synthetic VOB, ZERO synthetic OI, ZERO fake event IDs.
"""

from __future__ import annotations

import hashlib
import json
import resource
import time
from datetime import datetime
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from src.oracle.resolver_engine import ResolverEngine
from src.oracle.option_buyer_intelligence import _OiRollingTracker

IST = ZoneInfo("Asia/Kolkata")


def parse_ts(val: Any) -> datetime | None:
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=IST)
    if isinstance(val, str) and val:
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
        except Exception:
            return None
    return None


def run_genuine_telemetry_replay():
    dataset_path = "reports/oracle_full_truth_audit_20260821_112518/FULL_TRUTH_15M_TELEMETRY.jsonl"
    with open(dataset_path) as f:
        records = [json.loads(line) for line in f if line.strip()]

    engine = ResolverEngine()
    oi_tracker = _OiRollingTracker()
    ledger = []
    evaluation_latencies_us = []

    last_market_time: datetime | None = None
    future_data_violations = 0
    oi_arithmetic_recomputes = []
    
    # Genuine OI tracking per exact security_id
    for rec in records:
        market_time = parse_ts(rec.get("timestamp"))
        if not market_time:
            continue

        if last_market_time and market_time < last_market_time:
            future_data_violations += 1
        last_market_time = market_time

        session_date = str(market_time.date())
        if engine._session_id != session_date:
            engine.reset_session(session_date)
            oi_tracker.clear_all()

        # NOTE: Telemetry does NOT contain recorded NIFTY Futures 5L MLOFI.
        # Per Mission 2B.1 Stop Gate, we DO NOT synthesize flow. Flow remains None/unavailable.

        for side in ("CE", "PE"):
            prefix = "ce_" if side == "CE" else "pe_"
            sec_id = str(rec.get(f"{prefix}sec_id") or "")
            strike = rec.get(f"{prefix}strike")
            ltp = rec.get(f"{prefix}ltp")
            oi = rec.get(f"{prefix}oi")

            if not sec_id or oi is None or ltp is None:
                continue

            # Record exact real OI
            oi_tracker.record(sec_id, float(oi), float(ltp), market_time)

            curr_5m = oi_tracker.closed_window_metrics(sec_id, 5, market_time)
            prior_deltas = oi_tracker.prior_closed_window_deltas(sec_id, 5, market_time)
            oi_diag = engine.compute_oi_diagnostics(prior_deltas, curr_5m, market_time)

            # Option VOB: Telemetry has ce_vob_state ('TESTED') and pe_vob_state ('ACTIVE') without Horsepower events
            # We pass genuine payload without fake event IDs
            contract_payload = {
                "contract": {"security_id": sec_id, "strike": strike},
                "quote": {"security_id": sec_id, "strike": strike, "ltp": ltp, "oi": oi},
                "vob": {},  # Genuine: no manufactured horsepower events
            }

            # Flow diagnostics: Genuine empty flow series (returns unavailable)
            flow_diag = engine.compute_flow_diagnostics(market_time, market_time)

            t0 = time.perf_counter_ns()
            ev, diag = engine.synthesize_resolver_state(
                side=side,
                contract_payload=contract_payload,
                oi_diag=oi_diag,
                flow_diag=flow_diag,
                flow_payload=None,
                observed_at=market_time,
            )
            elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
            evaluation_latencies_us.append(elapsed_us)

            # Audit genuine real OI recompute if prior deltas exist
            if curr_5m and curr_5m.get("oi_delta") is not None and prior_deltas:
                med = float(median(prior_deltas))
                exp_x = round(abs(curr_5m["oi_delta"]) / med, 1) if med > 0 else None
                oi_arithmetic_recomputes.append({
                    "timestamp": market_time.isoformat(),
                    "side": side,
                    "security_id": sec_id,
                    "priors": list(prior_deltas),
                    "curr_delta": curr_5m["oi_delta"],
                    "median": med,
                    "expected_x": exp_x,
                    "engine_x": oi_diag.get("oi_x"),
                    "match": exp_x == oi_diag.get("oi_x"),
                })

            ledger.append({
                "timestamp": market_time.isoformat(),
                "side": side,
                "security_id": sec_id,
                "label": ev["label"],
                "variant": ev["variant"],
                "confluence_state": ev["confluence_state"],
                "pulse_key": ev["pulse_key"],
                "held_previous": ev["held_previous"],
            })

    ledger_json = json.dumps(ledger, sort_keys=True)
    l_hash = hashlib.sha256(ledger_json.encode("utf-8")).hexdigest()

    return {
        "dataset": dataset_path,
        "sample_count": len(records),
        "first_ts": records[0].get("timestamp"),
        "last_ts": records[-1].get("timestamp"),
        "total_evaluations": len(evaluation_latencies_us),
        "future_data_violations": future_data_violations,
        "oi_recomputes_count": len(oi_arithmetic_recomputes),
        "oi_recomputes_sample": oi_arithmetic_recomputes[:5],
        "distinct_labels": list(set(x["label"] for x in ledger)),
        "distinct_variants": list(set(x["variant"] for x in ledger)),
        "distinct_confluence_states": list(set(x["confluence_state"] for x in ledger)),
        "ledger_hash": l_hash,
    }


if __name__ == "__main__":
    res = run_genuine_telemetry_replay()
    print("Genuine Telemetry Replay Results (Zero Synthetic Data):")
    print(json.dumps(res, indent=2))
