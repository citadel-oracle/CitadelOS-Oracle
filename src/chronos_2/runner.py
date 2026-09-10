"""Isolated genuine Chronos2Pipeline runner; communicates through bounded JSON files."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

QUANTILE_COLUMNS = (("0.1", "p10"), ("0.25", "p25"), ("0.5", "p50"), ("0.75", "p75"), ("0.9", "p90"))


class PersistentChronosModel:
    def __init__(self, model_path, device):
        from chronos import Chronos2Pipeline

        started = time.perf_counter()
        self.pipeline = Chronos2Pipeline.from_pretrained(str(model_path), device_map=device, local_files_only=True)
        self.load_duration_ms = (time.perf_counter() - started) * 1000
        self.device = device

    def forecast(self, request):
        rows = request["rows"]
        feature_names = request.get("feature_names") or []
        columns = ["item_id", "timestamp", "target", *feature_names]
        # Chronos receives a contiguous positional series. Genuine exchange
        # timestamps remain in request lineage and are restored only after the
        # shared NSE session mapper creates valid output positions.
        regular = pd.date_range("2000-01-01", periods=len(rows), freq="5min")
        records = []
        for index, row in enumerate(rows):
            record = {"item_id": request["symbol"], "timestamp": regular[index], "target": float(row["target"])}
            for name in feature_names:
                record[name] = float(row[name])
            records.append(record)
        frame = pd.DataFrame(records, columns=columns)
        started = time.perf_counter()
        output = self.pipeline.predict_df(
            frame, prediction_length=int(request["prediction_length"]),
            quantile_levels=[0.10, 0.25, 0.50, 0.75, 0.90], freq="5min",
        )
        completed = time.perf_counter()
        forecast_rows = []
        expected_timestamps = request["future_timestamps"]
        if len(output) != len(expected_timestamps):
            raise ValueError("FORECAST_LENGTH_MISMATCH")
        for index, (_, raw) in enumerate(output.iterrows()):
            item = {"timestamp": expected_timestamps[index]}
            previous = None
            for column, name in QUANTILE_COLUMNS:
                value = float(raw[column])
                if not math.isfinite(value) or previous is not None and value < previous:
                    raise ValueError("INVALID_QUANTILE_ORDER")
                item[name] = value
                previous = value
            forecast_rows.append(item)
        return {
            "status": "READY", "device": self.device, "model_class": type(self.pipeline).__name__,
            "model_load_duration_ms": round(self.load_duration_ms, 3),
            "inference_duration_ms": round((completed - started) * 1000, 3),
            "input_feature_names": list(feature_names),
            "mode": request.get("mode"),
            "input_coverage": request.get("input_coverage"),
            "forecast_rows": forecast_rows,
        }


def run(request, model_path, device):
    return PersistentChronosModel(model_path, device).forecast(request)


def serve(model_path, device):
    import sys

    model = PersistentChronosModel(model_path, device)
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
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--device", default="cpu", choices=("cpu", "mps"))
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()
    if os.environ.get("CITADEL_CHRONOS_2_ENABLED", "0") != "1":
        raise SystemExit("CHRONOS_2_DISABLED_BY_CONFIGURATION")
    if args.stdio:
        serve(Path(args.model_path), args.device)
        return
    if not args.input or not args.output:
        parser.error("--input and --output are required without --stdio")
    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run(request, Path(args.model_path), args.device)
    temporary = Path(args.output).with_suffix(".tmp")
    temporary.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, args.output)


if __name__ == "__main__":
    main()
