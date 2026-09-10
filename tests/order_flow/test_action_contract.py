from src.order_flow.action_contract import validate_action_contract


def plan(side="CE", **updates):
    value = {
        "state": f"BUY {side} · CONFIRMED", "side": side,
        "entry_price": 24540.0, "trigger": 24541.0,
        "invalidation": 24530.0 if side == "CE" else 24550.0,
        "target_1": 24550.0 if side == "CE" else 24530.0,
        "target_2": 24560.0 if side == "CE" else 24520.0,
        "episode_id": "episode-1", "reason_for_state_change": "VIDEO CANDIDATE",
    }
    value.update(updates)
    return value


def test_valid_ce_and_pe_pass_unchanged():
    for side in ("CE", "PE"):
        candidate = plan(side)
        result = validate_action_contract(candidate)
        assert result.valid
        assert {key: result.canonical_plan[key] for key in candidate} == candidate


def test_wrong_side_targets_are_rejected():
    assert validate_action_contract(plan("CE", target_1=24485.0)).reason == "PLAN INVALID · TARGET_DIRECTION"
    assert validate_action_contract(plan("PE", target_1=24555.0)).reason == "PLAN INVALID · TARGET_DIRECTION"


def test_wrong_side_and_collapsed_invalidation_are_rejected():
    assert validate_action_contract(plan("CE", invalidation=24550.0)).reason == "PLAN INVALID · INVALIDATION_DIRECTION"
    assert validate_action_contract(plan("PE", trigger=24550.0)).reason == "PLAN INVALID · COLLAPSED_RISK"


def test_missing_target_is_not_fabricated():
    result = validate_action_contract(plan(target_1=None, target_2=None))
    assert result.valid
    assert result.canonical_plan["target_1"] is None
    assert result.canonical_plan["target_2"] is None


def test_protect_requires_real_level_revision():
    result = validate_action_contract(plan(state="T1 HIT · PROTECT", level_revisions=[{
        "reason": "ENTRY_LEVELS_LOCKED", "invalidation": 24530.0,
    }]))
    assert result.reason == "PLAN INVALID · PROTECTION_REVISION_REQUIRED"
    accepted = validate_action_contract(plan(
        state="T1 HIT · PROTECT", trigger=24539.0, invalidation=24539.0, level_revisions=[{
        "reason": "T1_PROTECTION_COMMITTED", "invalidation": 24539.0,
    }]))
    assert accepted.valid


def test_collapsed_entry_risk_stays_blocked_but_committed_t1_protection_can_equal_trigger():
    assert validate_action_contract(plan(invalidation=24541.0)).reason == "PLAN INVALID · COLLAPSED_RISK"
    protected = plan(
        state="RUNNER",
        trigger=24539.0,
        invalidation=24539.0,
        level_revisions=[{"reason": "T1_PROTECTION_COMMITTED", "invalidation": 24539.0}],
    )
    assert validate_action_contract(protected).valid


def test_exit_requires_canonical_reason():
    assert validate_action_contract(plan(state="INVALID / EXIT", reason_for_state_change="")).reason == "PLAN INVALID · EXIT_REASON_REQUIRED"


def test_rejected_candidate_retains_forensic_identity_without_canonical_action():
    result = validate_action_contract(plan("CE", target_1=24485.0))
    assert result.valid is False
    assert result.candidate_plan_id.startswith("candidate_")
    assert result.validated_plan_id is None
    assert result.canonical_plan is None
