"""Rule Registry and Configurable Runtime Parameters for Citadel Live Island.

IMPORTANT:
Certain parameters (e.g. 300ms burst window, 1.8s Hero tenure) are baseline engineering
defaults and must remain configurable for live-market calibration.
"""

from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass
class LiveIslandRegistry:
    # Rule and Configuration Version
    rule_version: str = "1.0.0"

    # -------------------------------------------------------------------------
    # AUTHORITATIVE USER-SPECIFIED DETECTION THRESHOLDS
    # -------------------------------------------------------------------------
    vix_min_change_pct: float = 2.0  # India VIX >= 2% change
    pcr_min_change_pct: float = 5.0  # Put-Call Ratio >= 5% change
    buyers_writers_min_change_pp: float = 5.0  # Buyers/Writers share >= 5 percentage points

    # -------------------------------------------------------------------------
    # CONFIGURABLE UNVALIDATED BASELINE DEFAULTS (EXPLICITLY TUNABLE)
    # -------------------------------------------------------------------------
    burst_window_ms: int = 300  # Coalescing microburst window (ms)
    hero_min_tenure_ms: int = 1800  # Minimum tenure before standard takeover (ms)
    hero_takeover_margin: float = 1.25  # Severity score multiplier required to preempt incumbent Hero
    impact_duration_ms: int = 2500  # Duration an event stays in IMPACT before moving to SETTLED (ms)
    max_active_events: int = 4  # Exactly 1 Hero + max 3 Companions
    max_memory_events: int = 3  # Maximum retention in memory plane
    memory_ttl_seconds: float = 60.0  # Default memory eviction TTL
    required_constituent_coverage_ratio: float = 0.80  # Required minimum coverage before BASELINE_READY

    # -------------------------------------------------------------------------
    # SEVERITY WEIGHTS FOR HERO DETERMINATION
    # -------------------------------------------------------------------------
    severity_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "critical": 4.5,
            "high": 3.0,
            "medium": 2.0,
            "low": 1.0,
        }
    )

    # Required instrument families for baseline readiness
    required_families: Set[str] = field(
        default_factory=lambda: {"vix", "underlying", "active_ce", "active_pe"}
    )


# Singleton default registry instance
DEFAULT_REGISTRY = LiveIslandRegistry()
