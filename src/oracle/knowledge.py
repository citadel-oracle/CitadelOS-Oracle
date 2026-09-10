"""Deterministic, read-only loader for the Oracle Knowledge Vault."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_STATUSES = frozenset({"HYPOTHESIS", "VALIDATED", "REJECTED"})
_ITEM_FIELDS = frozenset(
    {
        "id",
        "version",
        "source_tag",
        "status",
        "topic",
        "tags",
        "content_path",
        "definition",
        "rule",
        "valid_conditions",
        "invalidation",
        "when_not_to_use",
        "contradictions",
        "testable_hypothesis",
    }
)


class KnowledgeVaultError(RuntimeError):
    """Raised when the vault cannot be trusted as a complete read-only unit."""

    code = "ORACLE_KNOWLEDGE_VAULT_INVALID"


@dataclass(frozen=True)
class KnowledgeItem:
    item_id: str
    version: str
    source_tag: str
    status: str
    topic: str
    tags: tuple[str, ...]
    content_path: str
    definition: str
    rule: str
    valid_conditions: tuple[str, ...]
    invalidation: tuple[str, ...]
    when_not_to_use: tuple[str, ...]
    contradictions: tuple[str, ...]
    testable_hypothesis: str
    content: str


class KnowledgeVault:
    """Loads one validated snapshot and exposes no mutation operations."""

    SCHEMA_VERSION = 1

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.registry_path = self.root / "evidence_registry.json"
        document = self._read_registry()
        self._vault_version = self._version(
            document.get("vault_version"),
            "vault_version",
        )
        sources = self._sources(document.get("source_catalog"))
        items, canonical_entries, content = self._items(
            document.get("entries"),
            sources,
        )
        self._validate_links(items)
        canonical = {
            "schema_version": self.SCHEMA_VERSION,
            "vault_version": self._vault_version,
            "source_catalog": {
                key: sources[key] for key in sorted(sources)
            },
            "entries": canonical_entries,
            "content": {key: content[key] for key in sorted(content)},
        }
        encoded = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self._vault_hash = hashlib.sha256(encoded).hexdigest()
        self._items_by_id = MappingProxyType(
            {item.item_id: item for item in items}
        )
        self._items = tuple(items)

    @property
    def vault_version(self) -> str:
        return self._vault_version

    @property
    def vault_hash(self) -> str:
        return self._vault_hash

    @property
    def items(self) -> tuple[KnowledgeItem, ...]:
        return self._items

    def get(self, item_id: str) -> Optional[KnowledgeItem]:
        return self._items_by_id.get(str(item_id).strip().lower())

    def search(
        self,
        *,
        item_id: Optional[str] = None,
        topic: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> tuple[KnowledgeItem, ...]:
        normalized_id = self._optional_query(item_id)
        normalized_topic = self._optional_query(topic)
        normalized_tag = self._optional_query(tag)
        return tuple(
            item
            for item in self._items
            if (normalized_id is None or item.item_id == normalized_id)
            and (normalized_topic is None or item.topic == normalized_topic)
            and (
                normalized_tag is None
                or normalized_tag in item.tags
            )
        )

    def _read_registry(self) -> dict[str, Any]:
        try:
            document = json.loads(
                self.registry_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise KnowledgeVaultError("Knowledge registry is unreadable") from error
        if not isinstance(document, dict):
            raise KnowledgeVaultError("Knowledge registry must be an object")
        if set(document) != {
            "schema_version",
            "vault_version",
            "source_catalog",
            "entries",
        }:
            raise KnowledgeVaultError("Knowledge registry shape is invalid")
        if document.get("schema_version") != self.SCHEMA_VERSION:
            raise KnowledgeVaultError("Knowledge schema version is unsupported")
        return document

    def _items(
        self,
        raw_entries: Any,
        sources: Mapping[str, str],
    ) -> tuple[
        list[KnowledgeItem],
        list[dict[str, Any]],
        dict[str, str],
    ]:
        if not isinstance(raw_entries, list) or not raw_entries:
            raise KnowledgeVaultError("Knowledge entries are missing")
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        items: list[KnowledgeItem] = []
        canonical_entries: list[dict[str, Any]] = []
        content: dict[str, str] = {}
        for raw in sorted(
            raw_entries,
            key=lambda value: str(
                value.get("id", "") if isinstance(value, Mapping) else ""
            ),
        ):
            if not isinstance(raw, dict) or set(raw) != _ITEM_FIELDS:
                raise KnowledgeVaultError("Knowledge item shape is invalid")
            item_id = self._identifier(raw["id"], "id")
            if item_id in seen_ids:
                raise KnowledgeVaultError(f"Duplicate knowledge ID: {item_id}")
            seen_ids.add(item_id)
            source_tag = self._text(raw["source_tag"], "source_tag")
            if source_tag not in sources:
                raise KnowledgeVaultError(
                    f"Unknown source tag for {item_id}: {source_tag}"
                )
            content_path = self._content_path(raw["content_path"], item_id)
            if content_path in seen_paths:
                raise KnowledgeVaultError(
                    f"Duplicate content reference: {content_path}"
                )
            seen_paths.add(content_path)
            body = self._read_content(content_path, item_id)
            entry = {
                "id": item_id,
                "version": self._version(raw["version"], "version"),
                "source_tag": source_tag,
                "status": self._status(raw["status"]),
                "topic": self._identifier(raw["topic"], "topic"),
                "tags": self._text_list(raw["tags"], "tags", sort=True),
                "content_path": content_path,
                "definition": self._text(raw["definition"], "definition"),
                "rule": self._text(raw["rule"], "rule"),
                "valid_conditions": self._text_list(
                    raw["valid_conditions"],
                    "valid_conditions",
                ),
                "invalidation": self._text_list(
                    raw["invalidation"],
                    "invalidation",
                ),
                "when_not_to_use": self._text_list(
                    raw["when_not_to_use"],
                    "when_not_to_use",
                ),
                "contradictions": self._id_list(raw["contradictions"]),
                "testable_hypothesis": self._text(
                    raw["testable_hypothesis"],
                    "testable_hypothesis",
                ),
            }
            canonical_entries.append(entry)
            content[content_path] = body
            items.append(
                KnowledgeItem(
                    item_id=entry["id"],
                    version=entry["version"],
                    source_tag=entry["source_tag"],
                    status=entry["status"],
                    topic=entry["topic"],
                    tags=tuple(entry["tags"]),
                    content_path=entry["content_path"],
                    definition=entry["definition"],
                    rule=entry["rule"],
                    valid_conditions=tuple(entry["valid_conditions"]),
                    invalidation=tuple(entry["invalidation"]),
                    when_not_to_use=tuple(entry["when_not_to_use"]),
                    contradictions=tuple(entry["contradictions"]),
                    testable_hypothesis=entry["testable_hypothesis"],
                    content=body,
                )
            )
        return items, canonical_entries, content

    def _content_path(self, value: Any, item_id: str) -> str:
        relative = Path(self._text(value, "content_path"))
        if relative.is_absolute() or relative.suffix.lower() != ".md":
            raise KnowledgeVaultError(
                f"Invalid content reference for {item_id}"
            )
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise KnowledgeVaultError(
                f"Content reference escapes vault for {item_id}"
            ) from error
        if not candidate.is_file():
            raise KnowledgeVaultError(
                f"Missing content reference for {item_id}"
            )
        return relative.as_posix()

    def _read_content(self, relative: str, item_id: str) -> str:
        try:
            body = (self.root / relative).read_text(encoding="utf-8")
        except OSError as error:
            raise KnowledgeVaultError(
                f"Knowledge content is unreadable for {item_id}"
            ) from error
        body = body.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not body or f"<!-- knowledge-id: {item_id} -->" not in body:
            raise KnowledgeVaultError(
                f"Knowledge content identity mismatch for {item_id}"
            )
        return body

    @staticmethod
    def _sources(value: Any) -> dict[str, str]:
        if not isinstance(value, dict) or not value:
            raise KnowledgeVaultError("Source catalog is missing")
        result: dict[str, str] = {}
        for key, description in value.items():
            source = KnowledgeVault._text(key, "source_tag")
            if source in result:
                raise KnowledgeVaultError(f"Duplicate source tag: {source}")
            result[source] = KnowledgeVault._text(
                description,
                "source_description",
            )
        return result

    @staticmethod
    def _validate_links(items: list[KnowledgeItem]) -> None:
        identifiers = {item.item_id for item in items}
        for item in items:
            for target in item.contradictions:
                if target == item.item_id or target not in identifiers:
                    raise KnowledgeVaultError(
                        f"Invalid contradiction link: {item.item_id} -> {target}"
                    )

    @staticmethod
    def _identifier(value: Any, field: str) -> str:
        normalized = KnowledgeVault._text(value, field).lower()
        if not _IDENTIFIER.fullmatch(normalized):
            raise KnowledgeVaultError(f"Invalid {field}: {normalized}")
        return normalized

    @staticmethod
    def _version(value: Any, field: str) -> str:
        normalized = KnowledgeVault._text(value, field)
        if not _VERSION.fullmatch(normalized):
            raise KnowledgeVaultError(f"Invalid {field}: {normalized}")
        return normalized

    @staticmethod
    def _status(value: Any) -> str:
        normalized = KnowledgeVault._text(value, "status").upper()
        if normalized not in _STATUSES:
            raise KnowledgeVaultError(f"Invalid knowledge status: {normalized}")
        return normalized

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise KnowledgeVaultError(f"{field} must be text")
        normalized = value.strip()
        if not normalized or len(normalized) > 2_000:
            raise KnowledgeVaultError(f"{field} is invalid")
        return normalized

    @staticmethod
    def _text_list(
        value: Any,
        field: str,
        *,
        sort: bool = False,
    ) -> list[str]:
        if not isinstance(value, list) or not value:
            raise KnowledgeVaultError(f"{field} must be a non-empty list")
        normalized = [KnowledgeVault._text(item, field) for item in value]
        if len(normalized) != len(set(normalized)):
            raise KnowledgeVaultError(f"{field} contains duplicates")
        return sorted(normalized) if sort else normalized

    @staticmethod
    def _id_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            raise KnowledgeVaultError("contradictions must be a list")
        normalized = [
            KnowledgeVault._identifier(item, "contradiction")
            for item in value
        ]
        if len(normalized) != len(set(normalized)):
            raise KnowledgeVaultError("contradictions contains duplicates")
        return sorted(normalized)

    @staticmethod
    def _optional_query(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip().lower()
