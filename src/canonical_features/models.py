"""
Canonical Feature Engine Dataclasses and Immutability Contracts.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class SupertrendValue:
    value: Optional[float] = None
    direction: Optional[str] = None  # "BULLISH", "BEARISH", "NEUTRAL"
    upper_band: Optional[float] = None
    lower_band: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "direction": self.direction,
            "upper_band": self.upper_band,
            "lower_band": self.lower_band,
        }


@dataclass(frozen=True)
class CanonicalFeatureSnapshot:
    feature_snapshot_id: str
    schema_version: int = 1
    formula_version: str = "1.0.0"
    instrument: str = "NIFTY"
    timeframe: str = "5m"
    source_timestamp: str = ""
    bar_start: str = ""
    bar_end: str = ""
    bar_complete: bool = False
    source_revision: int = 0
    feature_revision: int = 0
    freshness_age_seconds: float = 0.0
    data_quality: str = "GOOD"
    ema_values: dict[str, Optional[float]] = field(default_factory=dict)
    atr_value: Optional[float] = None
    supertrend: SupertrendValue = field(
        default_factory=lambda: SupertrendValue(None, None, None, None)
    )
    vwap_value: Optional[float] = None
    missing_fields: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_snapshot_id": self.feature_snapshot_id,
            "schema_version": self.schema_version,
            "formula_version": self.formula_version,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "source_timestamp": self.source_timestamp,
            "bar_start": self.bar_start,
            "bar_end": self.bar_end,
            "bar_complete": self.bar_complete,
            "source_revision": self.source_revision,
            "feature_revision": self.feature_revision,
            "freshness_age_seconds": self.freshness_age_seconds,
            "data_quality": self.data_quality,
            "ema_values": dict(self.ema_values),
            "atr_value": self.atr_value,
            "supertrend": self.supertrend.to_dict(),
            "vwap_value": self.vwap_value,
            "missing_fields": list(self.missing_fields),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def generate_snapshot_id(
        cls,
        instrument: str,
        timeframe: str,
        bar_end: str,
        feature_revision: int,
    ) -> str:
        raw = f"{instrument}:{timeframe}:{bar_end}:{feature_revision}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return f"snap_{instrument.lower()}_{timeframe}_{digest}"
