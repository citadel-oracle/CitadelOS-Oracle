"""Tests for PriceAtom, Canonical Serialization, and Deterministic SHA-256 Hashing."""

import pytest
import math
from src.eye.contracts import PriceAtom, EyeContractError
from src.eye.serialization import canonical_json, compute_sha256


def test_price_atom_strictness():
    # Int ticks + quantum string
    atom = PriceAtom(ticks=2450000, quantum="0.01")
    assert atom.value == 24500.0

    # Float ticks rejected!
    with pytest.raises(EyeContractError, match="ticks must be an integer"):
        PriceAtom(ticks=24500.0, quantum="0.01")  # type: ignore

    # NaN / Infinity quantum or value rejected
    with pytest.raises(EyeContractError, match="Invalid quantum"):
        PriceAtom(ticks=2450000, quantum="NaN")

    with pytest.raises(EyeContractError, match="Invalid quantum"):
        PriceAtom(ticks=2450000, quantum="Infinity")


def test_canonical_serialization_determinism():
    data = {
        "z_key": "value2",
        "a_key": "value1",
        "items": [3, 2, 1],
        "sub": {"b": 2, "a": 1},
    }

    s1 = canonical_json(data)
    s2 = canonical_json(data)
    assert s1 == s2
    assert s1 == '{"a_key":"value1","items":[3,2,1],"sub":{"a":1,"b":2},"z_key":"value2"}'

    h1 = compute_sha256(data)
    h2 = compute_sha256(data)
    assert h1 == h2
    assert len(h1) == 64
