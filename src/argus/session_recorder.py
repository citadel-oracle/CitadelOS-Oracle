"""Append-only, restart-safe production evidence for ARGUS PRIME audits."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Sequence


class ArgusSessionRecorderError(RuntimeError):
    """Raised when the authoritative session stream cannot be trusted."""


class ArgusSessionRecorder:
    """Persist each distinct authoritative ARGUS snapshot exactly once."""

    SCHEMA_VERSION = 1

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = Lock()
        self._seen: dict[str, set[str]] = {}

    def append(
        self,
        *,
        projection: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        source: Mapping[str, Any],
    ) -> bool:
        record = self._record(projection=projection, rows=rows, source=source)
        calculation_id = str(record["calculation_id"])
        session_date = str(record["session_date"])
        with self._lock:
            seen = self._seen_ids(session_date)
            if calculation_id in seen:
                return False
            path = self._path(session_date)
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = (
                json.dumps(
                    record,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            try:
                descriptor = os.open(
                    path,
                    os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                    0o600,
                )
                try:
                    remaining = memoryview(encoded)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("short append")
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError as error:
                raise ArgusSessionRecorderError(
                    "ARGUS_SESSION_RECORD_APPEND_FAILED"
                ) from error
            seen.add(calculation_id)
            return True

    def _seen_ids(self, session_date: str) -> set[str]:
        cached = self._seen.get(session_date)
        if cached is not None:
            return cached
        path = self._path(session_date)
        seen: set[str] = set()
        if path.exists():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict) or not item.get(
                        "calculation_id"
                    ):
                        raise ValueError("invalid record")
                    seen.add(str(item["calculation_id"]))
            except (OSError, json.JSONDecodeError, ValueError) as error:
                raise ArgusSessionRecorderError(
                    "ARGUS_SESSION_RECORD_CORRUPT"
                ) from error
        self._seen[session_date] = seen
        return seen

    def _path(self, session_date: str) -> Path:
        return self.root / f"{session_date}.jsonl"

    @classmethod
    def _record(
        cls,
        *,
        projection: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        source: Mapping[str, Any],
    ) -> dict[str, Any]:
        prime = (
            projection.get("argus_prime")
            if isinstance(projection.get("argus_prime"), Mapping)
            else {}
        )
        source_event_time = projection.get("source_event_time")
        receipt_timestamp = (
            projection.get("receipt_timestamp")
            or projection.get("observation_timestamp")
        )
        # Session partitioning needs a trustworthy observation time; a
        # provider event is preferred but a receipt remains explicitly
        # labelled and is never promoted to source-event lineage.
        observation_timestamp = source_event_time or receipt_timestamp
        try:
            session_date = datetime.fromisoformat(
                str(observation_timestamp)
            ).date().isoformat()
        except ValueError as error:
            raise ArgusSessionRecorderError(
                "ARGUS_SESSION_SOURCE_TIMESTAMP_INVALID"
            ) from error
        futures = (
            source.get("futures")
            if isinstance(source.get("futures"), Mapping)
            else {}
        )
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "record_type": "ARGUS_PRIME_AUTHORITATIVE_SNAPSHOT",
            "session_date": session_date,
            "calculation_id": projection.get("calculation_id"),
            "snapshot_id": prime.get("snapshot_id"),
            "chain_snapshot_id": projection.get("chain_snapshot_id"),
            "source_timestamp": source_event_time,
            "source_event_time": source_event_time,
            "receipt_timestamp": receipt_timestamp,
            "observation_timestamp": observation_timestamp,
            "spot_source_timestamp": projection.get("spot_source_timestamp"),
            "option_chain_source_timestamp": projection.get(
                "option_chain_source_timestamp"
            ),
            "calculated_at": projection.get("calculated_at"),
            "symbol": projection.get("symbol"),
            "expiry": projection.get("expiry"),
            "spot": projection.get("spot"),
            "raw_scores": {
                "hero": prime.get("raw_score"),
                "engines": {
                    name: value.get("raw_score")
                    for name, value in (
                        prime.get("outcome_engines") or {}
                    ).items()
                    if isinstance(value, Mapping)
                },
            },
            "smoothed_scores": {
                "hero": prime.get("smoothed_score"),
                "engines": {
                    name: value.get("smoothed_score")
                    for name, value in (
                        prime.get("outcome_engines") or {}
                    ).items()
                    if isinstance(value, Mapping)
                },
            },
            "displayed_state": {
                "raw_direction": prime.get("raw_direction"),
                "direction": prime.get("direction"),
                "action": prime.get("action"),
                "score": prime.get("display_score"),
                "move_state": prime.get("move_state"),
                "retest_status": prime.get("retest_status"),
                "stability": deepcopy(prime.get("stability")),
            },
            "option_chain_evidence": [
                cls._option_row(item) for item in rows
            ],
            "futures_evidence": deepcopy(dict(futures)),
            "flow_evidence": deepcopy(prime.get("smart_money_flow")),
            "wall_evidence": deepcopy(prime.get("wall_outcome")),
            "gamma_evidence": {
                "regime": deepcopy(prime.get("gamma_regime")),
                "blast": deepcopy(prime.get("expiry_gamma_blast")),
            },
            "recommended_contract": deepcopy(
                prime.get("recommended_contract")
            ),
            "trigger": prime.get("trigger"),
            "invalidation": prime.get("invalidation_text"),
            "execution_influence": "ZERO",
        }

    @staticmethod
    def _option_row(row: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {"strike": row.get("strike")}
        for source_key, output_key in (("ce", "CE"), ("pe", "PE")):
            leg = row.get(source_key)
            if not isinstance(leg, Mapping):
                result[output_key] = None
                continue
            result[output_key] = {
                key: deepcopy(leg.get(key))
                for key in (
                    "security_id",
                    "trading_symbol",
                    "option_type",
                    "ltp",
                    "previous_close",
                    "oi",
                    "previous_oi",
                    "volume",
                    "iv",
                    "bid_price",
                    "ask_price",
                    "bid_quantity",
                    "ask_quantity",
                    "delta",
                    "gamma",
                    "theta",
                    "vega",
                    "source_timestamp",
                )
            }
        return result
