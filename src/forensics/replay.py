"""Read-only replay over immutable decision evidence and authoritative candles."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .journal import EvidenceJournal


class OpportunityReplayEngine:
    """Reconstructs persisted decisions without invoking any production engine."""

    def __init__(self, journal=None, candle_path="logs/kronos_alpha_candles.json", kronos_alpha_history="logs/kronos_alpha_history.json", chronos_2_history="logs/chronos_2_history.json"):
        self.journal = journal or EvidenceJournal()
        self.candle_path = Path(candle_path)
        self.kronos_alpha_history = Path(kronos_alpha_history)
        self.chronos_2_history = Path(chronos_2_history)

    def replay(self, candle_timestamp, *, outcome_until=None):
        row = self.journal.latest(event_type="CANDLE_DECISION_ENVELOPE", candle_id=str(candle_timestamp))
        if row is None:
            return {
                "status": "NOT_AVAILABLE",
                "candle_timestamp": str(candle_timestamp),
                "reason": "IMMUTABLE_DECISION_ENVELOPE_NOT_FOUND",
                "production_recalculation_performed": False,
            }
        envelope = deepcopy(row["payload"])
        return {
            "status": "RECONSTRUCTED",
            "candle_timestamp": str(candle_timestamp),
            "evidence_record_id": row["record_id"],
            "evidence_record_hash": row["record_hash"],
            "production_recalculation_performed": False,
            "technical": envelope.get("technical"),
            "kronos_core": envelope.get("kronos_core"),
            "kronos_alpha": self._forecast_at(self.kronos_alpha_history, "last_candle_timestamp", str(candle_timestamp), envelope.get("modules", {}).get("kronos_alpha")),
            "chronos_2": self._forecast_at(self.chronos_2_history, "context_end", str(candle_timestamp), envelope.get("modules", {}).get("chronos_2")),
            "argus": envelope.get("modules", {}).get("argus"),
            "athena": envelope.get("modules", {}).get("athena"),
            "oracle": envelope.get("modules", {}).get("personal_oracle"),
            "hermes": envelope.get("modules", {}).get("hermes"),
            "aegis": envelope.get("modules", {}).get("aegis_decision"),
            "risk": envelope.get("modules", {}).get("risk"),
            "paper": envelope.get("modules", {}).get("paper_execution"),
            "decision": envelope.get("final_decision"),
            "rejected_reason": envelope.get("why_no_trade"),
            "expected_trade": envelope.get("strategy"),
            "actual_market_outcome": self._outcome(envelope, outcome_until),
            "limitations": envelope.get("limitations", []),
        }

    def verify_evidence(self):
        return self.journal.verify()

    def _outcome(self, envelope, outcome_until):
        signal = envelope.get("strategy") or {}
        side = signal.get("signal")
        entry = signal.get("entry")
        if side not in {"BUY", "SELL"} or entry is None:
            return {"status": "NOT_APPLICABLE", "mfe": None, "mae": None, "reason": "NO_DIRECTIONAL_EXPECTED_TRADE"}
        if outcome_until is None:
            return {"status": "NOT_DETERMINABLE", "mfe": None, "mae": None, "reason": "OUTCOME_HORIZON_REQUIRED"}
        candles = self._candles()
        origin = str(envelope["candle"]["timestamp"])
        future = [row for row in candles if str(row.get("timestamp")) > origin and str(row.get("timestamp")) <= str(outcome_until)]
        if not future:
            return {"status": "NOT_DETERMINABLE", "mfe": None, "mae": None, "reason": "AUTHORITATIVE_FUTURE_CANDLES_UNAVAILABLE"}
        entry = float(entry)
        if side == "BUY":
            mfe = max(float(row["high"]) - entry for row in future)
            mae = max(entry - float(row["low"]) for row in future)
        else:
            mfe = max(entry - float(row["low"]) for row in future)
            mae = max(float(row["high"]) - entry for row in future)
        terminal = float(future[-1]["close"]) - entry
        if side == "SELL": terminal *= -1
        return {
            "status": "OBSERVED_UNDERLYING_ONLY",
            "horizon_end": str(outcome_until),
            "candles": len(future),
            "mfe_points": round(max(0.0, mfe), 6),
            "mae_points": round(max(0.0, mae), 6),
            "terminal_move_points": round(terminal, 6),
            "option_pnl": None,
            "option_pnl_reason": "TIMESTAMP_ALIGNED_OPTION_CANDLES_NOT_AVAILABLE",
        }

    def _candles(self):
        try:
            value = json.loads(self.candle_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        rows = value.get("candles", value) if isinstance(value, dict) else value
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _forecast_at(path, origin_key, origin, fallback):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            rows = value.get("forecasts", [])
            match = next((row for row in reversed(rows) if str(row.get(origin_key)) == origin), None)
            if match is not None:
                return {**deepcopy(match), "evidence_source": str(path), "publication_persisted": True}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return fallback or {"status": "NOT_AVAILABLE", "reason": "FORECAST_PUBLICATION_NOT_FOUND_FOR_CANDLE"}
