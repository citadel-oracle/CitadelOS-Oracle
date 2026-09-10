"""
Read-Only Shadow Adapters Package for Canonical Features.
"""

from src.canonical_features.adapters.ose_adapter import OseShadowAdapter
from src.canonical_features.adapters.vob_adapter import VobShadowAdapter
from src.canonical_features.adapters.tactical_edge_adapter import TacticalEdgeShadowAdapter
from src.canonical_features.adapters.edge_lab_adapter import EdgeLabShadowAdapter

__all__ = [
    "OseShadowAdapter",
    "VobShadowAdapter",
    "TacticalEdgeShadowAdapter",
    "EdgeLabShadowAdapter",
]
