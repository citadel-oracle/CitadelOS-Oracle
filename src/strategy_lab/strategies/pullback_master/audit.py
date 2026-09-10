"""Read-only institutional source audit for the authoritative Pine file."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def _balanced_call(lines: List[str], start: int) -> tuple[str, int]:
    text = lines[start]
    depth = text.count("(") - text.count(")")
    index = start
    while depth > 0 and index + 1 < len(lines):
        index += 1
        text += "\n" + lines[index]
        depth += lines[index].count("(") - lines[index].count(")")
    return text, index


def inspect_pine_source(path: str | Path) -> Dict[str, Any]:
    source_path = Path(path).expanduser().resolve()
    raw = source_path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.splitlines()
    version_match = re.search(r"^//@version=(\d+)\s*$", text, re.MULTILINE)
    if not version_match:
        raise ValueError("PINE_VERSION_NOT_DECLARED")

    inputs = []
    index = 0
    pattern = re.compile(r"\binput\.(bool|string|int|float|color|timeframe|symbol|session|source)\s*\(")
    while index < len(lines):
        match = pattern.search(lines[index])
        if not match:
            index += 1
            continue
        declaration, end = _balanced_call(lines, index)
        lhs = declaration.split("=", 1)[0].strip().split()[-1]
        inputs.append(
            {
                "name": lhs,
                "type": match.group(1),
                "line_start": index + 1,
                "line_end": end + 1,
                "declaration": " ".join(part.strip() for part in declaration.splitlines()),
            }
        )
        index = end + 1

    ta_calls = Counter(re.findall(r"\bta\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", text))
    security_calls = []
    for line_number, line in enumerate(lines, start=1):
        if "request.security(" in line:
            security_calls.append(
                {
                    "line": line_number,
                    "lookahead_off": "barmerge.lookahead_off" in line,
                    "gaps_off": "barmerge.gaps_off" in line,
                    "declaration": line.strip(),
                }
            )

    return {
        "source_path": str(source_path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "line_count": len(lines),
        "pine_version": int(version_match.group(1)),
        "inputs": inputs,
        "input_count": len(inputs),
        "ta_calls": dict(sorted(ta_calls.items())),
        "request_security": security_calls,
        "request_security_count": len(security_calls),
        "strategy_calls": dict(sorted(Counter(re.findall(r"\bstrategy\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)).items())),
        "has_process_orders_on_close": bool(
            re.search(r"\bprocess_orders_on_close\s*=\s*true\b", text)
        ),
        "has_calc_on_every_tick": bool(
            re.search(r"\bcalc_on_every_tick\s*=\s*true\b", text)
        ),
        "has_barstate_confirmed_gate": "barstate.isconfirmed" in text,
        "session_literals": sorted(set(re.findall(r'"(\d{4}-\d{4})"', text))),
        "contains_strategy_short": "strategy.short" in text,
        "contains_strategy_long": "strategy.long" in text,
    }
