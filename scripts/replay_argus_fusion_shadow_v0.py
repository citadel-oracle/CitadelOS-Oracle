#!/usr/bin/env python3
"""Read-only, diagnostically complete ARGUS Fusion replay.

The replay intentionally consumes only persisted, genuine inputs.  In
particular, it never reconstructs missing Flow Pulse microstructure from
candles, option prices, OI, or the completed forensic narrative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.argus.fusion_shadow import FUSION_VERSION, FusionShadowEngine


CHECKPOINTS = ("13:45", "14:14", "14:17", "14:20", "14:25", "14:29", "14:30", "14:32", "14:54")
EVENT_STATES = ("WATCH", "SETUP", "TRIGGER", "RUNNER", "INVALIDATED")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _timestamp(row: Mapping[str, Any]) -> str | None:
    for key in ("observation_timestamp", "source_event_time", "receipt_timestamp"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class _ReplayClock:
    def __init__(self) -> None:
        self.value = "1970-01-01T00:00:00+00:00"

    def now(self) -> str:
        return self.value


def _projection(row: Mapping[str, Any]) -> dict[str, Any]:
    evidence = [item for item in row.get("option_chain_evidence") or () if isinstance(item, Mapping)]
    window = []
    for item in evidence:
        ce, pe = _mapping(item.get("CE")), _mapping(item.get("PE"))
        window.append({
            "strike": item.get("strike"),
            "ce": {
                "security_id": ce.get("security_id"), "top_bid_price": ce.get("bid_price"),
                "top_ask_price": ce.get("ask_price"), "ltp": ce.get("ltp"),
                "oi": ce.get("oi"), "volume": ce.get("volume"), "iv": ce.get("iv"),
            },
            "pe": {
                "security_id": pe.get("security_id"), "top_bid_price": pe.get("bid_price"),
                "top_ask_price": pe.get("ask_price"), "ltp": pe.get("ltp"),
                "oi": pe.get("oi"), "volume": pe.get("volume"), "iv": pe.get("iv"),
            },
        })
    futures = _mapping(row.get("futures_evidence"))
    return {
        "status": row.get("status") or "AVAILABLE",
        "data": {
            "underlying": {
                "atm_strike": row.get("atm_strike") or _mapping(row.get("underlying_evidence")).get("atm_strike"),
                "ltp": row.get("spot"),
                "expiry": row.get("expiry"),
                "source_event_time": _timestamp(row),
                "receipt_timestamp": row.get("receipt_timestamp"),
            },
            "futures": futures,
            "atm_window": window,
            "tactical_edge": _mapping(row.get("tactical_edge")),
        },
    }


def _timeline_row(
    *,
    row: Mapping[str, Any],
    result: Mapping[str, Any],
    previous_state: str | None,
    previous_event_count: int,
    current_event_count: int,
) -> dict[str, Any]:
    fusion = _mapping(result.get("fusion"))
    hero = _mapping(result.get("hero"))
    evidence = _mapping(fusion.get("evidence"))
    return {
        "timestamp": _timestamp(row),
        "hero_state": hero.get("state"),
        "fusion_state": fusion.get("state"),
        "previous_fusion_state": previous_state,
        "transition_emitted": current_event_count > previous_event_count,
        "transition_event_id": result.get("state_event_id") if current_event_count > previous_event_count else None,
        "price_structure": _mapping(evidence.get("price_futures")),
        "flow": _mapping(evidence.get("flow")),
        "options": _mapping(evidence.get("options")),
        "ose": _mapping(_mapping(evidence.get("secondary_context")).get("ose")),
        "data_quality": _mapping(result.get("data_quality")),
        "next_proof": fusion.get("next_proof"),
        "action": fusion.get("action"),
        "transition_reason": fusion.get("transition_reason"),
        "exact_blockers": list(fusion.get("transition_blockers") or ()),
        "flow_microstructure": "UNKNOWN_NOT_RECONSTRUCTED",
    }


def _event_ledger(events: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    ledger: dict[str, list[dict[str, Any]]] = {state: [] for state in EVENT_STATES}
    for event in events:
        if event.get("event_type") != "ARGUS_FUSION_STATE_EVENT":
            continue
        state = _mapping(event.get("to")).get("fusion_state")
        if state in ledger:
            ledger[state].append({
                "state_event_id": event.get("state_event_id"),
                "timestamp": event.get("state_timestamp"),
                "from": _mapping(event.get("from")).get("fusion_state"),
                "reason": event.get("reason"),
                "data_quality": _mapping(event.get("data_quality")),
            })
    return ledger


def _checkpoints(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for item in timeline:
        try:
            parsed.append((datetime.fromisoformat(str(item.get("timestamp"))), item))
        except (TypeError, ValueError):
            continue
    checkpoints: list[dict[str, Any]] = []
    for requested in CHECKPOINTS:
        target = datetime.fromisoformat(f"2026-08-12T{requested}:00+05:30")
        if not parsed:
            checkpoints.append({"requested_ist": requested, "status": "NO_GENUINE_SNAPSHOT"})
            continue
        _, nearest = min(parsed, key=lambda pair: abs((pair[0] - target).total_seconds()))
        checkpoints.append({"requested_ist": requested, **nearest})
    return checkpoints


def _quote_index(rows: list[Mapping[str, Any]]) -> list[tuple[datetime, dict[str, dict[str, Any]]]]:
    indexed: list[tuple[datetime, dict[str, dict[str, Any]]]] = []
    for row in rows:
        timestamp = _timestamp(row)
        try:
            instant = datetime.fromisoformat(str(timestamp))
        except (TypeError, ValueError):
            continue
        quotes: dict[str, dict[str, Any]] = {}
        for chain_row in row.get("option_chain_evidence") or ():
            item = _mapping(chain_row)
            for source_key, side in (("CE", "CE"), ("PE", "PE")):
                leg = _mapping(item.get(source_key))
                security_id = str(leg.get("security_id") or "")
                if security_id:
                    quotes[security_id] = {
                        "security_id": security_id, "side": side, "strike": item.get("strike"),
                        "bid": _number(leg.get("bid_price")), "ask": _number(leg.get("ask_price")),
                        "ltp": _number(leg.get("ltp")),
                    }
        indexed.append((instant, quotes))
    return indexed


def _premium_counterfactual(rows: list[Mapping[str, Any]], events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Research-only ASK/BID outcome lookup; it never mutates engine records."""

    indexed = _quote_index(rows)
    by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        state = _mapping(event.get("to")).get("fusion_state")
        if state not in {"WATCH", "SETUP", "TRIGGER"}:
            continue
        snapshot = _mapping(event.get("state_snapshot"))
        try:
            event_time = datetime.fromisoformat(str(event.get("state_timestamp")))
        except (TypeError, ValueError):
            by_state[state].append({"status": "UNKNOWN", "reason": "EVENT_TIMESTAMP_UNAVAILABLE"})
            continue
        contracts = [
            _mapping(contract) for contract in snapshot.get("focus_contracts") or ()
            if isinstance(contract, Mapping)
        ]
        entries: list[dict[str, Any]] = []
        for contract in contracts:
            security_id = str(contract.get("security_id") or "")
            entry_ask = _number(contract.get("ask"))
            if not security_id or entry_ask is None or entry_ask <= 0:
                entries.append({"security_id": security_id or None, "status": "UNKNOWN", "reason": "EXECUTABLE_ASK_UNAVAILABLE"})
                continue
            later = [quotes[security_id] for instant, quotes in indexed if instant >= event_time and security_id in quotes]
            bids = [(index, _number(quote.get("bid"))) for index, quote in enumerate(later)]
            bids = [(index, bid) for index, bid in bids if bid is not None]
            if not bids:
                entries.append({"security_id": security_id, "status": "UNKNOWN", "reason": "SUBSEQUENT_EXECUTABLE_BID_UNAVAILABLE"})
                continue
            max_index, max_bid = max(bids, key=lambda item: item[1])
            min_index, min_bid = min(bids, key=lambda item: item[1])
            entries.append({
                "security_id": security_id,
                "side": contract.get("side"),
                "strike": contract.get("strike"),
                "event_ask": entry_ask,
                "event_bid": _number(contract.get("bid")),
                "event_ltp": _number(contract.get("ltp")),
                "event_spread": _number(contract.get("spread")),
                "max_executable_bid": max_bid,
                "min_executable_bid": min_bid,
                "mfe_percent": round((max_bid - entry_ask) / entry_ask * 100.0, 6),
                "mae_percent": round((min_bid - entry_ask) / entry_ask * 100.0, 6),
                "time_to_mfe_observations": max_index,
                "time_to_mae_observations": min_index,
                "research_only": True,
            })
        by_state[state].append({
            "state_event_id": event.get("state_event_id"), "timestamp": event.get("state_timestamp"),
            "contracts": entries, "source": "GENUINE_PERSISTED_ARGUS_OPTION_QUOTES",
        })
    return {
        state: by_state[state] or {"status": "UNKNOWN", "reason": f"NO_{state}_EVENT_FROM_GENUINE_REPLAY_INPUT"}
        for state in ("WATCH", "SETUP", "TRIGGER")
    }


