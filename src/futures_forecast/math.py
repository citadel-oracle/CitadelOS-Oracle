"""Pure forecast selection and validation helpers."""

from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence


class ForecastValidationError(ValueError):
    """Raised when model output cannot be published safely."""


def finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ForecastValidationError(f"{field}_INVALID")
    result = float(value)
    if not math.isfinite(result):
        raise ForecastValidationError(f"{field}_NON_FINITE")
    return result


def validate_ohlc_path(path: Sequence[Mapping[str, Any]], horizon: int | None = None) -> list[dict[str, float]]:
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)) or not path:
        raise ForecastValidationError("KRONOS_PATH_EMPTY")
    if horizon is not None and len(path) != horizon:
        raise ForecastValidationError("KRONOS_PATH_LENGTH_MISMATCH")
    result = []
    for raw in path:
        row = {name: finite_number(raw.get(name), f"KRONOS_{name.upper()}") for name in ("open", "high", "low", "close")}
        if row["high"] < max(row["open"], row["close"]) or row["low"] > min(row["open"], row["close"]):
            raise ForecastValidationError("KRONOS_OHLC_INVARIANT_FAILED")
        result.append(row)
    return result


def representative_ohlc_path(paths: Sequence[Sequence[Mapping[str, Any]]], source_close: float | None = None) -> dict[str, Any]:
    """Choose a genuine sampled path nearest the coordinate-wise median closes."""
    if not paths:
        raise ForecastValidationError("KRONOS_RAW_PATHS_EMPTY")
    validated = [validate_ohlc_path(path) for path in paths]
    horizon = len(validated[0])
    if any(len(path) != horizon for path in validated):
        raise ForecastValidationError("KRONOS_RAW_PATH_LENGTH_MISMATCH")
    median_close = [median(path[index]["close"] for path in validated) for index in range(horizon)]
    scale = max(1e-9, median(abs(value) for value in median_close))
    distances = [
        sum(((row["close"] - median_close[index]) / scale) ** 2 for index, row in enumerate(path)) / horizon
        for path in validated
    ]
    index = min(range(len(distances)), key=lambda value: (distances[value], value))
    terminals = [path[-1]["close"] for path in validated]
    source_close = validated[0][0]["open"] if source_close is None else finite_number(source_close, "KRONOS_SOURCE_CLOSE")
    terminal_median = median(terminals)
    dispersion = median(abs(value - terminal_median) for value in terminals)
    return {
        "representative_path_id": index,
        "representative_path": validated[index],
        "median_close_trajectory": median_close,
        "normalized_distance": distances[index],
        "sample_count": len(validated),
        "terminal_above_source_count": sum(value > source_close for value in terminals),
        "terminal_below_source_count": sum(value < source_close for value in terminals),
        "terminal_above_source_share": sum(value > source_close for value in terminals) / len(terminals),
        "terminal_below_source_share": sum(value < source_close for value in terminals) / len(terminals),
        "terminal_dispersion": dispersion,
    }


def validate_quantile_matrix(values: Any, *, quantile_count: int, horizon: int) -> list[list[float]]:
    if not isinstance(values, list) or len(values) != quantile_count:
        raise ForecastValidationError("FORECAST_QUANTILE_SHAPE_INVALID")
    matrix: list[list[float]] = []
    for row in values:
        if not isinstance(row, list) or len(row) != horizon:
            raise ForecastValidationError("FORECAST_QUANTILE_SHAPE_INVALID")
        matrix.append([finite_number(value, "FORECAST_QUANTILE") for value in row])
    for index in range(horizon):
        column = [row[index] for row in matrix]
        if column != sorted(column):
            raise ForecastValidationError("FORECAST_QUANTILE_ORDER_INVALID")
    return matrix
