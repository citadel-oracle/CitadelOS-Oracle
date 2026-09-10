"""
Dhan Read-Only Authentication Auditor.

Audits repository .env loading, credential presence, and Dhan API token authentication status without outputting secret tokens.
EXECUTION INFLUENCE: ZERO.
"""

from __future__ import annotations

import os, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import dotenv


def audit_dhan_authentication() -> dict[str, Any]:
    env_file = Path(".env")
    if env_file.exists():
        dotenv.load_dotenv(env_file)

    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()

    has_client_id = bool(client_id)
    has_access_token = bool(access_token)

    if not has_client_id or not has_access_token:
        auth_state = "DHAN_CREDENTIALS_MISSING"
        reason = "DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN missing in process environment and .env"
    else:
        # Test Dhan API option chain call
        from src.broker.dhan_client import DhanClient
        try:
            client = DhanClient()
            chain = client.get_option_chain("NSE_FNO", 13, "2026-08-06")
            if isinstance(chain, dict):
                status = str(chain.get("status", "")).lower()
                remarks = str(chain.get("remarks", "")).lower()
                data = chain.get("data", {})
                if status in ("success", "200", "true") and isinstance(data, dict) and "oc" in data:
                    auth_state = "DHAN_AUTHENTICATED"
                    reason = "Dhan API returned HTTP SUCCESS with valid option chain schema"
                else:
                    auth_state = "DHAN_TOKEN_REJECTED"
                    reason = f"Dhan API returned status '{status}' with remarks '{remarks}' (Token Rejected / Expired Code 808)"
            else:
                auth_state = "DHAN_AUTH_STATE_UNKNOWN"
                reason = "Dhan API returned unexpected non-dict payload"
        except Exception as e:
            auth_state = "DHAN_TOKEN_REJECTED"
            reason = f"DhanClient option chain call exception: {type(e).__name__} {str(e)}"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "env_file_exists": env_file.exists(),
        "has_client_id": has_client_id,
        "has_access_token": has_access_token,
        "auth_state": auth_state,
        "reason": reason,
        "underlying_security_id": 13,
        "underlying_name": "NIFTY",
        "execution_influence": "ZERO",
    }


def export_authentication_and_source_proof_artifact(output_path: str = "artifacts/dhan_session/authentication_and_source_proof.json") -> dict[str, Any]:
    audit_res = audit_dhan_authentication()
    artifact = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authentication_audit": audit_res,
        "auth_state": audit_res["auth_state"],
        "execution_influence": "ZERO",
    }
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(artifact, f, indent=2)
    return artifact
