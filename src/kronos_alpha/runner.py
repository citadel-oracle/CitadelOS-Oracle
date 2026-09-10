"""Persistent isolated official-model runner. HTTP routes never call it."""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.futures_forecast.math import ForecastValidationError, representative_ohlc_path, validate_ohlc_path


class PersistentKronosModel:
    """Load the certified official model once, then serve finalized contexts."""

    def __init__(self, source_root, model_path, tokenizer_path, device="cpu"):
        import torch

        sys.path.insert(0, str(source_root))
        from model import Kronos, KronosPredictor, KronosTokenizer

        started = time.perf_counter()
        tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_path)).eval()
        model = Kronos.from_pretrained(str(model_path)).eval()
        self.predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
        self.model_load_duration_ms = (time.perf_counter() - started) * 1000
        self.device = device
        self.torch = torch

    def forecast(self, request):
        import numpy as np
        import pandas as pd

        from .metrics import derive_metrics
        from .validation import validate_candles

        context = validate_candles(request["candles"], minimum_context=request.get("minimum_context", 64), context_limit=512)
        frame = pd.DataFrame([{key: candle[key] for key in ("open", "high", "low", "close", "volume", "amount") if key in candle} for candle in context])
        # The official model receives a regular position index; exchange gaps
        # remain only in immutable lineage and in the shared output mapper.
        timestamps = pd.Series(pd.date_range("2000-01-01", periods=len(context), freq="5min"))
        horizon = int(request.get("forecast_horizon", 6))
        future = pd.Series(pd.date_range(timestamps.iloc[-1] + pd.Timedelta(minutes=5), periods=horizon, freq="5min"))
        started = time.perf_counter()
        paths = []
        rejected_paths = 0
        for seed in range(int(request.get("sample_count", 8))):
            self.torch.manual_seed(seed)
            if self.device == "mps":
                self.torch.mps.manual_seed(seed)
            with self.torch.inference_mode():
                prediction = self.predictor.predict(frame, timestamps, future, horizon, T=1.0, top_p=0.9, sample_count=1, verbose=False)
            if not np.isfinite(prediction.to_numpy()).all():
                raise ValueError("official model returned non-finite output")
            candidate = prediction[["open", "high", "low", "close"]].to_dict("records")
            try:
                paths.append(validate_ohlc_path(candidate, horizon))
            except ForecastValidationError:
                rejected_paths += 1
        duration = (time.perf_counter() - started) * 1000
        selected = representative_ohlc_path(paths, context[-1]["close"])
        metrics = derive_metrics(paths, context[-1]["close"], timeframe_minutes=5, sideways_threshold_percentage=request.get("sideways_threshold_percentage", 0.15))
        generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        fingerprint = hashlib.sha256(json.dumps([{**candle, "timestamp": candle["timestamp"].isoformat()} for candle in context], sort_keys=True).encode()).hexdigest()
        return {
            "generated_at": generated,
            "model_status": "READY",
            "model_name": "NeoQuasar/Kronos-small",
            "model_revision": "901c26c1332695a2a8f243eb2f37243a37bea320",
            "device": self.device,
            "symbol": request.get("symbol", "NIFTY FUTURES"),
            "timeframe": "5m",
            "input_candle_count": len(context),
            "input_fingerprint": fingerprint,
            "last_input_candle_at": context[-1]["timestamp"].isoformat(),
            "last_inference_at": generated,
            "model_load_duration_ms": round(self.model_load_duration_ms, 3),
            "inference_duration_ms": round(duration, 3),
            "cache_status": "READY",
            "raw_paths": paths,
            "raw_path_count": len(paths),
            "requested_sample_count": int(request.get("sample_count", 8)),
            "rejected_ohlc_path_count": rejected_paths,
            **{key: value for key, value in selected.items() if key != "representative_path"},
            "representative_path": selected["representative_path"],
            **metrics,
            "reason_codes": ["KRONOS_FUTURES_FORECAST_READY", "EXECUTION_INFLUENCE_ZERO", "CLOSED_CANDLES_ONLY", "ADVISORY_ONLY"],
            "warnings": [],
            "missing_inputs": [],
            "source_metadata": {"source": request.get("source", "UNAVAILABLE"), "fixture_data": False, "external_refresh_on_read": False},
        }


def run_forecast(request, source_root, model_path, tokenizer_path, device="cpu"):
    return PersistentKronosModel(source_root, model_path, tokenizer_path, device).forecast(request)


def serve(source_root, model_path, tokenizer_path, device):
    model = PersistentKronosModel(source_root, model_path, tokenizer_path, device)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("command") == "STOP":
                return
            result = model.forecast(request)
        except Exception as exc:
            result = {"status": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}
        print("CITADEL_RESULT\t" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--tokenizer-path", required=True)
    parser.add_argument("--device", choices=("mps", "cpu"), default="cpu")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()
    if args.stdio:
        serve(args.source_root, args.model_path, args.tokenizer_path, args.device)
        return
    if not args.input or not args.output:
        parser.error("--input and --output are required without --stdio")
    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run_forecast(request, args.source_root, args.model_path, args.tokenizer_path, args.device)
    Path(args.output).write_text(json.dumps(result, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
