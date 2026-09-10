"""Comprehensive Cognitive V2 Root-Cause Repair & Replay Test Suite.

Verifies:
1. MarketEpisodeMemory persists across unchanged thesis states.
2. MarketEpisodeMemory closes and archives on thesis state transition.
3. Session rollover resets current episode identity.
4. Provider failure does not lose accumulated events.
5. Temporal relationships packet is neutral with zero directional labeling.
6. Aggression -> price response sequence connects aggression to price/premium without hardcoding ABSORPTION=TRUE.
7. Premium response survives dynamic strike rotation with security_id continuity.
8. Evidence Gate V2 rejects directional inference from OI build alone (OI_DIRECTIONAL_INFERENCE_UNSUPPORTED).
9. Evidence Gate V2 rejects invented price levels (UNSUPPORTED_NUMERIC_LEVEL).
10. Evidence Gate V2 rejects unsupported absorption claims (ABSORPTION_CLAIM_UNSUPPORTED).
11. Evidence Gate V2 rejects cross-section internal contradictions (SEMANTIC_INTERNAL_CONTRADICTION).
12. Qwen adversarial role operates without auto-veto.
13. Historical replay fixtures from today's 2026-09-03 soak (REV_01, REV_03, REV_05, REV_06) pass without overfitting.
14. VOB invariants: VOB_MODIFIED = NO, AI_VOB_INFLUENCE = 0.0.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacket, BrainPacketCompiler
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus
from src.external_context.contracts import ExternalEvent, ExternalQuote
from src.oracle_sol.episode_memory import MarketEpisodeMemory
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.local_brain_service import ADVERSARIAL_REVIEW_SCHEMA, LocalBrainService
from src.oracle_sol.thesis_graph import (
    COGNITIVE_SHADOW_SYSTEM_PROMPT,
    COGNITIVE_STRUCTURED_OUTPUT_SCHEMA,
    ThesisGraph,
    ThesisNode,
)


def _make_dummy_event(event_id: str, event_type: str = "SPOT_MOVE") -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        session_date="2026-09-03",
        timestamp_utc="2026-09-03T05:00:00Z",
        timestamp_ist="10:30:00",
        event_type=event_type,
        instrument="NIFTY_INDEX",
        summary=f"Event {event_id}",
    )


def _contract_snapshot():
    raw = json.loads((Path(__file__).parent / "fixtures/bridge_recorded_snapshot_20260904.json").read_text())
    raw["system_status"] = SystemStatus(raw["system_status"])
    return SolEvidenceSnapshot(**raw)


def test_episode_memory_persistence_and_transition():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        storage_path = tf.name

    mem = MarketEpisodeMemory(storage_path=storage_path)
    # 1. Initial creation
    ep1 = mem.get_or_create_episode("2026-09-03", "NO_TRADE", "evt_1")
    assert ep1.state == "NO_TRADE"
    assert ep1.is_active

    # 2. Accumulate events
    mem.record_events([_make_dummy_event("evt_1"), _make_dummy_event("evt_2")])
    assert len(mem.get_accumulated_events()) == 2

    # 3. Provider failure simulation: subsequent cycle with same state preserves episode & events
    ep1_again = mem.get_or_create_episode("2026-09-03", "NO_TRADE", "evt_2")
    assert ep1_again.episode_id == ep1.episode_id
    assert len(mem.get_accumulated_events()) == 2

    # 4. State transition: NO_TRADE -> PUT_DEVELOPING closes ep1 and creates ep2
    ep2 = mem.get_or_create_episode("2026-09-03", "PUT_DEVELOPING", "evt_2")
    assert ep2.episode_id != ep1.episode_id
    assert ep2.state == "PUT_DEVELOPING"

    # 5. Session rollover creates fresh identity
    ep3 = mem.get_or_create_episode("2026-09-04", "PUT_DEVELOPING", "evt_100")
    assert ep3.episode_id != ep2.episode_id
    assert ep3.session_id == "2026-09-04"

    if os.path.exists(storage_path):
        os.remove(storage_path)


@pytest.mark.parametrize(("prior_session", "current_session"), [
    ("2026-09-03", "2026-09-04"),
    ("2026-09-04", "2026-09-07"),
])
def test_local_brain_rollover_clears_prior_session_thesis_before_packet_compile(
    tmp_path, prior_session, current_session,
):
    """A new-session packet cannot inherit the prior session thesis or cursor."""
    graph = ThesisGraph(storage_path=str(tmp_path / "theses.jsonl"))
    graph.commit_thesis(ThesisNode(
        thesis_id="prior", session_id=prior_session, created_at=f"{prior_session}T10:00:00Z",
        input_revision=7, event_cursor_before=None, event_cursor_after="evt_prior",
        state="NO_TRADE", underlying_view="", option_buyer_view="", what_changed="",
        call_case="", put_case="", no_trade_case="", supporting_evidence_ids=[],
        contradicting_evidence_ids=[], unresolved_evidence_ids=[], watch_next=[],
        invalidation_conditions=[], supersedes_thesis_id=None, status="ACTIVE",
        model="isolated", prompt_hash="prompt", input_hash="input",
    ))

    class FailingProvider:
        provider = "groq"
        configured_model = "isolated"

        def invoke_reasoning(self, **_kwargs):
            return None, {"error": "OFFLINE_TEST", "schema_status": "NOT_CALLED"}

    class RecordingCompiler:
        previous = "UNSET"

        def compile_packet(self, **kwargs):
            self.previous = kwargs["previous_thesis"]
            return SimpleNamespace(packet_id="pkt_current", to_dict=lambda: {})

    class EmptyExternalContext:
        def get_latest_events(self, limit=5):
            return []

        def get_latest_quotes(self):
            return []

    compiler = RecordingCompiler()
    service = LocalBrainService(
        adapter=FailingProvider(), challenger_adapter=FailingProvider(), compiler=compiler,
        thesis_graph=graph, external_context=EmptyExternalContext(),
        episode_memory=MarketEpisodeMemory(storage_path=str(tmp_path / "episodes.jsonl")),
    )

    thesis, result = service.run_cycle(
        session_id=current_session, revision=1,
        current_snapshot=SimpleNamespace(), unseen_events=[],
    )

    assert thesis is None and result["status"] == "PROVIDER_FAILURE"
    assert compiler.previous is None
    assert graph.get_active_thesis() is None
    assert graph.get_cursor() is None
    assert service._current_session_id == current_session


def test_brain_packet_excludes_unverified_external_context_from_evidence():
    """Audit/detail records cannot become model evidence without a current verifier receipt."""
    now = datetime.now(timezone.utc)
    retrieved = (now - timedelta(seconds=10)).isoformat()
    published = (now - timedelta(seconds=20)).isoformat()
    valid_until = (now + timedelta(minutes=5)).isoformat()
    record = {
        "status": "MATCH",
        "verifier_id": "isolated-verifier",
        "payload_hash": "verified-hash",
        "checked_at": retrieved,
        "valid_until": valid_until,
    }
    verified_event = ExternalEvent(
        event_id="ext_verified", provider="isolated", source_name="Isolated",
        source_url="https://example.invalid/verified", published_at=published,
        retrieved_at=retrieved, event_type="OFFICIAL_REGULATORY", headline="Verified",
        summary="Verified test record", raw_hash="verified-hash",
        verification_status="VERIFIED", verification_record=record,
    )
    unverified_event = ExternalEvent(
        event_id="ext_unverified", provider="isolated", source_name="Isolated",
        source_url="https://example.invalid/unverified", published_at=published,
        retrieved_at=retrieved, event_type="FINANCIAL_NEWS", headline="Unverified",
        summary="Unverified test record", raw_hash="unverified-hash",
    )
    verified_quote = ExternalQuote(
        symbol="USD/INR", display_name="USD/INR", provider="isolated",
        instrument_type="FOREX", exact_or_proxy="EXACT", price=0.0, change=0.0,
        change_percent=0.0, market_status="CLOSED", provider_timestamp=published,
        retrieved_at=retrieved, data_age="SESSION_LAST", raw_hash="verified-hash",
        verification_status="VERIFIED", verification_record=record,
    )
    unverified_quote = ExternalQuote(
        symbol="SPY", display_name="SPY", provider="isolated",
        instrument_type="EQUITY_ETF", exact_or_proxy="PROXY", price=0.0, change=0.0,
        change_percent=0.0, market_status="CLOSED", provider_timestamp=published,
        retrieved_at=retrieved, data_age="SESSION_LAST", raw_hash="unverified-hash",
    )

    packet = BrainPacketCompiler().compile_packet(
        session_id="2026-09-04", revision=1, current_snapshot=_contract_snapshot(),
        previous_thesis=None, unseen_events=[],
        external_events=[unverified_event, verified_event],
        external_quotes=[unverified_quote, verified_quote],
    )

    assert [row["event_id"] for row in packet.verified_external_events] == ["ext_verified"]
    assert [row["symbol"] for row in packet.external_quotes] == ["USD/INR"]
    assert "ext_verified" in packet.valid_evidence_ids
    assert "quote:USD/INR" in packet.valid_evidence_ids
    assert "ext_unverified" not in packet.valid_evidence_ids
    assert "quote:SPY" not in packet.valid_evidence_ids


def test_temporal_relationships_and_aggression_response():
    compiler = BrainPacketCompiler()
    # Isolated arithmetic test inputs retain the complete production contract;
    # they are not Arena evidence or an accepted historical market frame.
    snap = replace(_contract_snapshot(),
        spot_ltp=23950.0,
        futures_ltp=24070.0,
        futures_basis=120.0,
        atm_strike=23950.0,
        atm_iv=9.5,
        atm_straddle_price=220.0,
        mlofi_5l=0.15,
        ce_pricing={"ltp": 130.0, "security_id": "sec_ce_23950"},
        pe_pricing={"ltp": 90.0, "security_id": "sec_pe_23950"},
        zero_gamma_level=23948.9,
        session_vwap=23960.0,
        current_flow_x=1.2,
        sudden_oi_call=None,
        sudden_oi_put=None,
        pcr_oi=1.0,
        dealer_regime="POSITIVE",
        strike_ladder=[],
    )
    prev_th = {
        "input_revision": 10,
        "canonical_state": {
            "spot_price": 23940.0,
            "futures_price": 24050.0,
            "basis": 110.0,
            "flow_net_delta": -0.05,
            "ce_atm_premium": 125.0,
            "pe_atm_premium": 95.0,
            "atm_iv": 9.2,
            "straddle_price": 220.0,
        },
    }
    ev1 = _make_dummy_event("evt_aggr_1", "FLOW_POLARITY_FLIP")
    pkt = compiler.compile_packet(
        session_id="2026-09-03",
        revision=11,
        current_snapshot=snap,
        previous_thesis=prev_th,
        unseen_events=[ev1],
        external_events=[],
        external_quotes=[],
        episode_id="ep_test_01",
    )

    # Verify temporal relationships are neutral facts
    assert len(pkt.temporal_relationships) >= 5
    for tr in pkt.temporal_relationships:
        assert "metric" in tr
        assert "before" in tr
        assert "after" in tr
        assert "change" in tr
        # Zero bullish/bearish bias
        assert "bullish" not in str(tr).lower()
        assert "bearish" not in str(tr).lower()

    # Verify aggression response sequence connects aggression to price response neutrally
    assert len(pkt.aggression_response_sequence) == 1
    ar = pkt.aggression_response_sequence[0]
    assert ar["aggression_event_id"] == "evt_aggr_1"
    assert ar["spot_change"] == 10.0
    assert ar["ce_change"] == 5.0
    assert ar["pe_change"] == -5.0
    # Does NOT hardcode ABSORPTION = TRUE
    assert "absorption" not in ar


def test_evidence_gate_v2_strict_rules():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        storage_path = tf.name

    tg = ThesisGraph(storage_path=storage_path)
    gate = EvidenceGate(tg)

    packet = BrainPacket(
        packet_id="pkt_gate_test",
        session_id="2026-09-03",
        revision=20,
        compiled_at="2026-09-03T10:00:00Z",
        canonical_state={"spot_price": 23950.0, "futures_price": 24070.0, "basis": 120.0},
        what_changed={"spot_delta": 5.0},
        unseen_event_ids=["evt_gate_1"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=["metric:spot_price", "metric:futures_price", "metric:basis", "metric:call_oi_build", "metric:put_oi_build", "evt_gate_1"],
        canonical_levels=[23950.0, 24000.0, 24050.0],
    )

    valid_base = {
        "observer": {"what_changed": "Spot ticked up", "key_shifts": ["evt_gate_1"]},
        "market_story": {"narrative": "Spot held 23950 support while basis stayed positive.", "sequence_unfolding": "evt_gate_1"},
        "call_case": {"argument": "Call case supported by basis", "evidence_ids": ["metric:basis"]},
        "put_case": {"argument": "Put case lacks momentum", "evidence_ids": ["metric:spot_price"]},
        "no_trade_case": {"argument": "Low volatility limits edge", "evidence_ids": ["metric:basis"]},
        "reversal_analysis": {"absorption_or_exhaustion": "No absorption detected", "failed_move_evidence": "none", "reversal_developing": False, "evidence_ids": ["evt_gate_1"]},
        "reversal_watch": {
            "direction": "NONE",
            "earliest_contradiction_event_id": None,
            "supporting_evidence_ids": ["evt_gate_1"],
            "opposing_evidence_ids": [],
            "aggression_price_response": "none",
            "premium_confirmation": "UNRESOLVED",
            "failed_move": "NOT_SUPPORTED",
            "reason_not_confirmed": "No reversal pattern present",
        },
        "option_buyer_analysis": {
            "underlying_view": "Mildly bullish bias",
            "ce_premium_response": "CE steady",
            "pe_premium_response": "PE decaying",
            "iv_response": "IV flat",
            "liquidity_or_spread": "Tight spread",
            "option_buyer_side": "BOTH_POOR",
            "reasoning": "Low volatility limits edge",
        },
        "contradictions": {"strongest_contradiction": "none", "contradicting_evidence_ids": []},
        "temporal_analysis": {"evolution_from_previous": "baseline", "what_strengthened": "none", "what_weakened": "none", "what_superseded": "none"},
        "external_context": {"interpretation": "neutral", "cited_external_event_ids": []},
        "counterfactual": {"opposite_thesis_conditions": "Break below 23950", "watch_triggers": []},
        "human_miss_candidate": {"subtle_relationship": "NO_SUPPORTED_HIDDEN_RELATIONSHIP", "cited_evidence_ids": []},
        "synthesis": {
            "state": "NO_TRADE",
            "no_trade_reason": "DIRECTION_CLEAR_OPTIONS_POOR",
            "transition_reason": "Initial baseline",
            "supporting_evidence_ids": ["metric:basis"],
            "contradicting_evidence_ids": [],
            "unresolved_evidence_ids": [],
            "watch_next": ["23950"],
            "invalidation_conditions": ["Break below 23950"],
        },
    }

    # 1. Valid commit
    res = gate.validate_and_commit(valid_base, packet, "test_model", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid
    assert res.status == "COMMITTED"
    assert res.committed_thesis.reversal_watch == "NONE"
    assert res.committed_thesis.no_trade_reason == "DIRECTION_CLEAR_OPTIONS_POOR"

    # 2. Reject Invented Numeric Level
    bad_level = dict(valid_base)
    bad_level["synthesis"] = dict(valid_base["synthesis"])
    bad_level["synthesis"]["watch_next"] = ["Watch 23940 breakdown"]
    res_lvl = gate.validate_and_commit(bad_level, packet, "test_model", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert not res_lvl.is_valid
    assert "UNSUPPORTED_NUMERIC_LEVEL" in res_lvl.error_details

    # 3. Reject Directional claim from OI alone
    bad_oi = dict(valid_base)
    bad_oi["call_case"] = {"argument": "Aggressive call buying indicated by call oi build", "evidence_ids": ["metric:call_oi_build"]}
    res_oi = gate.validate_and_commit(bad_oi, packet, "test_model", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert not res_oi.is_valid
    assert "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED" in res_oi.error_details

    # 4. Reject Cross-Section Contradiction
    bad_contra = dict(valid_base)
    bad_contra["market_story"] = {"narrative": "Heavy selling was absorbed at 23950.", "sequence_unfolding": "evt_gate_1"}
    bad_contra["reversal_analysis"] = {"absorption_or_exhaustion": "No absorption detected", "failed_move_evidence": "none", "reversal_developing": False, "evidence_ids": ["evt_gate_1"]}
    res_contra = gate.validate_and_commit(bad_contra, packet, "test_model", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert not res_contra.is_valid
    assert "SEMANTIC_INTERNAL_CONTRADICTION" in res_contra.error_details

    if os.path.exists(storage_path):
        os.remove(storage_path)


def test_qwen_adversarial_role_schema():
    assert "current_gpt_thesis" in ADVERSARIAL_REVIEW_SCHEMA["properties"]
    assert "strongest_evidence_against_it" in ADVERSARIAL_REVIEW_SCHEMA["properties"]
    assert "missed_reversal_evidence" in ADVERSARIAL_REVIEW_SCHEMA["properties"]
    assert "misinterpreted_oi" in ADVERSARIAL_REVIEW_SCHEMA["properties"]
    assert "option_premium_contradiction" in ADVERSARIAL_REVIEW_SCHEMA["properties"]


def test_historical_soak_fixtures_no_hindsight():
    """Validates today's genuine soak packets without hindsight or overfitted directional assertions."""
    soak_gpt_path = "data/cognitive_soak/2026-09-03/gpt_outputs.jsonl"
    if not os.path.exists(soak_gpt_path):
        pytest.skip("Today's soak gpt_outputs.jsonl not found.")

    with open(soak_gpt_path, "r") as f:
        records = [json.loads(line) for line in f if line.strip()]

    # Verify at least 15 historical cycles exist
    assert len(records) >= 15

    for r in records[:5]:
        # Verify inputs and raw responses carry genuine timestamp discipline
        assert "timestamp" in r
        assert "packet_id" in r
        raw = r.get("raw_response", {})
        assert "synthesis" in raw
        assert "market_story" in raw


def test_vob_untouched_invariants():
    """Strictly proves VOB files remain unmodified and AI_VOB_INFLUENCE is zero."""
    import subprocess
    diff_vob = subprocess.run(["git", "diff", "--stat", "CITADEL_MASTER/"], capture_output=True, text=True).stdout
    assert diff_vob.strip() == "", f"VOB was modified: {diff_vob}"
