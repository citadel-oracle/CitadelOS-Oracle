from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import torch

from src.kronos_alpha.runner import run_forecast


SOURCE = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/source/Kronos")
MODEL = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-small/snapshots/901c26c1332695a2a8f243eb2f37243a37bea320")
TOKENIZER = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-Tokenizer-base/snapshots/0e0117387f39004a9016484a186a908917e22426")


def fixture_request(count=64):
    start = datetime(2026, 1, 5, 3, 45, tzinfo=timezone.utc)
    candles = []
    for index in range(count):
        close = 24000 + index * 0.25
        candles.append({
            "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
            "open": close - 0.5,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "closed": True,
        })
    return {
        "symbol": "NIFTY",
        "source": "FIXTURE",
        "candles": candles,
        "minimum_context": 64,
        "forecast_horizon": 2,
        "sample_count": 2,
    }


@pytest.mark.integration
@pytest.mark.external_data
def test_real_cached_model_forecast_and_offline_reload(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert SOURCE.exists() and MODEL.exists() and TOKENIZER.exists()
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    first = run_forecast(fixture_request(), SOURCE, MODEL, TOKENIZER, device)
    second = run_forecast(fixture_request(), SOURCE, MODEL, TOKENIZER, device)

    assert first["model_status"] == second["model_status"] == "READY"
    assert first["device"] == device
    assert first["path_count"] == 2
    assert first["horizon_candles"] == 2
    assert sum(first[key] for key in ("bullish_probability", "bearish_probability", "sideways_probability")) == pytest.approx(100)
    assert first["source_metadata"]["fixture_data"] is True
    assert "FORECAST_COMPLETE" in first["reason_codes"]


@pytest.mark.integration
@pytest.mark.external_data
def test_mps_tensor_and_cpu_fallback_are_real():
    cpu = torch.tensor([2.0], device="cpu") * 3
    assert cpu.item() == 6
    if torch.backends.mps.is_available():
        mps = torch.tensor([2.0], device="mps") * 3
        assert mps.cpu().item() == 6
