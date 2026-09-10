"""
Runtime Configuration Contract & Environment Source Audit.

Declares the authoritative production repository, implementation worktree, environment source, log root, and artifact root.
Exposes token fingerprints via one-way SHA-256 short hashes without outputting secret tokens.
EXECUTION INFLUENCE: ZERO.
"""

from __future__ import annotations

import os, json, hashlib, dotenv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_runtime_configuration() -> dict[str, Any]:
    prod_repo = Path("/Users/ayushmudgal/Developer/CitadelOS")
    worktree_repo = Path("/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend")
    env_source = prod_repo / ".env"

    if env_source.exists():
        dotenv.load_dotenv(env_source, override=True)

    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()

    client_id_hash = hashlib.sha256(client_id.encode()).hexdigest()[:8] if client_id else "N/A"
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:8] if token else "N/A"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "production_repository": str(prod_repo),
        "worktree_repository": str(worktree_repo),
        "environment_source_file": str(env_source),
        "env_file_exists": env_source.exists(),
        "dhan_client_id_present": bool(client_id),
        "dhan_client_id_fingerprint": client_id_hash,
        "dhan_access_token_present": bool(token),
        "dhan_access_token_length": len(token),
        "dhan_access_token_fingerprint": token_hash,
        "log_root": str(worktree_repo / "logs"),
        "artifact_root": str(worktree_repo / "artifacts"),
        "launchd_script": str(worktree_repo / "scripts" / "run-citadel-backend.sh"),
        "execution_influence": "ZERO",
    }


def export_runtime_configuration_contract_artifact(output_path: str = "artifacts/major_leap/runtime_configuration_contract.json") -> dict[str, Any]:
    cfg = get_runtime_configuration()
    artifact = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": cfg,
        "execution_influence": "ZERO",
    }
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(artifact, f, indent=2)
    return artifact
