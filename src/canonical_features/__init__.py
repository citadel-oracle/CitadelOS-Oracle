"""
Canonical Feature Engine Package.
Authoritative source for market feature calculations, versioned snapshots, and shadow parity adapters.
"""

from src.canonical_features.models import (
    CanonicalFeatureSnapshot,
    SupertrendValue,
)
from src.canonical_features.engine import CanonicalFeatureEngine
from src.canonical_features.formula_registry import FormulaProfileRegistry
from src.canonical_features.service import CanonicalFeatureService

__all__ = [
    "CanonicalFeatureSnapshot",
    "SupertrendValue",
    "CanonicalFeatureEngine",
    "FormulaProfileRegistry",
    "CanonicalFeatureService",
]
