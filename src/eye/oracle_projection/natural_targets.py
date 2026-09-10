"""Natural Structural Target Ranker for Eye Oracle Projection."""

from typing import Dict, List, Optional, Any
from src.eye.oracle_projection.contracts import EyeNaturalTarget, NaturalTargetStatus


class NaturalTargetRanker:
    """Ranks existing market structure ahead of price as natural targets."""

    def rank_targets(self, entry_price: float, direction: str, candidate_levels: List[Dict[str, Any]]) -> List[EyeNaturalTarget]:
        valid_targets = []
        direction_upper = str(direction).upper()

        for cand in candidate_levels:
            try:
                px = float(cand.get("price", 0.0))
            except (ValueError, TypeError):
                continue

            if direction_upper == "BULLISH" and px <= entry_price:
                continue
            if direction_upper == "BEARISH" and px >= entry_price:
                continue

            dist = round(abs(px - entry_price), 2)
            if dist <= 0.0:
                continue

            valid_targets.append({
                "price": px,
                "target_type": str(cand.get("target_type", "STRUCTURAL_LEVEL")),
                "distance": dist,
                "source_event_keys": [cand.get("event_key", "EVT:UNKNOWN")],
                "timeframe": str(cand.get("timeframe", "15m")),
            })

        # Sort by distance (nearest to farthest)
        valid_targets.sort(key=lambda t: t["distance"])

        ranked_targets = []
        for idx, t in enumerate(valid_targets[:3], start=1):
            ranked_targets.append(
                EyeNaturalTarget(
                    price=t["price"],
                    target_type=t["target_type"],
                    distance=t["distance"],
                    source_event_keys=t["source_event_keys"],
                    timeframe=t["timeframe"],
                    rank=idx,
                    rank_reason=f"Rank {idx} nearest structural objective ({t['target_type']})",
                )
            )

        return ranked_targets
