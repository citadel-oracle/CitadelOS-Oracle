"""Price & Spatial Geometry Predicates using PriceAtom for Eye Engine E3."""

from typing import Optional
from src.eye.contracts import PriceAtom, PointEventPayload, ZoneEventPayload, EyeEventRecord


def level_equals(p1: PriceAtom, p2: PriceAtom, tolerance_ticks: int = 0) -> bool:
    return abs(p1.ticks - p2.ticks) <= tolerance_ticks


def level_above(p1: PriceAtom, p2: PriceAtom) -> bool:
    return p1.ticks > p2.ticks


def level_below(p1: PriceAtom, p2: PriceAtom) -> bool:
    return p1.ticks < p2.ticks


def level_within_zone(p: PriceAtom, zone_lower: PriceAtom, zone_upper: PriceAtom) -> bool:
    return zone_lower.ticks <= p.ticks <= zone_upper.ticks


def zones_overlap(z1_lower: PriceAtom, z1_upper: PriceAtom, z2_lower: PriceAtom, z2_upper: PriceAtom) -> bool:
    return max(z1_lower.ticks, z2_lower.ticks) <= min(z1_upper.ticks, z2_upper.ticks)


def event_retests_level(event: EyeEventRecord, target_level: PriceAtom, tolerance_ticks: int = 5) -> bool:
    if isinstance(event.payload, PointEventPayload):
        return abs(event.payload.primary_level.ticks - target_level.ticks) <= tolerance_ticks
    elif isinstance(event.payload, ZoneEventPayload):
        return level_within_zone(target_level, event.payload.lower, event.payload.upper)
    return False
