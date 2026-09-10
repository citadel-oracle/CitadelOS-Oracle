"""Append-only Visual Edge learning stream owned by Personal Oracle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
import tempfile
from typing import Any, Callable, Mapping

from src.oracle.contracts.learning import (
    CaptureCompleteness, LabelRevision, RetentionPermission,
    VisualArtifactReference, VisualEdgeLabel, VisualEdgeObservation,
    VisualEdgeOutcomeLink, VisualEdgeReason, seal,
)


class VisualEdgeError(RuntimeError):
    pass


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,200}$")


def _safe_id(value: str) -> str:
    value = str(value)
    if not _SAFE_ID.fullmatch(value): raise VisualEdgeError("VISUAL_EDGE_ID_INVALID")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(value)); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class VisualEdgeStore:
    """Hash-chained journal plus immutable payload files; projections are read-only."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.journal = self.root / "journal.jsonl"
        self.idempotency = self.root / "idempotency.json"
        self._lock = RLock()

    def append(self, *, event_type: str, record_id: str, payload: Mapping[str, Any],
               idempotency_key: str, operation: str) -> dict[str, Any]:
        record_id = _safe_id(record_id)
        if not idempotency_key.strip():
            raise VisualEdgeError("IDEMPOTENCY_KEY_REQUIRED")
        request_hash = _hash({"operation": operation, "payload": payload})
        with self._lock:
            index = self._index()
            existing = index.get(idempotency_key)
            if existing:
                if existing.get("request_hash") != request_hash or existing.get("operation") != operation:
                    raise VisualEdgeError("IDEMPOTENCY_CONFLICT")
                return self._payload(str(existing["event_type"]), str(existing["record_id"]))
            events = self._validated_events()
            duplicate = next((row for row in events if row.get("event_type") == event_type
                              and row.get("record_id") == record_id), None)
            if duplicate is not None:
                current = self._payload(event_type, record_id)
                if current != dict(payload): raise VisualEdgeError("IMMUTABLE_VISUAL_EDGE_CONFLICT")
                index[idempotency_key] = {"operation": operation, "request_hash": request_hash,
                                          "event_type": event_type, "record_id": record_id}
                _atomic(self.idempotency, index)
                return current
            previous = events[-1]["event_hash"] if events else "0" * 64
            envelope = {
                "sequence": len(events) + 1, "event_type": event_type, "record_id": record_id,
                "payload_hash": _hash(payload), "previous_hash": previous,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            envelope["event_hash"] = _hash(envelope)
            path = self.root / event_type / f"{record_id}.json"
            if path.exists():
                current = json.loads(path.read_text(encoding="utf-8"))
                if current != dict(payload): raise VisualEdgeError("IMMUTABLE_VISUAL_EDGE_CONFLICT")
            else:
                _atomic(path, dict(payload))
            self.root.mkdir(parents=True, exist_ok=True)
            with self.journal.open("ab") as handle:
                handle.write(_canonical(envelope) + b"\n"); handle.flush(); os.fsync(handle.fileno())
            index[idempotency_key] = {"operation": operation, "request_hash": request_hash,
                                      "event_type": event_type, "record_id": record_id}
            _atomic(self.idempotency, index)
            return dict(payload)

    def observation(self, observation_id: str) -> dict[str, Any] | None:
        observation_id = _safe_id(observation_id)
        path = self.root / "observations" / f"{observation_id}.json"
        if not path.exists(): return None
        observation = json.loads(path.read_text(encoding="utf-8"))
        revisions = self._related("revisions", observation_id)
        outcomes = self._related("outcomes", observation_id)
        return {"observation": observation, "revisions": revisions, "outcomes": outcomes,
                "current_label_version": 1 + len(revisions), "journal_verified": self.verify_chain()}

    def current_version(self, observation_id: str) -> int:
        projection = self.observation(observation_id)
        if projection is None: raise VisualEdgeError("VISUAL_EDGE_OBSERVATION_UNAVAILABLE")
        return int(projection["current_label_version"])

    def eligible_observation_ids(self) -> tuple[str, ...]:
        root = self.root / "observations"
        if not root.exists(): return ()
        eligible = []
        for path in sorted(root.glob("*.json")):
            projection = self.observation(path.stem)
            if not projection or not projection["outcomes"]: continue
            observation = projection["observation"]
            if (observation.get("retention_permission", {}).get("retention_status") == "ACTIVE"
                    and any(row.get("model_training_eligible") for row in projection["outcomes"])):
                eligible.append(path.stem)
        return tuple(eligible)

    def verify_chain(self) -> bool:
        self._validated_events(); return True

    def _related(self, kind: str, observation_id: str) -> list[dict[str, Any]]:
        root = self.root / kind
        if not root.exists(): return []
        rows = []
        for path in sorted(root.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("observation_id") == observation_id: rows.append(value)
        return rows

    def _payload(self, kind: str, record_id: str) -> dict[str, Any]:
        record_id = _safe_id(record_id)
        return json.loads((self.root / kind / f"{record_id}.json").read_text(encoding="utf-8"))

    def _index(self) -> dict[str, Any]:
        if not self.idempotency.exists(): return {}
        try:
            value = json.loads(self.idempotency.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise VisualEdgeError("VISUAL_EDGE_IDEMPOTENCY_INDEX_CORRUPT") from error
        return value if isinstance(value, dict) else {}

    def _validated_events(self) -> list[dict[str, Any]]:
        if not self.journal.exists(): return []
        events, previous = [], "0" * 64
        try:
            lines = self.journal.read_text(encoding="utf-8").splitlines()
            for sequence, line in enumerate(lines, 1):
                value = json.loads(line)
                claimed = value.pop("event_hash")
                if value.get("sequence") != sequence or value.get("previous_hash") != previous or _hash(value) != claimed:
                    raise VisualEdgeError("VISUAL_EDGE_JOURNAL_CHAIN_INVALID")
                payload = self._payload(str(value["event_type"]), str(value["record_id"]))
                if _hash(payload) != value.get("payload_hash"):
                    raise VisualEdgeError("VISUAL_EDGE_PAYLOAD_HASH_INVALID")
                value["event_hash"] = claimed; events.append(value); previous = claimed
        except VisualEdgeError:
            raise
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise VisualEdgeError("VISUAL_EDGE_JOURNAL_UNAVAILABLE") from error
        return events


class VisualEdgeRecorder:
    REQUIRED_TIMEFRAMES = ("1D", "4H", "1H", "15m", "5m", "3m", "1m")

    def __init__(self, store: VisualEdgeStore, *, completed_record_resolver: Callable[[str], Any | None]):
        self.store = store
        self.completed_record_resolver = completed_record_resolver

    def observe(self, raw: Mapping[str, Any], *, idempotency_key: str, actor_id: str,
                correlation_id: str) -> dict[str, Any]:
        if not actor_id or not correlation_id: raise VisualEdgeError("ACTOR_AND_CORRELATION_REQUIRED")
        hindsight = {"outcome", "mfe", "mae", "correctness_label", "evaluation_label", "completed_at", "exit_at"}
        if hindsight.intersection({str(key).lower() for key in raw}):
            raise VisualEdgeError("HINDSIGHT_FIELD_FORBIDDEN_IN_ORIGINAL_OBSERVATION")
        observed_at = str(raw.get("observed_at") or datetime.now(timezone.utc).isoformat())
        artifacts = tuple(self._artifact(row) for row in raw.get("chart_artifacts") or ())
        option_artifacts = tuple(self._artifact(row) for row in raw.get("option_chart_artifacts") or ())
        available_tf = {row.timeframe for row in artifacts if row.availability == "AVAILABLE"}
        missing = set(raw.get("missing_fields") or ())
        missing.update(f"TRADINGVIEW_ARTIFACT_{tf}" for tf in self.REQUIRED_TIMEFRAMES if tf not in available_tf)
        required_context = ("canonical_context_hashes", "authority_snapshot_ids", "option_snapshot", "decision_hash")
        missing.update(name.upper() for name in required_context if not raw.get(name))
        complete = not missing
        permission = RetentionPermission(
            actor_id=actor_id, permission=str(raw.get("permission") or "PRIVATE_RESEARCH"),
            retention_status=str(raw.get("retention_status") or "ACTIVE"), retain_until=raw.get("retain_until"),
            source_licensed=bool(raw.get("source_licensed", True)),
        )
        if permission.permission == "DENIED" or permission.retention_status != "ACTIVE":
            raise VisualEdgeError("VISUAL_EDGE_PERMISSION_OR_RETENTION_DENIED")
        completeness = CaptureCompleteness(
            state="COMPLETE" if complete else "PARTIAL", available_fields=tuple(sorted(set(raw.keys()) - {"missing_fields"})),
            missing_fields=tuple(sorted(missing)),
            training_eligible=complete and permission.permission == "RESEARCH_ELIGIBLE" and permission.source_licensed,
            policy_version="visual-edge-completeness-1.0.0",
        )
        request_hash = _hash({"raw": raw, "actor_id": actor_id, "correlation_id": correlation_id})
        observation_id = "visual-edge-" + request_hash[:24]
        observation = seal(VisualEdgeObservation(
            record_id=observation_id, observation_id=observation_id, version="1.0.0", created_at=observed_at,
            provenance={"owner": "PersonalOracle", "append_only": True, "mcp_available": False},
            correlation_id=correlation_id, observed_at=observed_at,
            label=VisualEdgeLabel(label=str(raw.get("label") or "UNSPECIFIED"),
                                  original_user_wording=str(raw.get("original_user_wording") or raw.get("label") or "")),
            reason=VisualEdgeReason(tags=tuple(raw.get("reason_tags") or ()), notes=raw.get("reason_notes")),
            chart_artifacts=artifacts, option_chart_artifacts=option_artifacts,
            tradingview_metadata=dict(raw.get("tradingview_metadata") or {}),
            canonical_context_hashes=dict(raw.get("canonical_context_hashes") or {}),
            authority_snapshot_ids=dict(raw.get("authority_snapshot_ids") or {}),
            option_snapshot=dict(raw.get("option_snapshot") or {}), decision_id=raw.get("decision_id"),
            decision_hash=raw.get("decision_hash"), trigger_definition=dict(raw.get("trigger_definition") or {}),
            invalidation_definition=dict(raw.get("invalidation_definition") or {}),
            target_definitions=tuple(dict(row) for row in raw.get("target_definitions") or ()),
            completeness=completeness, retention_permission=permission,
        ))
        return self.store.append(event_type="observations", record_id=observation_id, payload=observation.to_dict(),
                                 idempotency_key=idempotency_key, operation="CREATE_OBSERVATION")

    def revise(self, observation_id: str, raw: Mapping[str, Any], *, idempotency_key: str,
               actor_id: str, correlation_id: str, expected_prior_version: int) -> dict[str, Any]:
        if not actor_id or not correlation_id: raise VisualEdgeError("ACTOR_AND_CORRELATION_REQUIRED")
        if self.store.current_version(observation_id) != expected_prior_version:
            raise VisualEdgeError("EXPECTED_PRIOR_VERSION_CONFLICT")
        revision_id = f"{observation_id}-revision-{expected_prior_version + 1}"
        revision = seal(LabelRevision(
            record_id=revision_id, version="1.0.0", created_at=datetime.now(timezone.utc).isoformat(),
            provenance={"correlation_id": correlation_id, "append_only": True}, observation_id=observation_id,
            prior_version=expected_prior_version, revision_version=expected_prior_version + 1,
            revised_label=VisualEdgeLabel(label=str(raw.get("label") or ""), original_user_wording=str(raw.get("original_user_wording") or "")),
            reason=str(raw.get("reason") or ""), actor_id=actor_id,
        ))
        return self.store.append(event_type="revisions", record_id=revision_id, payload=revision.to_dict(),
                                 idempotency_key=idempotency_key, operation="REVISE_LABEL")

    def link_outcome(self, observation_id: str, raw: Mapping[str, Any], *, idempotency_key: str,
                     actor_id: str, correlation_id: str) -> dict[str, Any]:
        projection = self.store.observation(observation_id)
        if projection is None: raise VisualEdgeError("VISUAL_EDGE_OBSERVATION_UNAVAILABLE")
        if projection["outcomes"]: raise VisualEdgeError("OUTCOME_ALREADY_LINKED")
        source_id = str(raw.get("source_record_id") or "")
        event = self.completed_record_resolver(source_id)
        if event is None: raise VisualEdgeError("AUTHORITATIVE_COMPLETED_OUTCOME_UNAVAILABLE")
        source_hash = str(getattr(event, "immutable_source_hash", ""))
        if source_hash != str(raw.get("source_record_hash") or ""):
            raise VisualEdgeError("COMPLETED_OUTCOME_HASH_MISMATCH")
        completed_at = str(getattr(event, "exit_at"))
        observed_at = str(projection["observation"]["observed_at"])
        time_safe = datetime.fromisoformat(completed_at.replace("Z", "+00:00")) > datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        completed_outcome_id = str(getattr(event, "oracle_event_id"))
        outcome_id = f"{observation_id}-outcome-{completed_outcome_id}"
        completeness = projection["observation"]["completeness"]
        permission = projection["observation"]["retention_permission"]
        training = bool(time_safe and completeness.get("training_eligible") and permission.get("permission") == "RESEARCH_ELIGIBLE")
        link = seal(VisualEdgeOutcomeLink(
            record_id=outcome_id, version="1.0.0", created_at=datetime.now(timezone.utc).isoformat(),
            provenance={"actor_id": actor_id, "correlation_id": correlation_id, "authoritative_completed_trade": True},
            observation_id=observation_id, completed_outcome_id=completed_outcome_id,
            completed_outcome_hash=_hash(event.to_dict()), completed_at=completed_at, outcome=str(getattr(event, "outcome")),
            mfe=getattr(event, "mfe", None), mae=getattr(event, "mae", None),
            correctness_label=str(raw.get("correctness_label") or "NOT_EVALUATED"), source_record_id=source_id,
            source_record_hash=source_hash, time_safe_validated=time_safe, model_training_eligible=training,
        ))
        return self.store.append(event_type="outcomes", record_id=outcome_id, payload=link.to_dict(),
                                 idempotency_key=idempotency_key, operation="LINK_OUTCOME")

    @staticmethod
    def _artifact(raw: Mapping[str, Any]) -> VisualArtifactReference:
        return VisualArtifactReference(
            timeframe=str(raw.get("timeframe") or "UNKNOWN"), artifact_id=raw.get("artifact_id"),
            artifact_hash=raw.get("artifact_hash"), availability=str(raw.get("availability") or "UNAVAILABLE"),
            tradingview_symbol=raw.get("tradingview_symbol"), layout_id=raw.get("layout_id"),
            permission=str(raw.get("permission") or "PRIVATE_RESEARCH"),
        )
