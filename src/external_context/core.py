"""Deterministic External Context Core Service.

Coordinates provider-independent ingestion for:
- Official India (RBI, SEBI, MoSPI) [TIER_A_OFFICIAL]
- Financial News (Marketaux) [TIER_B_FINANCIAL_NEWS]
- Global Shock Radar (GDELT 2.0) [TIER_C_GLOBAL_RADAR]
- World Market Prices (Twelve Data) [EXACT vs PROXY]

Guarantees:
1. Zero LLM in the ingestion loop (deterministic facts only).
2. Immutable provenance hashes and raw payload archiving.
3. Provider-aware rate limiting and credit budgeting.
4. Aggressive deduplication.
5. Ingestion failures never affect Dhan or Fast Lane.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from dataclasses import replace
from typing import Any, Dict, List, Optional, Set

from src.external_context.adapters.base import BaseExternalAdapter
from src.external_context.adapters.finance_news import FinanceNewsAdapter
from src.external_context.adapters.global_shock import GlobalShockAdapter
from src.external_context.adapters.official_india import OfficialIndiaAdapter
from src.external_context.adapters.world_market import WorldMarketAdapter
from src.external_context.contracts import ExternalEvent, ExternalQuote

logger = logging.getLogger(__name__)


class ExternalContextCore:
    """Central manager and store for external market events and global quotes."""

    _instance: Optional[ExternalContextCore] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ExternalContextCore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, ledger_dir: Optional[Path] = None) -> None:
        self._lock = threading.RLock()
        self.official_adapter = OfficialIndiaAdapter()
        self.news_adapter = FinanceNewsAdapter()
        self.shock_adapter = GlobalShockAdapter()
        self.market_adapter = WorldMarketAdapter()

        # Durable append-only temporal ledgers
        self.ledger_dir = ledger_dir or Path("data/external_context")
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.events_ledger_file = self.ledger_dir / "external_events_ledger.jsonl"
        self.quotes_ledger_file = self.ledger_dir / "external_quotes_ledger.jsonl"

        # In-memory stores
        self._events: List[ExternalEvent] = []
        self._quotes: Dict[str, ExternalQuote] = {}
        self._seen_event_ids: Set[str] = set()
        self._seen_headline_keys: Set[str] = set()

        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_poll_at: Optional[str] = None
        self._last_successful_refresh_at: Optional[str] = None
        self._refresh_receipt_id: Optional[str] = None
        self._refresh_providers: Dict[str, str] = {}
        self._provider_success_at: Dict[str, str] = {}
        self.poll_cadence_seconds = 300

        # Hydrate initial memory from persistent ledgers
        self._hydrate_from_ledger()

    def _hydrate_from_ledger(self) -> None:
        """Hydrate active memory from persistent ledgers on initialization."""
        with self._lock:
            if self.events_ledger_file.exists():
                try:
                    with open(self.events_ledger_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                d = json.loads(line)
                                evt = ExternalEvent(
                                    event_id=d.get("event_id", ""),
                                    provider=d.get("provider", ""),
                                    source_name=d.get("source", d.get("source_name", "Official")),
                                    source_url=d.get("source_url", ""),
                                    published_at=d.get("published_at", ""),
                                    retrieved_at=d.get("retrieved_at", ""),
                                    event_type=d.get("event_type", "OFFICIAL_REGULATORY"),
                                    headline=d.get("headline", ""),
                                    summary=d.get("summary", ""),
                                    entities=d.get("entities", []),
                                    country=d.get("country", "IN"),
                                    market_tags=d.get("market_tags", []),
                                    verification_tier=d.get("verification_tier", "TIER_A_OFFICIAL"),
                                    freshness="UNAVAILABLE",
                                    raw_hash=d.get("raw_hash", ""),
                                    raw_artifact_ref=d.get("raw_artifact_ref"),
                                    verification_status=d.get("verification_status", "UNVERIFIED"),
                                    verification_record=d.get("verification_record", {}),
                                    why_it_matters=d.get("why_it_matters"),
                                    category_context=d.get("category_context"),
                                )
                                if evt.event_id and evt.event_id not in self._seen_event_ids:
                                    self._seen_event_ids.add(evt.event_id)
                                    self._events.append(evt)
                            except Exception:
                                continue
                except Exception as exc:
                    logger.debug("Failed hydrating events ledger: %s", exc)

            if self.quotes_ledger_file.exists():
                try:
                    with open(self.quotes_ledger_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                qd = json.loads(line)
                                q = ExternalQuote(
                                    symbol=qd.get("symbol", ""),
                                    display_name=qd.get("display_name", qd.get("symbol", "")),
                                    provider=qd.get("provider", "twelve_data"),
                                    instrument_type=qd.get("instrument_type", "EQUITY_ETF"),
                                    exact_or_proxy=qd.get("exact_or_proxy", "PROXY"),
                                    price=float(qd.get("price", 0.0)),
                                    change=float(qd.get("change", 0.0)),
                                    change_percent=float(qd.get("change_percent", 0.0)),
                                    market_status=qd.get("market_status", "OPEN"),
                                    provider_timestamp=qd.get("provider_timestamp", ""),
                                    retrieved_at=qd.get("retrieved_at", ""),
                                    data_age=qd.get("data_age", "LIVE"),
                                    notes=qd.get("notes"),
                                    cluster="SECONDARY" if qd.get("cluster") == "ASIA" else qd.get("cluster", "GLOBAL"),
                                    proxy_for=qd.get("proxy_for"),
                                    raw_hash=qd.get("raw_hash", ""),
                                    verification_status=qd.get("verification_status", "UNVERIFIED"),
                                    verification_record=qd.get("verification_record", {}),
                                )
                                if q.symbol:
                                    self._quotes[q.symbol] = q
                            except Exception:
                                continue
                except Exception as exc:
                    logger.debug("Failed hydrating quotes ledger: %s", exc)

    def start_background_polling(self) -> None:
        """Start asynchronous background polling thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._poll_thread = threading.Thread(
                target=self._run_poll_loop,
                name="ExternalContextCoreWorker",
                daemon=True,
            )
            self._poll_thread.start()

    def stop_background_polling(self) -> None:
        with self._lock:
            self._running = False

    def poll_all_now(self) -> Dict[str, int]:
        """Trigger immediate deterministic poll across all active providers."""
        with self._lock:
            self._last_poll_at = datetime.now(timezone.utc).isoformat()
            adapters = (self.official_adapter, self.news_adapter, self.shock_adapter, self.market_adapter)
            before = {adapter.provider_id: adapter.last_poll_time for adapter in adapters}
            new_events_count = 0
            
            # 1. Official India
            for evt in self.official_adapter.poll_events():
                if self._register_event(evt):
                    new_events_count += 1

            # 2. Finance News (Marketaux)
            if self.news_adapter.is_configured:
                for evt in self.news_adapter.poll_events():
                    if self._register_event(evt):
                        new_events_count += 1

            # 3. Global Shock Radar (GDELT)
            for evt in self.shock_adapter.poll_events():
                if self._register_event(evt):
                    new_events_count += 1

            # 4. World Market Quotes (Twelve Data)
            for quote in self.market_adapter.poll_quotes():
                self._quotes[quote.symbol] = quote
                try:
                    q_record = {
                        "quote_id": f"quote_{quote.symbol}_{quote.provider_timestamp.replace(':', '')}",
                        "provider": quote.provider,
                        "symbol": quote.symbol,
                        "display_name": quote.display_name,
                        "instrument_type": quote.instrument_type,
                        "exact_or_proxy": quote.exact_or_proxy,
                        "price": quote.price,
                        "change": quote.change,
                        "change_percent": quote.change_percent,
                        "market_status": quote.market_status,
                        "provider_timestamp": quote.provider_timestamp,
                        "retrieved_at": quote.retrieved_at,
                        "data_age": quote.data_age,
                        "notes": quote.notes,
                        "cluster": quote.cluster,
                        "proxy_for": quote.proxy_for,
                        "raw_hash": hashlib.sha256(f"{quote.symbol}_{quote.price}_{quote.provider_timestamp}".encode()).hexdigest(),
                        "verification_status": quote.verification_status,
                        "verification_record": quote.verification_record,
                    }
                    with open(self.quotes_ledger_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(q_record) + "\n")
                except Exception as exc:
                    logger.debug("Failed appending to quotes ledger: %s", exc)

            # Cached/no-op returns are not successful scans. Partial source success
            # is reported separately from item verification and overall readiness.
            self._refresh_providers = {adapter.provider_id: adapter.last_status for adapter in adapters}
            successful = [adapter.provider_id for adapter in adapters
                if adapter.last_poll_time != before[adapter.provider_id]
                and adapter.last_status in ("PROVIDER_HEALTHY", "NO_CURRENT_EVENTS") and not adapter.last_error]
            if successful:
                self._last_successful_refresh_at = datetime.now(timezone.utc).isoformat()
                for provider in successful:
                    self._provider_success_at[provider] = self._last_successful_refresh_at
                self._refresh_receipt_id = hashlib.sha256(
                    f"{self._last_successful_refresh_at}:{','.join(successful)}".encode()).hexdigest()[:20]
            return {
                "new_events": new_events_count,
                "total_events": len(self._events),
                "total_quotes": len(self._quotes),
            }

    def _register_event(self, evt: ExternalEvent) -> bool:
        """Deduplicate, cluster, and durably persist external event."""
        if evt.event_id in self._seen_event_ids:
            return False

        # Hardened content clustering:
        # Filter stopwords, preserve significant words and digits/dates
        stopwords = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is", "was", "by", "with", "from"}
        raw_tokens = "".join(c.lower() if c.isalnum() else " " for c in evt.headline).split()
        content_tokens = [t for t in raw_tokens if t not in stopwords or any(ch.isdigit() for ch in t)]
        cluster_key = " ".join(content_tokens[:16])

        if cluster_key and cluster_key in self._seen_headline_keys:
            return False

        self._seen_event_ids.add(evt.event_id)
        if cluster_key:
            self._seen_headline_keys.add(cluster_key)

        self._events.append(evt)

        # Append to durable ledger
        try:
            record = {
                "event_id": evt.event_id,
                "provider": evt.provider,
                "source": evt.source_name,
                "source_url": evt.source_url,
                "published_at": evt.published_at,
                "retrieved_at": evt.retrieved_at,
                "raw_hash": evt.raw_hash,
                "raw_artifact_ref": evt.raw_artifact_ref,
                "verification_tier": evt.verification_tier,
                "headline": evt.headline,
                "summary": evt.summary,
                "event_type": evt.event_type, "entities": evt.entities, "country": evt.country,
                "market_tags": evt.market_tags, "freshness": evt.freshness,
                "verification_status": evt.verification_status,
                "verification_record": evt.verification_record,
                "why_it_matters": evt.why_it_matters,
                "category_context": evt.category_context,
            }
            with open(self.events_ledger_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.debug("Failed appending to events ledger: %s", exc)

        # Cap in-memory history to 500 events
        if len(self._events) > 500:
            removed = self._events.pop(0)
            self._seen_event_ids.discard(removed.event_id)
        return True

    def get_latest_events(self, limit: int = 15) -> List[ExternalEvent]:
        with self._lock:
            clean_limit = max(1, min(limit, 100))
            return [replace(event, freshness="UNAVAILABLE") for event in reversed(self._events[-clean_limit:])]

    def get_latest_quotes(self) -> List[ExternalQuote]:
        with self._lock:
            if not self._quotes:
                self._hydrate_from_ledger()
            return list(self._quotes.values())

    def get_quote(self, symbol: str) -> Optional[ExternalQuote]:
        with self._lock:
            return self._quotes.get(symbol)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._quotes.clear()
            self._seen_event_ids.clear()
            self._seen_headline_keys.clear()

    def get_health(self) -> Dict[str, Any]:
        with self._lock:
            missing_keys = []
            if not self.news_adapter.is_configured:
                missing_keys.append("MARKETAUX_API_KEY")
            if not self.market_adapter.is_configured:
                missing_keys.append("TWELVEDATA_API_KEY")

            off_h = self.official_adapter.get_health()
            off_status = off_h.get("status", "HEALTHY")
            if off_status in ("READY", "ACTIVE"):
                off_status = "HEALTHY"

            return {
                "service": "ExternalContextCore",
                "running": self._running,
                "total_events_stored": len(self._events),
                "total_quotes_stored": len(self._quotes),
                "missing_keys": missing_keys,
                "providers": {
                    "rbi": {"provider_id": "rbi", "status": off_status, "tier": "TIER_A_OFFICIAL"},
                    "sebi": {"provider_id": "sebi", "status": off_status, "tier": "TIER_A_OFFICIAL"},
                    "mospi": {"provider_id": "mospi", "status": off_status, "tier": "TIER_A_OFFICIAL"},
                    "gdelt": self.shock_adapter.get_health(),
                    "marketaux": self.news_adapter.get_health(),
                    "twelve_data": self.market_adapter.get_health(),
                    "official_india": off_h,
                },
                "poll_cadence_seconds": self.poll_cadence_seconds,
                "last_poll_at": self._last_poll_at,
                "last_successful_refresh_at": self._last_successful_refresh_at,
                "refresh_receipt_id": self._refresh_receipt_id,
                "refresh_providers": self._refresh_providers,
                "provider_success_at": dict(self._provider_success_at),
            }

    def get_cockpit_context(self) -> Dict[str, Any]:
        from src.external_context.presentation import project_world_context
        with self._lock:
            return project_world_context([event.to_dict() for event in self._events[-100:]],
                                         [quote.to_dict() for quote in self._quotes.values()], self.get_health())

    def _run_poll_loop(self) -> None:
        """Periodic background poll with 300-second (5-minute) cadence."""
        while self._running:
            try:
                self.poll_all_now()
            except Exception as exc:
                logger.error("Error in ExternalContextCore poll loop: %s", exc)
            # Sleep 300 seconds (5 minutes) between refresh cycles
            time.sleep(float(self.poll_cadence_seconds))
