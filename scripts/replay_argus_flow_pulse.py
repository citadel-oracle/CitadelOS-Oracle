#!/usr/bin/env python3
"""Deterministic full-session evidence replay for ARGUS Flow Pulse."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.order_flow.contracts import DataQuality, DepthLevel, MarketEvent
from src.order_flow.features import BookPressureEngine, ResponseQualityEngine
from src.order_flow.flow_pulse import ArgusFlowPulseEngine
from src.order_flow.reconciler import VolumeReconciler


IST = timezone(timedelta(hours=5, minutes=30))
ACTION_STATES = {
    "EARLY BUY CE", "EARLY BUY PE", "BUY CE · CONFIRMED", "BUY PE · CONFIRMED",
    "T1 HIT · PROTECT", "T2 HIT · EXIT", "INVALID / EXIT", "RUNNER",
}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 6)


def distribution(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values), "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95), "p99_ms": percentile(values, 0.99),
        "max_ms": round(max(values), 6) if values else None,
    }


def market_event(payload: dict[str, Any]) -> MarketEvent:
    levels = tuple(DepthLevel(**item) for item in payload["depth_5"])
    return MarketEvent(
        1, str(payload["session_id"]), int(payload.get("feed_generation") or 1),
        str(payload["event_id"]), str(payload["exchange_segment"]), str(payload["security_id"]),
        str(payload["instrument_role"]), payload.get("expiry"), payload.get("strike"), payload.get("option_type"),
        int(payload.get("ltt_normalized_epoch") or payload.get("exchange_ltt") or 0),
        str(payload["receive_wall_utc"]), int(payload["feed_receive_monotonic_ns"]),
        int(payload["decode_done_monotonic_ns"]), float(payload["ltp"]), int(payload["ltq"]),
        int(payload["cumulative_volume"]), float(payload["atp"]), int(payload["open_interest"]),
        int(payload["high_open_interest"]), int(payload["low_open_interest"]),
        int(payload["total_buy_quantity"]), int(payload["total_sell_quantity"]), levels,
        DataQuality.DEGRADED if int(payload.get("transport_gap_count") or 0) else DataQuality.GOOD,
        str(payload["packet_fingerprint"]),
    )


def packets(path: Path, start_at: datetime, end_at: datetime) -> Iterable[dict[str, Any]]:
    last_timestamp: datetime | None = None
    with path.open() as handle:
        for line in handle:
            try:
                payload = json.loads(line)["payload"]
                timestamp = datetime.fromisoformat(str(payload["receive_time_ist"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if last_timestamp is not None and timestamp < last_timestamp:
                raise RuntimeError("RAW_PACKET_STREAM_NOT_EVENT_TIME_ORDERED")
            last_timestamp = timestamp
            if timestamp > end_at:
                break
            if start_at <= timestamp:
                yield payload


def journal_offset_at(path: Path, end_at: datetime) -> int:
    """Return the immutable byte boundary after the last record at/before end_at."""
    boundary = 0
    with path.open("rb") as handle:
        while True:
            line_start = handle.tell()
            line = handle.readline()
            if not line:
                return boundary
            try:
                payload = json.loads(line)["payload"]
                timestamp = datetime.fromisoformat(str(payload["receive_time_ist"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                boundary = handle.tell()
                continue
            if timestamp > end_at:
                return line_start
            boundary = handle.tell()


def prior_levels_from_raw(path: Path, session: str) -> tuple[float, float, float, str]:
    prior_session = (datetime.fromisoformat(session) - timedelta(days=1)).date()
    while prior_session.weekday() >= 5:
        prior_session -= timedelta(days=1)
    start_at = datetime.combine(prior_session, datetime.min.time(), IST).replace(hour=9, minute=15)
    end_at = start_at.replace(hour=15, minute=30)
    values = [
        float(payload["ltp"])
        for payload in packets(path, start_at, end_at)
        if payload.get("instrument_role") == "NIFTY_FUTURE"
    ]
    if not values:
        raise RuntimeError("PREVIOUS_FUTURES_SESSION_NOT_AVAILABLE")
    return max(values), min(values), values[-1], prior_session.isoformat()


def prior_raw_session_coverage(path: Path, session: str) -> dict[str, Any]:
    """Prove that raw evidence covers the session before using session extrema."""
    prior_session = (datetime.fromisoformat(session) - timedelta(days=1)).date()
    while prior_session.weekday() >= 5:
        prior_session -= timedelta(days=1)
    start_at = datetime.combine(prior_session, datetime.min.time(), IST).replace(hour=9, minute=15)
    end_at = start_at.replace(hour=15, minute=30)
    futures = [
        payload for payload in packets(path, start_at, end_at)
        if payload.get("instrument_role") == "NIFTY_FUTURE"
    ]
    first = datetime.fromisoformat(str(futures[0]["receive_time_ist"])) if futures else None
    last = datetime.fromisoformat(str(futures[-1]["receive_time_ist"])) if futures else None
    complete = bool(
        first and last
        and first <= start_at + timedelta(minutes=1)
        and last >= end_at - timedelta(minutes=1)
    )
    return {
        "complete_session": complete,
        "packet_count": len(futures),
        "first_packet": first.isoformat() if first else None,
        "last_packet": last.isoformat() if last else None,
        "required_range": f"{start_at.isoformat()}–{end_at.isoformat()}",
    }


def prior_levels_from_candles(path: Path, session: str) -> tuple[float, float, float, str]:
    document = json.loads(path.read_text())
    rows = document.get("candles") if isinstance(document, dict) else document
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows or []:
        timestamp = datetime.fromtimestamp(float(row.get("time") or row.get("timestamp")), tz=timezone.utc).astimezone(IST)
        by_day[timestamp.date().isoformat()].append(row)
    day = sorted(value for value in by_day if value < session)[-1]
    values = sorted(by_day[day], key=lambda row: float(row.get("time") or row.get("timestamp")))
    return max(float(row["high"]) for row in values), min(float(row["low"]) for row in values), float(values[-1]["close"]), day


def short_reversions(transitions: list[dict[str, Any]]) -> int:
    count = 0
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transition in transitions:
        by_field[str(transition["field"])].append(transition)
    for values in by_field.values():
        for left, right in zip(values, values[1:]):
            if (
                left["previous_state"] == right["new_state"]
                and left["new_state"] == right["previous_state"]
                and int(right["raw_update_index"]) - int(left["raw_update_index"]) <= 8
            ):
                count += 1
    return count


def timed_short_reversions(transitions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {f"<={seconds}s": 0 for seconds in (1, 2, 3, 5)}
    for left, right in zip(transitions, transitions[1:]):
        if left.get("old_headline") != right.get("new_headline") or left.get("new_headline") != right.get("old_headline"):
            continue
        elapsed = (
            datetime.fromisoformat(str(right["timestamp"]))
            - datetime.fromisoformat(str(left["timestamp"]))
        ).total_seconds()
        for seconds in (1, 2, 3, 5):
            if elapsed <= seconds:
                counts[f"<={seconds}s"] += 1
    return counts


def transition_durations(transitions: list[dict[str, Any]], end_at: datetime) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transition in transitions:
        by_field[str(transition["field"])].append(transition)
    for field, values in by_field.items():
        for index, transition in enumerate(values):
            started = datetime.fromisoformat(str(transition["timestamp"])).astimezone(IST)
            finished = (
                datetime.fromisoformat(str(values[index + 1]["timestamp"])).astimezone(IST)
                if index + 1 < len(values) else end_at
            )
            result[field].append({
                "state": transition["new_state"], "started_at": started.isoformat(),
                "duration_seconds": round(max(0.0, (finished - started).total_seconds()), 6),
                "raw_events": (
                    int(values[index + 1]["raw_update_index"]) - int(transition["raw_update_index"])
                    if index + 1 < len(values) else None
                ),
            })
    return dict(result)


def run(
    raw_path: Path,
    start: str,
    end: str,
    *,
    previous_raw: Path | None = None,
    candle_path: Path | None = None,
    recovery_checkpoint: Path | None = None,
) -> dict[str, Any]:
    session = start[:10]
    start_at, end_at = datetime.fromisoformat(start), datetime.fromisoformat(end)
    raw_coverage = prior_raw_session_coverage(previous_raw, session) if previous_raw is not None else None
    if previous_raw is not None and raw_coverage and raw_coverage["complete_session"]:
        pdh, pdl, close, source_day = prior_levels_from_raw(previous_raw, session)
        selected_previous_source = previous_raw
        reference_method = "LOSSLESS_FULL_SESSION_FUTURES_LTP"
    elif candle_path is not None:
        pdh, pdl, close, source_day = prior_levels_from_candles(candle_path, session)
        selected_previous_source = candle_path
        reference_method = "CANONICAL_COMPLETE_1M_FUTURES_CANDLES"
    elif previous_raw is not None:
        raise RuntimeError("PREVIOUS_RAW_SESSION_INCOMPLETE_AND_CANDLE_FALLBACK_UNAVAILABLE")
    else:
        raise ValueError("previous_raw or candle_path is required")

    engine = ArgusFlowPulseEngine()
    engine.register_reference_levels(
        previous_day_high=pdh, previous_day_low=pdl, previous_close=close,
        source_timestamp=source_day,
    )
    reconciler = VolumeReconciler()
    book_engine = BookPressureEngine()
    response_engine = ResponseQualityEngine()
    packet_count = 0
    futures_updates = 0
    update_ms: list[float] = []
    action_payload_ms: list[float] = []
    meter_payload_ms: list[float] = []
    actions: list[dict[str, Any]] = []
    headlines: list[dict[str, Any]] = []
    prior_headline: str | None = None
    semantics: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []
    validation_failures: list[dict[str, Any]] = []
    checkpoints: dict[str, dict[str, Any]] = {}
    dead_screen = {name: True for name in (
        "MARKET", "PRESSURE", "RESULT", "SPEED", "OPEN_RANGE", "NEXT_LEVEL", "WHAT_HAPPENED",
    )}
    final: dict[str, Any] | None = None
    last_future: MarketEvent | None = None

    for payload in packets(raw_path, start_at, end_at):
        packet_count += 1
        event = market_event(payload)
        trade = reconciler.reconcile(event)
        book = book_engine.update(event, trade)
        response = response_engine.update(event, trade, book) if event.instrument_role == "NIFTY_FUTURE" else None
        started_ns = perf_counter_ns()
        final = engine.update(event, trade, book=book, response=response)
        elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000.0
        event_ist = datetime.fromisoformat(event.receive_wall_utc).astimezone(IST)
        action_changes = engine.drain_transitions()
        semantic_changes = engine.drain_semantic_transitions()
        level_changes = engine.drain_level_transitions()
        validation_failures.extend(engine.drain_validation_events())
        if event.instrument_role == "NIFTY_FUTURE":
            last_future = event
            futures_updates += 1
            update_ms.append(elapsed_ms)
            headline = str(final.get("headline") or "NO TRADE")
            if headline != prior_headline:
                semantic = final.get("semantic") or {}
                latest_video = action_changes[-1] if action_changes else None
                headlines.append({
                    "timestamp": event_ist.isoformat(),
                    "old_headline": prior_headline,
                    "new_headline": headline,
                    "episode_state": final.get("state"),
                    "model": final.get("model"),
                    "video_event": (latest_video or {}).get("reason") or final.get("story"),
                    "key_level": final.get("key_level"),
                    "market": semantic.get("market"),
                    "pressure": semantic.get("pressure"),
                    "result": semantic.get("result"),
                    "speed": semantic.get("speed"),
                    "raw_update_index": futures_updates,
                })
                prior_headline = headline
            for transition in semantic_changes:
                semantics.append({**transition, "raw_update_index": futures_updates})
            for transition in level_changes:
                levels.append({**transition, "raw_update_index": futures_updates})
            for transition in action_changes:
                option = final.get("option") or {}
                futures = final.get("futures") or {}
                actions.append({
                    "time": transition.get("timestamp"), "time_ist": event_ist.isoformat(),
                    "state": transition.get("to"), "headline": final.get("headline"),
                    "model": transition.get("model"), "story": final.get("story"),
                    "side": transition.get("side"),
                    "entry_price": transition.get("entry_price"),
                    "key_level": final.get("key_level"), "next_level": final.get("next_level"),
                    "futures_ltp": futures.get("ltp"), "futures_trigger": futures.get("trigger"),
                    "option": f"{option.get('strike')} {option.get('option_type')}" if option else None,
                    "option_ask": option.get("ask"), "stop": futures.get("invalidation"),
                    "original_invalidation": transition.get("original_invalidation"),
                    "target_1": futures.get("target_1"), "target_2": futures.get("target_2"),
                    "level_lineage": transition.get("level_lineage"),
                    "reason": transition.get("reason"), "setup_id": transition.get("setup_id"),
                    "plan_validation": (final.get("action_contract") or {}).get("plan_validation"),
                    "validation_reason": (final.get("action_contract") or {}).get("validation_reason"),
                    "raw_update_index": futures_updates,
                })
            payload_started = perf_counter_ns()
            if action_changes or any(item.get("action_worthy") is True for item in level_changes):
                engine.action_payload()
                action_payload_ms.append((perf_counter_ns() - payload_started) / 1_000_000.0)
            else:
                engine.meters_payload()
                meter_payload_ms.append((perf_counter_ns() - payload_started) / 1_000_000.0)
            semantic = final.get("semantic") or {}
            dead_screen["MARKET"] &= semantic.get("market") not in {None, "UNAVAILABLE"}
            dead_screen["PRESSURE"] &= semantic.get("pressure") not in {None, "UNAVAILABLE"}
            dead_screen["RESULT"] &= semantic.get("result") not in {None, "UNAVAILABLE"}
            dead_screen["SPEED"] &= semantic.get("speed") not in {None, "UNAVAILABLE"}
            if event_ist >= start_at.replace(second=30):
                dead_screen["OPEN_RANGE"] &= (final.get("open_range") or {}).get("status") != "OPEN RANGE BUILDING"
            dead_screen["NEXT_LEVEL"] &= bool((final.get("next_level") or {}).get("name"))
            dead_screen["WHAT_HAPPENED"] &= bool(final.get("what_happened"))
            for checkpoint in ("09:15:00", "09:16:13", "09:18:00", "09:20:05", "15:30:00"):
                boundary = datetime.fromisoformat(f"{session}T{checkpoint}+05:30")
                if checkpoint not in checkpoints and event_ist >= boundary:
                    checkpoints[checkpoint] = {
                        "time_ist": event_ist.isoformat(), "headline": final.get("headline"),
                        "state": final.get("state"), "story": final.get("story"),
                        "next_level": final.get("next_level"), "option": final.get("option"),
                    }

    if final is None:
        raise RuntimeError("NO_PACKETS_IN_REPLAY_WINDOW")
    counts = Counter(str(item["field"]) for item in semantics)
    entries = [item for item in actions if item["state"] in ACTION_STATES and "BUY" in str(item["state"])]
    first_entry = entries[0] if entries else None
    visible_before = None
    if first_entry:
        trigger = first_entry.get("futures_trigger")
        episode_levels = [
            item for item in levels
            if item["raw_update_index"] < first_entry["raw_update_index"]
            and item["level"] in {"PDH", "PDL", "PREVIOUS CLOSE", "OR HIGH", "OR LOW", "LVN"}
            and item["new_state"] in {"APPROACHING", "TESTING", "BROKE BELOW", "BROKE ABOVE", "BREAK FAILED"}
            and isinstance(trigger, (int, float))
            and min(abs(float(item["level_low"]) - trigger), abs(float(item["level_high"]) - trigger)) <= engine.tick_size
        ]
        prior_level = episode_levels[0] if episode_levels else None
        if prior_level:
            visible_before = {
                "lead_seconds": round((datetime.fromisoformat(first_entry["time_ist"]) - datetime.fromisoformat(prior_level["timestamp"]).astimezone(IST)).total_seconds(), 6),
                "sequence_start": prior_level,
                "sequence": [
                    item for item in levels
                    if item["level"] == prior_level["level"]
                    and prior_level["raw_update_index"] <= item["raw_update_index"] <= first_entry["raw_update_index"]
                ],
            }
    raw_to_semantic = round(futures_updates / len(semantics), 6) if semantics else None
    headline_counts = Counter(
        "EARLY_BUY" if item["new_headline"].startswith("EARLY BUY")
        else "BUY_CONFIRMED" if item["new_headline"].startswith("BUY ")
        else str(item["new_headline"]).replace(" ", "_")
        for item in headlines
    )
    result = {
        "source": str(raw_path), "previous_source": str(selected_previous_source),
        "session": session, "packets_processed": packet_count, "raw_updates": futures_updates,
        "reference_levels": {
            "pdh": pdh, "pdl": pdl, "previous_close": close,
            "source_session": source_day, "method": reference_method,
            "partial_raw_rejected": bool(raw_coverage and not raw_coverage["complete_session"]),
            "raw_coverage": raw_coverage,
        },
        "raw_update_latency": distribution(update_ms),
        "semantic_engine": {
            "market_transitions": counts["MARKET"], "pressure_transitions": counts["PRESSURE"],
            "result_transitions": counts["RESULT"], "speed_transitions": counts["SPEED"],
            "total_transitions": len(semantics), "short_reversions": short_reversions(semantics),
            "raw_to_semantic_ratio": raw_to_semantic,
            "transition_durations": transition_durations(semantics, end_at),
            "transitions": semantics,
        },
        "level_radar": {
            "transitions": levels,
            "pdl_progression": [item for item in levels if item["level"] == "PDL"],
            "open_range_progression": [item for item in levels if item["level"] in {"OR LOW", "OR HIGH"}],
        },
        "action_events": actions,
        "action_validator": {
            "candidate_count": sum(item["state"] in ACTION_STATES for item in actions),
            "valid_count": sum(
                item["state"] in ACTION_STATES and item.get("plan_validation") == "PASS"
                for item in actions
            ),
            "blocked_count": len(validation_failures),
            "block_reasons": dict(Counter(
                str(item.get("VALIDATION_REASON") or "UNSPECIFIED") for item in validation_failures
            )),
            "blocked_candidates": validation_failures,
        },
        "headline_audit": {
            "raw_futures_updates": futures_updates,
            "transition_count": len(headlines),
            "watch_count": headline_counts["WATCH"],
            "setup_forming_count": headline_counts["SETUP_FORMING"],
            "early_buy_count": headline_counts["EARLY_BUY"],
            "buy_confirmed_count": headline_counts["BUY_CONFIRMED"],
            "short_reversions": timed_short_reversions(headlines),
            "transitions": headlines,
        },
        "opening_replay": {
            "checkpoints": checkpoints,
            "first_watch": next((item for item in actions if item["state"] == "WATCH"), None),
            "first_early": next((item for item in actions if str(item["state"]).startswith("EARLY BUY")), None),
            "first_confirm": next((item for item in actions if "CONFIRMED" in str(item["state"])), None),
            "pre_entry_visible_lead": visible_before,
        },
        "dead_screen": dead_screen,
        "payload_build": {
            "action": distribution(action_payload_ms), "meters": distribution(meter_payload_ms),
        },
        "telemetry": engine.telemetry(),
        "paper_lab": {"episodes": engine.paper_episodes(), "trades": engine.paper_trades()},
        "final": final,
        "execution_influence": "ZERO", "score_authority": "NONE",
    }
    canonical_ledger = {
        "session": result["session"],
        "reference_levels": result["reference_levels"],
        "action_events": result["action_events"],
        "semantic_transitions": result["semantic_engine"]["transitions"],
        "paper_episodes": result["paper_lab"]["episodes"],
        "paper_trades": result["paper_lab"]["trades"],
        "validation_failures": validation_failures,
    }
    canonical_bytes = json.dumps(
        canonical_ledger, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()
    result["determinism"] = {
        "canonical_event_ledger_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "canonical_event_ledger_bytes": len(canonical_bytes),
        "excluded_metadata": ["offline_wall_clock_performance"],
    }
    if recovery_checkpoint is not None and last_future is not None:
        journal_offset = journal_offset_at(raw_path, end_at)
        boundary_start = max(0, journal_offset - 4096)
        with raw_path.open("rb") as handle:
            handle.seek(boundary_start)
            boundary = handle.read(journal_offset - boundary_start)
        saved = {
            "version": 1,
            "session_id": raw_path.stem,
            "journal_offset": journal_offset,
            "boundary_sha256": hashlib.sha256(boundary).hexdigest(),
            "state": {
                "engine": engine, "reconciler": reconciler,
                "book_engine": book_engine, "response_engine": response_engine,
                "last_future": last_future, "packets": packet_count,
                "futures_updates": futures_updates,
            },
        }
        body = pickle.dumps(saved, protocol=5)
        encoded_checkpoint = pickle.dumps(
            {"sha256": hashlib.sha256(body).hexdigest(), "body": body}, protocol=5,
        )
        recovery_checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = recovery_checkpoint.with_suffix(recovery_checkpoint.suffix + ".tmp")
        temporary.write_bytes(encoded_checkpoint)
        os.replace(temporary, recovery_checkpoint)
        result["recovery_checkpoint"] = {
            "path": str(recovery_checkpoint), "journal_offset": journal_offset,
            "packet_count": packet_count, "futures_updates": futures_updates,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--previous-raw", type=Path)
    parser.add_argument("--candles", type=Path)
    parser.add_argument("--start", default="2026-08-11T09:15:00+05:30")
    parser.add_argument("--end", default="2026-08-11T15:30:00+05:30")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--recovery-checkpoint", type=Path)
    args = parser.parse_args()
    result = run(
        args.raw, args.start, args.end,
        previous_raw=args.previous_raw, candle_path=args.candles,
        recovery_checkpoint=args.recovery_checkpoint,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
