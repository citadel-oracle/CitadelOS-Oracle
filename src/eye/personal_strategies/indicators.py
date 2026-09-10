"""Deterministic Indicator Parity Engine for CITADEL Personal Strategies."""

import math
from typing import List, Dict, Tuple, Optional, Any



def compute_rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Wilder's Smoothing RSI calculation."""
    if len(closes) < period + 1:
        return [None] * len(closes)

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    rsi_values = [None] * (period)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(round(100.0 - (100.0 / (1.0 + rs)), 2))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(round(100.0 - (100.0 / (1.0 + rs)), 2))

    return rsi_values


def compute_bollinger_bands(
    closes: List[float], period: int = 20, num_std: float = 2.0
) -> List[Optional[Dict[str, float]]]:
    """Bollinger Bands (Middle, Upper, Lower, BBW, %b)."""
    results: List[Optional[Dict[str, float]]] = [None] * (period - 1)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(variance)

        upper = sma + (num_std * std)
        lower = sma - (num_std * std)
        bbw = ((upper - lower) / sma * 100.0) if sma > 0 else 0.0
        pct_b = ((closes[i] - lower) / (upper - lower)) if (upper - lower) > 0 else 0.5

        results.append({
            "middle": round(sma, 2),
            "upper": round(upper, 2),
            "lower": round(lower, 2),
            "std": round(std, 2),
            "bbw": round(bbw, 2),
            "pct_b": round(pct_b, 4),
        })

    return results


def compute_ema(closes: List[float], period: int = 15) -> List[Optional[float]]:
    """Exponential Moving Average."""
    if len(closes) < period:
        return [None] * len(closes)

    results: List[Optional[float]] = [None] * (period - 1)
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    results.append(round(ema, 2))

    for i in range(period, len(closes)):
        ema = (closes[i] * k) + (ema * (1.0 - k))
        results.append(round(ema, 2))

    return results


def compute_atr(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> List[Optional[float]]:
    """Average True Range (ATR)."""
    if len(closes) < period + 1:
        return [None] * len(closes)

    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)

    results: List[Optional[float]] = [None] * period
    atr = sum(tr_list[:period]) / period
    results.append(round(atr, 2))

    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        results.append(round(atr, 2))

    return results


def compute_supertrend(
    highs: List[float], lows: List[float], closes: List[float], period: int = 10, multiplier: float = 2.0
) -> List[Optional[Dict[str, Any]]]:
    """Supertrend indicator (10, 2)."""
    atr_vals = compute_atr(highs, lows, closes, period)
    results: List[Optional[Dict[str, Any]]] = [None] * len(closes)

    if len(closes) < period + 1:
        return results

    upper_band = 0.0
    lower_band = 0.0
    in_uptrend = True

    for i in range(period, len(closes)):
        atr = atr_vals[i]
        if atr is None:
            continue

        hl2 = (highs[i] + lows[i]) / 2.0
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)

        if i == period:
            upper_band = basic_upper
            lower_band = basic_lower
            in_uptrend = closes[i] > hl2
        else:
            prev_close = closes[i - 1]
            upper_band = basic_upper if basic_upper < upper_band or prev_close > upper_band else upper_band
            lower_band = basic_lower if basic_lower > lower_band or prev_close < lower_band else lower_band

            if in_uptrend and closes[i] < lower_band:
                in_uptrend = False
            elif not in_uptrend and closes[i] > upper_band:
                in_uptrend = True

        st_val = lower_band if in_uptrend else upper_band
        results[i] = {
            "value": round(st_val, 2),
            "trend": 1 if in_uptrend else -1,
            "upper": round(upper_band, 2),
            "lower": round(lower_band, 2),
        }

    return results


def compute_traditional_pivots(high: float, low: float, close: float) -> Dict[str, float]:
    """Traditional Daily Pivot & CPR levels."""
    p = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (p - bc) + p

    r1 = (2.0 * p) - low
    s1 = (2.0 * p) - high
    r2 = p + (high - low)
    s2 = p - (high - low)
    r3 = high + (2.0 * (p - low))
    s3 = low - (2.0 * (high - p))
    r4 = (3.0 * p) + (high - (3.0 * low))
    s4 = (3.0 * p) - ((3.0 * high) - low)

    return {
        "P": round(p, 2),
        "TC": round(max(tc, bc), 2),
        "BC": round(min(tc, bc), 2),
        "R1": round(r1, 2),
        "S1": round(s1, 2),
        "R2": round(r2, 2),
        "S2": round(s2, 2),
        "R3": round(r3, 2),
        "S3": round(s3, 2),
        "R4": round(r4, 2),
        "S4": round(s4, 2),
    }
