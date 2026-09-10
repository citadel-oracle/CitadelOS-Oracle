import math
from datetime import datetime, timezone


class CandleValidationError(ValueError):
    pass


def _timestamp(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raise CandleValidationError("timestamp must be epoch, ISO-8601, or datetime")


def validate_candles(candles, minimum_context=64, context_limit=512, now=None):
    if not isinstance(candles, list):
        raise CandleValidationError("candles must be a list")
    if len(candles) < minimum_context:
        raise CandleValidationError("insufficient closed-candle context")

    normalized = []
    for item in candles:
        if not isinstance(item, dict):
            raise CandleValidationError("every candle must be an object")
        if item.get("closed") is not True:
            raise CandleValidationError("only explicitly closed candles are accepted")
        timestamp = _timestamp(item.get("timestamp", item.get("time")))
        values = {}
        for field in ("open", "high", "low", "close"):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise CandleValidationError(f"{field} must be finite numeric")
            values[field] = float(value)
        if values["high"] < max(values.values()) or values["low"] > min(values.values()):
            raise CandleValidationError("invalid OHLC relationship")
        optional = {}
        for field in ("volume", "amount"):
            value = item.get(field)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise CandleValidationError(f"{field} must be finite numeric when supplied")
                optional[field] = float(value)
        normalized.append({"timestamp": timestamp, **values, **optional})

    normalized.sort(key=lambda candle: candle["timestamp"])
    timestamps = [candle["timestamp"] for candle in normalized]
    if len(timestamps) != len(set(timestamps)):
        raise CandleValidationError("duplicate candle timestamps")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if timestamps[-1] > reference:
        raise CandleValidationError("future candle timestamps are not accepted")
    return normalized[-context_limit:]
