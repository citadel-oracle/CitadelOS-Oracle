#!/usr/bin/env python3
"""Blind chronological replay for the shadow Oracle decision HUD.

Only persisted raw full packets and authoritative ARGUS session snapshots are
accepted.  The isolated reducer receives events in timestamp order and never
touches a live cache or runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.argus.prime import ArgusPrimeProjection
from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.service import OrderFlowService


def _stamp(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _canonical_structure(
    record: Mapping[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    rows = [
        {
            "strike": item.get("strike"),
            "ce": dict(item.get("CE") or {}),
            "pe": dict(item.get("PE") or {}),
        }
        for item in record.get("option_chain_evidence") or []
        if isinstance(item, Mapping)
    ]
    spot = float(record["spot"])
    atm = min((float(row["strike"]) for row in rows), key=lambda strike: abs(strike - spot))
    observed = str(record["observation_timestamp"])
    underlying = {
        "symbol": record.get("symbol") or "NIFTY",
        "expiry": record.get("expiry"),
        "ltp": spot,
        "atm_strike": atm,
        "fetched_at": observed,
    }
    gamma_evidence = record.get("gamma_evidence") or {}
    spine = ArgusPrimeProjection._strike_spine(
        rows,
        {},
        {},
        {},
        dict(gamma_evidence.get("regime") or {}),
        dict(gamma_evidence.get("blast") or {}),
        source={},
        underlying=underlying,
        history=history,
        selection={},
    )
    pcr = ArgusPrimeProjection._live_pcr(
        rows,
        history,
        observed,
        {},
        expiry=record.get("expiry"),
        underlying=record.get("symbol") or "NIFTY",
        snapshot_id=record.get("snapshot_id"),
    )
    history.append(
        {
            "source_timestamp": observed,
            "prime_strike_state": spine,
            "pcr_observation": {
                "timestamp": observed,
                "expiry": record.get("expiry"),
                "underlying": record.get("symbol") or "NIFTY",
                "snapshot_id": record.get("snapshot_id"),
                "total_call_oi": pcr.get("total_call_oi"),
                "total_put_oi": pcr.get("total_put_oi"),
                "pcr": pcr.get("oi_pcr"),
            },
        }
    )
    return {
        "data": {
            "underlying": {"atm_strike": atm},
            "tactical_edge": {
                "source_event_time": observed,
                "argus_prime": {
                    "freshness": "FRESH",
                    "source_event_time": observed,
                    "strike_spine": spine,
                    "live_pcr": pcr,
                },
            },
        }
    }


def _quantify_alerts(alerts, futures, options):
    false_alerts = measured = 0
    for alert in alerts:
        future_start = min(futures, key=lambda row: abs((row[0] - alert["timestamp"]).total_seconds()), default=None)
        option_side = "CE" if alert["side"] == "CALL" else "PE"
        option_start = min(
            (row for row in options if row[1] == option_side and row[2] == alert["strike"]),
            key=lambda row: abs((row[0] - alert["timestamp"]).total_seconds()),
            default=None,
        )
        if future_start is None or option_start is None:
            continue
        future_after = [row[1] for row in futures if 0 < (row[0] - alert["timestamp"]).total_seconds() <= 60]
        option_after = [row[3] for row in options if row[1] == option_side and row[2] == alert["strike"] and 0 < (row[0] - alert["timestamp"]).total_seconds() <= 60]
        if not future_after or not option_after:
            continue
        measured += 1
        future_move = max(future_after) - future_start[1] if alert["side"] == "CALL" else future_start[1] - min(future_after)
        executable_option_move = max(option_after) - option_start[4]
        if future_move < 5.0 and executable_option_move <= 0:
            false_alerts += 1
    return false_alerts, measured


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_packets", type=Path)
    parser.add_argument("argus_snapshots", type=Path)
    args = parser.parse_args()

    events: list[tuple[datetime, str, dict[str, Any]]] = []
    with args.raw_packets.open() as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("event_type") == "RAW_FULL_PACKET":
                payload = record.get("payload") or {}
                events.append((_stamp(payload["receive_wall_utc"]), "RAW", payload))
    with args.argus_snapshots.open() as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("record_type") == "ARGUS_PRIME_AUTHORITATIVE_SNAPSHOT":
                events.append((_stamp(record["observation_timestamp"]), "ARGUS", record))
    events.sort(key=lambda item: (item[0], 0 if item[1] == "RAW" else 1))

    raw_anchor = next(item for item in events if item[1] == "RAW")
    anchor_ns = int(raw_anchor[2]["feed_receive_monotonic_ns"])
    anchor_wall = raw_anchor[0]
    service = OrderFlowService()
    roles: dict[str, InstrumentIdentity] = {}
    structure_history: list[dict[str, Any]] = []
    futures: list[tuple[datetime, float]] = []
    options: list[tuple[datetime, str, float, float, float]] = []
    transitions: list[dict[str, Any]] = []
    prior: tuple[Any, ...] | None = None
    packet_count = snapshot_count = 0

    for wall, kind, payload in events:
        receive_ns = anchor_ns + int((wall - anchor_wall).total_seconds() * 1_000_000_000)
        if kind == "ARGUS":
            service.register_decision_structure(
                _canonical_structure(payload, structure_history), receive_ns=receive_ns
            )
            snapshot_count += 1
        else:
            packet_count += 1
            identity = InstrumentIdentity(
                exchange_segment=str(payload["exchange_segment"]),
                security_id=str(payload["security_id"]),
                role=str(payload["instrument_role"]),
                expiry=payload.get("expiry"),
                strike=payload.get("strike"),
                option_type=payload.get("option_type"),
            )
            if roles.get(identity.role) != identity:
                roles[identity.role] = identity
                service.register_instruments(tuple(roles.values()))
            tick = {
                **payload,
                "response_code": 8,
                "ltt": int(payload["exchange_ltt"]),
                "feed_receive_ns": int(payload["feed_receive_monotonic_ns"]),
                "decode_done_ns": int(payload["decode_done_monotonic_ns"]),
                "open_interest": int(payload.get("open_interest") or 0),
            }
            service.ingest_tick(tick)
            receive_ns = int(payload["feed_receive_monotonic_ns"])
            if identity.role == "NIFTY_FUTURE":
                futures.append((wall, float(payload["ltp"])))
            elif identity.option_type in {"CE", "PE"} and identity.strike is not None:
                top = (payload.get("depth_5") or [{}])[0]
                options.append((wall, identity.option_type, float(identity.strike), float(top.get("bid_price") or 0), float(top.get("ask_price") or 0)))

        projection = service.decision_hud.snapshot(now_ns=receive_ns, generated_at=wall.isoformat())
        current = tuple(
            value
            for side in ("call", "put")
            for value in (
                projection[side]["edge_state"],
                projection[side]["structure_state"],
                projection[side]["action"],
            )
        ) + (projection["focus_strike"], projection["data_quality"])
        if current != prior:
            transitions.append({"timestamp": wall, "projection": projection})
            prior = current

    side_transitions = []
    previous = {"call": None, "put": None}
    for transition in transitions:
        projection = transition["projection"]
        for key, label in (("call", "CALL"), ("put", "PUT")):
            state = projection[key]
            signature = (state["edge_state"], state["structure_state"], state["action"])
            if signature != previous[key]:
                side_transitions.append({
                    "timestamp": transition["timestamp"], "side": label,
                    "edge": state["edge_state"], "structure": state["structure_state"],
                    "action": state["action"], "strike": projection["focus_strike"],
                })
                previous[key] = signature

    edge_previous = {"CALL": None, "PUT": None}
    structure_previous = {"CALL": None, "PUT": None}
    action_previous = {"CALL": None, "PUT": None}
    edge_changes, structure_changes, action_changes = [], [], []
    for row in side_transitions:
        side = row["side"]
        if row["edge"] != edge_previous[side]:
            edge_changes.append(row)
            edge_previous[side] = row["edge"]
        if row["structure"] != structure_previous[side]:
            structure_changes.append(row)
            structure_previous[side] = row["structure"]
        if row["action"] != action_previous[side]:
            action_changes.append(row)
            action_previous[side] = row["action"]
    alerts = [row for row in edge_changes if row["edge"] == "REVERSAL BUILDING"]
    ready = [row for row in action_changes if row["action"] == "READY"]
    ready_plus = [row for row in action_changes if row["action"] == "READY+"]
    go = [row for row in action_changes if row["action"] == "GO"]
    ist = ZoneInfo("Asia/Kolkata")
    top_window = [row for row in futures if "11:25" <= row[0].astimezone(ist).strftime("%H:%M") <= "11:35"]
    bottom_window = [row for row in futures if "10:01" <= row[0].astimezone(ist).strftime("%H:%M") <= "10:11"]
    top = max(top_window, key=lambda item: item[1]) if top_window else None
    bottom = min(bottom_window, key=lambda item: item[1]) if bottom_window else None
    top_detected = top is not None and any(row["side"] == "PUT" and -120 <= (row["timestamp"] - top[0]).total_seconds() <= 30 for row in alerts)
    bottom_detected = bottom is not None and any(row["side"] == "CALL" and -120 <= (row["timestamp"] - bottom[0]).total_seconds() <= 30 for row in alerts)
    false_alerts, measured = _quantify_alerts(alerts, futures, options)
    top_leads = [
        round((top[0] - row["timestamp"]).total_seconds(), 3)
        for row in alerts
        if top is not None and row["side"] == "PUT" and -120 <= (row["timestamp"] - top[0]).total_seconds() <= 30
    ]
    print(json.dumps({
        "mode": "BLIND_CAUSAL_CHRONOLOGICAL",
        "packets": packet_count,
        "argus_snapshots": snapshot_count,
        "structure_coverage": "AUTHORITATIVE_PERSISTED_ARGUS_SNAPSHOTS_CANONICAL_FORMULAS",
        "edge_transitions": len(edge_changes),
        "structure_transitions": len(structure_changes),
        "edge_state_counts": dict(Counter(row["edge"] for row in edge_changes)),
        "structure_state_counts": dict(Counter(row["structure"] for row in structure_changes)),
        "reversal_alerts": len(alerts), "ready_count": len(ready),
        "ready_plus_count": len(ready_plus), "go_count": len(go),
        "top_11_30_independently_detected": top_detected if top else None,
        "top_warning_lead_seconds": max(top_leads) if top_leads else None,
        "bottom_detection": bottom_detected if bottom else None,
        "false_alerts": false_alerts, "false_alerts_measured": measured,
        "transition_count": len(side_transitions),
        "top_exact": {"timestamp": top[0].isoformat(), "price": top[1]} if top else None,
        "bottom_exact": {"timestamp": bottom[0].isoformat(), "price": bottom[1]} if bottom else None,
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
