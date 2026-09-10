"""
Anti-Double-Counting Feature Cluster Contribution Capping and Shadow Evaluator.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


CLUSTER_DEFINITIONS: dict[str, tuple[str, ...]] = {
    "premium_cluster": (
        "option.premium_return.5m",
        "option.premium_velocity.5m",
        "option.premium_acceleration.5m",
    ),
    "spot_cluster": (
        "spot.return.5m",
        "spot.velocity.5m",
        "spot.acceleration.5m",
    ),
    "straddle_cluster": (
        "option.straddle_price.5m",
        "option.straddle_velocity.5m",
        "option.straddle_acceleration.5m",
    ),
    "participation_cluster": (
        "market.pressure.5m",
        "market.breadth.5m",
        "market.persistence.5m",
    ),
    "oi_pcr_cluster": (
        "market.pcr_level.5m",
        "market.pcr_change.5m",
    ),
}

MAX_CLUSTER_CONTRIBUTION_PCT = 35.0  # Cap any single feature cluster to at most 35% of total score


@dataclass(frozen=True)
class ClusterComparisonResult:
    timestamp: str
    legacy_score: int
    cluster_adjusted_score: int
    difference: int
    affected_clusters: tuple[str, ...]
    cluster_breakdown: dict[str, float]
    execution_influence: str = "ZERO"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "legacy_score": self.legacy_score,
            "cluster_adjusted_score": self.cluster_adjusted_score,
            "difference": self.difference,
            "affected_clusters": list(self.affected_clusters),
            "cluster_breakdown": self.cluster_breakdown,
            "execution_influence": self.execution_influence,
        }


class ClusterCapEvaluator:
    """Evaluates component scores with feature cluster contribution capping in shadow mode."""

    def __init__(self, max_cluster_pct: float = MAX_CLUSTER_CONTRIBUTION_PCT):
        self.max_cluster_pct = max_cluster_pct

    def evaluate_shadow(
        self,
        component_scores: Mapping[str, float],
        weights: Mapping[str, float],
    ) -> ClusterComparisonResult:
        # Calculate legacy un-capped score
        total_weight = sum(weights.get(k, 0.0) for k in component_scores.keys())
        raw_awarded = sum(component_scores.get(k, 0.0) * weights.get(k, 0.0) for k in component_scores.keys())
        legacy_score = round(100.0 * raw_awarded / total_weight) if total_weight > 0 else 0

        # Group component scores by cluster
        cluster_totals: dict[str, float] = {}
        feature_to_cluster: dict[str, str] = {}
        for cluster_name, features in CLUSTER_DEFINITIONS.items():
            for feat in features:
                feature_to_cluster[feat] = cluster_name

        for feat, score in component_scores.items():
            cluster = feature_to_cluster.get(feat, "uncategorized")
            weight = weights.get(feat, 1.0)
            awarded = score * weight
            cluster_totals[cluster] = cluster_totals.get(cluster, 0.0) + awarded

        # Cap each cluster's maximum contribution
        max_allowed_per_cluster = (total_weight * self.max_cluster_pct) / 100.0 if total_weight > 0 else 100.0
        adjusted_awarded = 0.0
        affected_clusters: list[str] = []
        cluster_breakdown: dict[str, float] = {}

        for cluster, total_awarded in cluster_totals.items():
            if total_awarded > max_allowed_per_cluster:
                adjusted_awarded += max_allowed_per_cluster
                affected_clusters.append(cluster)
                cluster_breakdown[cluster] = max_allowed_per_cluster
            else:
                adjusted_awarded += total_awarded
                cluster_breakdown[cluster] = total_awarded

        cluster_adjusted_score = round(100.0 * adjusted_awarded / total_weight) if total_weight > 0 else 0
        difference = cluster_adjusted_score - legacy_score

        return ClusterComparisonResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            legacy_score=max(0, min(100, legacy_score)),
            cluster_adjusted_score=max(0, min(100, cluster_adjusted_score)),
            difference=difference,
            affected_clusters=tuple(affected_clusters),
            cluster_breakdown=cluster_breakdown,
            execution_influence="ZERO",
        )

    def export_shadow_report(
        self,
        sample_results: Sequence[ClusterComparisonResult],
        output_path: str = "artifacts/canonical_foundation/cluster_shadow_report.json",
    ) -> dict[str, Any]:
        report = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "max_cluster_pct_cap": self.max_cluster_pct,
            "sample_count": len(sample_results),
            "results": [r.to_dict() for r in sample_results],
            "execution_influence": "ZERO",
        }
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w") as f:
            json.dump(report, f, indent=2)
        return report
