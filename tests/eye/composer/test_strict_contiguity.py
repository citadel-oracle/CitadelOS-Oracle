"""E3 Contiguity Semantics Test Suite."""

import pytest
from src.eye.composer.contracts import ContiguityPolicy


def test_contiguity_policy_enum_values():
    assert ContiguityPolicy.STRICT_NEXT.value == "STRICT_NEXT"
    assert ContiguityPolicy.RELAXED_NEXT.value == "RELAXED_NEXT"
    assert ContiguityPolicy.ANY_FOLLOWING.value == "ANY_FOLLOWING"
