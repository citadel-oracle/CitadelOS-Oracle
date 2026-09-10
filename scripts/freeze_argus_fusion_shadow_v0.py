#!/usr/bin/env python3
"""Write the prospective, human-readable Fusion Shadow V0 freeze artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.argus.fusion_shadow import FUSION_SCHEMA_VERSION, FUSION_VERSION
FUSION_LOGIC_FILES = (
    "src/argus/fusion_shadow.py",
)
TRANSPORT_FILES = (
    "src/oracle/market_data_gateway.py",
    "src/api/oracle_fast_lane.py",
)
RESEARCH_FILES = (
    "src/argus/fusion_eod.py",
    "src/order_flow/recorder.py",
    "scripts/replay_argus_fusion_shadow_v0.py",
    "app/main.py",
)
UI_FILES = (
    "citadel-dashboard/src/components/institutional/ArgusFusionShadowPanel.tsx",
    "citadel-dashboard/src/components/institutional/ArgusFusionShadowPanel.module.css",
    "citadel-dashboard/src/app/oracle/page.tsx",
    "citadel-dashboard/src/components/institutional/OracleWorkspacePanel.tsx",
)
FILES = FUSION_LOGIC_FILES + TRANSPORT_FILES + RESEARCH_FILES + UI_FILES


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _fingerprint(paths: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    digests: dict[str, str] = {}
    for relative in paths:
        digests[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    payload = "\n".join(f"{path}:{digest}" for path, digest in sorted(digests.items()))
    return hashlib.sha256(payload.encode()).hexdigest(), digests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semantic-parity", choices=("PASS", "FAIL", "UNKNOWN"), required=True)
    parser.add_argument("--ui-build-id", default="UNAVAILABLE")
    parser.add_argument("--version", default=FUSION_VERSION)
    parser.add_argument("--previous-freeze", type=Path)
    parser.add_argument("--change-reason", default="TECHNICAL_HARDENING_DATA_CONTRACT_REPLAY_DIAGNOSTICS_AND_TRANSPORT")
    args = parser.parse_args()
    fingerprint, files = _fingerprint(FILES)
    logic_fingerprint, logic_files = _fingerprint(FUSION_LOGIC_FILES)
    transport_fingerprint, transport_files = _fingerprint(TRANSPORT_FILES)
    research_fingerprint, research_files = _fingerprint(RESEARCH_FILES)
    ui_fingerprint, ui_files = _fingerprint(UI_FILES)
    dirty = bool(_git("status", "--porcelain"))
    frozen_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "name": args.version,
        "freeze_timestamp": frozen_at,
        "git_head": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_dirty": dirty,
        "code_fingerprint": fingerprint,
        "fusion_logic_fingerprint": logic_fingerprint,
        "transport_runtime_fingerprint": transport_fingerprint,
        "research_fingerprint": research_fingerprint,
        "ui_fingerprint": ui_fingerprint,
        "file_digests": files,
        "logic_file_digests": logic_files,
        "transport_file_digests": transport_files,
        "research_file_digests": research_files,
        "ui_file_digests": ui_files,
        "schema_version": FUSION_SCHEMA_VERSION,
        "feature_version": args.version,
        "change_reason": args.change_reason,
        "previous_freeze": str(args.previous_freeze) if args.previous_freeze else None,
        "config_fingerprint": hashlib.sha256(f"{args.version}|FAILED_AGGRESSION_REVERSAL|TREND_PULLBACK_RE_ACCELERATION|BREAKOUT_EXPANSION|CONTINUATION|EXPIRY_FAST_MOMENTUM_UNPROVEN".encode()).hexdigest(),
        "ui_build_id": args.ui_build_id,
        "enabled_playbooks": [
            "FAILED_AGGRESSION_REVERSAL",
            "TREND_PULLBACK_RE_ACCELERATION",
            "BREAKOUT_EXPANSION",
            "CONTINUATION",
            "EXPIRY_FAST_MOMENTUM:UNPROVEN",
        ],
        "execution_influence": "ZERO",
        "semantic_parity": args.semantic_parity,
        "freeze_policy": "NEXT_GENUINE_MARKET_SESSION_RUNS_THIS_FROZEN_VERSION_UNLESS_A_DOCUMENTED_RELIABILITY_EMERGENCY_REQUIRES_CHANGE",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
