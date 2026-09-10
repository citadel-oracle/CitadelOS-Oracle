"""Audit Official & Primary Research Sources for Citadel Eye Engine Phase E4A."""

import json
from pathlib import Path

SOURCES = [
    {
        "source": "NSE",
        "document": "NIFTY Option Contract Specifications & Expiry Circular",
        "version_date": "2024-11 / 2026-08",
        "exact_section": "Equity Derivatives Contract Specifications",
        "concept_reviewed": "NIFTY option lot size 25, ₹0.05 tick size, Thursday weekly/monthly expiry",
        "use_in_e4a": "Contract identity, expiry class, tick size, lot size",
        "limitation": "Exchange specifications subject to SEBI regulatory revisions",
        "license_terms": "Public Official Exchange Circular",
        "direct_dependency": "NO",
        "copied_code": "NO",
    },
    {
        "source": "SEBI",
        "document": "Equity Derivatives Position Limits & FutEq Circular",
        "version_date": "2024-10 Circular",
        "exact_section": "Client & Member Position Limits",
        "concept_reviewed": "Futures Equivalent (FutEq) Delta = Option Quantity * Delta",
        "use_in_e4a": "Regulatory FutEq delta calculation separate from trading delta",
        "limitation": "Regulatory delta is position-limit compliance metric, not execution delta",
        "license_terms": "Public Regulatory Circular",
        "direct_dependency": "NO",
        "copied_code": "NO",
    },
    {
        "source": "RBI",
        "document": "Official Policy Repo Rate",
        "version_date": "2026-08",
        "exact_section": "Monetary Policy Baseline",
        "concept_reviewed": "Risk-free interest rate baseline (6.50%)",
        "use_in_e4a": "Black-Scholes independent model rate input r",
        "limitation": "Fixed baseline rate; yield curve term structure not modeled",
        "license_terms": "Public Policy Baseline",
        "direct_dependency": "NO",
        "copied_code": "NO",
    },
    {
        "source": "DhanHQ API v2",
        "document": "Dhan API v2 Documentation",
        "version_date": "2026-08",
        "exact_section": "Option Chain & Market Quote API",
        "concept_reviewed": "Option chain snapshots, market quotes, binary WebSocket feed",
        "use_in_e4a": "Slow lane option-chain & fast lane quote adapters",
        "limitation": "Dhan API does not return expired contracts post-expiry",
        "license_terms": "Dhan API Terms of Service",
        "direct_dependency": "NO",
        "copied_code": "NO",
    },
]


def audit_sources():
    print("=== PHASE E4A: RESEARCH SOURCES AUDIT ===")
    for s in SOURCES:
        print(f"[{s['source']}] {s['document']} ({s['version_date']})")

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E4A_RESEARCH_SOURCES_20260806.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(SOURCES, indent=2))
    print("Sources report written to", out_file)


if __name__ == "__main__":
    audit_sources()
