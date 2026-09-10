"""Data Freshness vs Event Age Evaluator for Eye Oracle Projection."""

from datetime import datetime, timezone
from typing import Dict, Optional, Any
from src.eye.oracle_projection.contracts import EyeFreshnessInfo


class FreshnessEvaluator:
    """Separates market data arrival age (ms) from semantic event age (seconds)."""

    def evaluate_freshness(
        self,
        market_data_last_seen_utc: Optional[str] = None,
        latest_event_at_utc: Optional[str] = None,
    ) -> EyeFreshnessInfo:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        if not market_data_last_seen_utc:
            return EyeFreshnessInfo(
                market_data_last_seen_utc="UNAVAILABLE",
                projection_computed_at_utc=now_iso,
                latest_closed_bar_at_utc="UNAVAILABLE",
                latest_event_at_utc=latest_event_at_utc or "UNAVAILABLE",
                source_age_ms=0.0,
                semantic_event_age_seconds=0.0,
                freshness_status="UNAVAILABLE",
            )

        md_iso = market_data_last_seen_utc
        evt_iso = latest_event_at_utc or md_iso

        try:
            md_dt = datetime.fromisoformat(md_iso.replace("Z", "+00:00"))
            source_age_ms = max(0.0, (now_dt - md_dt).total_seconds() * 1000.0)
        except Exception:
            source_age_ms = 0.0

        try:
            evt_dt = datetime.fromisoformat(evt_iso.replace("Z", "+00:00"))
            evt_age_sec = max(0.0, (now_dt - evt_dt).total_seconds())
        except Exception:
            evt_age_sec = 0.0

        status = "FRESH" if source_age_ms < 15000.0 else "STALE"

        return EyeFreshnessInfo(
            market_data_last_seen_utc=md_iso,
            projection_computed_at_utc=now_iso,
            latest_closed_bar_at_utc=md_iso,
            latest_event_at_utc=evt_iso,
            source_age_ms=round(source_age_ms, 3),
            semantic_event_age_seconds=round(evt_age_sec, 3),
            freshness_status=status,
        )
