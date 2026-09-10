"""Atomic, restart-safe and append-only Personal ORACLE ledger."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from .models import (
    SCHEMA_VERSION,
    BehavioralEnrichment,
    OracleAdvisory,
    OracleClassification,
    OracleEvent,
    OracleObservation,
    OracleOutcomeEvaluation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "logs" / "personal_oracle.json"
_LEDGER_LOCK = Lock()


class OracleLedgerError(RuntimeError):
    pass


class PersonalOracleLedger:
    def __init__(self, path: Path | str | None = None, max_events: int = 5000):
        configured_path = (
            path
            if path is not None
            else os.environ.get("CITADEL_PERSONAL_ORACLE_LEDGER_PATH", str(DEFAULT_PATH))
        )
        self.path = Path(configured_path)
        self.max_events = max_events
        self._cache: tuple[tuple[int, int, int], dict[str, Any]] | None = None

    def load_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_document()
        try:
            signature = self._signature()
            if self._cache is not None and self._cache[0] == signature:
                return json.loads(json.dumps(self._cache[1]))
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("schema_version") not in {1, 2, SCHEMA_VERSION} or not isinstance(raw.get("events"), list):
                raise ValueError("invalid ledger shape")
            for key in ("enrichments", "classifications", "observations", "advisories", "outcomes"):
                raw.setdefault(key, [])
            raw.setdefault("snapshot_version", 0)
            self._cache = (signature, raw)
            return raw
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise OracleLedgerError("Personal ORACLE ledger is unavailable or corrupt") from error

    def events(self) -> tuple[OracleEvent, ...]:
        return tuple(OracleEvent.from_mapping(row) for row in self.load_document()["events"])

    def enrichments(self) -> tuple[BehavioralEnrichment, ...]:
        return tuple(BehavioralEnrichment.from_mapping(row) for row in self.load_document().get("enrichments", []))

    def classifications(self) -> tuple[OracleClassification, ...]:
        return tuple(OracleClassification.from_mapping(row) for row in self.load_document().get("classifications", []))

    def observations(self) -> tuple[OracleObservation, ...]:
        return tuple(OracleObservation.from_mapping(row) for row in self.load_document().get("observations", []))

    def advisories(self) -> tuple[OracleAdvisory, ...]:
        return tuple(OracleAdvisory.from_mapping(row) for row in self.load_document().get("advisories", []))

    def outcomes(self) -> tuple[OracleOutcomeEvaluation, ...]:
        return tuple(OracleOutcomeEvaluation.from_mapping(row) for row in self.load_document().get("outcomes", []))

    def revision(self) -> tuple[int, int, int] | None:
        return self._signature() if self.path.exists() else None

    def append(self, event: OracleEvent) -> bool:
        with _LEDGER_LOCK:
            document = self.load_document()
            if any(row.get("oracle_event_id") == event.oracle_event_id for row in document["events"]):
                return False
            if len(document["events"]) >= self.max_events:
                raise OracleLedgerError("Personal ORACLE ledger event bound reached")
            document["events"].append(event.to_dict())
            document["schema_version"] = SCHEMA_VERSION
            document["snapshot_version"] = int(document.get("snapshot_version") or 0) + 1
            self._atomic_write(document)
            return True

    def append_enrichment(self, enrichment: BehavioralEnrichment | Mapping[str, Any]) -> bool:
        typed = enrichment if isinstance(enrichment, BehavioralEnrichment) else BehavioralEnrichment.from_mapping(enrichment)
        with _LEDGER_LOCK:
            document = self.load_document()
            rows = document.setdefault("enrichments", [])
            enrichment_id = typed.enrichment_id
            if not enrichment_id or any(row.get("enrichment_id") == enrichment_id for row in rows):
                return False
            if not any(row.get("oracle_event_id") == typed.oracle_event_id for row in document["events"]):
                raise OracleLedgerError("enrichment references an unknown event")
            rows.append(typed.to_dict())
            document["snapshot_version"] = int(document.get("snapshot_version") or 0) + 1
            self._atomic_write(document)
            return True

    def append_advisory(self, advisory: OracleAdvisory) -> bool:
        with _LEDGER_LOCK:
            document = self.load_document()
            rows = document.setdefault("advisories", [])
            if any(row.get("advisory_id") == advisory.advisory_id for row in rows):
                return False
            rows.append(advisory.to_dict())
            document["snapshot_version"] = int(document.get("snapshot_version") or 0) + 1
            self._atomic_write(document)
            return True

    def append_outcome(self, outcome: OracleOutcomeEvaluation) -> bool:
        with _LEDGER_LOCK:
            document = self.load_document()
            rows = document.setdefault("outcomes", [])
            if any(row.get("outcome_evaluation_id") == outcome.outcome_evaluation_id for row in rows):
                return False
            if not any(row.get("advisory_id") == outcome.advisory_id for row in document.get("advisories", [])):
                raise OracleLedgerError("outcome references an unknown advisory")
            rows.append(outcome.to_dict())
            document["snapshot_version"] = int(document.get("snapshot_version") or 0) + 1
            self._atomic_write(document)
            return True

    def replace_analysis(
        self,
        classifications: tuple[OracleClassification, ...],
        observations: tuple[OracleObservation, ...],
    ) -> None:
        with _LEDGER_LOCK:
            document = self.load_document()
            document["schema_version"] = SCHEMA_VERSION
            document["classifications"] = [row.to_dict() for row in classifications]
            document["observations"] = [row.to_dict() for row in observations]
            document["snapshot_version"] = int(document.get("snapshot_version") or 0) + 1
            self._atomic_write(document)

    def _atomic_write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._cache = (self._signature(), dict(document))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _signature(self) -> tuple[int, int, int]:
        stat = self.path.stat()
        return stat.st_ino, stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _empty_document() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_version": 0,
            "events": [],
            "enrichments": [],
            "classifications": [],
            "observations": [],
            "advisories": [],
            "outcomes": [],
        }
