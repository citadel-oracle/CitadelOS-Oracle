"""Phase-6B advisory constitution, memory, discipline and local-vault learning.

This bounded context never authorizes or mutates trading state.  It consumes immutable
completed-trade evidence and publishes append-only learning/explanation records.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Iterable, Mapping, Optional

from .models import OracleEvent, canonical_hash


SCHEMA_VERSION = "6B.1.0"
CONSTITUTION_VERSION = "ORACLE_CONSTITUTION_V1"
DISCIPLINE_POLICY_VERSION = "ORACLE_DISCIPLINE_V1"
LEARNING_POLICY_VERSION = "ORACLE_POST_TRADE_LEARNING_V1"
OBSIDIAN_POLICY_VERSION = "ORACLE_OBSIDIAN_APPEND_V1"
SAFETY = {
    "paper_only": True,
    "live_trading_enabled": False,
    "broker_submission": False,
    "advisory_only": True,
    "execution_influence": "ZERO",
    "execution_authority": False,
}

CONSTITUTION = (
    ("OC-001", "NEVER", "Never recommend a trade merely because the user insists."),
    ("OC-002", "NEVER", "Never treat an emotion label as sufficient trading evidence."),
    ("OC-003", "NEVER", "Never average a losing position automatically."),
    ("OC-004", "NEVER", "Never recommend revenge trading or unsupported re-entry."),
    ("OC-005", "NEVER", "Never ignore objective overtrading evidence."),
    ("OC-006", "NEVER", "Never ignore missing or stale evidence."),
    ("OC-007", "NEVER", "Never hide uncertainty or conflicting evidence."),
    ("OC-008", "ALWAYS", "Always explain why and why not."),
    ("OC-009", "ALWAYS", "Always expose missing and conflicting evidence."),
    ("OC-010", "ALWAYS", "Always state confidence boundaries without inventing probability."),
    ("OC-011", "ALWAYS", "Always preserve an immutable, attributable audit trail."),
)

MEMORY_FACT_TYPES = {
    "REPEATED_MISTAKE", "WINNING_CONDITION", "LOSING_CONDITION", "FAVOURITE_SETUP",
    "SETUP_STATISTIC", "JOURNAL_REFERENCE", "EXECUTION_DISCIPLINE",
    "BEHAVIOURAL_PATTERN", "RULE_VIOLATION", "USER_ATTEMPT",
}


class SecondBrainError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value: Any, maximum: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > maximum:
        raise ValueError("trading-memory text is missing or exceeds the safe bound")
    return text


@dataclass(frozen=True)
class SecondBrainEvent:
    event_id: str
    event_type: str
    idempotency_key: str
    actor_id: str
    correlation_id: str
    occurred_at: str
    recorded_at: str
    payload: Mapping[str, Any]
    previous_hash: str
    content_hash: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["payload"] = dict(self.payload)
        return value


class SecondBrainStore:
    """One atomic document containing a single ordered hash chain."""

    def __init__(self, path: Path | str, maximum_events: int = 20_000):
        self.path = Path(path)
        self.maximum_events = maximum_events
        self._lock = RLock()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "events": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SecondBrainError("second-brain ledger is unavailable or corrupt") from error
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("events"), list):
            raise SecondBrainError("second-brain ledger schema is invalid")
        previous = "GENESIS"
        seen: set[str] = set()
        for raw in value["events"]:
            event_id = str(raw.get("event_id") or "")
            if not event_id or event_id in seen or raw.get("previous_hash") != previous:
                raise SecondBrainError("second-brain ledger chain is invalid")
            unsigned = {key: raw.get(key) for key in (
                "event_id", "event_type", "idempotency_key", "actor_id", "correlation_id",
                "occurred_at", "recorded_at", "payload", "previous_hash", "schema_version",
            )}
            if canonical_hash(unsigned) != raw.get("content_hash"):
                raise SecondBrainError("second-brain ledger hash is invalid")
            previous = str(raw["content_hash"])
            seen.add(event_id)
        return value

    def events(self, event_type: Optional[str] = None) -> tuple[SecondBrainEvent, ...]:
        rows = self.load()["events"]
        return tuple(SecondBrainEvent(**row) for row in rows if event_type is None or row["event_type"] == event_type)

    def append(self, event_type: str, payload: Mapping[str, Any], *, idempotency_key: str,
               actor_id: str, correlation_id: str, occurred_at: Optional[str] = None) -> tuple[SecondBrainEvent, bool]:
        if not all(str(value or "").strip() for value in (event_type, idempotency_key, actor_id, correlation_id)):
            raise ValueError("event type, idempotency key, actor and correlation are required")
        with self._lock:
            document = self.load()
            for raw in document["events"]:
                if raw["idempotency_key"] == idempotency_key:
                    existing = SecondBrainEvent(**raw)
                    if existing.event_type != event_type or canonical_hash(existing.payload) != canonical_hash(payload):
                        raise SecondBrainError("idempotency key conflicts with immutable evidence")
                    return existing, False
            if len(document["events"]) >= self.maximum_events:
                raise SecondBrainError("second-brain ledger event bound reached")
            previous = document["events"][-1]["content_hash"] if document["events"] else "GENESIS"
            event_id = hashlib.sha256(f"{event_type}|{idempotency_key}".encode()).hexdigest()[:24]
            unsigned = {
                "event_id": event_id, "event_type": event_type, "idempotency_key": idempotency_key,
                "actor_id": actor_id, "correlation_id": correlation_id,
                "occurred_at": occurred_at or _now(), "recorded_at": _now(),
                "payload": dict(payload), "previous_hash": previous, "schema_version": SCHEMA_VERSION,
            }
            event = SecondBrainEvent(**unsigned, content_hash=canonical_hash(unsigned))
            document["events"].append(event.to_dict())
            self._atomic_write(document)
            return event, True

    def _atomic_write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, sort_keys=True, separators=(",", ":"), default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class LocalObsidianVault:
    """Append-only local filesystem boundary for the configured Obsidian vault."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()

    def append_once(self, relative_path: str, marker: str, title: str, body: str) -> bool:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
            raise ValueError("unsafe Obsidian note path")
        path = (self.root / relative).resolve()
        if self.root not in path.parents:
            raise ValueError("Obsidian note escapes configured vault")
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                if marker in existing:
                    return False
                with path.open("a", encoding="utf-8") as handle:
                    prefix = "" if existing.endswith("\n") else "\n"
                    handle.write(f"{prefix}\n{body.rstrip()}\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                return True
            content = f"# {title}\n\n{body.rstrip()}\n"
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                return self.append_once(relative_path, marker, title, body)
            return True

    def sync_learning(self, learning: Mapping[str, Any]) -> dict[str, Any]:
        learning_id = str(learning["learning_id"])
        event_id = str(learning["oracle_event_id"])
        date = str(learning["completed_at"])[:10]
        setup = str(learning.get("setup") or "UNAVAILABLE")
        outcome = str(learning.get("outcome") or "UNAVAILABLE")
        marker = f"<!-- citadel-oracle-learning:{learning_id} -->"
        trade_link = f"[[Trade Journal/{event_id}]]"
        compact = (
            f"## {event_id}\n\n{marker}\n\n"
            f"- Setup: {setup}\n- Outcome: {outcome}\n- Trade: {trade_link}\n"
            f"- Immutable learning hash: `{learning.get('source_event_hash')}`"
        )
        details = (
            f"{marker}\n\n- Completed: {learning['completed_at']}\n"
            f"- Setup: {setup}\n- Market context: `{json.dumps(learning.get('market_context'), sort_keys=True, default=str)}`\n"
            f"- Decision: `{json.dumps(learning.get('decision'), sort_keys=True, default=str)}`\n"
            f"- Entry: `{json.dumps(learning.get('entry'), sort_keys=True, default=str)}`\n"
            f"- Stop: `{json.dumps(learning.get('stop'), sort_keys=True, default=str)}`\n"
            f"- Targets: `{json.dumps(learning.get('targets'), sort_keys=True, default=str)}`\n"
            f"- Management: `{json.dumps(learning.get('management'), sort_keys=True, default=str)}`\n"
            f"- Exit: `{json.dumps(learning.get('exit'), sort_keys=True, default=str)}`\n"
            f"- Mistakes: {', '.join(learning.get('mistakes') or ['NONE OBSERVED'])}\n"
            f"- What worked: {', '.join(learning.get('what_worked') or ['UNAVAILABLE'])}\n"
            f"- What failed: {', '.join(learning.get('what_failed') or ['UNAVAILABLE'])}\n"
            f"- Lessons: {', '.join(learning.get('lessons') or ['COLLECT MORE EVIDENCE'])}\n"
            f"- Knowledge links: {', '.join(learning.get('knowledge_links') or ['NONE'])}"
        )
        notes = [
            (f"Daily Journal/{date}.md", f"Daily Journal — {date}", compact),
            (f"Trade Journal/{event_id}.md", f"Trade {event_id}", details),
            ("Playbook.md", "Playbook", compact),
            ("Learning Notes.md", "Learning Notes", compact),
            ("Research Notes.md", "Research Notes", compact),
            ("Knowledge Links.md", "Knowledge Links", compact),
        ]
        if learning.get("mistakes"):
            notes.append(("Mistake Log.md", "Mistake Log", compact))
        notes.append((("Winning Setups.md" if outcome == "WIN" else "Failed Setups.md"),
                      ("Winning Setups" if outcome == "WIN" else "Failed Setups"), compact))
        changed, duplicate = [], []
        for path, title, body in notes:
            (changed if self.append_once(path, marker, title, body) else duplicate).append(path)
        return {"status": "SYNCED", "changed_notes": changed, "duplicate_notes": duplicate,
                "vault": str(self.root), "policy_version": OBSIDIAN_POLICY_VERSION}

    def sync_learning_correction(self, learning: Mapping[str, Any], correction: Mapping[str, Any]) -> dict[str, Any]:
        correction_id = str(correction["correction_id"])
        marker = f"<!-- citadel-oracle-learning-correction:{correction_id} -->"
        body = (
            f"## Correction {correction['revision']}\n\n{marker}\n\n"
            f"- Corrected at: {correction['corrected_at']}\n"
            f"- Correction: {correction['correction']}\n"
            f"- Reason: {correction['reason']}\n"
            f"- Evidence: {', '.join(correction['evidence_references'])}\n"
            "- Immutable trade facts and outcome were not changed."
        )
        event_id = str(learning["oracle_event_id"])
        changed = []
        for path, title in ((f"Trade Journal/{event_id}.md", f"Trade {event_id}"),
                            ("Learning Notes.md", "Learning Notes")):
            if self.append_once(path, marker, title, body):
                changed.append(path)
        return {"status": "SYNCED", "changed_notes": changed,
                "policy_version": OBSIDIAN_POLICY_VERSION}


class DisciplineEngine:
    """Deterministic warnings based only on observable, time-safe evidence."""

    def assess(self, decision: Mapping[str, Any], events: Iterable[OracleEvent], *,
               context: Optional[Mapping[str, Any]] = None, now: Optional[datetime] = None) -> dict[str, Any]:
        context = dict(context or {})
        observed_at = now or datetime.now(timezone.utc)
        rows = sorted(events, key=lambda row: row.exit_at)
        warnings: list[dict[str, Any]] = []

        def warn(code: str, recommendation: str, evidence: list[str], constitution: list[str]) -> None:
            warnings.append({"code": code, "recommendation": recommendation,
                             "objective_evidence": evidence, "constitution_refs": constitution})

        action = str(decision.get("action") or "UNAVAILABLE").upper()
        missing = [str(item) for item in decision.get("missing_evidence") or ()]
        freshness = str(decision.get("freshness") or "UNAVAILABLE").upper()
        if action == "BUY" and missing:
            warn("MISSING_EVIDENCE_CONFLICT", "NO_TRADE", missing, ["OC-006", "OC-009"])
        if action == "BUY" and freshness != "FRESH":
            warn("STALE_EVIDENCE_CONFLICT", "NO_TRADE", [f"freshness={freshness}"], ["OC-006"])
        quality = decision.get("setup_quality")
        if action == "BUY" and isinstance(quality, (int, float)) and quality < 50:
            warn("LOW_QUALITY_TRADE", "WAIT", [f"setup_quality={quality}"], ["OC-007", "OC-010"])
        reason_codes = {str(item).upper() for item in decision.get("reason_codes") or ()}
        if reason_codes & {"ENTRY_EXTENDED", "LATE_ENTRY", "CHASE_ENTRY"}:
            warn("FOMO_RISK", "WAIT", sorted(reason_codes), ["OC-002", "OC-007"])
        trading_date = observed_at.date().isoformat()
        today = [row for row in rows if row.trading_date == trading_date]
        if len(today) >= 2:
            warn("OVERTRADING", "COOLDOWN", [f"completed_trades_today={len(today)}"], ["OC-005"])
        last = rows[-1] if rows else None
        if last:
            try:
                elapsed = (observed_at - datetime.fromisoformat(last.exit_at).astimezone(timezone.utc)).total_seconds()
            except ValueError:
                elapsed = None
            if last.outcome == "LOSS" and elapsed is not None and 0 <= elapsed < 900:
                warn("POST_LOSS_RAPID_REENTRY", "COOLDOWN",
                     [f"previous_trade={last.oracle_event_id}", f"seconds_since_loss={elapsed:.0f}"], ["OC-004"])
            symbol = str(context.get("symbol") or "")
            setup = str(context.get("setup") or "")
            if elapsed is not None and 0 <= elapsed < 1800 and symbol and last.symbol == symbol and (
                    not setup or last.setup_tag == setup):
                warn("DUPLICATE_THESIS", "REVIEW",
                     [f"previous_trade={last.oracle_event_id}", f"symbol={symbol}", f"seconds_since_exit={elapsed:.0f}"],
                     ["OC-004", "OC-011"])
        attempts = int(context.get("unsupported_attempts_last_10m") or 0)
        if attempts >= 3 and (not decision.get("trigger") or missing):
            warn("UNSUPPORTED_REPEATED_ATTEMPTS", "REVIEW",
                 [f"unsupported_attempts_last_10m={attempts}"], ["OC-001", "OC-002"])

        priority = {"NO_TRADE": 4, "COOLDOWN": 3, "REVIEW": 2, "WAIT": 1}
        recommendation = max((row["recommendation"] for row in warnings),
                             key=lambda value: priority[value], default="WAIT" if action != "BUY" else "REVIEW")
        return {
            "status": "AVAILABLE", "recommendation": recommendation, "warnings": warnings,
            "objective_evidence_required": True, "emotion_only_blocking": False,
            "subjective_emotion_inference": "NOT_PERFORMED", "policy_version": DISCIPLINE_POLICY_VERSION,
            "constitution_version": CONSTITUTION_VERSION, "execution_influence": "ZERO",
            "execution_authority": False,
        }


class OracleSecondBrainService:
    def __init__(self, store: SecondBrainStore, *, vault: Optional[LocalObsidianVault] = None,
                 event_provider=None):
        self.store = store
        self.vault = vault
        self.event_provider = event_provider or (lambda: ())
        self.discipline = DisciplineEngine()

    @staticmethod
    def constitution() -> dict[str, Any]:
        principles = [{"principle_id": pid, "kind": kind, "text": text} for pid, kind, text in CONSTITUTION]
        return {"version": CONSTITUTION_VERSION, "immutable": True, "principles": principles,
                "content_hash": canonical_hash({"version": CONSTITUTION_VERSION, "principles": principles}),
                "execution_influence": "ZERO", "execution_authority": False}

    def append_memory(self, fact: Mapping[str, Any], *, idempotency_key: str,
                      actor_id: str, correlation_id: str) -> dict[str, Any]:
        fact_type = str(fact.get("fact_type") or "").upper()
        if fact_type not in MEMORY_FACT_TYPES:
            raise ValueError("unsupported or non-trading memory fact")
        existing = next((row for row in self.store.events("TRADING_MEMORY_APPENDED")
                         if row.idempotency_key == idempotency_key), None)
        valid_from = str(fact.get("valid_from") or
                         (existing.payload.get("valid_from") if existing else _now()))
        payload = {
            "fact_type": fact_type,
            "fact": _bounded_text(fact.get("fact")),
            "evidence_references": sorted({str(item) for item in fact.get("evidence_references") or () if item}),
            "setup": str(fact.get("setup") or "") or None,
            "symbol": str(fact.get("symbol") or "") or None,
            "valid_from": valid_from,
            "version": int(fact.get("version") or 1),
        }
        if not payload["evidence_references"]:
            raise ValueError("trading memory requires objective evidence references")
        event, added = self.store.append("TRADING_MEMORY_APPENDED", payload,
                                         idempotency_key=idempotency_key, actor_id=actor_id,
                                         correlation_id=correlation_id, occurred_at=payload["valid_from"])
        return {"added": added, **event.to_dict()}

    def correct_memory(self, memory_event_id: str, correction: Mapping[str, Any], *,
                       idempotency_key: str, actor_id: str, correlation_id: str) -> dict[str, Any]:
        duplicate = next((row for row in self.store.events("TRADING_MEMORY_CORRECTION_APPENDED")
                          if row.idempotency_key == idempotency_key), None)
        if duplicate is not None:
            if (duplicate.payload.get("memory_event_id") != memory_event_id
                    or duplicate.payload.get("correction") != _bounded_text(correction.get("correction"))
                    or duplicate.payload.get("reason") != _bounded_text(correction.get("reason"))):
                raise SecondBrainError("idempotency key conflicts with immutable evidence")
            return {"added": False, **duplicate.to_dict()}
        if not any(row.event_id == memory_event_id for row in self.store.events("TRADING_MEMORY_APPENDED")):
            raise SecondBrainError("memory correction references an unknown event")
        prior_revisions = [row for row in self.store.events("TRADING_MEMORY_CORRECTION_APPENDED")
                           if row.payload.get("memory_event_id") == memory_event_id]
        payload = {"memory_event_id": memory_event_id, "revision": len(prior_revisions) + 1,
                   "correction": _bounded_text(correction.get("correction")),
                   "reason": _bounded_text(correction.get("reason")),
                   "expected_prior_hash": str(correction.get("expected_prior_hash") or "")}
        source = next(row for row in self.store.events("TRADING_MEMORY_APPENDED") if row.event_id == memory_event_id)
        if payload["expected_prior_hash"] != source.content_hash:
            raise SecondBrainError("memory correction prior hash conflict")
        event, added = self.store.append("TRADING_MEMORY_CORRECTION_APPENDED", payload,
                                         idempotency_key=idempotency_key, actor_id=actor_id,
                                         correlation_id=correlation_id)
        return {"added": added, **event.to_dict()}

    def correct_learning(self, learning_event_id: str, correction: Mapping[str, Any], *,
                         idempotency_key: str, actor_id: str, correlation_id: str) -> dict[str, Any]:
        duplicate = next((row for row in self.store.events("POST_TRADE_LEARNING_CORRECTION_APPENDED")
                          if row.idempotency_key == idempotency_key), None)
        if duplicate is not None:
            evidence = sorted({str(item) for item in correction.get("evidence_references") or () if item})
            if (duplicate.payload.get("learning_event_id") != learning_event_id
                    or duplicate.payload.get("correction") != _bounded_text(correction.get("correction"))
                    or duplicate.payload.get("reason") != _bounded_text(correction.get("reason"))
                    or duplicate.payload.get("evidence_references") != evidence):
                raise SecondBrainError("idempotency key conflicts with immutable evidence")
            return {"added": False, "correction": duplicate.to_dict(),
                    "obsidian": {"status": "ALREADY_SYNCED"}}
        source = next((row for row in self.store.events("POST_TRADE_LEARNING_APPENDED")
                       if row.event_id == learning_event_id), None)
        if source is None:
            raise SecondBrainError("learning correction references an unknown event")
        expected = str(correction.get("expected_prior_hash") or "")
        if expected != source.content_hash:
            raise SecondBrainError("learning correction prior hash conflict")
        revisions = [row for row in self.store.events("POST_TRADE_LEARNING_CORRECTION_APPENDED")
                     if row.payload.get("learning_event_id") == learning_event_id]
        payload = {
            "correction_id": hashlib.sha256(f"learning-correction|{idempotency_key}".encode()).hexdigest()[:24],
            "learning_event_id": learning_event_id, "oracle_event_id": source.payload.get("oracle_event_id"),
            "revision": len(revisions) + 1, "corrected_at": _now(),
            "correction": _bounded_text(correction.get("correction")),
            "reason": _bounded_text(correction.get("reason")),
            "evidence_references": sorted({str(item) for item in correction.get("evidence_references") or () if item}),
            "immutable_fields_unchanged": ["setup", "entry", "stop", "targets", "management", "exit", "outcome"],
            "expected_prior_hash": expected, "execution_influence": "ZERO",
        }
        if not payload["evidence_references"]:
            raise ValueError("learning correction requires evidence references")
        event, added = self.store.append(
            "POST_TRADE_LEARNING_CORRECTION_APPENDED", payload,
            idempotency_key=idempotency_key, actor_id=actor_id, correlation_id=correlation_id,
        )
        sync = {"status": "UNAVAILABLE", "reason": "OBSIDIAN_VAULT_NOT_CONFIGURED"}
        if added and self.vault is not None:
            sync = self.vault.sync_learning_correction(source.payload, payload)
        return {"added": added, "correction": event.to_dict(), "obsidian": sync}

    def record_completed_trade(self, event: OracleEvent) -> dict[str, Any]:
        context = dict(event.entry_context or {})
        mistakes = sorted(set(event.mistake_tags))
        what_worked = (["POSITIVE_OUTCOME_RECORDED"] if event.outcome == "WIN" else [])
        what_failed = (["NEGATIVE_OUTCOME_RECORDED"] if event.outcome == "LOSS" else []) + mistakes
        lessons = [f"REVIEW_{tag}" for tag in mistakes] or ["PRESERVE_EVIDENCE_AND_REVIEW_SETUP"]
        payload = {
            "learning_id": f"learning_{event.oracle_event_id}", "oracle_event_id": event.oracle_event_id,
            "source_record_id": event.source_record_id, "source_event_hash": event.immutable_source_hash,
            "completed_at": event.exit_at, "setup": event.setup_tag or event.strategy_name or "UNAVAILABLE",
            "market_context": {key: value for key, value in {
                "symbol": event.symbol, "timeframe": event.timeframe, "regime": event.market_regime,
                "technical_bias": event.technical_bias, "argus_bias": event.argus_bias,
            }.items() if value is not None},
            "decision": context.get("decision") or {"entry_reason": event.entry_reason, "decision_id": context.get("decision_id")},
            "entry": {"at": event.entry_at, "price": event.entry_price, "quantity": event.quantity,
                      "contract_security_id": event.contract_security_id},
            "stop": {"planned": event.planned_stop_price, "respected": None},
            "targets": {"planned": event.planned_target_price, "respected": None},
            "management": {"exit_reason": event.exit_reason, "mfe": event.mfe, "mae": event.mae},
            "exit": {"at": event.exit_at, "price": event.exit_price, "pnl": event.realized_pnl,
                     "outcome": event.outcome},
            "outcome": event.outcome, "mistakes": mistakes, "what_worked": what_worked,
            "what_failed": what_failed, "lessons": lessons,
            "knowledge_links": list(context.get("knowledge_references") or ()),
            "corrections_append_only": True, "hindsight_editing": False,
            "policy_version": LEARNING_POLICY_VERSION, "execution_influence": "ZERO",
        }
        learning, added = self.store.append(
            "POST_TRADE_LEARNING_APPENDED", payload,
            idempotency_key=f"post-trade:{event.oracle_event_id}", actor_id="SYSTEM_PERSONAL_ORACLE",
            correlation_id=event.source_event_id or event.oracle_event_id, occurred_at=event.exit_at,
        )
        if not added:
            existing_sync = next((row for row in reversed(self.store.events("OBSIDIAN_SYNC_RECORDED"))
                                  if row.payload.get("learning_event_id") == learning.event_id), None)
            return {"added": False, "learning": learning.to_dict(),
                    "obsidian": dict(existing_sync.payload) if existing_sync else
                    {"status": "UNAVAILABLE", "reason": "SYNC_RECORD_UNAVAILABLE"}}
        sync = {"status": "UNAVAILABLE", "reason": "OBSIDIAN_VAULT_NOT_CONFIGURED"}
        if self.vault is not None:
            try:
                sync = self.vault.sync_learning(payload)
            except (OSError, ValueError) as error:
                sync = {"status": "FAILED_SAFE", "reason": type(error).__name__}
        self.store.append("OBSIDIAN_SYNC_RECORDED", {
            "learning_event_id": learning.event_id, **sync, "execution_influence": "ZERO",
        }, idempotency_key=f"obsidian-sync:{event.oracle_event_id}:{canonical_hash(sync)}",
           actor_id="SYSTEM_OBSIDIAN_ADAPTER", correlation_id=event.source_event_id or event.oracle_event_id)
        if added:
            fact_type = "WINNING_CONDITION" if event.outcome == "WIN" else "LOSING_CONDITION"
            self.append_memory({"fact_type": fact_type,
                                "fact": f"Completed {event.outcome.lower()} evidence for {payload['setup']}",
                                "evidence_references": [event.oracle_event_id], "setup": payload["setup"],
                                "symbol": event.symbol, "valid_from": event.exit_at},
                               idempotency_key=f"learning-memory:{event.oracle_event_id}",
                               actor_id="SYSTEM_PERSONAL_ORACLE", correlation_id=event.oracle_event_id)
        return {"added": added, "learning": learning.to_dict(), "obsidian": sync}

    def project(self, decision: Mapping[str, Any], *, knowledge: Optional[Mapping[str, Any]] = None,
                context: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        started = perf_counter()
        events = tuple(self.event_provider())
        discipline = self.discipline.assess(decision, events, context=context)
        knowledge = dict(knowledge or {})
        related = [row.oracle_event_id for row in events[-5:]]
        constitution = self.constitution()
        why = str(decision.get("why") or "No canonical supporting explanation reported.")
        missing = [str(item) for item in decision.get("missing_evidence") or ()]
        conflicts = [str(item) for item in knowledge.get("conflicts") or ()]
        action = str(decision.get("action") or "UNAVAILABLE")
        explanation = {
            "why": [why],
            "why_not": ([f"Action is {action}; execution prerequisites are not satisfied."] if action != "BUY" else [])
                       + [f"Discipline: {row['code']}" for row in discipline["warnings"]],
            "missing_evidence": missing, "conflicting_evidence": conflicts,
            "alternative_scenarios": ["If missing evidence becomes fresh, rebuild the deterministic Decision Envelope.",
                                      "If invalidation is reached, preserve NO_TRADE/EXIT semantics."],
            "invalidation": decision.get("structural_invalidation"),
            "natural_targets": list(decision.get("targets") or ()),
            "discipline_warnings": discipline["warnings"],
            "related_journal_links": [f"Trade Journal/{item}.md" for item in related],
            "related_historical_trades": related,
            "knowledge_cards_used": list(knowledge.get("references") or ()),
            "constitution_refs": [item[0] for item in CONSTITUTION],
            "confidence_boundary": "NOT_A_PROBABILITY",
        }
        memory = self.store.events("TRADING_MEMORY_APPENDED")
        syncs = self.store.events("OBSIDIAN_SYNC_RECORDED")
        return {
            "status": "AVAILABLE", "constitution": constitution, "discipline": discipline,
            "explainability": explanation,
            "memory": {"append_only": True, "event_count": len(memory),
                       "latest_references": [row.event_id for row in memory[-5:]]},
            "obsidian": ({"status": syncs[-1].payload.get("status"),
                          "last_sync_event_id": syncs[-1].event_id,
                          "policy_version": OBSIDIAN_POLICY_VERSION} if syncs else
                         {"status": "NO_COMPLETED_TRADE_SYNC", "policy_version": OBSIDIAN_POLICY_VERSION}),
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "safety": dict(SAFETY), "schema_version": SCHEMA_VERSION,
        }

    def status(self) -> dict[str, Any]:
        rows = self.store.events()
        syncs = [row for row in rows if row.event_type == "OBSIDIAN_SYNC_RECORDED"]
        return {"status": "AVAILABLE", "schema_version": SCHEMA_VERSION,
                "constitution_version": CONSTITUTION_VERSION, "discipline_policy_version": DISCIPLINE_POLICY_VERSION,
                "event_count": len(rows), "hash_chained": True, "append_only": True,
                "obsidian": dict(syncs[-1].payload) if syncs else {"status": "NO_COMPLETED_TRADE_SYNC"},
                "safety": dict(SAFETY)}
