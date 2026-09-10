#!/usr/bin/env python3
"""Bounded, paper-only Personal Oracle Lite historical backfill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.service import PersonalOracleService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-lab-root", default="logs/strategy_lab")
    parser.add_argument("--ledger", default="logs/personal_oracle.json")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Persist new Oracle events. Without this flag the command is a dry-run.",
    )
    args = parser.parse_args()
    service = PersonalOracleService(
        ledger=PersonalOracleLedger(Path(args.ledger)),
        strategy_lab_root=Path(args.strategy_lab_root),
    )
    result = service.backfill_authoritative(dry_run=not args.execute)
    output = {
        "mode": "EXECUTE" if args.execute else "DRY_RUN",
        "paper_only": True,
        "execution_influence": "ZERO",
        "registered_strategy_count": len(service.discover_strategies()),
        **result,
    }
    print(json.dumps(output, sort_keys=True))
    return 0 if result["invalid"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
