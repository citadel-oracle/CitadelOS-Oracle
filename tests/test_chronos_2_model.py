import hashlib
import importlib.util
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


if importlib.util.find_spec("chronos") is None:
    pytest.skip("requires the isolated .venv-chronos-2 genuine-model runtime", allow_module_level=True)


MODEL_PATH = Path("/Users/ayushmudgal/Developer/models/chronos-2")
MODEL_REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"


def test_official_model_manifest_hash_package_and_class():
    from chronos import Chronos2Pipeline

    assert version("chronos-forecasting") == "2.3.1"
    assert hashlib.sha256((MODEL_PATH / "model.safetensors").read_bytes()).hexdigest() == "ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42"
    pipeline = Chronos2Pipeline.from_pretrained(MODEL_PATH, device_map="cpu", local_files_only=True)
    assert type(pipeline).__name__ == "Chronos2Pipeline"


def test_genuine_offline_cpu_quantile_inference():
    from chronos import Chronos2Pipeline

    pipeline = Chronos2Pipeline.from_pretrained(MODEL_PATH, device_map="cpu", local_files_only=True)
    context = pd.DataFrame({"item_id": "NIFTY", "timestamp": pd.date_range("2026-07-10 09:15", periods=64, freq="5min"),
                            "target": np.linspace(24100, 24200, 64)})
    output = pipeline.predict_df(context, prediction_length=12, quantile_levels=[.1, .25, .5, .75, .9], freq="5min")
    assert len(output) == 12
    quantiles = ["0.1", "0.25", "0.5", "0.75", "0.9"]
    assert np.isfinite(output[quantiles].to_numpy()).all()
    assert all((output[left] <= output[right]).all() for left, right in zip(quantiles, quantiles[1:]))