def _negative_controls(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same-session non-trigger windows; missing Flow remains explicit, not filled."""

    controls = []
    for checkpoint in _checkpoints(timeline):
        if checkpoint.get("requested_ist") not in {"13:45", "14:14", "14:20", "14:25"}:
            continue
        controls.append({
            "requested_ist": checkpoint.get("requested_ist"),
            "snapshot_timestamp": checkpoint.get("timestamp"),
            "fusion_state": checkpoint.get("fusion_state"),
            "action": checkpoint.get("action"),
            "exact_blockers": checkpoint.get("exact_blockers"),
            "result": "NO_SHADOW_TRIGGER",
            "limitation": "FLOW_MICROSTRUCTURE_UNKNOWN_NOT_RECONSTRUCTED",
        })
    return controls


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _run(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clock = _ReplayClock()
    subject = FusionShadowEngine(now=clock.now)
    timeline: list[dict[str, Any]] = []
    for row in rows:
        clock.value = _timestamp(row) or clock.value
        previous_state = _mapping(subject.projection().get("fusion")).get("state")
        before_count = len(subject.session_events())
        result = subject.ingest_argus(_projection(row))
        after_count = len(subject.session_events())
        timeline.append(_timeline_row(
            row=row, result=result, previous_state=previous_state,
            previous_event_count=before_count, current_event_count=after_count,
        ))
    events = subject.session_events()
    ledger = _event_ledger(events)
    no_transitions = all(not ledger[state] for state in EVENT_STATES)
    return {
        "final_state": _mapping(subject.projection().get("fusion")).get("state"),
        "transition_timeline": timeline,
        "forensic_checkpoints": _checkpoints(timeline),
        "transition_events": ledger,
        "zero_transitions": no_transitions,
        "zero_transition_reason": (
            "NO_GENUINE_FLOW_MICROSTRUCTURE_OR_CANONICAL_STRUCTURE_TRANSITIONS_IN_REPLAY_INPUT; "
            "OPTIONS_ALONE_WERE_NOT_PROMOTED_TO_TEMPORAL_STATE_EVIDENCE"
            if no_transitions else None
        ),
        "premium_counterfactual": _premium_counterfactual(rows, events),
        "negative_controls": _negative_controls(timeline),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    first, second = _run(rows), _run(rows)
    deterministic = _canonical_hash(first) == _canonical_hash(second)
    no_transitions = bool(first["zero_transitions"])
    report = {
        "replay": f"{FUSION_VERSION}_12_AUG_DIAGNOSTIC_REPLAY",
        "source": str(args.input),
        "genuine_argus_snapshots": len(rows),
        "replay_determinism": "PASS" if deterministic else "FAIL",
        "replay_data_completeness": "PARTIAL",
        "replay_state_detection": "UNKNOWN" if no_transitions else "PASS",
        "replay_trade_detection": "UNKNOWN" if no_transitions else "PASS",
        "result": first,
        "flow_microstructure_policy": "NOT_RECONSTRUCTED_FROM_CANDLES_OR_OPTIONS",
        "post_13_59_flow": "UNKNOWN",
        "known_limitation": "POST_13_59_GENUINE_FLOW_PULSE_MICROSTRUCTURE_WAS_NOT_PERSISTED; FLOW_REMAINS_UNKNOWN_AND_NO_FLOW-DEPENDENT_TRIGGER_IS_CLAIMED",
        "hindsight_tuning_performed": False,
        "research_only": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
