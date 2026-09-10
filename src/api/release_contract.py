"""Strict, read-only compatibility contract for the Post-E9 dashboard cutover.

The frontend keeps one V2 aggregate provider.  This document is emitted by
that provider so a deployment can reject a backend that does not own the
canonical Post-E9 schema instead of silently mixing worktrees.
"""

from __future__ import annotations

API_VERSION = "2.0"
SCHEMA_VERSION = 2
FRONTEND_SCHEMA_VERSION = 1
COMPATIBILITY_ID = "CITADEL_POST_E9_CANONICAL_V1"
CANONICAL_RELEASE = "POST_E9_ARGUS_ORACLE_P0"


def dashboard_release_contract() -> dict[str, object]:
    return {
        "compatibility_id": COMPATIBILITY_ID,
        "canonical_release": CANONICAL_RELEASE,
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "frontend_schema_versions": [FRONTEND_SCHEMA_VERSION],
        "backend_owner": "CITADEL_ORACLE_POST_E9_CANONICAL_BACKEND",
        "duplicate_backend_allowed": False,
        "activation_policy": "FRONTEND_AND_BACKEND_MUST_EMIT_MATCHING_COMPATIBILITY_ID",
    }
