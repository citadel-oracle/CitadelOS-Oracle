"""
Formula Compatibility Registry.
Explicit versioned calculation profiles matching legacy consumer implementations.
Centralized calculation so each profile is computed once and shared.
"""

from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class FormulaProfileSpec:
    profile_id: str
    feature_name: str
    consumer: str
    formula_type: str
    seed_method: str
    smoothing_method: str
    rounding_decimals: int
    exact_equivalence_notes: str


class FormulaProfileRegistry:
    PROFILES = {
        "EMA_INDICATOR_ENGINE_V1": FormulaProfileSpec(
            profile_id="EMA_INDICATOR_ENGINE_V1",
            feature_name="EMA",
            consumer="IndicatorEngine",
            formula_type="Exponential Moving Average",
            seed_method="SMA over initial period",
            smoothing_method="Standard alpha = 2/(p+1)",
            rounding_decimals=2,
            exact_equivalence_notes="Matches IndicatorEngine.ema rounded to 2 decimals",
        ),
        "EMA_OSE_V1": FormulaProfileSpec(
            profile_id="EMA_OSE_V1",
            feature_name="EMA",
            consumer="OSE",
            formula_type="Exponential Moving Average",
            seed_method="SMA over initial period",
            smoothing_method="Standard alpha = 2/(p+1)",
            rounding_decimals=6,
            exact_equivalence_notes="Matches OSEEngine.ema rounded to 6 decimals",
        ),
        "ATR_INDICATOR_ENGINE_V1": FormulaProfileSpec(
            profile_id="ATR_INDICATOR_ENGINE_V1",
            feature_name="ATR",
            consumer="IndicatorEngine",
            formula_type="Average True Range (Simple)",
            seed_method="Simple average of true ranges over window",
            smoothing_method="Simple Moving Average over last period TRs",
            rounding_decimals=2,
            exact_equivalence_notes="Matches IndicatorEngine.atr",
        ),
        "ATR_WILDER_VOB_V1": FormulaProfileSpec(
            profile_id="ATR_WILDER_VOB_V1",
            feature_name="ATR",
            consumer="VOB",
            formula_type="Wilder's ATR (Pine ta.atr)",
            seed_method="First period TR sum / period",
            smoothing_method="Wilder's RMA (k = 1/period)",
            rounding_decimals=4,
            exact_equivalence_notes="Matches Pine ta.atr(200) backing VOB order blocks",
        ),
        "ATR_OSE_V1": FormulaProfileSpec(
            profile_id="ATR_OSE_V1",
            feature_name="ATR",
            consumer="OSE",
            formula_type="Smooth ATR",
            seed_method="Sum of TRs[1:period+1] / period",
            smoothing_method="((prev * (p-1)) + current_tr) / p",
            rounding_decimals=6,
            exact_equivalence_notes="Matches OSEEngine.atr rounded to 6 decimals",
        ),
        "SUPERTREND_OSE_V1": FormulaProfileSpec(
            profile_id="SUPERTREND_OSE_V1",
            feature_name="Supertrend",
            consumer="OSE / Tactical Edge",
            formula_type="Supertrend Trailing Band",
            seed_method="Initial ATR seed",
            smoothing_method="Trailing upper/lower band with direction flip",
            rounding_decimals=4,
            exact_equivalence_notes="Matches OSEEngine.supertrend",
        ),
        "VWAP_CUMULATIVE_V1": FormulaProfileSpec(
            profile_id="VWAP_CUMULATIVE_V1",
            feature_name="VWAP",
            consumer="Kronos / Edge Lab",
            formula_type="Cumulative Volume-Weighted Price",
            seed_method="Intraday session start reset",
            smoothing_method="sum(typical_price * volume) / sum(volume)",
            rounding_decimals=4,
            exact_equivalence_notes="Matches canonical volume-weighted average price",
        ),
        "VWAP_TYPICAL_AVG_V1": FormulaProfileSpec(
            profile_id="VWAP_TYPICAL_AVG_V1",
            feature_name="VWAP",
            consumer="IndicatorEngine",
            formula_type="Typical Price Unweighted Average",
            seed_method="Equal weight per candle",
            smoothing_method="sum((H+L+C)/3) / len(candles)",
            rounding_decimals=2,
            exact_equivalence_notes="Matches IndicatorEngine.vwap approximation",
        ),
    }

    @classmethod
    def compute_profile(
        cls,
        profile_id: str,
        candles: Sequence[Mapping[str, Any]],
        period: int = 21,
        multiplier: float = 3.0,
    ) -> Any:
        if profile_id not in cls.PROFILES:
            raise ValueError(f"Unknown formula profile: {profile_id}")

        closes = [float(c["close"]) for c in candles if "close" in c]

        if profile_id == "EMA_INDICATOR_ENGINE_V1":
            if len(closes) < period:
                return None
            val = sum(closes[:period]) / period
            mult = 2.0 / (period + 1.0)
            for c in closes[period:]:
                val = (c - val) * mult + val
            return round(val, 2)

        elif profile_id == "EMA_OSE_V1":
            if len(closes) < period:
                return None
            val = sum(closes[:period]) / period
            mult = 2.0 / (period + 1.0)
            for c in closes[period:]:
                val = (c - val) * mult + val
            return round(val, 6)

        elif profile_id == "ATR_INDICATOR_ENGINE_V1":
            if len(candles) <= period:
                return None
            trs = []
            for i in range(1, len(candles)):
                h, l = float(candles[i]["high"]), float(candles[i]["low"])
                pc = float(candles[i - 1]["close"])
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            return round(sum(trs[-period:]) / period, 2)

        elif profile_id == "ATR_WILDER_VOB_V1":
            n = len(candles)
            if n < period:
                return None
            trs = [0.0] * n
            for i in range(n):
                h, l = float(candles[i]["high"]), float(candles[i]["low"])
                pc = float(candles[i - 1]["close"]) if i > 0 else float(candles[i]["close"])
                trs[i] = max(h - l, abs(h - pc), abs(l - pc))
            atr = sum(trs[:period]) / period
            k = 1.0 / period
            for i in range(period, n):
                atr = atr * (1 - k) + trs[i] * k
            return round(atr, 4)

        elif profile_id == "ATR_OSE_V1":
            if len(candles) < period + 1:
                return None
            trs = []
            for idx, row in enumerate(candles):
                h, l = float(row["high"]), float(row["low"])
                pc = float(candles[idx - 1]["close"]) if idx > 0 else float(row["close"])
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            atr = sum(trs[1 : period + 1]) / period
            for tr in trs[period + 1 :]:
                atr = ((atr * (period - 1)) + tr) / period
            return round(atr, 6)

        elif profile_id == "SUPERTREND_OSE_V1":
            if len(candles) < period + 1:
                return None, None
            trs = []
            for idx, row in enumerate(candles):
                h, l = float(row["high"]), float(row["low"])
                pc = float(candles[idx - 1]["close"]) if idx > 0 else float(row["close"])
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            atr = sum(trs[1 : period + 1]) / period
            upper = lower = st_val = None
            direction = 1
            for idx in range(period, len(candles)):
                if idx > period:
                    atr = ((atr * (period - 1)) + trs[idx]) / period
                row = candles[idx]
                hl2 = (float(row["high"]) + float(row["low"])) / 2.0
                basic_u = hl2 + (multiplier * atr)
                basic_l = hl2 - (multiplier * atr)
                prev_c = float(candles[idx - 1]["close"])
                prev_u = upper if upper is not None else basic_u
                prev_l = lower if lower is not None else basic_l
                upper = basic_u if basic_u < prev_u or prev_c > prev_u else prev_u
                lower = basic_l if basic_l > prev_l or prev_c < prev_l else prev_l
                if idx == period:
                    direction = 1 if float(row["close"]) > upper else -1
                else:
                    if st_val == prev_u:
                        direction = -1 if float(row["close"]) <= upper else 1
                    else:
                        direction = 1 if float(row["close"]) >= lower else -1
                st_val = lower if direction == 1 else upper
            dir_str = "BULLISH" if direction == 1 else "BEARISH"
            return round(st_val, 4) if st_val is not None else None, dir_str

        elif profile_id == "VWAP_CUMULATIVE_V1":
            if not candles:
                return None
            cum_pv = sum(
                ((float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0)
                * float(c.get("volume") or 1.0)
                for c in candles
            )
            cum_vol = sum(float(c.get("volume") or 1.0) for c in candles)
            return round(cum_pv / cum_vol, 4) if cum_vol > 0 else None

        elif profile_id == "VWAP_TYPICAL_AVG_V1":
            if not candles:
                return None
            tot = sum(
                (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
                for c in candles
            )
            return round(tot / len(candles), 2)

        return None
