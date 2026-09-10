"""Pure structural validation for Flow Pulse candidate actions.

This module deliberately does not decide market direction or setup quality.  It
only prevents an already-produced video candidate from becoming an impossible
trader-facing or paper action.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping


ACTION_CONTRACT_VERSION = "FLOW_PULSE_ACTION_CONTRACT_V1"
ENTRY_STATES = frozenset({
    "EARLY BUY CE", "EARLY BUY PE", "BUY CE · CONFIRMED", "BUY PE · CONFIRMED",
})
ACTIVE_STATES = ENTRY_STATES | {"HOLD", "T1 HIT · PROTECT", "RUNNER"}
EXIT_STATES = frozenset({"INVALID / EXIT", "T2 HIT · EXIT"})


@dataclass(frozen=True, slots=True)
class ActionValidation:
    valid: bool
    reason: str | None
    candidate_plan_id: str
    validated_plan_id: str | None
    canonical_plan: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "contract_version": ACTION_CONTRACT_VERSION,
            "plan_validation": "PASS" if self.valid else "FAIL",
            "validation_reason": self.reason,
            "candidate_plan_id": self.candidate_plan_id,
            "validated_plan_id": self.validated_plan_id,
            "canonical_plan": self.canonical_plan,
        }


def validate_action_contract(candidate: Mapping[str, Any]) -> ActionValidation:
    """Return a canonical action only when the candidate is structurally valid."""

    value = dict(candidate)
    candidate_id = _identity("candidate", value)
    state = str(value.get("state") or "NO TRADE")
    side = str(value.get("side") or "")
    actionable = state in ACTIVE_STATES or state in EXIT_STATES
    if not actionable:
        return _accepted(value, candidate_id)
    if side not in {"CE", "PE"}:
        return _rejected(candidate_id, "PLAN_INVALID · DIRECTION")

    entry = _number(value.get("entry_price"))
    trigger = _number(value.get("trigger"))
    invalidation = _number(value.get("invalidation"))
    target_1 = _number(value.get("target_1"))
    target_2 = _number(value.get("target_2"))

    if state in ACTIVE_STATES:
        if entry is None or trigger is None or invalidation is None:
            return _rejected(candidate_id, "PLAN INVALID · REQUIRED_LEVEL")
        revisions = value.get("level_revisions")
        protected = isinstance(revisions, list) and any(
            isinstance(item, Mapping)
            and str(item.get("reason") or "") == "T1_PROTECTION_COMMITTED"
            and _number(item.get("invalidation")) == invalidation
            for item in revisions
        )
        protected_active_state = state in {"T1 HIT · PROTECT", "HOLD", "RUNNER"}
        if trigger == invalidation and not (protected_active_state and protected):
            return _rejected(candidate_id, "PLAN INVALID · COLLAPSED_RISK")
        if side == "CE" and invalidation >= entry:
            return _rejected(candidate_id, "PLAN INVALID · INVALIDATION_DIRECTION")
        if side == "PE" and invalidation <= entry:
            return _rejected(candidate_id, "PLAN INVALID · INVALIDATION_DIRECTION")
        if abs(entry - invalidation) <= 0.0:
            return _rejected(candidate_id, "PLAN INVALID · NON_POSITIVE_RISK")
        if target_1 is not None and not _forward(target_1, entry, side):
            return _rejected(candidate_id, "PLAN INVALID · TARGET_DIRECTION")
        if target_2 is not None and not _forward(target_2, entry, side):
            return _rejected(candidate_id, "PLAN INVALID · TARGET_DIRECTION")
        if target_1 is not None and target_2 is not None:
            ordered = target_2 >= target_1 if side == "CE" else target_2 <= target_1
            if not ordered:
                return _rejected(candidate_id, "PLAN INVALID · TARGET_ORDER")

    if state in {"HOLD", "RUNNER"} and not value.get("episode_id"):
        return _rejected(candidate_id, "PLAN INVALID · ACTIVE_EPISODE_REQUIRED")
    if state == "T1 HIT · PROTECT":
        if not protected:
            return _rejected(candidate_id, "PLAN INVALID · PROTECTION_REVISION_REQUIRED")
    if state in EXIT_STATES and not str(value.get("reason_for_state_change") or "").strip():
        return _rejected(candidate_id, "PLAN INVALID · EXIT_REASON_REQUIRED")
    return _accepted(value, candidate_id)


def _accepted(value: dict[str, Any], candidate_id: str) -> ActionValidation:
    canonical = dict(value)
    canonical["candidate_plan_id"] = candidate_id
    validated_id = _identity("validated", canonical)
    canonical["validated_plan_id"] = validated_id
    canonical["action_contract_version"] = ACTION_CONTRACT_VERSION
    return ActionValidation(True, None, candidate_id, validated_id, canonical)


def _rejected(candidate_id: str, reason: str) -> ActionValidation:
    return ActionValidation(False, reason, candidate_id, None, None)


def _identity(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{prefix}_" + hashlib.sha256(encoded).hexdigest()[:24]


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _forward(target: float, entry: float, side: str) -> bool:
    return target > entry if side == "CE" else target < entry
