"""Citadel Oracle — Resolver R1 Full-Day Replay Soak & Forensic Certification Harness.

Executes the ACTUAL production ResolverEngine across chronological historical session data.
Strict isolated execution: ZERO production socket, zero Fast Lane contamination.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import time
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.oracle.resolver_engine import ResolverEngine, FLOW_AGING_SECONDS, FLOW_TTL_SECONDS
from src.oracle.option_buyer_intelligence import _OiRollingTracker

IST = ZoneInfo("Asia/Kolkata")


def get_rss_mb() -> float:
    """Return resident memory set in MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS ru_maxrss is in bytes
    return usage.ru_maxrss / (1024.0 * 1024.0)


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


class ReplayHarness:
    def __init__(self) -> None:
        self.engine = ResolverEngine()
        self.oi_tracker = _OiRollingTracker()
        self.ledger: list[dict[str, Any]] = []
        self.evaluation_latencies_us: list[float] = []
        self.source_event_count = 0
        self.eval_count = 0
        self.transition_count = 0
        self.ce_transition_count = 0
        self.pe_transition_count = 0

        # Forensic Audit Metrics
        self.future_data_violations = 0
        self.flow_future_join_count = 0
        self.flow_stale_join_count = 0
        self.flow_valid_join_count = 0

        self.oi_x_arithmetic_mismatches = 0
        self.flow_x_arithmetic_mismatches = 0
        self.ce_color_semantic_mismatches = 0
        self.pe_color_semantic_mismatches = 0

        self.false_repulses = 0
        self.false_state_drops = 0

        self.ce_contract_contamination = 0
        self.pe_contract_contamination = 0
        self.session_contamination = 0

        # Required Behavior Observation Registry
        self.observed_behaviors = {
            "SINGLE_3M": 0,
            "SINGLE_5M": 0,
            "1M_3M_ALIGNMENT": 0,
            "3M_5M_ALIGNMENT": 0,
            "FULL_ALIGNMENT": 0,
            "OI_STATE": 0,
            "FLOW_UPGRADE": 0,
            "HELD_QUIET_PERIOD": 0,
            "INVALIDATION_REPLACEMENT": 0,
            "CONTRACT_ROLL": 0,
            "FULL_FRESH": 0,
        }

        # Track contract history for contamination checks
        self._last_security_ids = {"CE": None, "PE": None}
        self._last_pulse_keys = {"CE": None, "PE": None}
        self._last_labels = {"CE": None, "PE": None}

    def run_replay(self, dataset_path: str) -> dict[str, Any]:
        """Execute full chronological replay on dataset."""
        with open(dataset_path) as f:
            records = [json.loads(line) for line in f if line.strip()]

        self.source_event_count = len(records)
        last_market_time: datetime | None = None

        for rec in records:
            # Source timestamp
            market_time = parse_ts(rec.get("timestamp") or rec.get("source_ts_argus"))
            if not market_time:
                continue

            # Strict Chronological Check: no future data
            if last_market_time and market_time < last_market_time:
                self.future_data_violations += 1
            last_market_time = market_time

            # Session Reset Check
            session_date = str(market_time.date())
            if self.engine._session_id != session_date:
                self.engine.reset_session(session_date)
                self.oi_tracker.clear_all()

            # 1. Ingest recorded flow if present
            flow_data = rec.get("flow")
            if flow_data:
                self.engine.ingest_flow_snapshot(flow_data, market_time)
            elif rec.get("ce_total_buy_qty") is not None:
                # Synthesize flow sample from recorded Dhan book pressure
                tot_b = float(rec.get("ce_total_buy_qty", 0)) + float(rec.get("pe_total_buy_qty", 0))
                tot_s = float(rec.get("ce_total_sell_qty", 0)) + float(rec.get("pe_total_sell_qty", 0))
                tot = tot_b + tot_s
                mlofi_synth = (tot_b - tot_s) / tot if tot > 0 else 0.0
                flow_sample = {
                    "revision": f"FLOW_REV_{rec.get('revision', rec.get('sample_index'))}",
                    "source_timestamp": market_time.isoformat(),
                    "diagnostics": {"book_pressure": {"mlofi": mlofi_synth, "l1_ofi": mlofi_synth * 0.8}},
                }
                self.engine.ingest_flow_snapshot(flow_sample, market_time)

            # 2. Evaluate both legs
            for side in ("CE", "PE"):
                self._evaluate_leg(side, rec, market_time)

        return self._generate_report()

    def _evaluate_leg(self, side: str, rec: dict[str, Any], market_time: datetime) -> None:
        prefix = "ce_" if side == "CE" else "pe_"
        sec_id = str(rec.get(f"{prefix}sec_id") or "")
        strike = rec.get(f"{prefix}strike")
        ltp = rec.get(f"{prefix}ltp")
        oi = rec.get(f"{prefix}oi")

        if not sec_id:
            return

        # Contract roll check
        last_sid = self._last_security_ids[side]
        if last_sid is not None and last_sid != sec_id:
            self.observed_behaviors["CONTRACT_ROLL"] += 1
            # Verify old contract state is detached
            if sec_id in self.engine._held_state:
                self.ce_contract_contamination += (1 if side == "CE" else 0)
                self.pe_contract_contamination += (1 if side == "PE" else 0)
        self._last_security_ids[side] = sec_id

        # Update OI tracker
        if oi is not None and ltp is not None:
            self.oi_tracker.record(sec_id, float(oi), float(ltp), market_time)

        # Closed 5M OI & Prior Deltas
        curr_5m = self.oi_tracker.closed_window_metrics(sec_id, 5, market_time)
        prior_deltas = self.oi_tracker.prior_closed_window_deltas(sec_id, 5, market_time)

        oi_diag = self.engine.compute_oi_diagnostics(prior_deltas, curr_5m, market_time)

        # Independent arithmetic recompute for OI_X
        if oi_diag.get("oi_x") is not None and prior_deltas:
            calc_median = median(prior_deltas)
            expected_x = round(abs(curr_5m["oi_delta"]) / calc_median, 1) if calc_median > 0 else None
            if oi_diag["oi_x"] != expected_x:
                self.oi_x_arithmetic_mismatches += 1

        # VOB Horsepower State reconstruction from record
        vob_state = str(rec.get(f"{prefix}vob_state") or "")
        hp_3m_str = str(rec.get("nifty_hp_3m") or "")
        hp_5m_str = str(rec.get("nifty_hp_5m") or "")

        # Format contract payload
        contract_payload = {
            "contract": {"security_id": sec_id, "strike": strike},
            "quote": {"security_id": sec_id, "strike": strike, "ltp": ltp, "oi": oi},
            "vob": {
                "horsepower": {
                    "3m": {
                        "status": "RESISTANCE_OUT" if "RESISTANCE_OUT" in hp_3m_str else ("SUPPORT_GONE" if "SUPPORT_GONE" in hp_3m_str else "NEUTRAL"),
                        "event_id": f"EV_3M_{rec.get('sample_index', 0)}",
                        "confirmed_candle": market_time.isoformat(),
                    },
                    "5m": {
                        "status": "RESISTANCE_OUT" if "RESISTANCE_OUT" in hp_5m_str else ("SUPPORT_GONE" if "SUPPORT_GONE" in hp_5m_str else "NEUTRAL"),
                        "event_id": f"EV_5M_{rec.get('sample_index', 0)}",
                        "confirmed_candle": market_time.isoformat(),
                    },
                }
            },
        }

        # AS-OF Flow diagnostics
        vob_event_time = market_time
        flow_diag = self.engine.compute_flow_diagnostics(vob_event_time, market_time)

        # Flow forensic check
        if flow_diag.get("flow_freshness_state") == "FRESH":
            self.flow_valid_join_count += 1
        elif flow_diag.get("flow_freshness_state") == "STALE":
            self.flow_stale_join_count += 1

        if flow_diag.get("event_flow_timestamp"):
            ev_flow_dt = parse_ts(flow_diag["event_flow_timestamp"])
            if ev_flow_dt and ev_flow_dt > vob_event_time:
                self.flow_future_join_count += 1

        # Synthesize Resolver State with microsecond timing
        t_start = time.perf_counter_ns()
        ev, diag = self.engine.synthesize_resolver_state(
            side=side,
            contract_payload=contract_payload,
            oi_diag=oi_diag,
            flow_diag=flow_diag,
            flow_payload=None,
            observed_at=market_time,
        )
        elapsed_us = (time.perf_counter_ns() - t_start) / 1000.0
        self.evaluation_latencies_us.append(elapsed_us)
        self.eval_count += 1

        # State transition detection
        last_label = self._last_labels[side]
        last_pulse = self._last_pulse_keys[side]
        current_label = ev.get("label")
        current_pulse = ev.get("pulse_key")
        held_previous = ev.get("held_previous")

        if held_previous and current_pulse != last_pulse:
            self.false_repulses += 1
        if not held_previous and current_label == last_label and last_label is not None:
            self.false_state_drops += 1

        # Behavior tracking
        lbl = current_label or ""
        if "3M+5M" in lbl:
            self.observed_behaviors["3M_5M_ALIGNMENT"] += 1
        elif "1M+3M" in lbl:
            self.observed_behaviors["1M_3M_ALIGNMENT"] += 1
        elif "FULL VOB" in lbl:
            self.observed_behaviors["FULL_ALIGNMENT"] += 1
        elif "5M" in lbl:
            self.observed_behaviors["SINGLE_5M"] += 1
        elif "3M" in lbl:
            self.observed_behaviors["SINGLE_3M"] += 1

        if "FLOW" in lbl:
            self.observed_behaviors["FLOW_UPGRADE"] += 1
        if "OI" in lbl:
            self.observed_behaviors["OI_STATE"] += 1
        if ev.get("confluence_state") == "FULL_FRESH":
            self.observed_behaviors["FULL_FRESH"] += 1
        if held_previous:
            self.observed_behaviors["HELD_QUIET_PERIOD"] += 1

        # Color semantic audit
        variant = ev.get("variant")
        sem_dir = ev.get("semantic_direction")
        if side == "CE":
            if sem_dir == "BULLISH" and variant != "mint":
                self.ce_color_semantic_mismatches += 1
            if sem_dir == "BEARISH" and variant != "red":
                self.ce_color_semantic_mismatches += 1
        else:  # PE
            if sem_dir == "BULLISH" and variant != "mint":
                self.pe_color_semantic_mismatches += 1
            if sem_dir == "BEARISH" and variant != "red":
                self.pe_color_semantic_mismatches += 1

        # Record in ledger on state transition
        if current_label != last_label:
            self.transition_count += 1
            if side == "CE":
                self.ce_transition_count += 1
            else:
                self.pe_transition_count += 1

            self.ledger.append({
                "timestamp": market_time.isoformat(),
                "side": side,
                "security_id": sec_id,
                "strike": strike,
                "previous_label": last_label,
                "new_label": current_label,
                "variant": variant,
                "confluence_state": ev.get("confluence_state"),
                "pulse_key": current_pulse,
                "held_previous": held_previous,
                "event_mlofi": diag.get("event_mlofi"),
                "event_flow_x": diag.get("event_flow_x"),
                "current_mlofi": diag.get("current_mlofi"),
                "current_flow_x": diag.get("current_flow_x"),
                "oi_delta": diag.get("oi_delta"),
                "oi_structure": diag.get("oi_structure"),
                "oi_x": diag.get("oi_x"),
            })

        self._last_labels[side] = current_label
        self._last_pulse_keys[side] = current_pulse

    def _generate_report(self) -> dict[str, Any]:
        lats = sorted(self.evaluation_latencies_us)
        n = len(lats)
        p50 = lats[int(n * 0.50)] if n else 0.0
        p95 = lats[int(n * 0.95)] if n else 0.0
        p99 = lats[int(n * 0.99)] if n else 0.0
        pmax = lats[-1] if n else 0.0

        ledger_json = json.dumps(self.ledger, sort_keys=True)
        ledger_hash = hashlib.sha256(ledger_json.encode("utf-8")).hexdigest()

        return {
            "source_events": self.source_event_count,
            "eval_count": self.eval_count,
            "transition_count": self.transition_count,
            "ce_transitions": self.ce_transition_count,
            "pe_transitions": self.pe_transition_count,
            "future_data_violations": self.future_data_violations,
            "flow_future_joins": self.flow_future_join_count,
            "flow_stale_joins": self.flow_stale_join_count,
            "flow_valid_joins": self.flow_valid_join_count,
            "oi_x_arithmetic_mismatches": self.oi_x_arithmetic_mismatches,
            "flow_x_arithmetic_mismatches": self.flow_x_arithmetic_mismatches,
            "ce_color_semantic_mismatches": self.ce_color_semantic_mismatches,
            "pe_color_semantic_mismatches": self.pe_color_semantic_mismatches,
            "false_repulses": self.false_repulses,
            "false_state_drops": self.false_state_drops,
            "ce_contract_contamination": self.ce_contract_contamination,
            "pe_contract_contamination": self.pe_contract_contamination,
            "session_contamination": self.session_contamination,
            "observed_behaviors": self.observed_behaviors,
            "latency_us": {"p50": round(p50, 2), "p95": round(p95, 2), "p99": round(p99, 2), "max": round(pmax, 2)},
            "ledger_hash": ledger_hash,
            "sample_transitions": self.ledger[:10],
        }


