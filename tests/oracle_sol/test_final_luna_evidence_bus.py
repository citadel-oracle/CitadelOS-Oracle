"""Test suite for Final Luna Evidence Bus, Semantic Metadata, and SESSION LAST projection."""

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from src.oracle_sol.brain_packet_compiler import (
    CANONICAL_SEMANTIC_METADATA,
    BrainPacket,
    BrainPacketCompiler,
)
from src.oracle_sol.cognitive_projection import project_cognitive_decision
from src.oracle_sol.contracts import SolEvidenceSnapshot
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.privacy_sanitizer import (
    ALLOWED_SUPPORTING_KEYS,
    PrivacyViolationError,
    sanitize_brain_packet,
    sanitize_event,
)
from src.oracle_sol.thesis_graph import ThesisGraph, ThesisNode


def test_buildup_heuristic_limitations_no_writer_causality():
    """Verify buildup labels have explicit heuristic limitations and disclaim writer causality."""
    buildup_meta = CANONICAL_SEMANTIC_METADATA.get("buildup")
    assert buildup_meta is not None
    assert "Heuristic classification" in buildup_meta["limitations"]
    assert "Does NOT claim proof of participant identity or writer causality" in buildup_meta["limitations"]

    closed_meta = CANONICAL_SEMANTIC_METADATA.get("closed_oi_buildup")
    assert closed_meta is not None
    assert "no writer causality" in closed_meta["limitations"]


def test_strike_spine_kinematics_metadata():
    """Verify Strike Spine kinematics (velocity, acceleration, concentration) are documented with units."""
    vel = CANONICAL_SEMANTIC_METADATA.get("oi_velocity")
    assert vel is not None
    assert vel["unit"] == "OI_PER_MINUTE"
    assert vel["producer"] == "ARGUS_PRIME_KINEMATICS"

    acc = CANONICAL_SEMANTIC_METADATA.get("oi_acceleration")
    assert acc is not None
    assert acc["unit"] == "OI_PER_MINUTE_SQUARED"
    assert acc["producer"] == "ARGUS_PRIME_KINEMATICS"

    conc = CANONICAL_SEMANTIC_METADATA.get("oi_concentration")
    assert conc is not None
    assert conc["unit"] == "RATIO_0_TO_1"
    assert conc["producer"] == "ARGUS_PRIME_KINEMATICS"


def test_max_pain_and_india_vix_truth_audits():
    """Verify Max Pain is excluded/non-canonical and India VIX is marked unavailable."""
    mp = CANONICAL_SEMANTIC_METADATA.get("max_pain")
    assert mp is not None
    assert "MAX_PAIN_NOT_CURRENTLY_CANONICAL" in mp["limitations"]
    assert "Excluded from canonical packet" in mp["limitations"]

    vix = CANONICAL_SEMANTIC_METADATA.get("india_vix")
    assert vix is not None
    assert "INDIA_VIX_UNAVAILABLE" in vix["limitations"]
    assert "Excluded from live packet" in vix["limitations"]


def test_gex_and_pcr_semantic_metadata():
    """Verify canonical PCR and GEX context are registered with proper semantics."""
    pcr = CANONICAL_SEMANTIC_METADATA.get("pcr_oi")
    assert pcr is not None
    assert pcr["semantic_scope"] == "OPTION_POSITIONING_RATIO"

    gex = CANONICAL_SEMANTIC_METADATA.get("total_net_gex_inr_cr")
    assert gex is not None
    assert gex["unit"] == "INR_CRORES"
    assert "Market maker aggregate gamma exposure" in gex["limitations"]

    dealer = CANONICAL_SEMANTIC_METADATA.get("dealer_regime")
    assert dealer is not None
    assert dealer["semantic_scope"] == "DEALER_GAMMA_REGIME"

    zg = CANONICAL_SEMANTIC_METADATA.get("zero_gamma")
    assert zg is not None
    assert zg["semantic_scope"] == "ZERO_GAMMA_PIVOT"


def test_privacy_sanitizer_allows_evidence_bus_keys():
    """Verify privacy sanitizer allows new evidence bus keys in supporting_values."""
    expected_keys = [
        "oi_velocity",
        "oi_acceleration",
        "oi_concentration",
        "total_net_gex_inr_cr",
        "dealer_regime",
        "zero_gamma_level",
        "pcr_oi",
        "buildup",
        "oi_buildup",
    ]
    for key in expected_keys:
        assert key in ALLOWED_SUPPORTING_KEYS, f"Key {key} missing from ALLOWED_SUPPORTING_KEYS"

    raw_event = {
        "event_id": "evt_test_kinematics_1",
        "event_type": "CLOSED_OI_BUILDUP",
        "instrument": "NIFTY_OPTIONS",
        "strike": 23650.0,
        "expiry": "2026-09-10",
        "supporting_values": {
            "oi_velocity": 1420.5,
            "oi_acceleration": 45.2,
            "oi_concentration": 0.38,
            "total_net_gex_inr_cr": 412.5,
            "dealer_regime": "LONG_GAMMA_PIN",
            "zero_gamma_level": 23600.0,
            "pcr_oi": 0.88,
            "buildup": "SHORT_COVERING",
        },
    }

    sanitized = sanitize_event(raw_event)
    sup = sanitized["supporting_values"]
    assert sup["oi_velocity"] == 1420.5
    assert sup["oi_acceleration"] == 45.2
    assert sup["oi_concentration"] == 0.38
    assert sup["total_net_gex_inr_cr"] == 412.5
    assert sup["dealer_regime"] == "LONG_GAMMA_PIN"
    assert sup["zero_gamma_level"] == 23600.0
    assert sup["pcr_oi"] == 0.88
    assert sup["buildup"] == "SHORT_COVERING"


def test_session_last_cutoff_4_projection():
    """Verify Cutoff 4 is projected as SESSION_LAST and revalidates as VALID."""
    graph = ThesisGraph(storage_path="data/oracle_sol/thesis_graph.jsonl")
    active = graph._nodes.get("thesis_2026-09-08_4_cutoff4_luna") or graph.get_active_thesis()
    assert active is not None
    assert active.state == "CALL_DEVELOPING"
    assert active.model == "gpt-5.6-luna"

    # Retained validation passes
    val = EvidenceGate.revalidate_retained(active.to_dict())
    assert val.is_valid is True
    assert val.status == "VALID"

    with open("data/oracle_sol/live_cognitive_status.json", "r", encoding="utf-8") as f:
        live_status = json.load(f)

    # Off-market projection
    proj = project_cognitive_decision(
        active=active,
        previous=None,
        live_status=live_status,
        snapshot={"market_session_date": "2026-09-08", "system_status": "MARKET_CLOSED"},
    )

    assert proj["gpt"]["status"] == "SESSION_LAST"
    assert proj["gpt"]["model_id"] == "gpt-5.6-luna"
    assert proj["market_status"] in ("MARKET_CLOSED", "SESSION_LAST")
    assert proj["primary_decision"]["state"] == "CALL_DEVELOPING"
    assert proj["primary_decision"]["thesis_evolution"] == "STRENGTHENING"
    assert proj["primary_decision"]["opportunity_maturity"] == "EMERGING"
    assert proj["retained_validation"]["status"] == "VALID"
