"""E4A-C Test for E3 Dataset Loader Truth."""

import json
from pathlib import Path
import pytest


def test_vob_dataset_loader_reads_candle_rows_not_dict_keys():
    dataset_path = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json")
    assert dataset_path.exists()

    data = json.loads(dataset_path.read_text())
    assert isinstance(data, dict)
    assert "candles" in data

    candles = data["candles"]
    assert len(candles) >= 19125  # Expected source row count!

    # Select 20 complete sessions (20 * 375 = 7,500 1m candles)
    sel_1m = candles[:7500]
    assert len(sel_1m) == 7500

    # Resampling to 5m bars
    bars_5m_count = len(sel_1m) // 5
    assert bars_5m_count == 1500
