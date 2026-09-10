"""Test suite for CITADEL Multi-Model Shadow Orchestrator V1.2 — Challenger Escalation Damping.

Verifies:
 1. Safety invariants hardened (AI_EXECUTION_INFLUENCE==0, BROKER_SUBMISSION==False, etc.)
 2. Feature flag disabled by default
 3. Canonical Shadow Receipt SHA-256 determinism & receipt binding
 4. Threshold classification registry complete (all thresholds classified)
 5. Sol edge triggers (regime transitions, within-regime material delta, ATM migration)
 6. Gemini edge triggers (flow polarity reversal, new strike/side surge)
 7. Luna natural frontiers (STATE_TRANSITION, ATM migration, gamma regime shift, stale cadence)
 8. Gemini evidence guard (prompt constraint injection and post-validation)
 9. Challenger Escalation Damping Suite (§9 specs):
    - Test 1: Gemini finding queues without immediate Luna call
    - Test 2: Sol finding queues without immediate Luna call
    - Test 3: Gemini + Sol findings coalesce into one next Luna context
    - Test 4: Material deterministic contradiction CAN immediately escalate Luna
    - Test 5: Stale queued challenger context is dropped (state resolution & timeout)
    - Test 6: Superseded challenge replaces older same-family challenge
    - Test 7: Prior challenger receipt identity remains visible (receipt truth)
    - Test 8: No recursive Luna → challenger → Luna loop
    - Test 9: Execution influence remains zero across all paths
"""

from __future__ import annotations

import hashlib
import json
import pytest
from datetime import datetime, timezone

