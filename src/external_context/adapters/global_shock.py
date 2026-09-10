"""Global Shock Radar Adapter (GDELT 2.0).

Provides keyless, broad global macroeconomic and geopolitical coverage.
Updates every ~15 minutes; enforces a 15-minute minimum cadence to avoid redundant queries.
Role: Global geopolitical events, breaking macro shocks. Aggressively deduplicated.
GDELT does NOT become financial price truth.
"""

from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.external_context.adapters.base import BaseExternalAdapter
from src.external_context.contracts import (
    ExternalEvent,
    ExternalQuote,
    VerificationTier,
)

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


class GlobalShockAdapter(BaseExternalAdapter):
    """Keyless adapter querying GDELT 2.0 Document API on a ~15-minute cadence."""

    def __init__(self, cadence_seconds: float = 900.0, timeout_seconds: float = 4.0) -> None:
        super().__init__(provider_id="gdelt")
        self.cadence_seconds = cadence_seconds
        self.timeout_seconds = timeout_seconds
        self.last_poll_time: Optional[float] = None
        self.seen_urls: Set[str] = set()
        self.is_configured = True
        self.last_status = "READY"

        try:
            import certifi
            self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            self._ssl_context = ssl.create_default_context()

    def poll_quotes(self) -> List[ExternalQuote]:
        return []

    def poll_events(self) -> List[ExternalEvent]:
        now = time.time()
        # Enforce roughly 15-minute cadence
        if self.last_poll_time is not None and (now - self.last_poll_time) < self.cadence_seconds:
            return []

        self.last_poll_time = now
        query_terms = "(India OR RBI OR NIFTY OR crude OR Fed OR geopolitical)"
        params = {
            "query": query_terms,
            "mode": "artlist",
            "maxrecords": "5",
            "format": "json",
            "sort": "DateDesc",
        }
        url = f"{GDELT_DOC_API}?{urllib.parse.urlencode(params)}"

        events: List[ExternalEvent] = []
        
        # 1. First poll GDELT 2.0 official 15-minute radar manifest
        try:
            manifest_url = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
            m_req = urllib.request.Request(
                manifest_url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"},
            )
            with urllib.request.urlopen(m_req, timeout=4.0, context=self._ssl_context) as m_resp:
                m_raw = m_resp.read().decode("utf-8", errors="replace")
            
            lines = [l.strip() for l in m_raw.splitlines() if l.strip()]
            if lines:
                # Line format: <size> <md5> <url>
                parts = lines[0].split()
                if len(parts) >= 3:
                    file_size, file_md5, file_url = parts[0], parts[1], parts[2]
                    filename = file_url.split("/")[-1]
                    batch_id = filename.split(".")[0]
                    if batch_id not in self.seen_urls:
                        self.seen_urls.add(batch_id)
                        # Formulate clean datetime from batch YYYYMMDDHHMMSS
                        pub_dt = datetime.now(timezone.utc).isoformat()
                        if len(batch_id) >= 14:
                            try:
                                dt = datetime.strptime(batch_id[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                                pub_dt = dt.isoformat()
                            except Exception:
                                pass
                        
                        g_event = ExternalEvent.create(
                            provider="gdelt",
                            source_name="GDELT 2.0 Global Radar",
                            source_url=file_url,
                            published_at=pub_dt,
                            event_type="GLOBAL_SHOCK_RADAR",
                            headline=f"GDELT Global Radar Pulse: {batch_id[:4]}-{batch_id[4:6]}-{batch_id[6:8]} {batch_id[8:10]}:{batch_id[10:12]} UTC",
                            summary=f"Automated 15-minute Global Knowledge Graph and event telemetry stream. Batch ID: {batch_id}, Hash: {file_md5}, Size: {file_size} bytes.",
                            entities=["GDELT", "GLOBAL_RADAR"],
                            country="GLOBAL",
                            market_tags=["GLOBAL_SHOCK", "GEOPOLITICAL", "RADAR"],
                            verification_tier=VerificationTier.TIER_C_GLOBAL_RADAR.value,
                            raw_payload=m_raw,
                            why_it_matters=None,
                            category_context="GLOBAL_RADAR_TELEMETRY",
                        )
                        events.append(g_event)
        except Exception as m_exc:
            logger.debug("Failed fetching GDELT lastupdate.txt: %s", m_exc)

        # 2. Attempt optional query to GDELT DOC API if needed
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=self._ssl_context) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)

            articles = data.get("articles", [])
            for art in articles:
                title = (art.get("title") or "").strip()
                art_url = (art.get("url") or "").strip()
                domain = (art.get("domain") or "GDELT Global News").strip()
                seendate = (art.get("seendate") or "").strip()

                if not title or not art_url:
                    continue

                if art_url in self.seen_urls:
                    continue
                self.seen_urls.add(art_url)

                # Parse seendate YYYYMMDDTHHMMSSZ
                pub_iso = datetime.now(timezone.utc).isoformat()
                if len(seendate) >= 15:
                    try:
                        parsed = datetime.strptime(seendate[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                        pub_iso = parsed.isoformat()
                    except Exception:
                        pass

                evt = ExternalEvent.create(
                    provider="gdelt",
                    source_name=f"GDELT / {domain}",
                    source_url=art_url,
                    published_at=pub_iso,
                    event_type="GEOPOLITICAL_SHOCK",
                    headline=title,
                    summary=f"Global shock monitoring match from {domain}. Macro/geopolitical radar alert.",
                    entities=[domain, "GLOBAL_RADAR"],
                    country="GLOBAL",
                    market_tags=["GLOBAL_SHOCK", "GEOPOLITICS", "MACRO"],
                    verification_tier=VerificationTier.TIER_C_GLOBAL_RADAR.value,
                    raw_payload=json.dumps(art, sort_keys=True),
                    why_it_matters=None,
                    category_context="GLOBAL_GEOPOLITICAL_RADAR",
                )
                events.append(evt)

            self.last_status = "PROVIDER_HEALTHY" if events else "NO_CURRENT_EVENTS"
            self.last_error = None
        except Exception as exc:
            logger.debug("GDELT doc API fetch error: %s", exc)
            if not events:
                self.last_error = str(exc)
                self.last_status = "FETCH_FAILED"

        if events:
            self.last_status = "PROVIDER_HEALTHY"
            self.last_error = None

        return events
