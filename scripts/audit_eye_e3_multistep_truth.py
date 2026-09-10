"""Audit Multi-Step Definition Truth for Citadel Eye Engine E3-E."""

import json
from pathlib import Path
from datetime import datetime, timezone
from src.eye.composer.setup_registry import get_e3_setup_definitions


def audit_multistep_truth():
    print("=== PHASE E3-E: MULTI-STEP DEFINITION AUDIT ===")
    defs = get_e3_setup_definitions()
    results = []

    for d in defs:
        mandatory_steps = [s for s in d.steps if not s.optional_step]
        item = {
            "setup_id": d.setup_id,
            "setup_family": d.setup_family,
            "status": d.status,
            "total_steps": len(d.steps),
            "mandatory_steps": len(mandatory_steps),
            "optional_steps": len(d.steps) - len(mandatory_steps),
            "is_valid_multistep": len(mandatory_steps) >= 2 if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "SYNTHETICALLY_TESTABLE_RESEARCH") else True,
        }
        results.append(item)
        print(f"{d.setup_id:45s} | Status: {d.status:30s} | Mandatory Steps: {len(mandatory_steps)}")

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E3E_MULTISTEP_DEFINITION_AUDIT_20260806.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print("Audit report written to", out_file)


if __name__ == "__main__":
    audit_multistep_truth()
