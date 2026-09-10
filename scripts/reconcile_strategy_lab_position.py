#!/usr/bin/env python3
"""Local, paper-only reconciliation for one exactly identified Strategy Lab position."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import argus, strategy_lab_service


def _backend_running() -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", 8000)) == 0


def _quote(projection: Mapping[str, Any], contract: str) -> Mapping[str, Any] | None:
    data = projection.get("data")
    rows = data.get("atm_window") if isinstance(data, Mapping) else None
    for row in rows if isinstance(rows, list) else []:
        for side in ("ce", "pe"):
            quote = row.get(side) if isinstance(row, Mapping) else None
            if isinstance(quote, Mapping) and str(quote.get("security_id") or "") == contract:
                return quote
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--position-id", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--quantity", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup-root")
    arguments = parser.parse_args()
    if not arguments.dry_run and _backend_running():
        print(json.dumps({"status": "REJECTED", "reason": "BACKEND_MUST_BE_STOPPED_FOR_LOCAL_RECONCILIATION"}))
        return 2
    quote = _quote(argus.get_oi("NIFTY"), arguments.contract)
    result = strategy_lab_service.reconcile_paper_position(
        strategy_id=arguments.strategy_id,
        position_id=arguments.position_id,
        contract=arguments.contract,
        quantity=arguments.quantity,
        quote=quote or {},
        dry_run=arguments.dry_run,
        backup_root=arguments.backup_root,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"VALIDATED", "RECONCILED", "ALREADY_RECONCILED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
