"""Zero-VOB Provenance Guard, Field Allowlist & Evidence Validator (P0.3 Hardened).

Enforces strict field-level allowlist validation, fail-closed contamination rejection,
and deterministic validation of model evidence references across 7 typed sensorium domains.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Set, Tuple

from src.oracle_sol.field_registry import (
    CONTRACT_PRICING_ALLOWED_KEYS,
    SOL_VOB_FREE_FIELD_REGISTRY,
    STRIKE_LADDER_ALLOWED_KEYS,
)


FORBIDDEN_VOB_SUBSTRINGS: Tuple[str, ...] = (
    "vob",
    "horsepower",
    "vob_direction",
    "vob_horsepower",
    "vob_score",
    "vob_zone",
    "vob_state",
    "vob_alignment",
    "cvob",
    "pvob",
    "neutral_vob_alias",
    "hidden_vob",
    "vob_reversal",
)

METADATA_ALLOWLIST_KEYS: Set[str] = {
    "snapshot_id",
    "canonical_snapshot_id",
    "market_session_date",
    "identity_quality",
    "replay_stable",
    "timestamp_utc",
    "timestamp_ist",
    "system_status",
    "upstream_source_health",
    "dhan_quote_age_ms",
    "order_flow_age_ms",
    "option_chain_age_ms",
    "availability_matrix",
    "source_hashes",
    "vob_free_verified",
    "schema_version",
}


class VobContaminationError(ValueError):
    """Raised when an active payload contains forbidden VOB lineage or indirect alias."""


class UnverifiedLineageError(ValueError):
    """Raised when an incoming field carries unknown or unapproved lineage."""


class InvalidEvidenceReferenceError(ValueError):
    """Raised when a model output references non-existent or hallucinated evidence."""


class ProvenanceGuard:
    """Automated validator enforcing fail-closed VOB quarantine and field-level allowlisting."""

    @staticmethod
    def is_vob_key(key: str) -> bool:
        k = key.lower().strip()
        if k.startswith("vob_free_") or k.startswith("vob_quarantine_") or k == "vob_free":
            return False
        for forbidden in FORBIDDEN_VOB_SUBSTRINGS:
            if forbidden in k:
                return True
        return False

    @classmethod
    def assert_vob_free_fail_closed(cls, data: Any, path: str = "") -> None:
        """Recursively assert zero VOB contamination. Fails closed immediately upon detection."""
        if isinstance(data, dict):
            for k, v in data.items():
                current_path = f"{path}.{k}" if path else k
                if cls.is_vob_key(k):
                    raise VobContaminationError(
                        f"FAIL-CLOSED: Forbidden VOB lineage detected at '{current_path}'. Payload rejected."
                    )
                cls.assert_vob_free_fail_closed(v, current_path)
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                cls.assert_vob_free_fail_closed(item, f"{path}[{idx}]")

    @classmethod
    def verify_field_level_allowlist(cls, snapshot_dict: Dict[str, Any], strict: bool = True) -> bool:
        """Verify that every root and nested field strictly adheres to the authoritative Field Registry."""
        cls.assert_vob_free_fail_closed(snapshot_dict)

        all_authorized_root = set(SOL_VOB_FREE_FIELD_REGISTRY.keys()) | METADATA_ALLOWLIST_KEYS
        unauthorized_root = set(snapshot_dict.keys()) - all_authorized_root
        if unauthorized_root:
            if strict:
                raise UnverifiedLineageError(
                    f"FAIL-CLOSED: Unauthorized root fields in Sol snapshot: {unauthorized_root}"
                )
            return False

        # Validate nested strike ladder items
        ladder = snapshot_dict.get("strike_ladder") or []
        if isinstance(ladder, list):
            for idx, strike_item in enumerate(ladder):
                if isinstance(strike_item, dict):
                    unauthorized_nested = set(strike_item.keys()) - STRIKE_LADDER_ALLOWED_KEYS
                    if unauthorized_nested:
                        if strict:
                            raise UnverifiedLineageError(
                                f"FAIL-CLOSED: Unauthorized nested keys in strike_ladder[{idx}]: {unauthorized_nested}"
                            )
                        return False

        # Validate contract pricing items
        for pr_key in ("ce_pricing", "pe_pricing"):
            pr_data = snapshot_dict.get(pr_key)
            if isinstance(pr_data, dict):
                unauthorized_pricing = set(pr_data.keys()) - CONTRACT_PRICING_ALLOWED_KEYS
                if unauthorized_pricing:
                    if strict:
                        raise UnverifiedLineageError(
                            f"FAIL-CLOSED: Unauthorized nested keys in {pr_key}: {unauthorized_pricing}"
                        )
                    return False

        return True

    @staticmethod
    def compute_sha256(payload: Any) -> str:
        """Compute deterministic SHA-256 hash of serialized JSON."""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class EvidenceReferenceValidator:
    """Validates that model-cited event IDs, snapshot IDs, and expectation IDs exist in context."""

    @staticmethod
    def validate_references(
        model_output: Dict[str, Any],
        known_event_ids: Set[str],
        known_expectation_ids: Set[str],
        current_snapshot_id: str,
    ) -> Tuple[bool, List[str]]:
        """Validate all citations. Returns (is_valid, validation_errors)."""
        errors: List[str] = []

        # 1. Validate Expectation Evaluations
        raw_evals = model_output.get("expectation_evaluations", [])
        if isinstance(raw_evals, list):
            for ev in raw_evals:
                if isinstance(ev, dict):
                    exp_id = str(ev.get("expectation_id", ""))
                    if exp_id and exp_id not in known_expectation_ids:
                        errors.append(f"Model cited non-existent expectation_id '{exp_id}'.")

                    # Check event refs in evaluation
                    event_refs = ev.get("actual_event_refs", [])
                    if isinstance(event_refs, list):
                        for e_ref in event_refs:
                            if e_ref and e_ref not in known_event_ids:
                                errors.append(f"Evaluation cited non-existent event_id '{e_ref}'.")

        # 2. Validate Evidence References List
        evidence_refs = model_output.get("evidence_references", [])
        if isinstance(evidence_refs, list):
            for ref in evidence_refs:
                ref_str = str(ref).strip()
                if ref_str.startswith("evt_") and ref_str not in known_event_ids:
                    errors.append(f"Model cited non-existent event reference '{ref_str}'.")
                elif ref_str.startswith("snap_") and ref_str != current_snapshot_id:
                    errors.append(f"Model cited foreign snapshot reference '{ref_str}'.")

        return len(errors) == 0, errors
