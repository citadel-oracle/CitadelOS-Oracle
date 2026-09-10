"""Finance News Adapter (Marketaux).

Handles institutional financial news ingestion adhering to documented free tier:
- 100 requests / day
- 3 articles / request
- Deduplication and keyword filtering
- Graceful degradation if API key is missing (MARKETAUX_KEY_REQUIRED).
"""

from __future__ import annotations

import json
import logging
import os
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

MARKETAUX_API_URL = "https://api.marketaux.com/v1/news/all"


PROVIDER_FREE_LIMIT_REQUESTS_PER_DAY = 100
CITADEL_INTERNAL_DAILY_BUDGET = 80


class FinanceNewsAdapter(BaseExternalAdapter):
    """Adapter for Marketaux financial news API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        daily_budget: int = CITADEL_INTERNAL_DAILY_BUDGET,  # Internal reserve headroom below 100 req/day provider limit
        timeout_seconds: float = 6.0,
    ) -> None:
        super().__init__(provider_id="marketaux")
        self.citadel_internal_daily_budget = daily_budget or CITADEL_INTERNAL_DAILY_BUDGET
        self.daily_budget = self.citadel_internal_daily_budget
        self.provider_daily_limit = PROVIDER_FREE_LIMIT_REQUESTS_PER_DAY
        self.api_key = (
            api_key
            or os.getenv("MARKETAUX_API_KEY", "")
            or os.getenv("MARKETAUX_API_TOKEN", "")
        )
        if not self.api_key or len(self.api_key.strip()) < 8:
            try:
                import subprocess
                res = subprocess.run(
                    ["security", "find-generic-password", "-s", "MARKETAUX_API_TOKEN", "-w"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0 and len(res.stdout.strip()) >= 8:
                    self.api_key = res.stdout.strip()
            except Exception:
                pass

        self.daily_budget = daily_budget
        self.request_count_today = 0
        self.current_day_utc = datetime.now(timezone.utc).date()
        self.timeout_seconds = timeout_seconds
        self.seen_article_hashes: Set[str] = set()

        try:
            import certifi
            self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            self._ssl_context = ssl.create_default_context()

        if not self.api_key or len(self.api_key.strip()) < 8:
            self.is_configured = False
            self.last_status = "KEY_REQUIRED"
        else:
            self.is_configured = True
            self.last_status = "KEY_CONFIGURED"

    def poll_quotes(self) -> List[ExternalQuote]:
        return []

    def poll_events(self) -> List[ExternalEvent]:
        self.last_poll_time = time.time()
        now_utc = datetime.now(timezone.utc)
        if now_utc.date() != self.current_day_utc:
            self.current_day_utc = now_utc.date()
            self.request_count_today = 0

        if not self.is_configured:
            self.last_status = "KEY_REQUIRED"
            return []

        if self.request_count_today >= self.daily_budget:
            self.last_status = "RATE_LIMITED"
            logger.warning("Marketaux daily budget reached (%d requests)", self.request_count_today)
            return []

        # Safe targeted search for India / Macro news
        params = {
            "api_token": self.api_key,
            "countries": "in",
            "filter_entities": "true",
            "limit": 3,  # Free entitlement allows 3 articles per request
            "language": "en",
        }
        url = f"{MARKETAUX_API_URL}?{urllib.parse.urlencode(params)}"

        events: List[ExternalEvent] = []
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
            )
            self.request_count_today += 1
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=self._ssl_context) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            articles = data.get("data", [])
            for article in articles:
                uuid_str = article.get("uuid", "")
                title = (article.get("title") or "").strip()
                desc = (article.get("description") or article.get("snippet") or "").strip()
                url_ref = (article.get("url") or "").strip()
                source = (article.get("source") or "Financial News").strip()
                pub_at = article.get("published_at") or ""

                if not title:
                    continue

                if uuid_str in self.seen_article_hashes:
                    continue
                self.seen_article_hashes.add(uuid_str)

                # Extract entities & tags
                entity_list = [
                    e.get("name") for e in article.get("entities", []) if isinstance(e, dict) and e.get("name")
                ]
                tags = ["FINANCE_NEWS", "MARKETAUX"]
                combined_lower = f"{title} {desc}".lower()
                if "rbi" in combined_lower:
                    tags.append("RBI")
                if "nifty" in combined_lower:
                    tags.append("NIFTY")

                # Source-grounded category context (broad domain label, NOT headline causality)
                category_context = None
                if "rbi" in combined_lower or "repo" in combined_lower or "monetary policy" in combined_lower:
                    category_context = "MONETARY_POLICY_BANKING"
                elif "nifty" in combined_lower or "sensex" in combined_lower:
                    category_context = "EQUITY_BENCHMARK_INDEX"
                elif "inflation" in combined_lower or "cpi" in combined_lower or "iip" in combined_lower:
                    category_context = "MACROECONOMIC_INDICATOR"
                elif "crude" in combined_lower or "oil" in combined_lower:
                    category_context = "COMMODITY_ENERGY"
                elif "rupee" in combined_lower or "usd/inr" in combined_lower:
                    category_context = "FOREIGN_EXCHANGE"
                elif "earnings" in combined_lower or "revenue" in combined_lower or "profit" in combined_lower:
                    category_context = "CORPORATE_EARNINGS"
                else:
                    category_context = "FINANCIAL_MARKETS"

                evt = ExternalEvent.create(
                    provider="marketaux",
                    source_name=source,
                    source_url=url_ref,
                    published_at=pub_at,
                    event_type="FINANCIAL_NEWS",
                    headline=title,
                    summary=desc[:600],
                    entities=entity_list,
                    country="IN",
                    market_tags=tags,
                    verification_tier=VerificationTier.TIER_B_FINANCIAL_NEWS.value,
                    raw_payload=json.dumps(article, sort_keys=True),
                    why_it_matters=None,  # Never synthesize fake article-specific causality
                    category_context=category_context,
                )
                events.append(evt)

            self.last_status = "PROVIDER_HEALTHY" if events else "NO_CURRENT_EVENTS"
            self.last_error = None
        except Exception as exc:
            logger.debug("Marketaux API error: %s", exc)
            self.last_error = str(exc)
            self.last_status = "FETCH_FAILED"

        return events

    def get_health(self) -> Dict[str, Any]:
        h = super().get_health()
        h["requests_today"] = self.request_count_today
        h["provider_daily_limit"] = self.provider_daily_limit
        h["citadel_internal_daily_budget"] = self.citadel_internal_daily_budget
        h["citadel_internal_reserve_headroom"] = max(0, self.provider_daily_limit - self.citadel_internal_daily_budget)
        h["daily_budget"] = self.daily_budget
        return h
