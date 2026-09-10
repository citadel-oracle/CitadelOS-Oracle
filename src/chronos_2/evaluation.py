from __future__ import annotations

from datetime import datetime, timezone


class ChronosRealizationEvaluator:
    def __init__(self, ledger):
        self.ledger = ledger

    def evaluate(self, candles, now=None):
        ordered = sorted(candles, key=lambda item: item["timestamp"])
        evaluated = {item["forecast_id"] for item in self.ledger.evaluations()}
        completed = []
        for forecast in self.ledger.forecasts():
            if forecast["forecast_id"] in evaluated:
                continue
            future = [item for item in ordered if item["timestamp"] > forecast["context_end"]]
            if len(future) < forecast["prediction_length"]:
                continue
            realized = future[:forecast["prediction_length"]]
            rows = forecast["forecast_rows"]
            origin = forecast["forecast_origin"]
            actual = [item["close"] for item in realized]
            terminal = actual[-1]
            p50 = [item["p50"] for item in rows]
            terminal_direction = "BULLISH" if terminal > origin else "BEARISH" if terminal < origin else "SIDEWAYS"
            predicted = forecast.get("derived_analytics", {}).get("directional_bias")
            evaluation = {
                "forecast_id": forecast["forecast_id"], "evaluated_at": (now or datetime.now(timezone.utc)).isoformat(),
                "terminal_p50_absolute_error": abs(terminal - p50[-1]),
                "terminal_p50_percentage_error": abs(terminal - p50[-1]) / terminal * 100 if terminal else None,
                "median_path_mae": sum(abs(value - p50[index]) for index, value in enumerate(actual)) / len(actual),
                "directional_result": terminal_direction, "directional_correct": predicted == terminal_direction,
                "p10_p90_interval_coverage": 100 * sum(row["p10"] <= actual[index] <= row["p90"] for index, row in enumerate(rows)) / len(rows),
                "p25_p75_interval_coverage": 100 * sum(row["p25"] <= actual[index] <= row["p75"] for index, row in enumerate(rows)) / len(rows),
                "observed_high_within_forecast_range": max(item["high"] for item in realized) <= forecast["forecast_high"],
                "observed_low_within_forecast_range": min(item["low"] for item in realized) >= forecast["forecast_low"],
                "persistence_correct": _persistence(actual, origin) >= 60 if (forecast.get("derived_analytics", {}).get("trend_persistence") or 0) >= 60 else None,
                "reversal_observed": _reversal(actual, origin),
                "ce_quality_directional_outcome": terminal > origin if forecast.get("derived_analytics", {}).get("ce_quality", {}).get("score") is not None else None,
                "pe_quality_directional_outcome": terminal < origin if forecast.get("derived_analytics", {}).get("pe_quality", {}).get("score") is not None else None,
            }
            if self.ledger.append_evaluation(evaluation):
                completed.append(evaluation)
        return completed

    def summary(self):
        rows = self.ledger.evaluations()
        count = len(rows)
        maturity = "COLLECTING" if count < 20 else "PRELIMINARY" if count < 50 else "STABLE" if count < 100 else "MATURE"
        return {"status": "available", "evaluated_forecasts": count, "maturity": maturity,
                "directional_accuracy": None if not count else 100 * sum(bool(row["directional_correct"]) for row in rows) / count,
                "median_absolute_error": None if not count else sum(row["median_path_mae"] for row in rows) / count,
                "p10_p90_coverage": None if not count else sum(row["p10_p90_interval_coverage"] for row in rows) / count,
                "warning": "INSUFFICIENT_COMPARABLE_SAMPLE" if count < 20 else None}


def _persistence(values, origin):
    bullish = values[-1] > origin
    return 100 * sum(value > origin if bullish else value < origin for value in values) / len(values)


def _reversal(values, origin):
    changes = [values[index] - (origin if index == 0 else values[index - 1]) for index in range(len(values))]
    return any(changes[index] * changes[index - 1] < 0 for index in range(1, len(changes)))
