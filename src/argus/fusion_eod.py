"""Read-only end-of-day summaries for ARGUS Fusion Shadow evidence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Mapping


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


class FusionShadowEODAnalyzer:
    """Consumes only append-only Fusion records, never live engine state."""

    def __init__(self, recorder: Any) -> None:
        self.recorder = recorder

    def analyze_session(self, session_id: str) -> dict[str, Any]:
        rows = self.recorder.read_fusion_session(session_id)
        return self.analyze_rows(rows, session_id=session_id)

    def analyze_rows(self, rows: list[Mapping[str, Any]], *, session_id: str | None = None) -> dict[str, Any]:
        events = [dict(row) for row in rows if isinstance(row, Mapping)]
        state_events = [row for row in events if row.get("event_type") == "ARGUS_FUSION_STATE_EVENT"]
        trade_events = [row for row in events if str(row.get("event_type", "")).startswith("ARGUS_FUSION_TRADE_")]
        latest_trade: dict[str, dict[str, Any]] = {}
        for row in trade_events:
            trade_id = str(row.get("trade_id") or "")
            if trade_id:
                latest_trade[trade_id] = row
        fusion_counts = Counter(
            str(_mapping(row.get("to")).get("fusion_state") or "UNKNOWN")
            for row in state_events
        )
        hero_timeline = [
            {
                "state_event_id": row.get("state_event_id"),
                "timestamp": row.get("state_timestamp"),
                "hero_state": _mapping(row.get("to")).get("hero_state"),
                "fusion_state": _mapping(row.get("to")).get("fusion_state"),
                "reason": row.get("reason"),
                "data_quality": _mapping(row.get("data_quality")),
            }
            for row in state_events
        ]
        closed = [trade for trade in latest_trade.values() if trade.get("status") in {"CLOSED", "INVALIDATED"}]
        unresolved = [trade for trade in latest_trade.values() if trade.get("status") not in {"CLOSED", "INVALIDATED"}]
        return {
            "status": "AVAILABLE",
            "session_id": session_id,
            "source": "ARGUS_FUSION_SHADOW_APPEND_ONLY_LEDGER",
            "state_counts": {
                "watch": fusion_counts["WATCH"],
                "setup": fusion_counts["SETUP"],
                "trigger": fusion_counts["TRIGGER"],
                "runner": fusion_counts["RUNNER"],
                "invalidated": fusion_counts["INVALIDATED"],
                "data_locked": fusion_counts["DATA_LOCKED"],
            },
            "hero_timeline": hero_timeline,
            "shadow_trades": {
                "count": len(latest_trade),
                "closed_or_invalidated": len(closed),
                "unresolved": len(unresolved),
                "records": deepcopy(list(latest_trade.values())),
                "result_policy": "NO_EDGE_CLAIM_FROM_A_SINGLE_SESSION_OR_UNRESOLVED_RESEARCH_RECORD",
            },
            "data_quality": {
                "locked_events": fusion_counts["DATA_LOCKED"],
                "source_rows": len(events),
                "recorder_drops": _mapping(self.recorder.health()).get("RECORDER_DROPS"),
            },
            "advisory_only": True,
            "execution_influence": "ZERO",
            "broker_submission": False,
        }
