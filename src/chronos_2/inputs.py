from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from statistics import pstdev
from zoneinfo import ZoneInfo

from src.market.session_calendar import NSESessionCalendar


IST = ZoneInfo("Asia/Kolkata")
MODEL_FEATURES = ("open", "high", "low", "volume", "realized_volatility", "atr_normalized")


class ChronosInputError(ValueError):
    pass


def validate_closed_candles(candles, *, minimum=64, limit=256, now=None):
    if not isinstance(candles, list):
        raise ChronosInputError("CANDLES_MALFORMED")
    reference = now or datetime.now(IST)
    reference = reference.replace(tzinfo=IST) if reference.tzinfo is None else reference.astimezone(IST)
    normalized = []
    seen = set()
    previous = None
    for raw in candles[-limit:]:
        if not isinstance(raw, dict) or raw.get("closed") is not True or raw.get("is_closed") is not True:
            raise ChronosInputError("INCOMPLETE_CANDLE")
        timestamp = datetime.fromisoformat(str(raw.get("timestamp")).replace("Z", "+00:00"))
        timestamp = timestamp.replace(tzinfo=IST) if timestamp.tzinfo is None else timestamp.astimezone(IST)
        closed_at = datetime.fromisoformat(str(raw.get("candle_closed_at")).replace("Z", "+00:00"))
        closed_at = closed_at.replace(tzinfo=IST) if closed_at.tzinfo is None else closed_at.astimezone(IST)
        if timestamp.isoformat() in seen:
            raise ChronosInputError("DUPLICATE_CANDLE")
        if previous is not None and timestamp <= previous:
            raise ChronosInputError("UNSORTED_CANDLES")
        if closed_at > reference:
            raise ChronosInputError("LOOK_AHEAD_CANDLE")
        values = {}
        for name in ("open", "high", "low", "close"):
            value = float(raw.get(name))
            if not math.isfinite(value):
                raise ChronosInputError("NON_FINITE_CANDLE")
            values[name] = value
        if values["high"] < max(values.values()) or values["low"] > min(values.values()):
            raise ChronosInputError("INVALID_OHLC")
        volume = raw.get("volume")
        volume = float(volume) if isinstance(volume, (int, float)) and math.isfinite(float(volume)) else None
        normalized.append({**raw, **values, "volume": volume, "timestamp": timestamp.isoformat(), "candle_closed_at": closed_at.isoformat()})
        seen.add(timestamp.isoformat())
        previous = timestamp
    if len(normalized) < minimum:
        raise ChronosInputError("CONTEXT_INSUFFICIENT")
    return normalized


def build_model_rows(candles):
    closes = [item["close"] for item in candles]
    rows = []
    for index, item in enumerate(candles):
        returns = [closes[pos] / closes[pos - 1] - 1 for pos in range(max(1, index - 11), index + 1)]
        realized = pstdev(returns) if len(returns) > 1 else 0.0
        true_ranges = []
        for pos in range(max(0, index - 13), index + 1):
            previous_close = closes[pos - 1] if pos else closes[pos]
            true_ranges.append(max(item2 := candles[pos]["high"] - candles[pos]["low"], abs(candles[pos]["high"] - previous_close), abs(candles[pos]["low"] - previous_close)))
        atr_normalized = (sum(true_ranges) / len(true_ranges)) / item["close"] if item["close"] else 0.0
        rows.append({
            "timestamp": item["timestamp"], "target": item["close"], "open": item["open"],
            "high": item["high"], "low": item["low"], "volume": item["volume"],
            "realized_volatility": realized, "atr_normalized": atr_normalized,
        })
    available = [name for name in MODEL_FEATURES if all(row.get(name) is not None for row in rows)]
    mode = "MULTIVARIATE" if len(available) >= 4 else "UNIVARIATE"
    selected = available if mode == "MULTIVARIATE" else []
    coverage = round(100 * len(available) / len(MODEL_FEATURES), 2)
    return rows, mode, selected, coverage


def future_timestamps(origin, count, calendar=None):
    calendar = calendar or NSESessionCalendar()
    current = datetime.fromisoformat(str(origin).replace("Z", "+00:00"))
    current = current.replace(tzinfo=IST) if current.tzinfo is None else current.astimezone(IST)
    output = []
    candidate = current + timedelta(minutes=5)
    while len(output) < count:
        session = calendar.session_for_date(candidate.date())
        if session["session_state"] in {"OPEN", "SPECIAL_SESSION"}:
            opening = datetime.fromisoformat(session["scheduled_open"])
            closing = datetime.fromisoformat(session["scheduled_close"])
            if candidate < opening:
                candidate = opening
            if opening <= candidate < closing:
                output.append(candidate.isoformat())
                candidate += timedelta(minutes=5)
                continue
        next_open = session.get("next_valid_open") or calendar.status(candidate).get("next_valid_open")
        if not next_open:
            raise ChronosInputError("FUTURE_SESSION_UNAVAILABLE")
        candidate = datetime.fromisoformat(next_open)
    return output


def input_fingerprint(candles, feature_names, model_revision):
    value = {"model_revision": model_revision, "features": list(feature_names), "candles": [
        {key: item.get(key) for key in ("timestamp", "open", "high", "low", "close", "volume")}
        for item in candles
    ]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recent_volatility_points(candles):
    closes = [item["close"] for item in candles[-20:]]
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    return pstdev(changes) if len(changes) > 1 else None


def argus_features(projection):
    if not isinstance(projection, dict):
        return {"status": "UNAVAILABLE", "features": {}, "coverage": 0.0, "reason": "ARGUS_CACHE_UNAVAILABLE"}
    data = projection.get("data") if isinstance(projection.get("data"), dict) else {}
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
    walls = data.get("walls") if isinstance(data.get("walls"), dict) else {}
    verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
    features = {
        "total_ce_oi": totals.get("ce_oi"), "total_pe_oi": totals.get("pe_oi"),
        "total_ce_change_oi": totals.get("intraday_ce_change_oi"), "total_pe_change_oi": totals.get("intraday_pe_change_oi"),
        "aggregate_pcr": totals.get("pcr"), "call_wall": _level(walls.get("highest_ce_oi")),
        "put_wall": _level(walls.get("highest_pe_oi")), "writer_bias": verdict.get("bias"),
        "preferred_option_side": verdict.get("preferred_option_side"), "confidence": verdict.get("confidence"),
    }
    present = sum(value is not None for value in features.values())
    return {"status": str(projection.get("freshness") or projection.get("status") or "UNAVAILABLE").upper(),
            "features": features, "coverage": round(100 * present / len(features), 2),
            "reason": "CURRENT_SNAPSHOT_NOT_HISTORICAL_SEQUENCE", "timestamp": (data.get("underlying") or {}).get("fetched_at")}


def _level(value):
    return value.get("strike") if isinstance(value, dict) else None
