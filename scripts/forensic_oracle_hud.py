#!/usr/bin/env python3
"""Deterministic, descriptive-only forensic audit for the Oracle chart-top HUD.

This utility never changes trading state.  It combines the lossless packet
journal with the canonical DECISION_HUD_TRANSITION records and makes evidence
gaps explicit instead of inventing missing display history.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.order_flow.contracts import DataQuality, DepthLevel, MarketEvent
from src.order_flow.decision_hud import OracleDecisionHudEngine
from src.order_flow.features import BookPressureEngine
from src.order_flow.reconciler import VolumeReconciler


IST = timezone(timedelta(hours=5, minutes=30))
SESSION_START = "09:15:00"
SESSION_END = "15:30:00"
HORIZONS = (10, 30, 60, 180, 300)


def parse_timestamp(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 6)


def packet_payloads(path: Path, session: str) -> Iterable[dict[str, Any]]:
    start = parse_timestamp(f"{session}T{SESSION_START}+05:30")
    end = parse_timestamp(f"{session}T{SESSION_END}+05:30")
    prior: datetime | None = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                payload = row["payload"]
                timestamp = parse_timestamp(payload["receive_time_ist"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if prior is not None and timestamp < prior:
                raise RuntimeError("RAW_PACKET_STREAM_NOT_EVENT_TIME_ORDERED")
            prior = timestamp
            if start <= timestamp < end:
                yield payload


def market_event(payload: Mapping[str, Any]) -> MarketEvent:
    return MarketEvent(
        1,
        str(payload["session_id"]),
        int(payload.get("feed_generation") or 1),
        str(payload["event_id"]),
        str(payload["exchange_segment"]),
        str(payload["security_id"]),
        str(payload["instrument_role"]),
        payload.get("expiry"),
        payload.get("strike"),
        payload.get("option_type"),
        int(payload.get("ltt_normalized_epoch") or payload.get("exchange_ltt") or 0),
        str(payload["receive_wall_utc"]),
        int(payload["feed_receive_monotonic_ns"]),
        int(payload["decode_done_monotonic_ns"]),
        float(payload["ltp"]),
        int(payload["ltq"]),
        int(payload["cumulative_volume"]),
        float(payload["atp"]),
        int(payload["open_interest"]),
        int(payload["high_open_interest"]),
        int(payload["low_open_interest"]),
        int(payload["total_buy_quantity"]),
        int(payload["total_sell_quantity"]),
        tuple(DepthLevel(**dict(item)) for item in payload["depth_5"]),
        DataQuality.DEGRADED
        if int(payload.get("transport_gap_count") or 0)
        else DataQuality.GOOD,
        str(payload["packet_fingerprint"]),
    )


def session_candles(path: Path, session: str) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("candles") if isinstance(document, dict) else document
    result = []
    for item in rows or []:
        timestamp = datetime.fromtimestamp(
            float(item.get("time") or item.get("timestamp")), tz=timezone.utc
        ).astimezone(IST)
        if timestamp.date().isoformat() == session and SESSION_START <= timestamp.time().isoformat() < SESSION_END:
            result.append(dict(item))
    return sorted(result, key=lambda item: float(item.get("time") or item.get("timestamp")))


def level_lineage(candles_path: Path, raw_path: Path, session: str) -> dict[str, Any]:
    session_day = datetime.fromisoformat(session).date()
    prior_day = session_day - timedelta(days=1)
    while prior_day.weekday() >= 5:
        prior_day -= timedelta(days=1)
    prior_session = prior_day.isoformat()
    prior = session_candles(candles_path, prior_session)
    current = session_candles(candles_path, session)
    if not prior or not current:
        raise RuntimeError("CANONICAL_FUTURES_CANDLE_SESSION_UNAVAILABLE")

    raw_prior_path = raw_path.with_name(f"{prior_session}.jsonl")
    raw_prior = list(packet_payloads(raw_prior_path, prior_session)) if raw_prior_path.exists() else []
    raw_futures = [item for item in raw_prior if item.get("instrument_role") == "NIFTY_FUTURE"]
    raw_first = parse_timestamp(raw_futures[0]["receive_time_ist"]) if raw_futures else None
    raw_last = parse_timestamp(raw_futures[-1]["receive_time_ist"]) if raw_futures else None
    # This is a provenance gate, not a market rule: a file that starts hours
    # late or ends early cannot define a previous *session* high/low/close.
    raw_complete = bool(
        raw_first
        and raw_last
        and raw_first.time() <= parse_timestamp(f"{prior_session}T09:16:00+05:30").time()
        and raw_last.time() >= parse_timestamp(f"{prior_session}T15:29:00+05:30").time()
    )

    today_packets = [
        item for item in packet_payloads(raw_path, session)
        if item.get("instrument_role") == "NIFTY_FUTURE"
    ]
    minute_end = parse_timestamp(f"{session}T09:16:00+05:30")
    range_end = parse_timestamp(f"{session}T09:15:30+05:30")
    first_minute = [item for item in today_packets if parse_timestamp(item["receive_time_ist"]) < minute_end]
    opening_range = [item for item in first_minute if parse_timestamp(item["receive_time_ist"]) < range_end]

    def source(value: float, method: str, source_range: str) -> dict[str, Any]:
        return {
            "value": value,
            "instrument": "NIFTY FUTURES",
            "security_id": "58072",
            "contract": "NIFTY-Aug2026-FUT",
            "expiry": "2026-08-25",
            "session_date": prior_session if method.startswith("PREVIOUS") else session,
            "source_file": str(candles_path if "CANDLE" in method else raw_path),
            "source_timestamp_range": source_range,
            "calculation_method": method,
        }

    first_current = current[0]
    result = {
        "previous_day_high": source(
            max(float(item["high"]) for item in prior),
            "PREVIOUS_SESSION_MAX_CANONICAL_1M_CANDLE_HIGH",
            f"{prior_session} 09:15:00–15:29:59 IST",
        ),
        "previous_day_low": source(
            min(float(item["low"]) for item in prior),
            "PREVIOUS_SESSION_MIN_CANONICAL_1M_CANDLE_LOW",
            f"{prior_session} 09:15:00–15:29:59 IST",
        ),
        "previous_close": source(
            float(prior[-1]["close"]),
            "PREVIOUS_SESSION_FINAL_CANONICAL_1M_CANDLE_CLOSE",
            f"{prior_session} 15:29:00–15:29:59 IST",
        ),
        "opening_1m": {
            "high": source(float(first_current["high"]), "CURRENT_SESSION_FIRST_CANONICAL_1M_CANDLE_HIGH", f"{session} 09:15:00–09:15:59 IST"),
            "low": source(float(first_current["low"]), "CURRENT_SESSION_FIRST_CANONICAL_1M_CANDLE_LOW", f"{session} 09:15:00–09:15:59 IST"),
        },
        "opening_range_30s": {
            "high": source(max(float(item["ltp"]) for item in opening_range), "CURRENT_SESSION_RAW_FUTURES_LTP_MAX_FIRST_30S", f"{session} 09:15:00–09:15:29.999 IST"),
            "low": source(min(float(item["ltp"]) for item in opening_range), "CURRENT_SESSION_RAW_FUTURES_LTP_MIN_FIRST_30S", f"{session} 09:15:00–09:15:29.999 IST"),
        },
        "opening_1m_raw": {
            "high": max(float(item["ltp"]) for item in first_minute),
            "low": min(float(item["ltp"]) for item in first_minute),
        },
        "partial_previous_raw": {
            "path": str(raw_prior_path),
            "complete_session": raw_complete,
            "packet_count": len(raw_futures),
            "first_packet": raw_first.isoformat() if raw_first else None,
            "last_packet": raw_last.isoformat() if raw_last else None,
            "high": max((float(item["ltp"]) for item in raw_futures), default=None),
            "low": min((float(item["ltp"]) for item in raw_futures), default=None),
            "close": float(raw_futures[-1]["ltp"]) if raw_futures else None,
            "eligible_for_session_lineage": raw_complete,
        },
    }
    return result


def hud_records(paths: list[Path], session: str) -> list[dict[str, Any]]:
    start = parse_timestamp(f"{session}T{SESSION_START}+05:30").astimezone(timezone.utc)
    end = parse_timestamp(f"{session}T{SESSION_END}+05:30").astimezone(timezone.utc)
    seen: set[str] = set()
    result = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if row.get("event_type") != "DECISION_HUD_TRANSITION":
                        continue
                    payload = dict(row["payload"])
                    stamp = parse_timestamp(payload["generated_at"]).astimezone(timezone.utc)
                    identity = str(payload["projection_id"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                if start <= stamp < end and identity not in seen:
                    seen.add(identity)
                    result.append(payload)
    return sorted(result, key=lambda item: parse_timestamp(item["generated_at"]))


FIELDS = {
    "CE_EDGE_RAW": ("call", "raw_edge_state"),
    "CE_EDGE_DISPLAY": ("call", "display_edge_state"),
    "CE_STRUCTURE_RAW": ("call", "raw_structure_state"),
    "CE_STRUCTURE_DISPLAY": ("call", "display_structure_state"),
    "PE_EDGE_RAW": ("put", "raw_edge_state"),
    "PE_EDGE_DISPLAY": ("put", "display_edge_state"),
    "PE_STRUCTURE_RAW": ("put", "raw_structure_state"),
    "PE_STRUCTURE_DISPLAY": ("put", "display_structure_state"),
}


def value_at(record: Mapping[str, Any], path: tuple[str, str]) -> Any:
    return (record.get(path[0]) or {}).get(path[1])


def color(value: Any) -> str:
    text = str(value or "UNKNOWN").upper()
    if text == "DATA LOCKED":
        return "LOCKED"
    if "BUYING" in text or text in {"BUY BUILDING", "BUY STRONG"}:
        return "GREEN"
    if "SELLING" in text or text == "SELL STRONG":
        return "RED"
    if "REVERSAL" in text or "TURNING" in text or "FADING" in text:
        return "AMBER"
    return "GRAY"


def transition_rows(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not records:
        return result
    prior = records[0]
    for item in records[1:]:
        for name, path in FIELDS.items():
            old, new = value_at(prior, path), value_at(item, path)
            if old != new:
                result[name].append({
                    "field": name,
                    "timestamp": item["generated_at"],
                    "source_timestamp": item.get("source_timestamp"),
                    "old_state": old,
                    "new_state": new,
                    "old_color": color(old),
                    "new_color": color(new),
                    "focus_strike": item.get("focus_strike"),
                    "quality": item.get("data_quality"),
                    "revision": item.get("revision"),
                })
        prior = item
    return result


def short_reversions(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {f"<={seconds}s": 0 for seconds in (1, 2, 3, 5)}
    for left, right in zip(rows, rows[1:]):
        left_identity = (left.get("field"), left.get("layer"), left.get("side"))
        right_identity = (right.get("field"), right.get("layer"), right.get("side"))
        if left_identity != right_identity:
            continue
        if left["old_state"] != right["new_state"] or left["new_state"] != right["old_state"]:
            continue
        duration = (parse_timestamp(right["timestamp"]) - parse_timestamp(left["timestamp"])).total_seconds()
        for seconds in (1, 2, 3, 5):
            if duration <= seconds:
                counts[f"<={seconds}s"] += 1
    return counts


def recorded_hud_audit(records: list[dict[str, Any]], packets: list[dict[str, Any]]) -> dict[str, Any]:
    transitions = transition_rows(records)
    if not records:
        return {"status": "ABSENT", "reason": "NO_CANONICAL_HUD_RECORDS"}
    first_time = parse_timestamp(records[0]["generated_at"])
    last_time = parse_timestamp(records[-1]["generated_at"])
    source_updates = sum(
        first_time <= parse_timestamp(item["receive_wall_utc"]) <= last_time
        and item.get("option_type") in {"CE", "PE"}
        for item in packets
    )
    focus_switches = []
    quality_transitions = []
    for prior, item in zip(records, records[1:]):
        if prior.get("focus_strike") != item.get("focus_strike"):
            focus_switches.append({
                "timestamp": item["generated_at"],
                "before": prior.get("focus_strike"),
                "after": item.get("focus_strike"),
                "before_revision": prior.get("revision"),
                "after_revision": item.get("revision"),
                "ce_contract": (item.get("call") or {}).get("contract"),
                "pe_contract": (item.get("put") or {}).get("contract"),
            })
        if prior.get("data_quality") != item.get("data_quality"):
            quality_transitions.append({
                "timestamp": item["generated_at"],
                "before": prior.get("data_quality"),
                "after": item.get("data_quality"),
                "revision": item.get("revision"),
            })
    color_rows = [
        row for name, rows in transitions.items() if name.endswith("DISPLAY")
        for row in rows if row["old_color"] != row["new_color"]
    ]
    color_rows.sort(key=lambda item: parse_timestamp(item["timestamp"]))
    minutes = max(1 / 60, (last_time - first_time).total_seconds() / 60)
    blank_states = [
        item for item in records
        if any(
            not (item.get(side) or {}).get(field)
            for side in ("call", "put")
            for field in ("contract", "display_edge_state", "display_structure_state")
        )
    ]
    field_summary = {
        name: {
            "count": len(rows),
            "per_minute": round(len(rows) / minutes, 6),
            "short_reversions": short_reversions(rows),
        }
        for name, rows in transitions.items()
    }
    raw_count = sum(len(rows) for name, rows in transitions.items() if name.endswith("RAW"))
    display_count = sum(len(rows) for name, rows in transitions.items() if name.endswith("DISPLAY"))
    return {
        "status": "PARTIAL_SESSION_CANONICAL_EVIDENCE",
        "evidence_start": records[0]["generated_at"],
        "evidence_end": records[-1]["generated_at"],
        "source_updates": source_updates,
        "canonical_revisions": len(records),
        "field_transitions": field_summary,
        "raw_transitions": raw_count,
        "display_transitions": display_count,
        "raw_to_display_ratio": round(raw_count / display_count, 6) if display_count else None,
        "dom_color_changes_reconstructable": len(color_rows),
        "color_changes_per_minute": round(len(color_rows) / minutes, 6),
        "short_color_reversions": short_reversions(color_rows),
        "focus_switches": focus_switches,
        "data_lock_transitions": quality_transitions,
        "blank_states": len(blank_states),
        "atomic_ce_pe": all((item.get("call") or {}).get("contract") and (item.get("put") or {}).get("contract") for item in records),
        "atomic_edge_structure": all(
            all((item.get(side) or {}).get(field) is not None for field in ("display_edge_state", "display_structure_state"))
            for item in records for side in ("call", "put")
        ),
        "ledger": records,
        "transitions": transitions,
    }


def fixed_strike_edge_replay(packets: list[dict[str, Any]], strike: float) -> dict[str, Any]:
    engine = OracleDecisionHudEngine()
    # Fixed-contract forensic only.  This bypasses focus selection without
    # altering the classifier or its event-time persistence.
    engine._focus_strike = strike
    reconciler = VolumeReconciler()
    books = BookPressureEngine()
    latest_future: float | None = None
    latest = {"CE": None, "PE": None}
    ledgers: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    coverage = {
        side: {"packets": 0, "volume": 0, "oi": 0, "depth_5": 0, "first": None, "last": None, "security_ids": Counter(), "roles": Counter()}
        for side in ("CE", "PE")
    }
    for payload in packets:
        if payload.get("instrument_role") == "NIFTY_FUTURE":
            latest_future = float(payload["ltp"])
            continue
        if float(payload.get("strike") or -1) != strike or payload.get("option_type") not in {"CE", "PE"}:
            continue
        event = market_event(payload)
        trade = reconciler.reconcile(event)
        book = books.update(event, trade)
        side = str(event.option_type)
        state_side = "call" if side == "CE" else "put"
        before_raw = engine._sides[state_side].edge.raw_value
        before_display = engine._sides[state_side].edge.value
        engine.ingest_option(event, trade, book, now_ns=event.feed_receive_ns)
        after_raw = engine._sides[state_side].edge.raw_value
        after_display = engine._sides[state_side].edge.value
        depth = event.depth_5[0]
        row = {
            "timestamp": event.receive_wall_utc,
            "nifty_futures_price": latest_future,
            "side": side,
            "security_id": event.security_id,
            "expiry": event.expiry,
            "instrument_role": event.instrument_role,
            "bid": depth.bid_price,
            "ask": depth.ask_price,
            "ltp": event.ltp,
            "cumulative_volume": event.cumulative_volume,
            "open_interest": event.oi,
            "raw_edge_state": after_raw,
            "display_edge_state": after_display,
            "raw_structure_state": None,
            "display_structure_state": None,
            "quality_state": event.data_quality.value,
            "canonical_focus_strike": None,
            "canonical_revision": None,
            "dom_visible_state": None,
        }
        ledgers.append(row)
        latest[side] = row
        info = coverage[side]
        info["packets"] += 1
        info["volume"] += event.cumulative_volume is not None
        info["oi"] += event.oi is not None
        info["depth_5"] += len(event.depth_5) == 5
        info["first"] = info["first"] or event.receive_wall_utc
        info["last"] = event.receive_wall_utc
        info["security_ids"][event.security_id] += 1
        info["roles"][event.instrument_role] += 1
        if before_raw != after_raw:
            transitions.append({**row, "layer": "RAW_EDGE", "old_state": before_raw, "new_state": after_raw})
        if before_display != after_display:
            transitions.append({**row, "layer": "DISPLAY_EDGE", "old_state": before_display, "new_state": after_display})
    normalized_coverage = {}
    for side, info in coverage.items():
        count = int(info["packets"])
        normalized_coverage[side] = {
            "packet_count": count,
            "first_packet_timestamp": info["first"],
            "last_packet_timestamp": info["last"],
            "security_ids": dict(info["security_ids"]),
            "instrument_roles": dict(info["roles"]),
            "volume_coverage": round(info["volume"] / count, 6) if count else 0.0,
            "oi_coverage": round(info["oi"] / count, 6) if count else 0.0,
            "depth_5_coverage": round(info["depth_5"] / count, 6) if count else 0.0,
        }
    raw = [item for item in transitions if item["layer"] == "RAW_EDGE"]
    display = [item for item in transitions if item["layer"] == "DISPLAY_EDGE"]
    return {
        "status": "PARTIAL" if any(item["last"] and parse_timestamp(item["last"]).time() < parse_timestamp("2026-08-11T15:29:00+05:30").time() for item in coverage.values()) else "COMPLETE",
        "strike": strike,
        "coverage": normalized_coverage,
        "raw_edge_transitions": len(raw),
        "display_edge_transitions": len(display),
        "raw_short_reversions": short_reversions(raw),
        "display_short_reversions": short_reversions(display),
        "transitions": transitions,
        "packet_ledger": ledgers,
        "limitations": [
            "CANONICAL_STRIKE_SPINE_NOT_RECORDED_BEFORE_13_28_IST",
            "24600_NOT_PRESENT_IN_LOSSLESS_OPTION_BASKET_AFTER_10_59_11_IST",
            "DOM_VISIBLE_STATE_NOT_RECONSTRUCTABLE_WITHOUT_CANONICAL_HUD_EVENT",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="2026-08-11")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--projections", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    packets = list(packet_payloads(args.raw, args.session))
    records = hud_records(args.projections, args.session)
    result = {
        "session": args.session,
        "mode": "OFF_MARKET_DETERMINISTIC_FORENSIC",
        "descriptive_only": True,
        "not_edge_validation": True,
        "today_used_for_parameter_optimization": False,
        "flow_pulse_changed": False,
        "trading_logic_changed": False,
        "level_lineage": level_lineage(args.candles, args.raw, args.session),
        "recorded_canonical_hud": recorded_hud_audit(records, packets),
        "fixed_24600_edge_replay": fixed_strike_edge_replay(packets, 24600.0),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "canonical_records": len(records),
        "packet_count": len(packets),
        "fixed_24600_packets": sum(item["packet_count"] for item in result["fixed_24600_edge_replay"]["coverage"].values()),
    }, indent=2))


if __name__ == "__main__":
    main()
