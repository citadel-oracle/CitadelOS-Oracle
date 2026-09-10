from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path


class ChronosStorageError(RuntimeError):
    pass


class AtomicJsonDocument:
    def __init__(self, path, schema_version=1):
        self.path = Path(path)
        self.schema_version = schema_version

    def read(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ChronosStorageError("CHRONOS_STORAGE_CORRUPT") from error
        if not isinstance(value, dict) or value.get("schema_version") != self.schema_version:
            raise ChronosStorageError("CHRONOS_STORAGE_SCHEMA_INVALID")
        return value

    def write(self, value):
        document = {"schema_version": self.schema_version, **deepcopy(value)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(document, handle, sort_keys=True, separators=(",", ":"))
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            raise ChronosStorageError("CHRONOS_STORAGE_WRITE_FAILED") from error
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return document


class ForecastLedger:
    def __init__(self, path, retention=500):
        self.document = AtomicJsonDocument(path)
        self.retention = max(20, min(2000, int(retention)))

    def _read(self):
        value = self.document.read()
        if value is None:
            return {"schema_version": 1, "forecasts": [], "evaluations": []}
        if not isinstance(value.get("forecasts"), list) or not isinstance(value.get("evaluations"), list):
            raise ChronosStorageError("CHRONOS_LEDGER_SCHEMA_INVALID")
        return value

    def append_forecast(self, forecast):
        value = self._read()
        forecast_id = forecast.get("forecast_id") or hashlib.sha256(
            f'{forecast.get("model_revision")}|{forecast.get("symbol")}|{forecast.get("timeframe")}|{forecast.get("input_fingerprint")}|{forecast.get("mode")}'.encode()
        ).hexdigest()[:24]
        if any(item.get("forecast_id") == forecast_id for item in value["forecasts"]):
            return forecast_id, False
        record = deepcopy(forecast)
        record["forecast_id"] = forecast_id
        record["realization_status"] = "PENDING"
        value["forecasts"] = [*value["forecasts"], record][-self.retention:]
        self.document.write(value)
        return forecast_id, True

    def append_evaluation(self, evaluation):
        value = self._read()
        forecast_id = evaluation["forecast_id"]
        if any(item.get("forecast_id") == forecast_id for item in value["evaluations"]):
            return False
        original = next((item for item in value["forecasts"] if item.get("forecast_id") == forecast_id), None)
        if original is None:
            return False
        value["evaluations"] = [*value["evaluations"], deepcopy(evaluation)][-self.retention:]
        self.document.write(value)
        return True

    def forecasts(self):
        return deepcopy(self._read()["forecasts"])

    def evaluations(self):
        return deepcopy(self._read()["evaluations"])

    def history(self, limit=50):
        value = self._read()
        bounded = max(1, min(100, int(limit)))
        return {"status": "available", "count": len(value["forecasts"]), "forecasts": deepcopy(value["forecasts"][-bounded:]),
                "evaluation_count": len(value["evaluations"]), "schema_version": 1}
