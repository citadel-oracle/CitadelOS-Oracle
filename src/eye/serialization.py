"""Canonical Serialization and SHA-256 Hashing for Eye Engine Contracts."""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence


class EyeSerializationError(ValueError):
    pass


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise EyeSerializationError("Naive datetime cannot be serialized")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, float):
        if not (-float("inf") < value < float("inf")):
            raise EyeSerializationError("NaN and Infinity are forbidden in canonical serialization")
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda r: str(r[0]))}
    if isinstance(value, (tuple, list, set)):
        return [_plain(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    """Produces stable, sorted UTF-8 JSON representation."""
    plain = _plain(value)
    return json.dumps(plain, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def compute_sha256(value: Any) -> str:
    """Produces SHA-256 hash of the canonical JSON representation."""
    encoded = canonical_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
