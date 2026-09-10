"""Tests for Eye Engine Core Contracts, Immutability, Payloads, and Authority."""

import pytest
from datetime import datetime, timezone

from src.eye.contracts import (
    EyeContractError,
    EyeEventRecord,
    InstrumentIdentity,
    EvaluationContext,
    BarReference,
    PriceAtom,
    PointEventPayload,
    ZoneEventPayload,
    StateEventPayload,
    RelationshipEventPayload,
    EyeEvidence,
    ProducerProvenance,
    FreshnessSnapshot,
    ProbabilityAssessment,
    AuthorityType,
    ProbabilityStatus,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
    PayloadKind,
)


def test_immutability_and_strictness():
    atom = PriceAtom(ticks=2450000, quantum="0.01")
    with pytest.raises((TypeError, AttributeError)):
        atom.ticks = 2460000  # type: ignore

    inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
    )
    with pytest.raises((TypeError, AttributeError)):
        inst.normalized_symbol = "BANKNIFTY"  # type: ignore


def test_instrument_identity_validation():
    # Underlying index must NOT carry option strike/expiry/type
    with pytest.raises(EyeContractError, match="Underlying index must not carry option fields"):
        InstrumentIdentity(
            raw_symbol="NSE:NIFTY",
            normalized_symbol="NIFTY",
            exchange="NSE",
            instrument_type="UNDERLYING_INDEX",
            underlying="NIFTY",
            source="DHAN",
            market="NSE",
            strike=24500.0,  # Invalid for underlying index!
        )

    # Exact option MUST carry underlying, expiry, strike, option_type
    with pytest.raises(EyeContractError, match="Exact option requires complete option identity"):
        InstrumentIdentity(
            raw_symbol="NSE:NIFTY260811C24500",
            normalized_symbol="NIFTY260811C24500",
            exchange="NSE",
            instrument_type="EXACT_OPTION",
            underlying="NIFTY",
            source="DHAN",
            market="NSE",
            # Missing strike, expiry, option_type!
        )

    # Valid exact option
    option_inst = InstrumentIdentity(
        raw_symbol="NSE:NIFTY260811C24500",
        normalized_symbol="NIFTY260811C24500",
        exchange="NSE",
        instrument_type="EXACT_OPTION",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
        expiry="2026-08-11",
        strike=24500.0,
        option_type="CALL",
        security_id="41016",
    )
    assert option_inst.instrument_key == "EXACT_OPTION:NIFTY:2026-08-11:24500.0:CALL"


def test_payload_variants():
    # Point Event Payload
    point = PointEventPayload(
        primary_level=PriceAtom(ticks=2450000, quantum="0.01"),
        direction=EventDirection.BULLISH,
    )
    assert point.payload_kind == PayloadKind.POINT

    # Zone Event Payload
    zone = ZoneEventPayload(
        lower=PriceAtom(ticks=2440000, quantum="0.01"),
        upper=PriceAtom(ticks=2450000, quantum="0.01"),
        zone_role="SUPPORT",
    )
    assert zone.payload_kind == PayloadKind.ZONE
    assert zone.midpoint.ticks == 2445000

    # Zone lower bound cannot exceed upper bound
    with pytest.raises(EyeContractError, match="Zone lower bound cannot exceed upper bound"):
        ZoneEventPayload(
            lower=PriceAtom(ticks=2460000, quantum="0.01"),
            upper=PriceAtom(ticks=2450000, quantum="0.01"),
            zone_role="RESISTANCE",
        )


def test_probability_and_authority():
    # Default probability status is NOT_ESTABLISHED
    prob = ProbabilityAssessment()
    assert prob.status == ProbabilityStatus.NOT_ESTABLISHED
    assert prob.probability is None

    # Numeric probability forbidden when status is NOT_ESTABLISHED
    with pytest.raises(EyeContractError, match="Numeric probability requires ESTABLISHED status"):
        ProbabilityAssessment(
            status=ProbabilityStatus.NOT_ESTABLISHED,
            probability=0.75,
        )

    # Authority must be OBSERVATION_ONLY in E1
    prov = ProducerProvenance(
        engine_name="StructureEngineV2",
        source_file="src/structure/structure_engine_v2.py",
        source_symbol="StructureEngineV2.analyze",
        source_commit="8632791",
        producer_version="1.0.0",
        rule_id="BOS_CLOSE_BREAK_V1",
        rule_version="1.0.0",
    )
    assert prov.authority == AuthorityType.OBSERVATION_ONLY