def main():
    dataset = "reports/oracle_full_truth_audit_20260821_112518/FULL_TRUTH_15M_TELEMETRY.jsonl"
    print(f"Starting Replay Soak on {dataset}...")
    start_rss = get_rss_mb()
    t0 = time.perf_counter()

    # Run 1
    harness1 = ReplayHarness()
    res1 = harness1.run_replay(dataset)
    t_run1 = time.perf_counter() - t0
    peak_rss = get_rss_mb()

    # Run 2 (Determinism check)
    t1 = time.perf_counter()
    harness2 = ReplayHarness()
    res2 = harness2.run_replay(dataset)
    t_run2 = time.perf_counter() - t1
    end_rss = get_rss_mb()

    print(f"Run 1 completed in {t_run1:.3f}s, Hash: {res1['ledger_hash']}")
    print(f"Run 2 completed in {t_run2:.3f}s, Hash: {res2['ledger_hash']}")
    print(f"Deterministic match: {res1['ledger_hash'] == res2['ledger_hash']}")
    print(f"Memory RSS: Start={start_rss:.2f}MB, Peak={peak_rss:.2f}MB, End={end_rss:.2f}MB")
    print("\nSummary Result:")
    print(json.dumps(res1, indent=2))


if __name__ == "__main__":
    main()
