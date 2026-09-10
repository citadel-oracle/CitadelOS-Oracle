"""Strict, bounded retrieval over source manifests and the legacy hypothesis vault."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping

from src.oracle.contracts.learning import (
    CitationLocator, ExcerptPolicy, KnowledgeCard, KnowledgeCardReference,
    KnowledgeConflict, KnowledgeRetrievalQuery, KnowledgeRetrievalResult,
    KnowledgeSourceManifest, LearningContractError, ValidationStatus, seal,
)
from src.oracle.knowledge import KnowledgeVault
from src.oracle.knowledge_corpus import (
    Phase5AKnowledgeRegistry, RETRIEVAL_POLICY_VERSION,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = PROJECT_ROOT / "oracle_knowledge" / "phase4_registry.json"
DEFAULT_LEGACY_VAULT = PROJECT_ROOT / "oracle_knowledge"


class KnowledgeRegistryError(RuntimeError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _tokens(*values: Any) -> set[str]:
    return {token for value in values for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2}


class Phase4KnowledgeRegistry:
    """Loads one immutable registry snapshot and verifies every card locator."""

    def __init__(self, path: Path | str = DEFAULT_REGISTRY, *, legacy_root: Path | str = DEFAULT_LEGACY_VAULT):
        self.path = Path(path)
        raw_bytes = self.path.read_bytes()
        try:
            document = json.loads(raw_bytes)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise KnowledgeRegistryError("KNOWLEDGE_REGISTRY_INVALID") from error
        self.registry_version = str(document.get("registry_version") or "")
        self.generated_at = str(document.get("generated_at") or "")
        self.legacy_vault = KnowledgeVault(Path(legacy_root))
        self.registry_file_hash = hashlib.sha256(raw_bytes).hexdigest()
        self.vault_hash = _hash({"phase4": self.registry_file_hash, "legacy": self.legacy_vault.vault_hash})
        try:
            sources = [self._source(row) for row in document.get("sources") or ()]
            self.sources = {row.source_id: row for row in sources}
            cards = [self._card(row) for row in document.get("cards") or ()]
        except (KeyError, TypeError, ValueError, LearningContractError) as error:
            raise KnowledgeRegistryError("KNOWLEDGE_REGISTRY_INVALID") from error
        if len(self.sources) != len(sources) or len({row.card_id for row in cards}) != len(cards):
            raise KnowledgeRegistryError("KNOWLEDGE_REGISTRY_DUPLICATE_ID")
        self.cards = {row.card_id: row for row in cards}
        self._validate_links()

    def _source(self, raw: Mapping[str, Any]) -> KnowledgeSourceManifest:
        policy = ExcerptPolicy(**raw["excerpt_policy"])
        source_id = str(raw["source_id"])
        return seal(KnowledgeSourceManifest(
            record_id=f"source:{source_id}", version=str(raw["edition_version"]), created_at=self.generated_at,
            provenance={"registry": self.registry_version, "known_locators": list(raw.get("known_locators") or ())},
            source_id=source_id, title=str(raw["title"]), author_organisation=str(raw["author_organisation"]),
            edition_version=str(raw["edition_version"]), publication_date=raw.get("publication_date"),
            source_type=str(raw["source_type"]), document_hash=str(raw["document_hash"]),
            source_location=str(raw["source_location"]), ingestion_status=str(raw["ingestion_status"]),
            excerpt_policy=policy, validation_status=ValidationStatus(raw["validation_status"]),
            stable_locators=tuple(raw.get("known_locators") or ()),
            limitations=tuple(raw.get("limitations") or ()), contradictions=tuple(raw.get("contradictions") or ()),
        ))

    def _card(self, raw: Mapping[str, Any]) -> KnowledgeCard:
        source = self.sources.get(str(raw["source_id"]))
        if source is None:
            raise LearningContractError("card source does not exist")
        locator_value = str(raw.get("locator") or "")
        known = source.stable_locators
        if locator_value not in known:
            raise LearningContractError("citation locator does not exist in the source manifest")
        excerpt = raw.get("permitted_excerpt")
        if excerpt and (not source.excerpt_policy.excerpt_allowed or len(str(excerpt).split()) > source.excerpt_policy.maximum_words):
            raise LearningContractError("excerpt policy exceeded")
        citation = CitationLocator(
            source_id=source.source_id, source_version=source.edition_version,
            document_hash=str(raw.get("document_hash") or ""), locator=locator_value,
            section=locator_value.split(" > ", 1)[0], paragraph=locator_value.split(" > ", 1)[-1],
        )
        card_id = str(raw["card_id"])
        return seal(KnowledgeCard(
            record_id=card_id, card_id=card_id, version=str(raw["version"]), created_at=self.generated_at,
            provenance={"source_manifest_hash": source.content_hash, "registry": self.registry_version},
            source_id=source.source_id, concept=str(raw["concept"]), principle=str(raw["principle"]),
            required_evidence=tuple(raw["required_evidence"]), valid_conditions=tuple(raw["valid_conditions"]),
            failure_conditions=tuple(raw["failure_conditions"]), contradictions=tuple(raw["contradictions"]),
            when_not_to_use=tuple(raw["when_not_to_use"]), option_buying_relevance=str(raw["option_buying_relevance"]),
            relevant_timeframes=tuple(raw["relevant_timeframes"]), relevant_citadel_fields=tuple(raw["relevant_citadel_fields"]),
            citation=citation, permitted_excerpt=str(excerpt) if excerpt else None,
            paraphrased_interpretation=str(raw["paraphrased_interpretation"]),
            validation_status=ValidationStatus(raw["validation_status"]),
            linked_empirical_evidence_ids=tuple(raw.get("linked_empirical_evidence_ids") or ()),
            domains=tuple(raw.get("domains") or ()), regimes=tuple(raw.get("regimes") or ()),
            setup_types=tuple(raw.get("setup_types") or ()), contradicts_card_ids=tuple(raw.get("contradicts_card_ids") or ()),
        ))

    def _validate_links(self) -> None:
        for card in self.cards.values():
            source = self.sources[card.source_id]
            if card.citation.document_hash != source.document_hash or card.citation.source_version != source.edition_version:
                raise KnowledgeRegistryError("KNOWLEDGE_SOURCE_HASH_MISMATCH")
            if any(item not in self.cards for item in card.contradicts_card_ids):
                raise KnowledgeRegistryError("KNOWLEDGE_CONTRADICTION_TARGET_MISSING")

    def get(self, card_id: str) -> KnowledgeCard | None:
        return self.cards.get(str(card_id))


class KnowledgeRetrievalService:
    """Deterministic lexical/filter retrieval; no LLM and no whole-source loads."""

    def __init__(self, registry: Phase4KnowledgeRegistry | Phase5AKnowledgeRegistry | None = None):
        self.registry = registry or Phase5AKnowledgeRegistry()
        self._cache: dict[str, KnowledgeRetrievalResult] = {}
        self._lock = RLock()

    def search(self, query: KnowledgeRetrievalQuery) -> KnowledgeRetrievalResult:
        semantic = {
            "instrument": query.instrument.upper(), "setup_type": query.setup_type,
            "market_regime": query.market_regime, "timeframe": query.timeframe,
            "option_buying_relevance": query.option_buying_relevance,
            "current_evidence_claims": list(query.current_evidence_claims), "question": query.question,
            "allowed_validation_statuses": sorted(value.value for value in query.allowed_validation_statuses),
            "maximum_cards": query.maximum_cards, "vault_version": self.registry.registry_version,
            "vault_hash": self.registry.vault_hash,
        }
        query_hash = _hash(semantic)
        with self._lock:
            if query_hash in self._cache:
                return self._cache[query_hash]
        tokens = _tokens(query.question, *query.current_evidence_claims)
        allowed = set(query.allowed_validation_statuses)
        scored: list[tuple[int, int, str, KnowledgeCard]] = []
        for card in self.registry.cards.values():
            raw = self.registry.raw(card.card_id) if hasattr(self.registry, "raw") else None
            if card.validation_status not in allowed:
                continue
            if raw is not None and query.instrument.upper() not in {value.upper() for value in raw.instruments}:
                continue
            if query.timeframe and card.relevant_timeframes and query.timeframe not in card.relevant_timeframes:
                continue
            if query.setup_type and card.setup_types and query.setup_type not in card.setup_types:
                continue
            if query.market_regime and card.regimes and query.market_regime not in card.regimes:
                continue
            if query.option_buying_relevance and card.option_buying_relevance not in {query.option_buying_relevance, "HIGH"}:
                continue
            if raw is not None and raw.research_only:
                continue
            source = self.registry.sources.get(card.source_id)
            haystack_tokens = _tokens(
                card.concept, card.principle, *card.domains, *card.relevant_citadel_fields,
                *(raw.measurable_predicates if raw else ()),
                *(raw.setup_types if raw else ()),
                source.title if source else "", source.author_organisation if source else "",
                card.citation.locator,
            )
            score = len(tokens & haystack_tokens)
            if score or not tokens:
                quality = {"INTERNAL_VALIDATED": 0, "OFFICIAL_PRIMARY": 1, "PEER_REVIEWED_PRIMARY": 2,
                           "WORKING_PAPER_PRIMARY": 3, "USER_PROVIDED_NOT_VERIFIED": 5}.get(
                               raw.source_quality if raw else "", 4)
                scored.append((-score, quality, card.card_id, card))
        scored.sort(key=lambda row: (row[0], row[1], row[2]))
        selected = [row[3] for row in scored[: query.maximum_cards]]
        # Material counter-principles displace the last low-ranked card if needed.
        counters_added = 0
        counter_ids: set[str] = set()
        for card in tuple(selected):
            if card not in selected:
                continue
            for other_id in card.contradicts_card_ids:
                other = self.registry.cards[other_id]
                other_raw = self.registry.raw(other_id) if hasattr(self.registry, "raw") else None
                if (other.validation_status in allowed and other not in selected and counters_added < 2
                        and (other_raw is None or query.instrument.upper() in {value.upper() for value in other_raw.instruments})
                        and (other_raw is None or not other_raw.research_only)
                        and (not query.timeframe or not other.relevant_timeframes or query.timeframe in other.relevant_timeframes)
                        and (getattr(self.registry, "schema_version", None) != "5a.1.0"
                             or not query.setup_type or not other.setup_types or query.setup_type in other.setup_types)
                        and (getattr(self.registry, "schema_version", None) != "5a.1.0"
                             or not query.market_regime or not other.regimes or query.market_regime in other.regimes)):
                    if len(selected) >= query.maximum_cards:
                        replace_index = next((index for index in range(len(selected) - 1, -1, -1)
                                              if selected[index].card_id not in counter_ids
                                              and selected[index].card_id != card.card_id
                                              and not selected[index].contradicts_card_ids), None)
                        if replace_index is None:
                            continue
                        selected[replace_index] = other
                    else:
                        selected.append(other)
                    counter_ids.add(other.card_id)
                    counters_added += 1
        selected = sorted({row.card_id: row for row in selected}.values(), key=lambda row: row.card_id)
        references = tuple(KnowledgeCardReference(
            card_id=card.card_id, card_version=card.version, card_hash=card.content_hash,
            validation_status=card.validation_status, citation=card.citation,
            relevance="Matched current verified fields/question; explanatory only and never a probability.",
        ) for card in selected)
        pairs: set[tuple[str, str]] = set()
        conflicts = []
        for card in selected:
            for other in card.contradicts_card_ids:
                pair = tuple(sorted((card.card_id, other)))
                if other in {item.card_id for item in selected} and pair not in pairs:
                    pairs.add(pair)
                    explanation = (self.registry.conflict_explanation(pair)
                                   if hasattr(self.registry, "conflict_explanation") else None)
                    conflicts.append(KnowledgeConflict(
                        conflict_id="knowledge-conflict-" + _hash(pair)[:16], card_ids=pair,
                        materiality="MATERIAL", explanation=explanation or
                        "A source-backed driver principle is bounded by an explicit counter-principle.",
                    ))
        result = seal(KnowledgeRetrievalResult(
            record_id="knowledge-result-" + query_hash[:24], version=RETRIEVAL_POLICY_VERSION,
            created_at=self.registry.generated_at,
            provenance={"deterministic": True, "legacy_hypothesis_count": len(self.registry.legacy_vault.items),
                        "legacy_hypotheses_promoted": 0},
            query_hash=query_hash, vault_version=self.registry.registry_version, vault_hash=self.registry.vault_hash,
            card_references=references, conflicts=tuple(conflicts), omitted_count=max(0, len(scored) - len(selected)),
            whole_source_loaded=False,
        ))
        with self._lock:
            self._cache[query_hash] = result
        return result

    def research_cards(self, *, setup_type: str | None = None, domain: str | None = None) -> tuple[Any, ...]:
        """Deterministic research-only catalog; never part of live evidence retrieval."""
        if not hasattr(self.registry, "curated_cards"):
            return ()
        values = (
            card for card in self.registry.curated_cards.values()
            if card.research_only
            and (setup_type is None or setup_type in card.setup_types)
            and (domain is None or card.domain == domain)
        )
        return tuple(sorted(values, key=lambda card: card.card_id))


def build_query(*, instrument: str, question: str, setup_type: str | None = None,
                market_regime: str | None = None, timeframe: str | None = None,
                option_buying_relevance: str | None = "HIGH", current_evidence_claims=(),
                maximum_cards: int = 5) -> KnowledgeRetrievalQuery:
    semantic = {"instrument": instrument, "question": question, "setup_type": setup_type,
                "market_regime": market_regime, "timeframe": timeframe,
                "option_buying_relevance": option_buying_relevance,
                "claims": list(current_evidence_claims), "maximum_cards": maximum_cards}
    return seal(KnowledgeRetrievalQuery(
        record_id="knowledge-query-" + _hash(semantic)[:24], version="oracle-knowledge-query-4.0.0",
        created_at=datetime.now(timezone.utc).isoformat(), provenance={"caller": "oracle_phase4"},
        instrument=instrument, setup_type=setup_type, market_regime=market_regime, timeframe=timeframe,
        option_buying_relevance=option_buying_relevance, current_evidence_claims=tuple(current_evidence_claims),
        question=question, allowed_validation_statuses=(ValidationStatus.INTERNALLY_VALIDATED,
            ValidationStatus.SOURCE_VERIFIED, ValidationStatus.SOURCE_BACKED_UNVALIDATED,
            ValidationStatus.USER_PROVIDED_UNVALIDATED, ValidationStatus.CONFLICTED,
            ValidationStatus.FUTURE_DATA_DEPENDENT),
        maximum_cards=maximum_cards,
    ))
