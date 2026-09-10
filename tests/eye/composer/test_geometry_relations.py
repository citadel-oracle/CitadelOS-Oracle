"""E3 Price & Spatial Geometry Predicates Test Suite."""

import pytest
from src.eye.contracts import PriceAtom
from src.eye.composer.relations import level_equals, level_above, level_below, level_within_zone, zones_overlap


def test_price_atom_geometry_relations():
    p24500 = PriceAtom(ticks=2450000)
    p24505 = PriceAtom(ticks=2450500)
    p24600 = PriceAtom(ticks=2460000)

    assert level_equals(p24500, p24505, tolerance_ticks=500) is True
    assert level_above(p24600, p24500) is True
    assert level_below(p24500, p24600) is True
    assert level_within_zone(p24505, p24500, p24600) is True
    assert zones_overlap(p24500, p24505, p24505, p24600) is True
