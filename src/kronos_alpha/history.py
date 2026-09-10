import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


class ForecastHistoryLedger:
    SCHEMA_VERSION = 1

    def __init__(self, path="logs/kronos_alpha_history.json", retention=500):
        self.path = Path(path)
        self.retention = max(10, min(2000, int(retention)))

    def append_forecast(self, result):
        document = self._read()
        forecast_id = result.get("forecast_id") or hashlib.sha256(f'{result.get("model_revision")}|{result.get("symbol")}|{result.get("timeframe")}|{result.get("input_fingerprint")}'.encode()).hexdigest()[:24]
        if any(item.get("forecast_id") == forecast_id for item in document["forecasts"]):
            return forecast_id, False
        record = {
            "forecast_id": forecast_id,
            "generated_at": result["generated_at"],
            "session_state": result.get("session", {}).get("session_state"),
            "symbol": result["symbol"],
            "timeframe": result["timeframe"],
            "model_revision": result["model_revision"],
            "tokenizer_revision": result["tokenizer_revision"],
            "input_fingerprint": result["input_fingerprint"],
            "last_candle_timestamp": result["last_input_candle_at"],
            "context_count": result["input_candle_count"],
            "horizon": result["horizon_candles"],
            "path_count": result["valid_path_count"],
            "bullish_probability": result["bullish_probability"],
            "bearish_probability": result["bearish_probability"],
            "sideways_probability": result["sideways_probability"],
            "bullish_persistence": result.get("bullish_persistence_probability"),
            "bearish_persistence": result.get("bearish_persistence_probability"),
            "reversal_probability": result["reversal_probability"],
            "forecast_volatility": result["forecast_volatility"],
            "forecast_uncertainty": result["forecast_uncertainty"],
            "expected_return_percentage": result["expected_return_percentage"],
            "expected_high": result["expected_high"],
            "expected_low": result["expected_low"],
            "ce_quality_score": result.get("outlooks", {}).get("ce", {}).get("option_buying_quality_score"),
            "pe_quality_score": result.get("outlooks", {}).get("pe", {}).get("option_buying_quality_score"),
            "forecast_quality_score": result.get("outlooks", {}).get("forecast_quality_score"),
            "input_source": result.get("source_metadata", {}).get("source"),
            "freshness": result.get("input_metadata", {}).get("freshness"),
            "evaluation_status": "PENDING",
        }
        document["forecasts"].append(record)
        document["forecasts"] = document["forecasts"][-self.retention:]
        self._write(document)
        return forecast_id, True

    def append_evaluation(self, evaluation):
        document = self._read()
        forecast_id = evaluation["forecast_id"]
        if any(item.get("forecast_id") == forecast_id for item in document["evaluations"]):
            return False
        if not any(item.get("forecast_id") == forecast_id for item in document["forecasts"]):
            return False
        document["evaluations"].append(deepcopy(evaluation))
        document["evaluations"] = document["evaluations"][-self.retention:]
        self._write(document)
        return True

    def pending(self):
        document = self._read()
        evaluated = {item["forecast_id"] for item in document["evaluations"]}
        return [deepcopy(item) for item in document["forecasts"] if item["forecast_id"] not in evaluated]

    def payload(self, limit=50):
        document = self._read()
        return {"schema_version": self.SCHEMA_VERSION, "count": len(document["forecasts"]), "forecasts": deepcopy(document["forecasts"][-max(1, min(100, limit)):]), "evaluation_count": len(document["evaluations"])}

    def evaluations(self):
        return deepcopy(self._read()["evaluations"])

    def _read(self):
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("schema_version") != self.SCHEMA_VERSION or not isinstance(document.get("forecasts"), list) or not isinstance(document.get("evaluations"), list):
                raise ValueError("invalid history schema")
            return document
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"schema_version": self.SCHEMA_VERSION, "forecasts": [], "evaluations": []}

    def _write(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.path)


class RealizationEvaluator:
    def __init__(self, ledger, minimum_mature_sample=100):
        self.ledger = ledger
        self.minimum_mature_sample = minimum_mature_sample

    def evaluate(self, candles, now=None):
        ordered = sorted(candles, key=lambda item: item["timestamp"])
        completed = []
        for forecast in self.ledger.pending():
            future = [item for item in ordered if item["timestamp"] > forecast["last_candle_timestamp"]]
            if len(future) < forecast["horizon"]:
                continue
            realized = future[:forecast["horizon"]]
            last_input = next((item for item in reversed(ordered) if item["timestamp"] == forecast["last_candle_timestamp"]), None)
            if last_input is None:
                continue
            realized_return = 100 * (realized[-1]["close"] / last_input["close"] - 1)
            threshold = 0.15
            direction = "BULLISH" if realized_return > threshold else "BEARISH" if realized_return < -threshold else "SIDEWAYS"
            evaluation = {
                "forecast_id": forecast["forecast_id"],
                "evaluated_at": (now or datetime.now(timezone.utc)).isoformat(),
                "realized_return_percentage": realized_return,
                "realized_direction": direction,
                "directional_correct": direction == max(("BULLISH", "BEARISH", "SIDEWAYS"), key=lambda name: forecast[f"{name.lower()}_probability"]),
                "forecast_error_percentage_points": abs(realized_return - forecast["expected_return_percentage"]),
                "expected_high_covered": max(item["high"] for item in realized) >= forecast["expected_high"],
                "expected_low_covered": min(item["low"] for item in realized) <= forecast["expected_low"],
                "ce_alignment_outcome": realized_return > 0 if forecast["ce_quality_score"] is not None else None,
                "pe_alignment_outcome": realized_return < 0 if forecast["pe_quality_score"] is not None else None,
            }
            if self.ledger.append_evaluation(evaluation):
                completed.append(evaluation)
        return completed

    def summary(self):
        evaluations = self.ledger.evaluations()
        count = len(evaluations)
        if not count:
            return {"evaluated_forecasts": 0, "directional_hit_rate": None, "average_forecast_error": None, "calibration_status": "INSUFFICIENT_SAMPLE", "sample_warning": "No completed forecast horizons are available."}
        label = "MATURE" if count >= self.minimum_mature_sample else "PRELIMINARY" if count >= 20 else "EARLY_EVALUATION"
        return {
            "evaluated_forecasts": count,
            "directional_hit_rate": 100 * sum(item["directional_correct"] for item in evaluations) / count,
            "average_forecast_error": sum(item["forecast_error_percentage_points"] for item in evaluations) / count,
            "calibration_status": label,
            "sample_warning": None if label == "MATURE" else "Small sample; calibration remains pending.",
        }
