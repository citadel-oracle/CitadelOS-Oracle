import math
from statistics import mean, median, pstdev


class ForecastValidationError(ValueError):
    pass


def normalize_paths(paths):
    if not isinstance(paths, list) or not paths:
        raise ForecastValidationError("at least one forecast path is required")
    normalized, horizon = [], None
    for path in paths:
        if not isinstance(path, list) or not path:
            raise ForecastValidationError("forecast path must contain candles")
        clean = []
        for candle in path:
            values = []
            for field in ("open", "high", "low", "close"):
                value = candle.get(field) if isinstance(candle, dict) else None
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ForecastValidationError("forecast OHLC must be finite numeric")
                values.append(float(value))
            open_, high, low, close = values
            clean.append({"open": open_, "high": max(high, open_, close, low), "low": min(low, open_, close, high), "close": close})
        horizon = horizon or len(clean)
        if len(clean) != horizon:
            raise ForecastValidationError("forecast paths must share one horizon")
        normalized.append(clean)
    return normalized


def _direction(value, threshold):
    return "BULLISH" if value > threshold else "BEARISH" if value < -threshold else "SIDEWAYS"


def _persistent(path, last_close, direction, threshold):
    closes = [last_close, *[item["close"] for item in path]]
    steps = [100 * (right / left - 1) for left, right in zip(closes, closes[1:])]
    final_return = 100 * (closes[-1] / last_close - 1)
    if _direction(final_return, threshold) != direction:
        return False
    if direction == "BULLISH":
        advancement = sum(step > 0 for step in steps) / len(steps)
        structure = sum(right["low"] >= left["low"] for left, right in zip(path, path[1:])) / max(1, len(path) - 1)
        adverse = 100 * (min(item["low"] for item in path) / last_close - 1)
    else:
        advancement = sum(step < 0 for step in steps) / len(steps)
        structure = sum(right["high"] <= left["high"] for left, right in zip(path, path[1:])) / max(1, len(path) - 1)
        adverse = 100 * (max(item["high"] for item in path) / last_close - 1)
    interruptions = sum(step * final_return < 0 for step in steps)
    late_share = abs(steps[-1]) / max(abs(final_return), 1e-9)
    return advancement >= 0.60 and structure >= 0.50 and abs(adverse) <= max(abs(final_return) * 0.60, threshold) and interruptions <= max(1, len(steps) // 3) and late_share <= 0.60


def _reversal(path, last_close, threshold):
    closes = [item["close"] for item in path]
    initial_index = max(1, len(closes) // 3)
    initial = closes[initial_index - 1]
    initial_return = 100 * (initial / last_close - 1)
    if abs(initial_return) <= threshold:
        return None
    if initial_return > 0:
        peak = max(closes)
        extension = 100 * (peak / last_close - 1)
        retracement = 100 * (peak - closes[-1]) / last_close
    else:
        trough = min(closes)
        extension = 100 * (last_close - trough) / last_close
        retracement = 100 * (closes[-1] - trough) / last_close
    meaningful = extension > threshold and retracement >= max(threshold, extension * 0.50)
    return ("BULLISH" if initial_return > 0 else "BEARISH", meaningful)


def derive_metrics(paths, last_close, timeframe_minutes=5, sideways_threshold_percentage=0.15):
    if not isinstance(last_close, (int, float)) or not math.isfinite(last_close) or last_close <= 0:
        raise ForecastValidationError("last close must be positive finite numeric")
    clean = normalize_paths(paths)
    if len(clean) < 2:
        raise ForecastValidationError("at least two valid paths are required for probabilities")
    threshold = abs(float(sideways_threshold_percentage))
    terminal_returns = [100 * (path[-1]["close"] / last_close - 1) for path in clean]
    directions = [_direction(value, threshold) for value in terminal_returns]
    counts = {name: directions.count(name) for name in ("BULLISH", "BEARISH", "SIDEWAYS")}
    probabilities = {name: counts[name] * 100 / len(clean) for name in counts}
    expected_return = mean(terminal_returns)
    dominant = max(counts, key=counts.get)

    direction_paths = {name: [path for path, value in zip(clean, directions) if value == name] for name in ("BULLISH", "BEARISH")}
    persistence = {}
    for name, selected in direction_paths.items():
        persistence[name] = None if len(selected) < 2 else sum(_persistent(path, last_close, name, threshold) for path in selected) * 100 / len(selected)

    reversal_observations = [_reversal(path, last_close, threshold) for path in clean]
    meaningful = [value for value in reversal_observations if value is not None]
    bullish_initial = [value for value in meaningful if value[0] == "BULLISH"]
    bearish_initial = [value for value in meaningful if value[0] == "BEARISH"]
    reversal = sum(value[1] for value in meaningful) * 100 / len(clean)
    bullish_reversal = None if not bullish_initial else sum(value[1] for value in bullish_initial) * 100 / len(bullish_initial)
    bearish_reversal = None if not bearish_initial else sum(value[1] for value in bearish_initial) * 100 / len(bearish_initial)

    step_returns, range_percentages = [], []
    for path in clean:
        closes = [last_close, *[item["close"] for item in path]]
        step_returns.extend(100 * (right / left - 1) for left, right in zip(closes, closes[1:]))
        range_percentages.extend(100 * (item["high"] - item["low"]) / last_close for item in path)
    dispersion = pstdev(terminal_returns) if len(terminal_returns) > 1 else 0.0
    volatility = mean(range_percentages) + pstdev(step_returns) * math.sqrt(len(clean[0]))
    disagreement = 100 - max(probabilities.values())
    quantile_width = max(terminal_returns) - min(terminal_returns)
    uncertainty_score = min(100.0, 0.5 * min(100, dispersion / max(threshold, 0.01) * 25) + 0.3 * disagreement + 0.2 * min(100, quantile_width / max(threshold * 4, 0.01) * 25))
    volatility_label = "LOW" if volatility < threshold else "MODERATE" if volatility < threshold * 3 else "HIGH" if volatility < threshold * 6 else "EXTREME"
    uncertainty_label = "LOW" if uncertainty_score < 25 else "MEDIUM" if uncertainty_score < 55 else "HIGH"
    ordered = sorted(terminal_returns)
    quantile = lambda fraction: ordered[round((len(ordered) - 1) * fraction)]
    dominant_persistence = persistence.get(dominant)
    return {
        "expected_direction": dominant,
        "bullish_probability": probabilities["BULLISH"],
        "bearish_probability": probabilities["BEARISH"],
        "sideways_probability": probabilities["SIDEWAYS"],
        "expected_return_percentage": expected_return,
        "median_return_percentage": median(terminal_returns),
        "expected_high": mean(max(item["high"] for item in path) for path in clean),
        "expected_low": mean(min(item["low"] for item in path) for path in clean),
        "forecast_volatility": volatility,
        "volatility_label": volatility_label,
        "trend_persistence_probability": dominant_persistence,
        "bullish_persistence_probability": persistence["BULLISH"],
        "bearish_persistence_probability": persistence["BEARISH"],
        "reversal_probability": reversal,
        "bullish_reversal_probability": bullish_reversal,
        "bearish_reversal_probability": bearish_reversal,
        "forecast_uncertainty": uncertainty_score,
        "uncertainty_label": uncertainty_label,
        "forecast_dispersion": dispersion,
        "upside_quantile": quantile(0.9),
        "downside_quantile": quantile(0.1),
        "valid_path_count": len(clean),
        "path_count": len(clean),
        "horizon_candles": len(clean[0]),
        "horizon_minutes": len(clean[0]) * timeframe_minutes,
    }
