"""Immutable Sol Shadow Ledger, Prediction Store & DuckDB Engine (P0.2 Hardened).

Persists every reasoning cycle, exact model request envelope, immutable prediction,
and separate evaluation record into an append-only ledger with visible persistence telemetry
and single-owner database access.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.oracle_sol.gemini_adapter import safe_provider_error_telemetry

from src.oracle_sol.contracts import (
    SolBeaconOutput,
    SolEvidenceSnapshot,
    SolModelRequestEnvelope,
    ThesisState,
)


class SolShadowLedger:
    """Thread-safe append-only ledger with visible JSONL and DuckDB health."""

    def __init__(
        self,
        runtime_mode: str,
        storage_dir: Optional[str] = None,
        ledger_file_path: Optional[str] = None,
        duckdb_path: Optional[str] = None,
    ) -> None:
        normalized_runtime_mode = str(runtime_mode).strip().upper()
        if normalized_runtime_mode not in {"LIVE", "REPLAY", "TEST"}:
            raise ValueError("runtime_mode must be one of LIVE, REPLAY, or TEST")

        if storage_dir:
            default_dir = Path(storage_dir)
        elif ledger_file_path:
            default_dir = Path(ledger_file_path).parent
        elif duckdb_path:
            default_dir = Path(duckdb_path).parent
        else:
            default_dir = Path("data/sol_shadow")

        self.ledger_file_path = Path(
            ledger_file_path or default_dir / "sol_shadow_cycles.jsonl"
        )
        self.duckdb_path = Path(
            duckdb_path or default_dir / "sol_shadow.duckdb"
        )
        self.ledger_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_mode = normalized_runtime_mode
        self._lock = threading.Lock()
        self._jsonl_ok: bool = True
        self._duckdb_ok: bool = False
        self._last_successful_write_utc: Optional[str] = None
        self._last_persistence_error: Optional[str] = None
        self._init_duckdb()

    @property
    def duckdb_health(self) -> str:
        return "OK" if self._duckdb_ok else "DEGRADED"

    def _init_duckdb(self) -> None:
        """Initialize DuckDB table schema for the single Oracle owner."""
        con = None
        try:
            import duckdb

            config = {
                "max_memory": "1200MB",
                "threads": "2",
                "preserve_insertion_order": "false",
            }
            con = duckdb.connect(str(self.duckdb_path), config=config)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sol_shadow_ledger (
                    cycle_id VARCHAR PRIMARY KEY,
                    timestamp_utc TIMESTAMP,
                    timestamp_ist VARCHAR,
                    snapshot_id VARCHAR,
                    previous_thesis_id VARCHAR,
                    new_thesis_id VARCHAR,
                    system_status VARCHAR,
                    reasoning_status VARCHAR,
                    market_verdict VARCHAR,
                    developing_state VARCHAR,
                    what_changed VARCHAR,
                    core_narrative VARCHAR,
                    strongest_contradiction VARCHAR,
                    configured_model VARCHAR,
                    actually_invoked_model VARCHAR,
                    latency_str VARCHAR,
                    input_hash VARCHAR,
                    status VARCHAR,
                    vob_free_verified VARCHAR,
                    raw_payload_json VARCHAR
                )
                """
            )
            self._duckdb_ok = True
        except Exception as exc:
            self._duckdb_ok = False
            self._last_persistence_error = f"DuckDB init warning: {exc}"
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    def record_cycle(
        self,
        cycle_id: str,
        snapshot: SolEvidenceSnapshot,
        previous_thesis_id: str,
        new_thesis: ThesisState,
        beacon: SolBeaconOutput,
        telemetry: Dict[str, Any],
        recent_event_ids: List[str],
        request_envelope: Optional[SolModelRequestEnvelope] = None,
    ) -> str:
        """Record an immutable ledger entry preserving canonical cycle_id and exact input envelope."""
        now_utc = datetime.now(timezone.utc).isoformat()
        now_ist = snapshot.timestamp_ist
        input_hash = request_envelope.input_hash if request_envelope else telemetry.get("input_hash", "")

        record: Dict[str, Any] = {
            "cycle_id": cycle_id,
            "timestamp_utc": now_utc,
            "timestamp_ist": now_ist,
            "snapshot_id": snapshot.snapshot_id,
            "event_ids": recent_event_ids,
            "previous_thesis_id": previous_thesis_id,
            "new_thesis_id": new_thesis.thesis_id,
            "system_status": beacon.system_status,
            "reasoning_status": beacon.reasoning_status,
            "market_verdict": beacon.market_verdict,
            "developing_state": beacon.developing_state,
            "what_changed": new_thesis.what_changed,
            "core_narrative": new_thesis.core_narrative,
            "strongest_contradiction": new_thesis.strongest_contradiction,
            "active_expectations": [
                e.to_dict() for e in new_thesis.active_expectations
            ],
            "evaluation_history": [
                e.to_dict() for e in new_thesis.evaluation_history
            ],
            "configured_model": beacon.configured_model,
            "actually_invoked_model": beacon.actually_invoked_model,
            "api_latency": telemetry.get("api_latency", "NOT MEASURED"),
            "input_hash": input_hash,
            "request_envelope": request_envelope.to_dict() if request_envelope else None,
            "status": telemetry.get("status", "SUCCESS"),
            "provider_error_telemetry": safe_provider_error_telemetry(telemetry),
            "runtime_mode": self.runtime_mode,
            "vob_free_verified": "ZERO_VOB_ALLOWLIST_CONFIRMED",
            "snapshot_data": snapshot.to_dict(),
            "external_context_id": (
                request_envelope.user_payload.get("external_context", {}).get("external_context_id")
                if request_envelope and isinstance(request_envelope.user_payload, dict) and isinstance(request_envelope.user_payload.get("external_context"), dict)
                else None
            ),
        }

        with self._lock:
            # 1. Append to JSONL
            try:
                with open(self.ledger_file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                self._jsonl_ok = True
                self._last_successful_write_utc = now_utc
            except Exception as exc:
                self._jsonl_ok = False
                self._last_persistence_error = f"JSONL write error: {exc}"

            # 2. Append to DuckDB under the single-owner process lock
            con = None
            try:
                import duckdb

                config = {
                    "max_memory": "1200MB",
                    "threads": "2",
                    "preserve_insertion_order": "false",
                }
                con = duckdb.connect(str(self.duckdb_path), config=config)
                con.execute(
                    """
                    INSERT INTO sol_shadow_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        datetime.now(timezone.utc),
                        now_ist,
                        snapshot.snapshot_id,
                        previous_thesis_id,
                        new_thesis.thesis_id,
                        beacon.system_status,
                        beacon.reasoning_status,
                        beacon.market_verdict or "NONE",
                        beacon.developing_state,
                        new_thesis.what_changed,
                        new_thesis.core_narrative,
                        new_thesis.strongest_contradiction,
                        beacon.configured_model,
                        beacon.actually_invoked_model,
                        str(telemetry.get("api_latency", "NOT MEASURED")),
                        input_hash,
                        telemetry.get("status", "SUCCESS"),
                        "ZERO_VOB_ALLOWLIST_CONFIRMED",
                        json.dumps(record, sort_keys=True, default=str),
                    ),
                )
                self._duckdb_ok = True
            except Exception as exc:
                self._duckdb_ok = False
                self._last_persistence_error = f"DuckDB write lock contention or error: {exc}"
            finally:
                if con is not None:
                    try:
                        con.close()
                    except Exception:
                        pass

        return cycle_id

    def read_recent_cycles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Read recent reasoning cycles from JSONL ledger."""
        if not self.ledger_file_path.exists():
            return []

        cycles: List[Dict[str, Any]] = []
        with self._lock:
            with open(self.ledger_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            cycles.append(json.loads(line))
                        except Exception:
                            continue
        return cycles[-limit:]

    def health(self) -> Dict[str, Any]:
        """Return visible persistence health telemetry."""
        with self._lock:
            return {
                "runtime_mode": self.runtime_mode,
                "jsonl_health": "OK" if self._jsonl_ok else "ERROR",
                "duckdb_health": "OK" if self._duckdb_ok else "DEGRADED",
                "last_successful_write_utc": self._last_successful_write_utc,
                "last_persistence_error": self._last_persistence_error,
                "ledger_file_path": str(self.ledger_file_path),
                "duckdb_path": str(self.duckdb_path),
            }
