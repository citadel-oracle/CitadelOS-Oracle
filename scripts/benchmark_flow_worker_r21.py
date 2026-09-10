"""Read-only R2.1 capacity/parity benchmark against genuine raw journal rows."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.oracle.isolated_flow_worker import IsolatedOrderFlowWorker
from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.recorder import OrderFlowEvidenceRecorder
from src.order_flow.service import OrderFlowService


def _rows(path: Path, limit: int) -> list[dict[str, Any]]:
    tail: deque[dict[str, Any]] = deque(maxlen=limit * 4)
    ist = ZoneInfo("Asia/Kolkata")
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload") if isinstance(row, Mapping) else None
            if isinstance(payload, Mapping):
                try:
                    received = datetime.fromisoformat(
                        str(payload["receive_wall_utc"])
                    ).astimezone(ist)
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    received.weekday() < 5
                    and (received.hour, received.minute) >= (9, 15)
                    and (received.hour, received.minute) < (15, 30)
                ):
                    tail.append(dict(payload))
    latest_by_role: dict[str, dict[str, Any]] = {}
    for payload in tail:
        role = str(payload.get("instrument_role") or "")
        if role:
            latest_by_role[role] = payload
    selected = {str(value["security_id"]) for value in latest_by_role.values()}
    return [row for row in tail if str(row.get("security_id")) in selected][-limit:]


def _identity(row: Mapping[str, Any]) -> InstrumentIdentity:
    return InstrumentIdentity(
        exchange_segment=str(row["exchange_segment"]), security_id=str(row["security_id"]),
        role=str(row["instrument_role"]), expiry=row.get("expiry"), strike=row.get("strike"),
        option_type=row.get("option_type"),
    )


def _tick(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "response_code": 8,
        "exchange_segment": row["exchange_segment"],
        "security_id": str(row["security_id"]),
        "feed_generation": int(row.get("feed_generation") or 1),
        "ltt": int(row.get("ltt_raw_epoch") or row.get("exchange_ltt") or 0),
        "receive_wall_utc": str(row["receive_wall_utc"]),
        "feed_receive_ns": int(row["feed_receive_monotonic_ns"]),
        "decode_done_ns": int(row["decode_done_monotonic_ns"]),
        "ltp": row["ltp"], "ltq": row["ltq"],
        "cumulative_volume": row["cumulative_volume"], "atp": row["atp"],
        "open_interest": row["open_interest"],
        "high_open_interest": row["high_open_interest"],
        "low_open_interest": row["low_open_interest"],
        "total_buy_quantity": row["total_buy_quantity"],
        "total_sell_quantity": row["total_sell_quantity"],
        "depth_5": [dict(value) for value in row["depth_5"]],
        "packet_fingerprint": str(row["packet_fingerprint"]),
        "transport_gap_count": int(row.get("transport_gap_count") or 0),
        "gateway_queue_lag_ns": int(row.get("gateway_queue_lag_ns") or 0),
    }


def _semantic(value: Mapping[str, Any]) -> dict[str, Any]:
    # Transport/clock/recorder metadata necessarily differs across processes;
    # the versioned analytical contract below must remain byte-equivalent.
    keep = (
        "formula_version", "revision", "snapshot_id", "session_id", "call_strength",
        "put_strength", "directional_score", "directional_state", "action_eligible",
        "action_lock_reasons", "family_values", "confidence", "data_quality",
        "signed_flow_coverage", "profile_coverage", "reversal_state", "profile",
    )
    return {key: value.get(key) for key in keep}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("journal", type=Path)
    parser.add_argument("--packets", type=int, default=1_000)
    args = parser.parse_args()
    rows = _rows(args.journal, args.packets)
    if len(rows) < min(100, args.packets):
        raise SystemExit("insufficient genuine rows")
    identities_by_role: dict[str, InstrumentIdentity] = {}
    for row in rows:
        identities_by_role[str(row["instrument_role"])] = _identity(row)
    identities = tuple(sorted(identities_by_role.values(), key=lambda item: item.role))
    selected_ids = {item.security_id for item in identities}
    ticks = [_tick(row) for row in rows if str(row["security_id"]) in selected_ids]

    accepted = OrderFlowService()
    accepted.register_instruments(identities)
    for tick in ticks:
        accepted.ingest_tick(tick)

    with tempfile.TemporaryDirectory(prefix="oracle-flow-r21-") as root:
        recorder = OrderFlowEvidenceRecorder(Path(root))
        recorder.register_instruments(identities)
        worker = IsolatedOrderFlowWorker(recorder=recorder)
        worker.register_instruments(identities)
        worker.start()
        try:
            started = time.perf_counter()
            for tick in ticks:
                if not worker.ingest_tick(tick):
                    raise RuntimeError("required Flow input rejected")
            deadline = time.monotonic() + 30.0
            health = worker.health()
            while int(health.get("FLOW_INPUT_PROCESSED") or 0) < len(ticks) and time.monotonic() < deadline:
                time.sleep(0.01)
                health = worker.health()
            elapsed = time.perf_counter() - started
            time.sleep(0.3)
            health = worker.health()
            actual = worker.latest_projection()
            semantic_parity = _semantic(actual) == _semantic(accepted.latest_projection())
            output = {
                "journal": str(args.journal),
                "genuine_packets": len(ticks),
                "instrument_count": len(identities),
                "elapsed_seconds": round(elapsed, 6),
                "measured_processing_capacity_per_s": round(len(ticks) / elapsed, 3),
                "semantic_parity": semantic_parity,
                "health": health,
                "recorder": recorder.health(),
            }
            print(json.dumps(output, sort_keys=True))
            if int(health.get("FLOW_REQUIRED_DROPS") or 0) or not semantic_parity:
                raise SystemExit(1)
        finally:
            worker.stop()


if __name__ == "__main__":
    main()
