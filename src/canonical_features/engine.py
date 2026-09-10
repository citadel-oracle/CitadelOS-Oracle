"""
Canonical Feature Engine Core.
Incremental bar formation, feature calculation, state persistence, and snapshot publication.
"""

from __future__ import annotations
import copy
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Optional, Sequence

from src.canonical_features.models import (
    CanonicalFeatureSnapshot,
    SupertrendValue,
)


class CanonicalFeatureEngine:
    def __init__(
        self,
        instrument: str = "NIFTY",
        timeframe: str = "5m",
        max_history: int = 500,
        ema_periods: tuple[int, ...] = (21, 38, 50),
        atr_period: int = 14,
        supertrend_period: int = 10,
        supertrend_multiplier: float = 3.0,
    ):
        self.instrument = instrument
        self.timeframe = timeframe
        self.max_history = max_history
        self.ema_periods = ema_periods
        self.atr_period = atr_period
        self.supertrend_period = supertrend_period
        self.supertrend_multiplier = supertrend_multiplier

        self._candles: list[dict[str, Any]] = []
        self._forming_bar: Optional[dict[str, Any]] = None
        self._last_processed_timestamp: Optional[str] = None
        self._processed_keys: set[str] = set()
        self._source_revision: int = 0
        self._feature_revision: int = 0
        self._last_snapshot: Optional[CanonicalFeatureSnapshot] = None

    def bootstrap(self, candles: Sequence[Mapping[str, Any]]) -> CanonicalFeatureSnapshot:
        """One-time bootstrap from bounded historical bars."""
        self._candles = [dict(c) for c in candles[-self.max_history:]]
        self._forming_bar = None
        self._source_revision += len(candles)
        self._feature_revision += 1
        if self._candles:
            self._last_processed_timestamp = str(self._candles[-1].get("timestamp") or self._candles[-1].get("end_time") or "")
        return self._compute_snapshot(bar_complete=True)

    def update_bar(
        self,
        bar: Mapping[str, Any],
        is_complete: bool = False,
    ) -> CanonicalFeatureSnapshot:
        """Incremental bar update (forming or completed)."""
        bar_dict = dict(bar)
        bar_start = str(bar_dict.get("timestamp") or bar_dict.get("start_time") or "")
        bar_end = str(bar_dict.get("end_time") or bar_start)

        event_key = f"{self.instrument}:{self.timeframe}:{bar_start}:{bar_end}:{bar_dict.get('close')}:{is_complete}"

        # Idempotency check
        if event_key in self._processed_keys and self._last_snapshot is not None:
            return self._last_snapshot

        # Out-of-order event rejection / check
        if (
            self._last_processed_timestamp
            and bar_end < self._last_processed_timestamp
            and is_complete
        ):
            # Out-of-order completed bar rejection (returns last valid snapshot)
            if self._last_snapshot:
                return self._last_snapshot

        self._source_revision += 1
        self._processed_keys.add(event_key)
        # Keep set bounded
        if len(self._processed_keys) > 2000:
            self._processed_keys.clear()

        if is_complete:
            self._candles.append(bar_dict)
            if len(self._candles) > self.max_history:
                self._candles.pop(0)
            self._forming_bar = None
            self._last_processed_timestamp = bar_end
            self._feature_revision += 1
            return self._compute_snapshot(bar_complete=True)
        else:
            self._forming_bar = bar_dict
            self._feature_revision += 1
            return self._compute_snapshot(bar_complete=False)

    def ingest_candles(
        self, candles: Sequence[Mapping[str, Any]]
    ) -> CanonicalFeatureSnapshot:
        """Batch ingestion helper that processes complete candles."""
        for c in candles:
            self.update_bar(c, is_complete=True)
        return self._last_snapshot or self._compute_snapshot(bar_complete=True)

    def export_state(self) -> dict[str, Any]:
        """Export state for restart recovery."""
        return {
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "candles": copy.deepcopy(self._candles),
            "forming_bar": copy.deepcopy(self._forming_bar),
            "last_processed_timestamp": self._last_processed_timestamp,
            "processed_keys": list(self._processed_keys),
            "source_revision": self._source_revision,
            "feature_revision": self._feature_revision,
        }

    def import_state(self, state: dict[str, Any]) -> None:
        """Import state for restart recovery."""
        self.instrument = state.get("instrument", self.instrument)
        self.timeframe = state.get("timeframe", self.timeframe)
        self._candles = [dict(c) for c in state.get("candles", [])]
        self._forming_bar = dict(state["forming_bar"]) if state.get("forming_bar") else None
        self._last_processed_timestamp = state.get("last_processed_timestamp")
        self._processed_keys = set(state.get("processed_keys", []))
        # Rebuild processed keys from candles if missing
        if not self._processed_keys and self._candles:
            for c in self._candles:
                ts = str(c.get("timestamp") or c.get("start_time") or "")
                self._processed_keys.add(f"{ts}:{ts}:True")
        self._source_revision = state.get("source_revision", 0)
        self._feature_revision = state.get("feature_revision", 0)
        self._last_snapshot = self._compute_snapshot(bar_complete=self._forming_bar is None)

    # ------------------------------------------------------------------
    # Calculations
    # ------------------------------------------------------------------

    def _compute_snapshot(self, bar_complete: bool) -> CanonicalFeatureSnapshot:
        active_candles = list(self._candles)
        if self._forming_bar and not bar_complete:
            active_candles.append(self._forming_bar)

        missing_fields: list[str] = []
        if not active_candles:
            missing_fields.append("candles")
            snapshot = CanonicalFeatureSnapshot(
                feature_snapshot_id=CanonicalFeatureSnapshot.generate_snapshot_id(
                    self.instrument, self.timeframe, "", self._feature_revision
                ),
                instrument=self.instrument,
                timeframe=self.timeframe,
                bar_complete=bar_complete,
                source_revision=self._source_revision,
                feature_revision=self._feature_revision,
                missing_fields=tuple(missing_fields),
                provenance={"engine": "CanonicalFeatureEngine", "version": "1.0.0"},
            )
            self._last_snapshot = snapshot
            return snapshot

        last_bar = active_candles[-1]
        bar_start = str(last_bar.get("timestamp") or last_bar.get("start_time") or "")
        bar_end = str(last_bar.get("end_time") or bar_start)
        source_ts = datetime.now(timezone.utc).isoformat()

        # 1. EMA
        closes = [float(c["close"]) for c in active_candles if "close" in c]
        ema_values: dict[str, Optional[float]] = {}
        for p in self.ema_periods:
            ema_val = self._calc_ema(closes, p)
            ema_values[f"ema_{p}"] = ema_val
            if ema_val is None:
                missing_fields.append(f"ema_{p}")

        # 2. ATR
        atr_val = self._calc_atr(active_candles, self.atr_period)
        if atr_val is None:
            missing_fields.append("atr")

        # 3. Supertrend
        st_val = self._calc_supertrend(
            active_candles,
            period=self.supertrend_period,
            multiplier=self.supertrend_multiplier,
        )
        if st_val.value is None:
            missing_fields.append("supertrend")

        # 4. VWAP
        vwap_val = self._calc_vwap(active_candles)
        if vwap_val is None:
            missing_fields.append("vwap")

        snap_id = CanonicalFeatureSnapshot.generate_snapshot_id(
            self.instrument, self.timeframe, bar_end, self._feature_revision
        )

        snapshot = CanonicalFeatureSnapshot(
            feature_snapshot_id=snap_id,
            schema_version=1,
            formula_version="1.0.0",
            instrument=self.instrument,
            timeframe=self.timeframe,
            source_timestamp=source_ts,
            bar_start=bar_start,
            bar_end=bar_end,
            bar_complete=bar_complete,
            source_revision=self._source_revision,
            feature_revision=self._feature_revision,
            freshness_age_seconds=0.0,
            data_quality="GOOD" if not missing_fields else "PARTIAL",
            ema_values=ema_values,
            atr_value=atr_val,
            supertrend=st_val,
            vwap_value=vwap_val,
            missing_fields=tuple(missing_fields),
            provenance={
                "engine": "CanonicalFeatureEngine",
                "version": "1.0.0",
                "total_bars": len(active_candles),
            },
        )

        self._last_snapshot = snapshot
        return snapshot

    @staticmethod
    def _calc_ema(closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        # Seed with simple average of first period closes
        value = sum(closes[:period]) / period
        multiplier = 2.0 / (period + 1.0)
        for c in closes[period:]:
            value = (c - value) * multiplier + value
        return round(value, 4)

    @staticmethod
    def _calc_atr(candles: list[dict[str, Any]], period: int) -> Optional[float]:
        if len(candles) < period + 1:
            return None
        true_ranges: list[float] = []
        for idx, c in enumerate(candles):
            high, low = float(c["high"]), float(c["low"])
            prev_close = (
                float(candles[idx - 1]["close"]) if idx > 0 else float(c["close"])
            )
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        # First seed is simple average of initial period TRs
        atr = sum(true_ranges[1 : period + 1]) / period
        for tr in true_ranges[period + 1 :]:
            atr = ((atr * (period - 1)) + tr) / period
        return round(atr, 4)

    @staticmethod
    def _calc_supertrend(
        candles: list[dict[str, Any]], period: int = 10, multiplier: float = 3.0
    ) -> SupertrendValue:
        if len(candles) < period + 1:
            return SupertrendValue(None, None, None, None)

        trs: list[float] = []
        for idx, c in enumerate(candles):
            high, low = float(c["high"]), float(c["low"])
            prev_close = (
                float(candles[idx - 1]["close"]) if idx > 0 else float(c["close"])
            )
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

        atr = sum(trs[1 : period + 1]) / period
        upper = lower = st_val = None
        direction = 1  # 1 for bullish, -1 for bearish

        for idx in range(period, len(candles)):
            if idx > period:
                atr = ((atr * (period - 1)) + trs[idx]) / period

            row = candles[idx]
            hl2 = (float(row["high"]) + float(row["low"])) / 2.0
            basic_upper = hl2 + (multiplier * atr)
            basic_lower = hl2 - (multiplier * atr)

            prev_close = float(candles[idx - 1]["close"])
            prev_upper = upper if upper is not None else basic_upper
            prev_lower = lower if lower is not None else basic_lower

            upper = basic_upper if basic_upper < prev_upper or prev_close > prev_upper else prev_upper
            lower = basic_lower if basic_lower > prev_lower or prev_close < prev_lower else prev_lower

            if idx == period:
                direction = 1 if float(row["close"]) > upper else -1
            else:
                prev_st = st_val
                if prev_st == prev_upper:
                    direction = -1 if float(row["close"]) <= upper else 1
                else:
                    direction = 1 if float(row["close"]) >= lower else -1

            st_val = lower if direction == 1 else upper

        dir_str = "BULLISH" if direction == 1 else "BEARISH"
        return SupertrendValue(
            value=round(st_val, 4) if st_val is not None else None,
            direction=dir_str,
            upper_band=round(upper, 4) if upper is not None else None,
            lower_band=round(lower, 4) if lower is not None else None,
        )

    @staticmethod
    def _calc_vwap(candles: list[dict[str, Any]]) -> Optional[float]:
        if not candles:
            return None
        cum_pv = 0.0
        cum_vol = 0.0
        for c in candles:
            close = float(c.get("close") or 0.0)
            high = float(c.get("high") or close)
            low = float(c.get("low") or close)
            tp = (high + low + close) / 3.0
            vol = float(c.get("volume") or 0.0)
            if vol <= 0.0:
                vol = 1.0  # fallback weight when volume is unpopulated
            cum_pv += tp * vol
            cum_vol += vol

        if cum_vol <= 0.0:
            return None
        return round(cum_pv / cum_vol, 4)
