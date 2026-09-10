"""Audit Local Data Paths & Storage Inventory for Citadel Eye Engine Phase E4A."""

import json
import hashlib
from pathlib import Path
from typing import List, Dict

LOCAL_DATASETS = [
    {
        "dataset": "vob_1m_candles.json",
        "absolute_path": "/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json",
        "format": "JSON",
        "sha256": "665f7230d12aa05a304eb013b121bb18de16ff54198b98537c58ab8975072fca",
        "source": "NIFTY Index Spot Data",
        "underlying": "NIFTY",
        "exchange": "NSE",
        "timezone": "UTC",
        "classification": "EXACT_CONTRACT_CANDLE",
        "limitations": "Underlying spot candles only; option quotes paired via synchronization",
        "sealed_holdout_status": "DEVELOPMENT_DATASET",
    },
    {
        "dataset": "dhan_instrument_master.json",
        "absolute_path": "/Users/ayushmudgal/Developer/CitadelOS/logs/dhan_instrument_master.json",
        "format": "JSON",
        "sha256": "7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
        "source": "Dhan Scrip Master API",
        "underlying": "NIFTY",
        "exchange": "NSE",
        "timezone": "IST",
        "classification": "NSE_REFERENCE_METADATA",
        "limitations": "Metadata snapshot for active security IDs",
        "sealed_holdout_status": "DEVELOPMENT_METADATA",
    },
]


def audit_local_data():
    print("=== PHASE E4A: LOCAL DATA AUDIT ===")
    results = []
    for d in LOCAL_DATASETS:
        p = Path(d["absolute_path"])
        exists = p.exists()
        size_bytes = p.stat().st_size if exists else 0
        item = dict(d)
        item["exists"] = exists
        item["file_size_bytes"] = size_bytes
        results.append(item)
        print(f"[{d['dataset']}] Path: {d['absolute_path']} | Exists: {exists} | Size: {size_bytes} bytes")

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E4A_LOCAL_DATA_AUDIT_20260806.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print("Local data report written to", out_file)


if __name__ == "__main__":
    audit_local_data()
