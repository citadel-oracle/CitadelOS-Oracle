"""Phase-5A local curated knowledge corpus and restart-safe ingestion ledger.

This module is deliberately read-only with respect to trading.  It validates and
retrieves source-backed explanatory records; it imports no risk, mission,
condition, execution, broker, position, or Guardian service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from src.oracle.contracts.learning import (
    CitationLocator, ExcerptPolicy, KnowledgeCard, KnowledgeSourceManifest,
    LearningContractError, ValidationStatus, seal,
)
from src.oracle.knowledge import KnowledgeVault


CORPUS_SCHEMA_VERSION = "5a.2.0"
KNOWLEDGE_POLICY_VERSION = "oracle-knowledge-advisory-5a.2.0"
INGESTION_POLICY_VERSION = "oracle-knowledge-ingestion-5a.2.0"
RETRIEVAL_POLICY_VERSION = "oracle-knowledge-retrieval-5a.2.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"5a.1.0", CORPUS_SCHEMA_VERSION})
SUPPORTED_KNOWLEDGE_POLICIES = frozenset({"oracle-knowledge-advisory-5a.1.0", KNOWLEDGE_POLICY_VERSION})
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PHASE5A_REGISTRY = PROJECT_ROOT / "oracle_knowledge" / "registry" / "phase5a_registry.json"
DEFAULT_CORPUS_REGISTRY = PROJECT_ROOT / "oracle_knowledge" / "registry" / "expanded_registry.json"
DEFAULT_LEGACY_VAULT = PROJECT_ROOT / "oracle_knowledge"
_HASH = "0123456789abcdef"


class CorpusError(RuntimeError):
    pass


class IngestionStage(str, Enum):
    DISCOVERED = "DISCOVERED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    RIGHTS_ACCESS_CHECKED = "RIGHTS/ACCESS_CHECKED"
    DUPLICATE_CHECKED = "DUPLICATE_CHECKED"
    FETCHED = "FETCHED"
    HASHED = "HASHED"
    EXTRACTED = "EXTRACTED"
    REVIEWED = "REVIEWED"
    CARD_VALIDATED = "CARD_VALIDATED"
    REGISTERED = "REGISTERED"
    RETRIEVAL_TESTED = "RETRIEVAL_TESTED"


STAGES = tuple(IngestionStage)
ALLOWED_STATUSES = frozenset({
    "SOURCE_BACKED_UNVALIDATED", "INTERNALLY_VALIDATED", "HYPOTHESIS",
    "USER_PROVIDED_UNVALIDATED",
    "CONFLICTED", "FUTURE_DATA_DEPENDENT", "PENDING_SOURCE", "REJECTED", "DEPRECATED",
})
ACCEPTED_STATUSES = frozenset({
    "SOURCE_BACKED_UNVALIDATED", "INTERNALLY_VALIDATED", "HYPOTHESIS", "CONFLICTED",
    "FUTURE_DATA_DEPENDENT", "USER_PROVIDED_UNVALIDATED",
})
SOURCE_TYPES = frozenset({"BOOK", "PAPER", "OFFICIAL_DOCUMENTATION", "INTERNAL_EVIDENCE", "USER_PROVIDED"})


def _sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _hash(value: str, field: str) -> str:
    normalized = str(value).lower()
    if len(normalized) != 64 or any(char not in _HASH for char in normalized):
        raise CorpusError(f"{field} must be a SHA-256 hash")
    return normalized


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusError(f"{field} is required")
    return value.strip()


def _items(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise CorpusError(f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} list")
    result = tuple(_text(item, field) for item in value)
    if len(result) != len(set(result)):
        raise CorpusError(f"{field} contains duplicates")
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CorpusError(f"{field} must be an object")
    return MappingProxyType(dict(sorted(value.items())))


@dataclass(frozen=True)
class CuratedKnowledgeCard:
    card_id: str
    version: str
    card_type: str
    concept: str
    domain: str
    definition_principle: str
    measurable_predicates: tuple[str, ...]
    required_evidence: tuple[str, ...]
    optional_confirmations: tuple[str, ...]
    valid_conditions: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    contradictions: tuple[str, ...]
    when_not_to_use: tuple[str, ...]
    timeframes: tuple[str, ...]
    instruments: tuple[str, ...]
    option_buying_relevance: str
    relevant_citadel_fields: tuple[str, ...]
    data_availability: Mapping[str, str]
    source_id: str
    exact_locator: str
    short_excerpt: str | None
    paraphrase: str
    source_quality: str
    source_hash_version: str
    validation_status: str
    empirical_status: str
    execution_influence: str
    knowledge_policy_version: str
    regimes: tuple[str, ...]
    setup_types: tuple[str, ...]
    contradicts_card_ids: tuple[str, ...]
    research_only: bool
    research_fields: Mapping[str, Any]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id, "version": self.version, "card_type": self.card_type,
            "concept": self.concept, "domain": self.domain, "definition_principle": self.definition_principle,
            "measurable_predicates": list(self.measurable_predicates), "required_evidence": list(self.required_evidence),
            "optional_confirmations": list(self.optional_confirmations), "valid_conditions": list(self.valid_conditions),
            "failure_conditions": list(self.failure_conditions), "contradictions": list(self.contradictions),
            "when_not_to_use": list(self.when_not_to_use), "timeframes": list(self.timeframes),
            "instruments": list(self.instruments), "option_buying_relevance": self.option_buying_relevance,
            "relevant_citadel_fields": list(self.relevant_citadel_fields), "data_availability": dict(self.data_availability),
            "source_id": self.source_id, "exact_locator": self.exact_locator, "short_excerpt": self.short_excerpt,
            "paraphrase": self.paraphrase, "source_quality": self.source_quality,
            "source_hash_version": self.source_hash_version, "validation_status": self.validation_status,
            "empirical_status": self.empirical_status, "execution_influence": self.execution_influence,
            "knowledge_policy_version": self.knowledge_policy_version, "regimes": list(self.regimes),
            "setup_types": list(self.setup_types), "contradicts_card_ids": list(self.contradicts_card_ids),
            "research_only": self.research_only, "research_fields": dict(self.research_fields),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], source: Mapping[str, Any]) -> "CuratedKnowledgeCard":
        status = _text(raw.get("validation_status"), "validation_status")
        if status not in ALLOWED_STATUSES or status not in ACCEPTED_STATUSES:
            raise CorpusError("accepted registry contains an unavailable status")
        locator = _text(raw.get("exact_locator"), "exact_locator")
        if locator not in tuple(source["stable_locators"]):
            raise CorpusError("citation locator does not exist in source manifest")
        if _text(raw.get("source_hash_version"), "source_hash_version") != source["document_hash"]:
            raise CorpusError("knowledge source hash mismatch")
        excerpt = raw.get("short_excerpt")
        policy = source["excerpt_policy"]
        if excerpt is not None:
            excerpt = _text(excerpt, "short_excerpt")
            if not policy["excerpt_allowed"] or len(excerpt.split()) > int(policy["maximum_words"]):
                raise CorpusError("excerpt policy exceeded")
        card_policy = raw.get("knowledge_policy_version")
        if raw.get("execution_influence") != "ZERO" or card_policy not in SUPPORTED_KNOWLEDGE_POLICIES:
            raise CorpusError("knowledge execution boundary is invalid")
        card_type = _text(raw.get("card_type"), "card_type")
        research_only = raw.get("research_only") is True
        research_fields = _mapping(raw.get("research_fields") or {}, "research_fields")
        if card_type == "STRATEGY_RESEARCH":
            required = {
                "instrument_scope", "timeframe_scope", "regime_filter", "setup_logic",
                "trigger_logic", "invalidation_logic", "target_logic", "option_filter",
                "required_data", "missing_data", "cost_model", "backtest_plan", "oos_plan",
                "failure_analysis", "research_status",
            }
            if not research_only or research_fields.get("research_status") != "RESEARCH_ONLY" or not required.issubset(research_fields):
                raise CorpusError("strategy card must remain a complete RESEARCH_ONLY record")
        semantic = dict(raw)
        supplied_hash = str(semantic.pop("content_hash", ""))
        computed_hash = _sha(semantic)
        if supplied_hash and supplied_hash != computed_hash:
            raise CorpusError("knowledge card content hash mismatch")
        return cls(
            card_id=_text(raw.get("card_id"), "card_id"), version=_text(raw.get("version"), "version"),
            card_type=card_type, concept=_text(raw.get("concept"), "concept"), domain=_text(raw.get("domain"), "domain"),
            definition_principle=_text(raw.get("definition_principle"), "definition_principle"),
            measurable_predicates=_items(raw.get("measurable_predicates"), "measurable_predicates"),
            required_evidence=_items(raw.get("required_evidence"), "required_evidence"),
            optional_confirmations=_items(raw.get("optional_confirmations"), "optional_confirmations", allow_empty=True),
            valid_conditions=_items(raw.get("valid_conditions"), "valid_conditions"),
            failure_conditions=_items(raw.get("failure_conditions"), "failure_conditions"),
            contradictions=_items(raw.get("contradictions"), "contradictions"),
            when_not_to_use=_items(raw.get("when_not_to_use"), "when_not_to_use"),
            timeframes=_items(raw.get("timeframes"), "timeframes"),
            instruments=_items(raw.get("instruments"), "instruments"),
            option_buying_relevance=_text(raw.get("option_buying_relevance"), "option_buying_relevance"),
            relevant_citadel_fields=_items(raw.get("relevant_citadel_fields"), "relevant_citadel_fields"),
            data_availability=_mapping(raw.get("data_availability"), "data_availability"),
            source_id=_text(raw.get("source_id"), "source_id"), exact_locator=locator,
            short_excerpt=excerpt, paraphrase=_text(raw.get("paraphrase"), "paraphrase"),
            source_quality=_text(raw.get("source_quality"), "source_quality"),
            source_hash_version=source["document_hash"], validation_status=status,
            empirical_status=_text(raw.get("empirical_status"), "empirical_status"),
            execution_influence="ZERO", knowledge_policy_version=str(card_policy),
            regimes=_items(raw.get("regimes"), "regimes", allow_empty=True),
            setup_types=_items(raw.get("setup_types"), "setup_types", allow_empty=True),
            contradicts_card_ids=_items(raw.get("contradicts_card_ids"), "contradicts_card_ids", allow_empty=True),
            research_only=research_only, research_fields=research_fields, content_hash=computed_hash,
        )


class Phase5AKnowledgeRegistry:
    """Loads one content-addressed local snapshot; never fetches the network."""

    def __init__(self, path: Path | str = DEFAULT_CORPUS_REGISTRY, *, legacy_root: Path | str = DEFAULT_LEGACY_VAULT):
        self.path = Path(path)
        registry = self._read(self.path)
        self.schema_version = str(registry.get("schema_version") or "")
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise CorpusError("unsupported corpus schema version")
        self.registry_version = _text(registry.get("registry_version"), "registry_version")
        self.generated_at = _text(registry.get("generated_at"), "generated_at")
        datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        root = self.path.parents[1]
        source_rows = self._read(root / _text(registry.get("source_manifests"), "source_manifests"))
        card_rows: list[Mapping[str, Any]] = []
        corpus_files = [self.path, root / registry["source_manifests"]]
        for relative in registry.get("card_files") or ():
            target = root / _text(relative, "card_file")
            corpus_files.append(target)
            document = self._read(target)
            defaults = document.get("defaults") or {}
            if not isinstance(defaults, dict):
                raise CorpusError("card defaults must be an object")
            for row in document.get("cards") or ():
                if not isinstance(row, dict):
                    raise CorpusError("knowledge card must be an object")
                card_rows.append({**defaults, **row})
        extra_paths = {
            "audit": root / _text(registry.get("audit_report"), "audit_report"),
            "summary": root / _text(registry.get("ingestion_summary"), "ingestion_summary"),
            "pending": root / _text(registry.get("pending_sources"), "pending_sources"),
            "rejected": root / _text(registry.get("rejected_sources"), "rejected_sources"),
            "conflicts": root / _text(registry.get("conflicts"), "conflicts"),
        }
        optional_paths = {
            key: root / _text(registry.get(key), key)
            for key in ("fetched_sources", "ingestion_ledger", "retrieval_fixtures")
            if registry.get(key)
        }
        corpus_files.extend(extra_paths.values())
        corpus_files.extend(optional_paths.values())
        user_source_paths = [root / _text(item, "user_source_file") for item in registry.get("user_source_files") or ()]
        corpus_files.extend(user_source_paths)
        sources_raw = source_rows.get("sources") or ()
        self.source_records = {str(row["source_id"]): row for row in sources_raw}
        if len(self.source_records) != len(sources_raw):
            raise CorpusError("duplicate source id")
        self._validate_sources()
        self._validate_duplicate_sources()
        curated = [CuratedKnowledgeCard.from_mapping(row, self.source_records.get(str(row.get("source_id"))) or {}) for row in card_rows]
        if len({card.card_id for card in curated}) != len(curated):
            raise CorpusError("duplicate card id")
        self.curated_cards = MappingProxyType({card.card_id: card for card in curated})
        self._validate_card_links()
        self.sources = MappingProxyType({source_id: self._adapt_source(row) for source_id, row in self.source_records.items()})
        self.cards = MappingProxyType({card.card_id: self._adapt_card(card) for card in curated})
        self.legacy_vault = KnowledgeVault(Path(legacy_root))
        file_hashes = {str(target.relative_to(root)): hashlib.sha256(target.read_bytes()).hexdigest() for target in corpus_files}
        self.registry_file_hash = file_hashes[str(self.path.relative_to(root))]
        self.vault_hash = _sha({"corpus_files": file_hashes, "legacy": self.legacy_vault.vault_hash})
        self.audit = self._read(extra_paths["audit"])
        self.summary = self._read(extra_paths["summary"])
        self.pending = self._read(extra_paths["pending"])
        self.rejected = self._read(extra_paths["rejected"])
        self.conflict_registry = self._read(extra_paths["conflicts"])
        self.fetched_sources = self._read(optional_paths["fetched_sources"]) if "fetched_sources" in optional_paths else {"sources": []}
        self.retrieval_fixtures = self._read(optional_paths["retrieval_fixtures"]) if "retrieval_fixtures" in optional_paths else {"fixtures": []}
        self.ingestion_ledger_path = optional_paths.get("ingestion_ledger")
        self._validate_fetched_metadata()
        self._validate_user_sources(root, user_source_paths)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise CorpusError("knowledge corpus document is unreadable") from error
        if not isinstance(value, dict):
            raise CorpusError("knowledge corpus document must be an object")
        return value

    def _validate_sources(self) -> None:
        required = {
            "source_id", "title", "author_organisation", "edition_version", "publication_date",
            "source_type", "document_hash", "hash_scope", "source_location", "access_status",
            "rights_status", "ingestion_status", "excerpt_policy", "stable_locators", "provenance",
            "validation_status", "limitations", "contradictions",
        }
        for row in self.source_records.values():
            if not required.issubset(row) or row["source_type"] not in SOURCE_TYPES:
                raise CorpusError("source manifest is incomplete")
            _hash(row["document_hash"], "document_hash")
            if row["ingestion_status"] != "VERIFIED" or row["access_status"] != "ACCESSIBLE":
                raise CorpusError("accepted source must be accessible and verified")
            if row["validation_status"] not in ACCEPTED_STATUSES:
                raise CorpusError("accepted source has unavailable status")
            _items(row["stable_locators"], "stable_locators")
            policy = row["excerpt_policy"]
            if not isinstance(policy, dict) or policy.get("full_text_runtime_allowed") is not False:
                raise CorpusError("whole-source runtime loading is forbidden")
            if int(policy.get("maximum_words", -1)) > 25:
                raise CorpusError("excerpt policy exceeds corpus maximum")

    def _validate_duplicate_sources(self) -> None:
        locations: set[str] = set()
        hashes: set[str] = set()
        for row in self.source_records.values():
            location = str(row["source_location"])
            document_hash = str(row["document_hash"])
            if location in locations:
                raise CorpusError("duplicate source URL")
            if document_hash in hashes:
                raise CorpusError("duplicate source content hash")
            locations.add(location)
            hashes.add(document_hash)

    def _validate_fetched_metadata(self) -> None:
        rows = self.fetched_sources.get("sources", [])
        if not isinstance(rows, list):
            raise CorpusError("fetched source metadata must be a list")
        by_source = {str(row.get("source_id")): row for row in rows if row.get("source_id")}
        if len(by_source) != len(rows):
            raise CorpusError("duplicate fetched source metadata")
        for source_id, source in self.source_records.items():
            row = by_source.get(source_id)
            if row is None:
                if self.schema_version == CORPUS_SCHEMA_VERSION:
                    raise CorpusError("accepted source fetch metadata is missing")
                continue
            if row.get("access_status") not in {"VERIFIED", "REUSED_PINNED", "LOCAL_USER_PROVIDED"}:
                raise CorpusError("accepted source fetch is not verified")
            if row.get("sha256") != source["document_hash"]:
                raise CorpusError("fetched source hash mismatch")

    def _validate_user_sources(self, root: Path, paths: list[Path]) -> None:
        registered = {str(path.relative_to(root)): path for path in paths}
        for source in self.source_records.values():
            if source["source_type"] != "USER_PROVIDED":
                continue
            relative = str(source["source_location"])
            path = registered.get(relative)
            if path is None or not path.is_file():
                raise CorpusError("user-provided source file is unavailable")
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["document_hash"]:
                raise CorpusError("user-provided source hash mismatch")

    def source_fetch_required(self, source_id: str, *, source_location: str, expected_hash: str) -> bool:
        """Return whether authoring must refetch; this method never performs I/O."""
        for row in self.fetched_sources.get("sources") or ():
            if (row.get("source_id") == source_id and row.get("source_location") == source_location
                    and row.get("sha256") == expected_hash
                    and row.get("access_status") in {"VERIFIED", "REUSED_PINNED", "LOCAL_USER_PROVIDED"}):
                return False
        return True

    def conflict_explanation(self, card_ids: tuple[str, str]) -> str | None:
        pair = set(card_ids)
        for row in self.conflict_registry.get("conflicts") or ():
            if set(row.get("card_ids") or ()) == pair:
                return str(row.get("resolution") or row.get("explanation") or "") or None
        return None

    def _validate_card_links(self) -> None:
        identifiers = set(self.curated_cards)
        for card in self.curated_cards.values():
            if card.source_id not in self.source_records:
                raise CorpusError("card source does not exist")
            if any(target not in identifiers for target in card.contradicts_card_ids):
                raise CorpusError("knowledge contradiction target missing")

    def _adapt_source(self, raw: Mapping[str, Any]) -> KnowledgeSourceManifest:
        policy = ExcerptPolicy(**raw["excerpt_policy"])
        return seal(KnowledgeSourceManifest(
            record_id=f"source:{raw['source_id']}", version=str(raw["edition_version"]), created_at=self.generated_at,
            provenance={**dict(raw["provenance"]), "hash_scope": raw["hash_scope"], "rights_status": raw["rights_status"]},
            source_id=str(raw["source_id"]), title=str(raw["title"]), author_organisation=str(raw["author_organisation"]),
            edition_version=str(raw["edition_version"]), publication_date=raw.get("publication_date"),
            source_type=str(raw["source_type"]), document_hash=str(raw["document_hash"]),
            source_location=str(raw["source_location"]), ingestion_status="VERIFIED", excerpt_policy=policy,
            validation_status=ValidationStatus(str(raw["validation_status"])), stable_locators=tuple(raw["stable_locators"]),
            limitations=tuple(raw["limitations"]), contradictions=tuple(raw["contradictions"]),
        ))

    def _adapt_card(self, card: CuratedKnowledgeCard) -> KnowledgeCard:
        source = self.sources[card.source_id]
        citation = CitationLocator(
            source_id=card.source_id, source_version=source.edition_version,
            document_hash=source.document_hash, locator=card.exact_locator, section=card.exact_locator,
        )
        return seal(KnowledgeCard(
            record_id=card.card_id, card_id=card.card_id, version=card.version, created_at=self.generated_at,
            provenance={"curated_card_hash": card.content_hash, "registry": self.registry_version,
                        "execution_influence": "ZERO", "knowledge_policy_version": card.knowledge_policy_version,
                        "research_only": card.research_only},
            source_id=card.source_id, concept=card.concept, principle=card.definition_principle,
            required_evidence=card.required_evidence, valid_conditions=card.valid_conditions,
            failure_conditions=card.failure_conditions, contradictions=card.contradictions,
            when_not_to_use=card.when_not_to_use, option_buying_relevance=card.option_buying_relevance,
            relevant_timeframes=card.timeframes, relevant_citadel_fields=card.relevant_citadel_fields,
            citation=citation, permitted_excerpt=card.short_excerpt, paraphrased_interpretation=card.paraphrase,
            validation_status=ValidationStatus(card.validation_status), linked_empirical_evidence_ids=(),
            domains=(card.domain,), regimes=card.regimes, setup_types=card.setup_types,
            contradicts_card_ids=card.contradicts_card_ids,
        ))

    def get(self, card_id: str) -> KnowledgeCard | None:
        return self.cards.get(str(card_id))

    def raw(self, card_id: str) -> CuratedKnowledgeCard | None:
        return self.curated_cards.get(str(card_id))


class IngestionLedger:
    """Append-only hash chain for authoring-time pipeline transitions."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._states: dict[str, IngestionStage] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._accept(json.loads(line), recovering=True)

    def advance(self, *, candidate_id: str, stage: IngestionStage, idempotency_key: str,
                actor_id: str, correlation_id: str, details: Mapping[str, Any]) -> dict[str, Any]:
        if idempotency_key in self._idempotency:
            return self._idempotency[idempotency_key]
        prior = self._states.get(candidate_id)
        expected = STAGES[0] if prior is None else STAGES[STAGES.index(prior) + 1] if prior != STAGES[-1] else None
        if stage is not expected:
            raise CorpusError("invalid ingestion transition")
        event = {
            "schema_version": CORPUS_SCHEMA_VERSION, "policy_version": INGESTION_POLICY_VERSION,
            "candidate_id": _text(candidate_id, "candidate_id"), "stage": stage.value,
            "idempotency_key": _text(idempotency_key, "idempotency_key"), "actor_id": _text(actor_id, "actor_id"),
            "correlation_id": _text(correlation_id, "correlation_id"), "details": dict(details),
            "prior_hash": self.events[-1]["event_hash"] if self.events else "0" * 64,
        }
        event["event_hash"] = _sha(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        self._accept(event, recovering=False)
        return event

    def _accept(self, event: Mapping[str, Any], *, recovering: bool) -> None:
        value = dict(event)
        supplied = value.pop("event_hash", "")
        if supplied != _sha(value):
            raise CorpusError("ingestion ledger hash mismatch")
        expected_prior = self.events[-1]["event_hash"] if self.events else "0" * 64
        if event.get("prior_hash") != expected_prior:
            raise CorpusError("ingestion ledger chain mismatch")
        key = str(event["idempotency_key"])
        if key in self._idempotency:
            if self._idempotency[key] != event:
                raise CorpusError("ingestion idempotency conflict")
            return
        stage = IngestionStage(event["stage"])
        prior = self._states.get(str(event["candidate_id"]))
        expected = STAGES[0] if prior is None else STAGES[STAGES.index(prior) + 1] if prior != STAGES[-1] else None
        if stage is not expected:
            raise CorpusError("ingestion ledger transition invalid")
        self.events.append(dict(event)); self._idempotency[key] = dict(event)
        self._states[str(event["candidate_id"])] = stage

    def state(self, candidate_id: str) -> IngestionStage | None:
        return self._states.get(str(candidate_id))

    def verify(self) -> bool:
        try:
            recovered = IngestionLedger(self.path)
        except (CorpusError, OSError, ValueError, KeyError):
            return False
        return recovered.events == self.events
