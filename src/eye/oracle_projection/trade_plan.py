"""Trade Plan Builder for Eye Oracle Projection."""

from typing import Dict, List, Optional, Any
from src.eye.oracle_projection.contracts import (
    EyeTradePlan, TradePlanStatus, EyeEntryGeometry, EyeStructuralStop, EyeNaturalTarget,
    EntryGeometryStatus, StructuralStopStatus
)
from src.eye.oracle_projection.entry_geometry import EntryGeometryBuilder
from src.eye.oracle_projection.structural_stop import StructuralStopBuilder
from src.eye.oracle_projection.natural_targets import NaturalTargetRanker


class TradePlanBuilder:
    """Combines entry geometry, structural stop, and natural targets to derive R:R."""

    def build_trade_plan(
        self,
        entry_raw: Optional[Any],
        stop_raw: Optional[Any],
        targets_raw: List[Any],
    ) -> EyeTradePlan:
        entry_builder = EntryGeometryBuilder()
        stop_builder = StructuralStopBuilder()

        if isinstance(entry_raw, EyeEntryGeometry):
            entry_geom = entry_raw
        elif isinstance(entry_raw, dict) and "entry_status" in entry_raw:
            entry_geom = EyeEntryGeometry(
                entry_low=entry_raw.get("entry_low"),
                entry_high=entry_raw.get("entry_high"),
                entry_reference=entry_raw.get("entry_reference"),
                entry_geometry_type=entry_raw.get("entry_geometry_type", "NONE"),
                entry_status=entry_raw["entry_status"] if isinstance(entry_raw["entry_status"], EntryGeometryStatus) else EntryGeometryStatus(entry_raw["entry_status"]),
                source_event_keys=entry_raw.get("source_event_keys", []),
                is_confirmed=entry_raw.get("is_confirmed", True),
            )
        else:
            entry_geom = entry_builder.build_entry_geometry(entry_raw)

        if isinstance(stop_raw, EyeStructuralStop):
            stop_obj = stop_raw
        elif isinstance(stop_raw, dict) and "status" in stop_raw:
            stop_obj = EyeStructuralStop(
                sl_price=stop_raw.get("sl_price"),
                sl_type=stop_raw.get("sl_type", "NONE"),
                structural_reference=stop_raw.get("structural_reference", "NONE"),
                source_event_key=stop_raw.get("source_event_key"),
                reason=stop_raw.get("reason", ""),
                distance_from_entry=stop_raw.get("distance_from_entry"),
                status=stop_raw["status"] if isinstance(stop_raw["status"], StructuralStopStatus) else StructuralStopStatus(stop_raw["status"]),
                is_confirmed=stop_raw.get("is_confirmed", True),
            )
        else:
            stop_obj = stop_builder.build_structural_stop(stop_raw)

        targets = []
        for idx, t in enumerate(targets_raw, start=1):
            if isinstance(t, EyeNaturalTarget):
                targets.append(t)
            elif isinstance(t, dict):
                targets.append(
                    EyeNaturalTarget(
                        price=float(t["price"]),
                        target_type=str(t.get("target_type", "STRUCTURAL_LEVEL")),
                        distance=float(t.get("distance", 0.0)),
                        source_event_keys=t.get("source_event_keys", []),
                        timeframe=str(t.get("timeframe", "15m")),
                        rank=t.get("rank", idx),
                        rank_reason=str(t.get("rank_reason", f"Rank {idx}")),
                    )
                )

        ref_entry = entry_geom.entry_reference
        sl_price = stop_obj.sl_price

        if (
            entry_geom.entry_status != EntryGeometryStatus.ACTIVE
            or stop_obj.status != StructuralStopStatus.ACTIVE
            or ref_entry is None
            or sl_price is None
        ):
            return EyeTradePlan(
                entry_geometry=entry_geom,
                structural_stop=stop_obj,
                natural_targets=targets,
                risk_points=None,
                reward_to_t1=None,
                reward_to_t2=None,
                reward_to_t3=None,
                rr_mid=None,
                rr_conservative=None,
                status=TradePlanStatus.RR_NOT_ESTABLISHED,
            )

        # Detect direction from entry vs SL if possible, or target orientation
        is_bullish = sl_price < ref_entry

        # Filter valid profit-side targets, excluding entry and SL
        valid_targets = []
        seen_prices = set()
        for t in targets:
            px = t.price
            if px == ref_entry or px == sl_price or px in seen_prices:
                continue
            if is_bullish and px > ref_entry:
                valid_targets.append(t)
                seen_prices.add(px)
            elif not is_bullish and px < ref_entry:
                valid_targets.append(t)
                seen_prices.add(px)

        # Sort targets monotonically away from entry towards profit
        if is_bullish:
            valid_targets.sort(key=lambda x: x.price)
        else:
            valid_targets.sort(key=lambda x: x.price, reverse=True)

        # Re-assign ranks
        targets = [
            EyeNaturalTarget(
                price=t.price,
                target_type=t.target_type,
                distance=round(abs(t.price - ref_entry), 2),
                source_event_keys=t.source_event_keys,
                timeframe=t.timeframe,
                rank=idx,
                rank_reason=f"Rank {idx} nearest structural objective ({t.target_type})",
            )
            for idx, t in enumerate(valid_targets[:3], start=1)
        ]

        risk_pts = round(abs(ref_entry - sl_price), 2)

        if not targets or risk_pts <= 0:
            return EyeTradePlan(
                entry_geometry=entry_geom,
                structural_stop=stop_obj,
                natural_targets=targets,
                risk_points=None,
                reward_to_t1=None,
                reward_to_t2=None,
                reward_to_t3=None,
                rr_mid=None,
                rr_conservative=None,
                status=TradePlanStatus.RR_NOT_ESTABLISHED,
            )

        reward_t1 = round(abs(targets[0].price - ref_entry), 2) if len(targets) >= 1 else None
        reward_t2 = round(abs(targets[1].price - ref_entry), 2) if len(targets) >= 2 else None
        reward_t3 = round(abs(targets[2].price - ref_entry), 2) if len(targets) >= 3 else None

        rr_mid = round(reward_t1 / risk_pts, 2) if reward_t1 is not None else None

        # Conservative entry edge risk/reward
        entry_edge = entry_geom.entry_high if ref_entry > sl_price else entry_geom.entry_low
        cons_risk = round(abs(entry_edge - sl_price), 2) if entry_edge else risk_pts
        cons_reward = round(abs(targets[0].price - entry_edge), 2) if entry_edge and len(targets) >= 1 else None
        rr_cons = round(cons_reward / cons_risk, 3) if cons_reward and cons_risk > 0 else rr_mid

        return EyeTradePlan(
            entry_geometry=entry_geom,
            structural_stop=stop_obj,
            natural_targets=targets,
            risk_points=risk_pts,
            reward_to_t1=reward_t1,
            reward_to_t2=reward_t2,
            reward_to_t3=reward_t3,
            rr_mid=rr_mid,
            rr_conservative=rr_cons,
            status=TradePlanStatus.ACTIVE,
        )
