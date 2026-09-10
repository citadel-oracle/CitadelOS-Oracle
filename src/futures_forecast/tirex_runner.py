"""Persistent isolated open-source NX-AI/TiRex-2 CPU worker."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time


MODEL = "NX-AI/TiRex-2"
MODEL_REVISION = "05e5b26db52bfb256f1ae1bdf785589850482de3"
PACKAGE_VERSION = "0.1.1"


class TiRexWorkerModel:
    def __init__(self, device: str = "cpu"):
        import torch
        from tirex2 import load_model

        self.device = device
        started = time.perf_counter()
        self.model = load_model(MODEL, device=device, hf_kwargs={"revision": MODEL_REVISION, "local_files_only": True})
        self.load_duration_ms = (time.perf_counter() - started) * 1000
        self.quantile_levels = [round(float(value), 6) for value in self.model.model.quantiles]
        self.torch = torch

    def forecast(self, request):
        from tirex2 import TimeseriesType

        values = [float(value) for value in request["closes"]]
        if len(values) < 64 or any(not math.isfinite(value) for value in values):
            raise ValueError("TIREX_CONTEXT_INVALID")
        target = self.torch.tensor(values, dtype=self.torch.float32).unsqueeze(0)
        series = TimeseriesType(target=target, past_covariates=None, future_covariates=None)
        started = time.perf_counter()
        raw = self.model.forecast([series], prediction_length=int(request["prediction_length"]), output_type="numpy")[0]
        duration = (time.perf_counter() - started) * 1000
        if tuple(raw.shape) != (1, 9, int(request["prediction_length"])):
            raise ValueError("TIREX_OUTPUT_SHAPE_INVALID")
        return {
            "status": "READY",
            "model": MODEL,
            "model_revision": MODEL_REVISION,
            "package_version": PACKAGE_VERSION,
            "device": self.device,
            "dtype": "float32",
            "model_load_duration_ms": round(self.load_duration_ms, 3),
            "inference_duration_ms": round(duration, 3),
            "quantile_levels": self.quantile_levels,
            "raw_shape": list(raw.shape),
            "quantiles": raw[0].tolist(),
        }


def serve(device: str) -> None:
    model = TiRexWorkerModel(device)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("command") == "STOP":
                return
            result = model.forecast(request)
        except Exception as exc:
            result = {"status": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}
        print("CITADEL_RESULT\t" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    args = parser.parse_args()
    if not args.stdio:
        raise SystemExit("TiRex worker requires --stdio")
    if os.environ.get("CITADEL_TIREX_ENABLED", "0") != "1":
        raise SystemExit("TIREX_DISABLED_BY_CONFIGURATION")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    serve(args.device)


if __name__ == "__main__":
    main()