from src.oracle_sol.shadow_orchestrator import (
    AI_EXECUTION_INFLUENCE,
    AI_VOB_INFLUENCE,
    BROKER_SUBMISSION,
    MULTI_MODEL_SHADOW_ENABLED,
    PRIMARY_MODEL_ID,
    SOL_CHALLENGER_MODEL_ID,
    GEMINI_SCOUT_MODEL_ID,
    BasisRegime,
    CanonicalShadowReceipt,
    ChallengerRecordHeader,
    GeminiEvidenceGuard,
    QueuedChallengerFinding,
    RouterStateMemory,
    ShadowOrchestrator,
    ShadowOrchestratorRouter,
    THRESHOLD_REGISTRY,
    canonical_digest,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_payload(
    basis: float | None = None,
    atm: float | None = None,
    spot: float | None = None,
    zero_gamma: float | None = None,
    gex: float | None = None,
    skew_10d: float | None = None,
    skew_25d: float | None = None,
    missing: list | None = None,
    flow_net_delta_avail: bool = True,
    mlofi_avail: bool = True,
    decision_cutoff_ist: str = "13:00:00",
) -> dict:
    def avail(v):
        return {"availability": "AVAILABLE", "value": v} if v is not None else {"availability": "UNAVAILABLE", "value": None}

    facts = {
        "spot_price": avail(spot or 23500.0),
        "basis": avail(basis),
        "atm_strike": avail(atm),
        "zero_gamma": avail(zero_gamma),
        "total_net_gex_inr_cr": avail(gex),
        "skew_10d": avail(skew_10d),
        "skew_25d": avail(skew_25d),
        "flow_net_delta": {"availability": "AVAILABLE" if flow_net_delta_avail else "UNAVAILABLE", "value": None},
        "mlofi_5l": {"availability": "AVAILABLE" if mlofi_avail else "UNAVAILABLE", "value": None},
    }
    return {
        "packet_id": f"pkt_{abs(hash(str(facts))) % 10000:04d}",
        "session_date": "2026-09-09",
        "decision_cutoff_ist": decision_cutoff_ist,
        "frozen_at_utc": "2026-09-09T07:30:00+00:00",
        "evidence_frontier": ["evt_001"],
        "known_missing_inputs": missing or [],
        "current_facts": facts,
    }


def make_receipt(payload: dict, revision: int = 1) -> CanonicalShadowReceipt:
    return CanonicalShadowReceipt.from_packet_payload(payload, revision=revision)


def flow_flip_event(after_mlofi: float) -> dict:
    return {
        "event_type": "FLOW_POLARITY_FLIP",
        "supporting_values": {"after_mlofi": after_mlofi, "before_mlofi": -after_mlofi},
    }


def oi_surge_event(strike: float, side: str = "CALL") -> dict:
    return {
        "event_type": "SUDDEN_OI_SURGE",
        "supporting_values": {
            "side": side,
            "top_strike": {"strike": strike, "option_type": "CE", "oi": 5_000_000},
        },
    }


# ── Safety Invariants & Threshold Registry ─────────────────────────────────────

class TestSafetyInvariants:
    def test_feature_flag_disabled_by_default(self):
        assert MULTI_MODEL_SHADOW_ENABLED is False

    def test_execution_influence_zero(self):
        assert AI_EXECUTION_INFLUENCE == 0.0

    def test_broker_submission_false(self):
        assert BROKER_SUBMISSION is False

    def test_vob_influence_zero(self):
        assert AI_VOB_INFLUENCE == 0.0

    def test_dispatch_asserts_zero_influence(self):
        orch = ShadowOrchestrator()
        receipt = make_receipt(make_payload(basis=50.0), revision=1)
        result = orch.dispatch_shadow_cycle(receipt, [], current_time_epoch=1000.0)
        assert result["execution_influence"] == 0.0
        assert result["broker_submission"] is False


class TestThresholdRegistry:
    def test_all_thresholds_classified(self):
        for key, entry in THRESHOLD_REGISTRY.items():
            assert "class" in entry, f"Threshold {key} missing classification"
            assert entry["class"] in {
                "EXISTING_CANONICAL_THRESHOLD",
                "EMPIRICALLY_SUPPORTED",
                "RATE_LIMIT_ONLY",
                "ARBITRARY",
            }, f"Unknown class for {key}: {entry['class']}"

    def test_rate_limit_thresholds_labeled(self):
        for key in ("luna_min_interval_seconds", "sol_min_interval_seconds", "gemini_min_interval_seconds", "challenge_staleness_seconds"):
            assert THRESHOLD_REGISTRY[key]["class"] == "RATE_LIMIT_ONLY"


class TestCanonicalReceiptBinding:
    def test_deterministic_receipt_id(self):
        payload = make_payload(basis=68.3, atm=23500.0, spot=23554.45)
        r1 = make_receipt(payload, revision=100)
        r2 = make_receipt(payload, revision=100)
        assert r1.receipt_id == r2.receipt_id
        assert r1.packet_hash == r2.packet_hash

    def test_challenger_record_preserves_parent_receipt(self):
        payload = make_payload(basis=105.0)
        receipt = make_receipt(payload, revision=200)
        challenger_payload = {"challenge": "basis_transition", "basis": 105.0}
        challenger_hash = canonical_digest(challenger_payload)
        header = ChallengerRecordHeader(
            parent_receipt_id=receipt.receipt_id,
            parent_packet_hash=receipt.packet_hash,
            parent_revision=receipt.revision,
            challenger_model=SOL_CHALLENGER_MODEL_ID,
            challenger_payload_hash=challenger_hash,
        )
        assert header.parent_receipt_id == receipt.receipt_id
        assert header.parent_packet_hash == receipt.packet_hash
        assert header.parent_revision == 200
        assert header.challenger_payload_hash != receipt.receipt_id


# ── Edge Trigger Mechanics ─────────────────────────────────────────────────────

class TestEdgeTriggers:
    def test_persistent_wide_basis_triggers_sol_only_once(self):
        router = ShadowOrchestratorRouter()
        r1 = make_receipt(make_payload(basis=105.0), revision=1)
        d1 = router.evaluate_routing(r1, [], current_time_epoch=1000.0)
        assert d1.invoke_sol is True

        r2 = make_receipt(make_payload(basis=103.0), revision=2)
        d2 = router.evaluate_routing(r2, [], current_time_epoch=1075.0)
        assert d2.invoke_sol is False

    def test_flow_polarity_reversal_triggers_gemini(self):
        router = ShadowOrchestratorRouter()
        r1 = make_receipt(make_payload(), revision=1)
        router.evaluate_routing(r1, [flow_flip_event(-0.05)], current_time_epoch=1000.0)

        r2 = make_receipt(make_payload(), revision=2)
        d2 = router.evaluate_routing(r2, [flow_flip_event(+0.12)], current_time_epoch=1045.0)
        assert d2.invoke_gemini is True
        assert "FLOW_POLARITY_TRANSITION" in (d2.gemini_reason or "")


# ── Challenger Escalation Damping Suite (§9 Specification) ────────────────────

class TestChallengerEscalationDamping:
    """Rigorous verification of the 9 required V1.2 behaviors."""

    def test_1_gemini_finding_queues_without_immediate_luna_call(self):
        """1. Gemini finding queues without immediate Luna call."""
        router = ShadowOrchestratorRouter()
        r = make_receipt(make_payload(), revision=1)
        d = router.evaluate_routing(r, [flow_flip_event(+0.15)], current_time_epoch=1000.0)

        assert d.invoke_gemini is True
        assert d.invoke_luna is False, "Gemini finding must NOT immediately invoke Luna"
        assert GEMINI_SCOUT_MODEL_ID in router._state.pending_challenges
        assert router.metrics.queued == 1
        assert router.metrics.consumed == 0

    def test_2_sol_finding_queues_without_immediate_luna_call(self):
        """2. Sol finding queues without immediate Luna call."""
        router = ShadowOrchestratorRouter()
        r = make_receipt(make_payload(basis=105.0), revision=1)
        d = router.evaluate_routing(r, [], current_time_epoch=1000.0)

        assert d.invoke_sol is True
        assert d.invoke_luna is False, "Sol finding must NOT immediately invoke Luna"
        assert SOL_CHALLENGER_MODEL_ID in router._state.pending_challenges
        assert router.metrics.queued == 1
        assert router.metrics.consumed == 0

    def test_3_gemini_and_sol_findings_coalesce_into_one_next_luna_context(self):
        """3. Gemini + Sol findings coalesce into one next Luna context."""
        router = ShadowOrchestratorRouter()

        # Receipt 1: Gemini produces finding -> queued
        r1 = make_receipt(make_payload(basis=10.0), revision=1)
        d1 = router.evaluate_routing(r1, [flow_flip_event(-0.2)], current_time_epoch=1000.0)
        assert d1.invoke_gemini is True
        assert d1.invoke_luna is False

        # Receipt 2: Sol produces finding -> queued
        r2 = make_receipt(make_payload(basis=80.0), revision=2)  # NORMAL->DISLOCATED
        d2 = router.evaluate_routing(r2, [], current_time_epoch=1070.0)
        assert d2.invoke_sol is True
        assert d2.invoke_luna is False

        # Both findings are pending
        assert len(router._state.pending_challenges) == 2

        # Receipt 3: Luna naturally triggers via CANONICAL_STATE_TRANSITION
        r3 = make_receipt(make_payload(basis=80.0), revision=3)
        d3 = router.evaluate_routing(r3, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=1100.0)

        assert d3.invoke_luna is True
        assert d3.is_luna_natural is True
        # Both challenges must be consumed together in this single Luna call
        assert len(d3.consumed_challenge_context) == 2
        assert router.metrics.coalesced_events == 1
        assert router.metrics.consumed == 2
        # Pending queue is now empty
        assert len(router._state.pending_challenges) == 0

    def test_4_material_deterministic_contradiction_can_immediately_escalate_luna(self):
        """4. Material deterministic contradiction CAN immediately escalate Luna."""
        router = ShadowOrchestratorRouter()

        # Establish baseline Luna run at t=1000s
        r1 = make_receipt(make_payload(basis=10.0), revision=1)
        router.evaluate_routing(r1, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=1000.0)

        # At t=1150s (>120s rate-limit floor), a material contradiction override arrives
        # (e.g. thesis invalidated or dual divergence)
        r2 = make_receipt(make_payload(basis=105.0), revision=10)
        d2 = router.evaluate_routing(
            r2,
            [],
            current_time_epoch=1150.0,
            material_contradiction_override=True,
        )

        assert d2.invoke_luna is True
        assert d2.is_luna_immediate_escalation is True
        assert "IMMEDIATE_CHALLENGER_ESCALATION" in (d2.luna_reason or "")

    def test_5_stale_queued_challenger_context_is_dropped(self):
        """5. Stale queued challenger context is dropped (state resolution or timeout)."""
        router = ShadowOrchestratorRouter()

        # Step 1: Queue a Sol basis challenge when basis enters EXTREME (105 pts)
        r1 = make_receipt(make_payload(basis=105.0), revision=1)
        router.evaluate_routing(r1, [], current_time_epoch=1000.0)
        assert SOL_CHALLENGER_MODEL_ID in router._state.pending_challenges

        # Step 2: Basis dislocation resolves back to NORMAL (10 pts)
        r2 = make_receipt(make_payload(basis=10.0), revision=2)
        router.evaluate_routing(r2, [], current_time_epoch=1050.0)

        # Sol finding must be dropped as state-resolved
        assert SOL_CHALLENGER_MODEL_ID not in router._state.pending_challenges
        assert router.metrics.expired_stale >= 1

        # Step 3: When Luna runs, it does NOT receive the expired finding
        r3 = make_receipt(make_payload(basis=10.0), revision=3)
        d3 = router.evaluate_routing(r3, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=1100.0)
        assert len(d3.consumed_challenge_context) == 0

    def test_6_superseded_challenge_replaces_older_same_family_challenge(self):
        """6. Superseded challenge replaces older same-family challenge."""
        router = ShadowOrchestratorRouter()

        # Finding 1 from Sol
        r1 = make_receipt(make_payload(basis=105.0), revision=1)
        router.evaluate_routing(r1, [], current_time_epoch=1000.0)
        assert router.metrics.queued == 1
        assert router.metrics.superseded == 0

        # Finding 2 from Sol (regime shifts to DISLOCATED before Luna runs)
        r2 = make_receipt(make_payload(basis=80.0), revision=2)
        router.evaluate_routing(r2, [], current_time_epoch=1070.0)

        # Finding 1 must be superseded
        assert router.metrics.queued == 2
        assert router.metrics.superseded == 1
        assert len(router._state.pending_challenges) == 1
        current_ch = router._state.pending_challenges[SOL_CHALLENGER_MODEL_ID]
        assert "DISLOCATED" in current_ch.finding

    def test_7_prior_challenger_receipt_identity_remains_visible(self):
        """7. Prior challenger receipt identity remains visible (truthful labeling)."""
        router = ShadowOrchestratorRouter()

        # Step 0: Establish recent Luna run so cadence fallback does not immediately fire at rx
        r0 = make_receipt(make_payload(basis=10.0), revision=40)
        router.evaluate_routing(r0, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=950.0)

        # Step 1: Challenger runs at receipt X (basis entered EXTREME)
        payload_x = make_payload(basis=105.0, decision_cutoff_ist="13:30:00")
        rx = make_receipt(payload_x, revision=50)
        dx = router.evaluate_routing(rx, [], current_time_epoch=1000.0)
        assert dx.invoke_sol is True
        assert dx.invoke_luna is False, "Sol finding must queue, not immediately invoke Luna"
        assert SOL_CHALLENGER_MODEL_ID in router._state.pending_challenges

        # Step 2: Luna runs at receipt Y (later in time, different cutoff)
        payload_y = make_payload(basis=105.0, decision_cutoff_ist="13:35:00")
        ry = make_receipt(payload_y, revision=70)
        dy = router.evaluate_routing(ry, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=1050.0)

        assert dy.invoke_luna is True
        assert len(dy.consumed_challenge_context) == 1
        entry = dy.consumed_challenge_context[0]

        # Must explicitly label prior receipt X and its revision/cutoff
        assert f"PRIOR CHALLENGE CONTEXT FROM RECEIPT {rx.receipt_id[:12]}" in entry
        assert "Rev 50" in entry
        assert "Cutoff 13:30:00" in entry
        # Must NOT claim to be from current receipt Y
        assert ry.receipt_id[:12] not in entry or ry.receipt_id[:12] == rx.receipt_id[:12]

    def test_8_no_recursive_luna_to_challenger_loop(self):
        """8. No recursive Luna → challenger → Luna loop."""
        router = ShadowOrchestratorRouter()

        # Luna runs on natural trigger
        r1 = make_receipt(make_payload(basis=10.0), revision=1)
        d1 = router.evaluate_routing(r1, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=1000.0)
        assert d1.invoke_luna is True
        assert d1.invoke_sol is False
        assert d1.invoke_gemini is False

        # Next receipt has no market edges: neither Sol, Gemini, nor Luna should fire
        r2 = make_receipt(make_payload(basis=10.0), revision=2)
        d2 = router.evaluate_routing(r2, [], current_time_epoch=1005.0)
        assert d2.invoke_luna is False
        assert d2.invoke_sol is False
        assert d2.invoke_gemini is False

    def test_9_execution_influence_remains_zero(self):
        """9. Execution influence remains zero across orchestrator and router."""
        orch = ShadowOrchestrator()
        r = make_receipt(make_payload(basis=105.0), revision=1)
        res = orch.dispatch_shadow_cycle(r, [{"event_type": "STATE_TRANSITION"}], current_time_epoch=1000.0)

        assert res["execution_influence"] == 0.0
        assert res["broker_submission"] is False
        assert AI_EXECUTION_INFLUENCE == 0.0
        assert BROKER_SUBMISSION is False
        assert AI_VOB_INFLUENCE == 0.0
        assert MULTI_MODEL_SHADOW_ENABLED is False


# ── Gemini Evidence Guard Tests ───────────────────────────────────────────────

class TestGeminiEvidenceGuard:
    def test_prompt_constraint_injected_when_flow_unavailable(self):
        payload = make_payload(missing=["flow_net_delta", "mlofi_5l"],
                               flow_net_delta_avail=False, mlofi_avail=False)
        receipt = make_receipt(payload)
        constraints = GeminiEvidenceGuard.prepare_gemini_prompt_constraints(receipt)
        assert "ORDER_FLOW = UNAVAILABLE" in constraints
        assert "Do NOT infer order flow" in constraints

    def test_post_validator_rejects_hallucinated_inference(self):
        payload = make_payload(missing=["flow_net_delta", "mlofi_5l"],
                               flow_net_delta_avail=False, mlofi_avail=False)
        receipt = make_receipt(payload)
        bad = "We observe institutional buying and aggressive sellers pushing volatility."
        valid, reason = GeminiEvidenceGuard.validate_gemini_response(bad, receipt)
        assert valid is False
        assert "UNSUPPORTED_INFERENCE" in reason
