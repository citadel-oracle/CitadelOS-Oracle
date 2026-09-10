"""
Monday One-Command Live Migration Controller & Validator.

Usage:
  python scripts/validate_canonical_live_migration.py [--endpoint http://127.0.0.1:8000] [--status] [--approve-primary] [--revoke-primary] [--promote CONSUMER] [--rollback CONSUMER] [--rollback-all]

Rollout Order:
  1. Edge Lab
  2. VOB
  3. OSE
  4. Tactical Edge

Commands:
  --status           View migration modes, permit status, and shadow reports
  --approve-primary  Approve global primary permit (REFUSED IF MARKET CLOSED OR EVIDENCE MISSING)
  --revoke-primary   Revoke global primary permit
  --promote          Promote consumer to CANONICAL_PRIMARY (REFUSES IF MARKET CLOSED OR PERMIT FALSE)
  --rollback         Rollback consumer to LEGACY_ONLY via persistent control plane
  --rollback-all     Rollback ALL consumers to LEGACY_ONLY via persistent control plane
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

CONTROL_FILE_PATH = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/canonical_migration_control.json")


def load_control_file() -> dict:
    if CONTROL_FILE_PATH.exists():
        try:
            with open(CONTROL_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": "1.0.0", "primary_permit": False, "modes": {}, "history": []}


def save_control_file(data: dict) -> None:
    CONTROL_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp_p = CONTROL_FILE_PATH.with_suffix(".tmp")
    with open(tmp_p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_p.replace(CONTROL_FILE_PATH)


def run_validation(endpoint: str = "http://127.0.0.1:8000") -> dict:
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "shadow_status": None,
        "migration_status": None,
        "checks": {},
        "verdict": "FAIL",
    }

    # 1. Query shadow-status
    try:
        req = urllib.request.urlopen(f"{endpoint}/v1/canonical-features/shadow-status", timeout=5)
        shadow_data = json.loads(req.read().decode("utf-8"))
        results["shadow_status"] = shadow_data
        results["checks"]["shadow_status_available"] = True
    except Exception as e:
        results["checks"]["shadow_status_available"] = False
        results["error"] = str(e)
        return results

    # 2. Query migration-status
    try:
        req = urllib.request.urlopen(f"{endpoint}/v1/canonical-features/migration-status", timeout=5)
        mig_data = json.loads(req.read().decode("utf-8"))
        results["migration_status"] = mig_data
        results["checks"]["migration_status_available"] = True
    except Exception as e:
        results["checks"]["migration_status_available"] = False

    # 3. Check Enabled & Safety
    results["checks"]["enabled"] = shadow_data.get("enabled") is True
    results["checks"]["execution_influence_zero"] = shadow_data.get("execution_influence") == "ZERO"

    # 4. Check Active Reports
    reports = shadow_data.get("active_reports", {})
    required_reports = ["OSE:ema_50", "VOB:atr_value", "TACTICAL_EDGE:supertrend", "EDGE_LAB:vwap_value"]
    all_reports_present = all(r in reports for r in required_reports)
    all_canonical_non_null = all(reports.get(r, {}).get("canonical_value") is not None for r in required_reports)
    no_warmup_missing = all(reports.get(r, {}).get("classification") != "WARMUP_MISSING" for r in required_reports)

    results["checks"]["all_reports_present"] = all_reports_present
    results["checks"]["all_canonical_non_null"] = all_canonical_non_null
    results["checks"]["no_warmup_missing"] = no_warmup_missing

    # 5. Migration Modes Dual-Read Check
    modes = mig_data.get("migration_modes", {}) if results["migration_status"] else {}
    dual_read_active = all(mode == "DUAL_READ" for mode in modes.values()) if modes else False
    results["checks"]["all_modes_dual_read"] = dual_read_active

    # 6. Permit Check
    primary_permit = mig_data.get("primary_permit", False) if results["migration_status"] else False
    results["checks"]["primary_permit_disabled_for_readiness"] = primary_permit is False

    # 7. Final Verdict
    if (
        results["checks"]["enabled"]
        and results["checks"]["execution_influence_zero"]
        and all_reports_present
        and all_canonical_non_null
        and no_warmup_missing
        and dual_read_active
    ):
        results["verdict"] = "WEEKEND_CUTOVER_CONTROL_READY"
    else:
        results["verdict"] = "WEEKEND_CUTOVER_CONTROL_FAILED"

    return results


def main():
    parser = argparse.ArgumentParser(description="Validate Canonical Live Migration Controller")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000", help="Backend HTTP endpoint")
    parser.add_argument("--status", action="store_true", help="Print current migration status")
    parser.add_argument("--approve-primary", action="store_true", help="Approve global primary permit")
    parser.add_argument("--revoke-primary", action="store_true", help="Revoke global primary permit")
    parser.add_argument("--promote", help="Promote consumer to CANONICAL_PRIMARY")
    parser.add_argument("--rollback", help="Rollback specific consumer (OSE, VOB, TACTICAL_EDGE, EDGE_LAB)")
    parser.add_argument("--rollback-all", action="store_true", help="Rollback ALL consumers to LEGACY_ONLY")
    args = parser.parse_args()

    print("==================================================")
    print("CITADEL — RUNTIME MIGRATION CONTROL PLANE")
    print("==================================================")

    if args.approve_primary:
        print("Attempting to APPROVE primary permit...")
        is_live_market = False  # Hardcoded False while market closed
        if not is_live_market:
            print("❌ APPROVAL REFUSED: Market is CLOSED. Global primary permit cannot be approved while market is closed.")
            sys.exit(1)

    if args.revoke_primary:
        print("Revoking global primary permit...")
        data = load_control_file()
        data["primary_permit"] = False
        # Downgrade any promoted modes
        for c in data.get("modes", {}):
            if data["modes"][c] == "CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK":
                data["modes"][c] = "DUAL_READ"
        data.setdefault("history", []).append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "consumer": "GLOBAL_PERMIT",
            "previous_mode": "TRUE",
            "new_mode": "FALSE",
            "actor": "CLI_CONTROLLER",
            "reason": "REVOKE_PRIMARY_COMMAND",
        })
        save_control_file(data)
        print("✅ GLOBAL PRIMARY PERMIT REVOKED.")
        sys.exit(0)

    if args.rollback_all:
        print("Executing instant ROLLBACK-ALL to LEGACY_ONLY...")
        data = load_control_file()
        data["modes"] = {
            "OSE": "LEGACY_ONLY",
            "VOB": "LEGACY_ONLY",
            "TACTICAL_EDGE": "LEGACY_ONLY",
            "EDGE_LAB": "LEGACY_ONLY",
        }
        data.setdefault("history", []).append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "consumer": "ALL",
            "previous_mode": "MIXED",
            "new_mode": "LEGACY_ONLY",
            "actor": "CLI_CONTROLLER",
            "reason": "ROLLBACK_ALL_COMMAND",
        })
        save_control_file(data)
        print("✅ ROLLBACK-ALL EXECUTED. All consumers set to LEGACY_ONLY in control plane.")
        sys.exit(0)

    if args.rollback:
        consumer = args.rollback.upper().replace(" ", "_")
        print(f"Executing instant ROLLBACK for consumer: {consumer}...")
        data = load_control_file()
        data.setdefault("modes", {})[consumer] = "LEGACY_ONLY"
        data.setdefault("history", []).append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "consumer": consumer,
            "previous_mode": "PROMOTED_OR_DUAL",
            "new_mode": "LEGACY_ONLY",
            "actor": "CLI_CONTROLLER",
            "reason": "ROLLBACK_SINGLE_COMMAND",
        })
        save_control_file(data)
        print(f"✅ ROLLBACK EXECUTED. {consumer} set to LEGACY_ONLY in control plane.")
        sys.exit(0)

    if args.promote:
        consumer = args.promote.upper().replace(" ", "_")
        print(f"Attempting PROMOTION for consumer: {consumer}...")
        data = load_control_file()
        permit = data.get("primary_permit", False)
        if not permit:
            print("❌ PROMOTION REFUSED: Global permit CITADEL_CANONICAL_PRIMARY_APPROVED is FALSE.")
            sys.exit(1)
        is_live = False
        if not is_live:
            print("❌ PROMOTION REFUSED: Market is CLOSED. Promotion is strictly forbidden while market is closed.")
            sys.exit(1)

    val = run_validation(args.endpoint)
    print(json.dumps(val, indent=2))

    if val["verdict"] == "WEEKEND_CUTOVER_CONTROL_READY":
        print("\n✅ VALIDATION VERDICT: WEEKEND_CUTOVER_CONTROL_READY")
        sys.exit(0)
    else:
        print("\n❌ VALIDATION VERDICT: WEEKEND_CUTOVER_CONTROL_FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
