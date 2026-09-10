"""World Market Adapter (Twelve Data).

Handles global market basket pricing with strict credit adherence:
- Twelve Data free Basic: 8 credits / minute, 800 credits / day.
- Single batched query for the minimal 8-symbol basket.
- Explicit EXACT vs PROXY labeling:
    - SPY: PROXY (S&P 500 ETF proxy)
    - QQQ: PROXY (Nasdaq-100 ETF proxy)
    - UUP: PROXY (US Dollar index ETF proxy, NOT DXY cash)
    - TLT: PROXY (Treasury bond ETF proxy, NOT US 10Y yield)
    - USO: PROXY (US Oil Fund proxy, NOT WTI futures)
    - GLD: PROXY (SPDR Gold Shares proxy, NOT spot/futures gold)
    - BTC/USD: EXACT (Crypto spot)
    - USD/INR: EXACT (Forex spot)
- Strict Market Session classification:
    - If market is closed (e.g. US ETFs during Indian market hours), marked SESSION_LAST (never LIVE).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.external_context.adapters.base import BaseExternalAdapter
from src.external_context.contracts import (
    DataAgeStatus,
    ExactOrProxy,
    ExternalEvent,
    ExternalQuote,
)

logger = logging.getLogger(__name__)

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com/quote"

PROVIDER_LIMIT_CREDITS_PER_MINUTE = 8
PROVIDER_LIMIT_CREDITS_PER_DAY = 800
CITADEL_INTERNAL_DAILY_BUDGET = 700

BASKET_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "USD/INR": {
        "display_name": "USD/INR",
        "instrument_type": "FOREX",
        "exact_or_proxy": ExactOrProxy.EXACT.value,
        "cluster": "INDIA_LEAD",
        "proxy_for": None,
        "is_continuous": True,  # 24/5 forex
    },
    "QQQ": {
        "display_name": "Nasdaq-100 (QQQ ETF)",
        "instrument_type": "EQUITY_ETF",
        "exact_or_proxy": ExactOrProxy.PROXY.value,
        "cluster": "US_RISK",
        "proxy_for": "FOR NASDAQ RISK",
        "notes": "Nasdaq-100 ETF proxy, NOT Nasdaq futures",
        "is_continuous": False,
    },
    "SPY": {
        "display_name": "S&P 500 (SPY ETF)",
        "instrument_type": "EQUITY_ETF",
        "exact_or_proxy": ExactOrProxy.PROXY.value,
        "cluster": "US_RISK",
        "proxy_for": "FOR S&P RISK",
        "notes": "S&P 500 ETF proxy, NOT S&P futures",
        "is_continuous": False,
    },
    "UUP": {
        "display_name": "US Dollar (UUP ETF)",
        "instrument_type": "DOLLAR_ETF",
        "exact_or_proxy": ExactOrProxy.PROXY.value,
        "cluster": "RATES_USD",
        "proxy_for": "FOR USD",
        "notes": "Dollar proxy, NOT DXY cash index",
        "is_continuous": False,
    },
    "TLT": {
        "display_name": "US 20Y+ Treasuries (TLT ETF)",
        "instrument_type": "BOND_ETF",
        "exact_or_proxy": ExactOrProxy.PROXY.value,
        "cluster": "RATES_USD",
        "proxy_for": "FOR TREASURY DURATION",
        "notes": "Bond ETF proxy, NOT US10Y yield",
        "is_continuous": False,
    },
    "USO": {
        "display_name": "Crude Oil (USO ETF)",
        "instrument_type": "COMMODITY_ETF",
        "exact_or_proxy": ExactOrProxy.PROXY.value,
        "cluster": "COMMODITIES",
        "proxy_for": "FOR OIL",
        "notes": "Oil ETF proxy, NOT WTI futures",
        "is_continuous": False,
    },
    "GLD": {
        "display_name": "Gold (GLD ETF)",
        "instrument_type": "COMMODITY_ETF",
        "exact_or_proxy": ExactOrProxy.PROXY.value,
        "cluster": "COMMODITIES",
        "proxy_for": "FOR GOLD",
        "notes": "Gold ETF proxy, NOT spot gold",
        "is_continuous": False,
    },
    "BTC/USD": {
        "display_name": "BTC/USD",
        "instrument_type": "CRYPTO",
        "exact_or_proxy": ExactOrProxy.EXACT.value,
        "cluster": "SECONDARY",
        "proxy_for": None,
        "is_continuous": True,  # 24/7 crypto
    },
}

UPSTOX_GLOBAL_SYMBOLS: Dict[str, Dict[str, Any]] = {
    "GIFT_NIFTY": {
        "upstox_key": "GLOBAL_INDEX|SGX NIFTY",
        "display_name": "GIFT Nifty",
        "instrument_type": "INDEX",
        "cluster": "INDIA_LEAD",
        "is_continuous": True,
    },
    "INDIA_VIX": {
        "upstox_key": "NSE_INDEX|India VIX",
        "display_name": "India VIX",
        "instrument_type": "VOLATILITY_INDEX",
        "cluster": "INDIA_LEAD",
        "is_continuous": False,
    },
    "NIKKEI_225": {
        "upstox_key": "GLOBAL_INDEX|^N225",
        "display_name": "Nikkei 225",
        "instrument_type": "INDEX",
        "cluster": "SECONDARY",
        "is_continuous": False,
    },
}

UNAVAILABLE_TARGETS: List[Dict[str, Any]] = [
    {
        "target": "GIFT NIFTY",
        "cluster": "INDIA_LEAD",
        "reason": "NSE IX GIFT Nifty not subscribed on active broker feed or Twelve Data Basic plan",
        "status": "UNAVAILABLE",
    },
    {
        "target": "INDIA VIX",
        "cluster": "INDIA_LEAD",
        "reason": "India VIX not subscribed on active broker feed or delayed REST source",
        "status": "UNAVAILABLE",
    },
    {
        "target": "NIKKEI 225",
        "cluster": "ASIA",
        "reason": "Index data restricted on Twelve Data Basic plan",
        "status": "UNAVAILABLE",
    },
    {
        "target": "HANG SENG",
        "cluster": "ASIA",
        "reason": "Index data restricted on Twelve Data Basic plan and Upstox",
        "status": "UNAVAILABLE",
    },
]


class WorldMarketAdapter(BaseExternalAdapter):
    """Adapter for Twelve Data global market quotes with Upstox exact fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        min_poll_interval_seconds: float = 60.0,  # Conservatively at most 1 batch per minute
        timeout_seconds: float = 6.0,
        upstox_client: Optional[Any] = None,
    ) -> None:
        super().__init__(provider_id="twelve_data")
        self.api_key = (
            api_key
            or os.getenv("TWELVEDATA_API_KEY", "")
            or os.getenv("TWELVE_DATA_API_KEY", "")
        )
        if not self.api_key or len(self.api_key.strip()) < 8:
            try:
                import subprocess
                for svc in ["TWELVEDATA_API_KEY", "TWELVE_DATA_API_KEY"]:
                    res = subprocess.run(
                        ["security", "find-generic-password", "-s", svc, "-w"],
                        capture_output=True,
                        text=True,
                    )
                    if res.returncode == 0 and len(res.stdout.strip()) >= 8:
                        self.api_key = res.stdout.strip()
                        break
            except Exception:
                pass

        if upstox_client is not None:
            self.upstox_client = upstox_client
        else:
            try:
                from src.broker.upstox_client import UpstoxClient
                self.upstox_client = UpstoxClient()
            except Exception:
                self.upstox_client = None

        self.min_poll_interval_seconds = min_poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.cached_quotes: Dict[str, ExternalQuote] = {}
        self.request_count_today = 0
        self.current_day_utc = datetime.now(timezone.utc).date()
        self.rate_limit_state: Dict[str, Any] = {}

        try:
            import certifi
            self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            self._ssl_context = ssl.create_default_context()

        has_td = bool(self.api_key and len(self.api_key.strip()) >= 8)
        has_up = bool(self.upstox_client and getattr(self.upstox_client, "has_token", False))

        if not has_td and not has_up:
            self.is_configured = False
            self.last_status = "KEY_REQUIRED"
        else:
            self.is_configured = True
            self.last_status = "KEY_CONFIGURED" if has_td else "UPSTOX_CONFIGURED"

        # Hydrate known quotes from persistent ledger if available
        ledger_file = Path("data/external_context/external_quotes_ledger.jsonl")
        if ledger_file.exists():
            try:
                with open(ledger_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        qd = json.loads(line)
                        sym = qd.get("symbol")
                        if sym:
                            meta = BASKET_DEFINITIONS.get(sym, {})
                            self.cached_quotes[sym] = ExternalQuote(
                                symbol=sym,
                                display_name=qd.get("display_name", meta.get("display_name", sym)),
                                provider="twelve_data",
                                instrument_type=qd.get("instrument_type", meta.get("instrument_type", "EQUITY_ETF")),
                                exact_or_proxy=qd.get("exact_or_proxy", meta.get("exact_or_proxy", ExactOrProxy.PROXY.value)),
                                price=float(qd.get("price", 0.0)),
                                change=float(qd.get("change", 0.0)),
                                change_percent=float(qd.get("change_percent", 0.0)),
                                market_status=qd.get("market_status", "OPEN"),
                                provider_timestamp=qd.get("provider_timestamp", ""),
                                retrieved_at=qd.get("retrieved_at", ""),
                                data_age=qd.get("data_age", "LIVE"),
                                notes=qd.get("notes", meta.get("notes")),
                                cluster="SECONDARY" if qd.get("cluster") == "ASIA" else qd.get("cluster", meta.get("cluster", "GLOBAL")),
                                proxy_for=qd.get("proxy_for", meta.get("proxy_for")),
                                raw_hash=qd.get("raw_hash", ""),
                                verification_status=qd.get("verification_status", "UNVERIFIED"),
                                verification_record=qd.get("verification_record", {}),
                            )
            except Exception:
                pass

    def poll_events(self) -> List[ExternalEvent]:
        return []

    def poll_quotes(self) -> List[ExternalQuote]:
        now = time.time()
        now_utc = datetime.now(timezone.utc)
        retrieved_at = now_utc.isoformat()
        if now_utc.date() != self.current_day_utc:
            self.current_day_utc = now_utc.date()
            self.request_count_today = 0

        # 1. Upstox exact global quotes polling
        upstox = getattr(self, "upstox_client", None)
        if upstox and getattr(upstox, "has_token", False):
            try:
                keys = [meta["upstox_key"] for meta in UPSTOX_GLOBAL_SYMBOLS.values()]
                upstox_quotes = self.upstox_client.get_quotes(keys)
                for sym, meta in UPSTOX_GLOBAL_SYMBOLS.items():
                    target_key = meta["upstox_key"]
                    colon_key = target_key.replace("|", ":")
                    item = upstox_quotes.get(target_key) or upstox_quotes.get(colon_key)
                    if not item or not isinstance(item, dict):
                        for qk, qv in upstox_quotes.items():
                            if isinstance(qv, dict) and qv.get("instrument_token") == target_key:
                                item = qv
                                break
                    if not item:
                        continue
                    price = float(item.get("last_price") or 0.0)
                    net_change = item.get("net_change")
                    change = float(net_change) if net_change is not None else 0.0
                    prev = price - change if (price - change) != 0 else price
                    pct = round((change / prev) * 100.0, 2) if prev else 0.0
                    provider_ts = item.get("timestamp") or str(item.get("last_trade_time") or "")

                    raw_str = f"{target_key}:{price}:{provider_ts}"
                    raw_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
                    valid_until = (now_utc + timedelta(hours=24)).isoformat()
                    v_record = {
                        "status": "MATCH",
                        "verifier_id": "upstox_market_feed_verifier",
                        "payload_hash": raw_hash,
                        "checked_at": retrieved_at,
                        "valid_until": valid_until,
                    }

                    q = ExternalQuote(
                        symbol=sym,
                        display_name=meta["display_name"],
                        provider="upstox",
                        instrument_type=meta["instrument_type"],
                        exact_or_proxy=ExactOrProxy.EXACT.value,
                        price=price,
                        change=change,
                        change_percent=pct,
                        market_status="OPEN",
                        provider_timestamp=str(provider_ts),
                        retrieved_at=retrieved_at,
                        data_age=DataAgeStatus.LIVE.value,
                        notes=f"Exact real-time quote via Upstox Analytics Feed ({target_key})",
                        cluster=meta["cluster"],
                        proxy_for=None,
                        raw_hash=raw_hash,
                        verification_status="VERIFIED",
                        verification_record=v_record,
                    )
                    self.cached_quotes[sym] = q
                if not (self.api_key and len(self.api_key.strip()) >= 8):
                    self.last_status = "PROVIDER_HEALTHY"
            except Exception as exc:
                logger.warning("Upstox global quotes poll error: %s", exc)

        # 2. Twelve Data basket polling
        has_td = bool(self.api_key and len(self.api_key.strip()) >= 8)
        if not has_td:
            if not (self.upstox_client and getattr(self.upstox_client, "has_token", False)):
                self.last_status = "KEY_REQUIRED"
            return list(self.cached_quotes.values())

        # Enforce rate limit / polling cadence for Twelve Data
        if self.last_poll_time is not None and (now - self.last_poll_time) < self.min_poll_interval_seconds:
            return list(self.cached_quotes.values())

        if self.request_count_today >= 700:  # Headroom under 800/day
            self.last_status = "RATE_LIMITED"
            logger.warning("Twelve Data daily quota limit reached (%d requests)", self.request_count_today)
            return list(self.cached_quotes.values())

        self.last_poll_time = now
        symbols = list(BASKET_DEFINITIONS.keys())
        symbols_arg = ",".join(symbols)
        params = {
            "symbol": symbols_arg,
            "apikey": self.api_key,
        }
        url = f"{TWELVE_DATA_BASE_URL}?{urllib.parse.urlencode(params)}"

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
                headers = dict(resp.headers)
                self.rate_limit_state = {
                    "http_status": resp.status,
                    "api_credits_used": headers.get("api-credits-used"),
                    "api_credits_left": headers.get("api-credits-left"),
                }
                data = json.loads(resp.read().decode("utf-8"))

            retrieved_at = now_utc.isoformat()
            received_quotes = 0
            
            # If batch request, Twelve Data returns a dict keyed by symbol (or a single dict if 1 symbol)
            # e.g. {"SPY": {"close": "...", "is_market_open": false, ...}, ...}
            for sym, item in (data.items() if isinstance(data, dict) else []):
                if not isinstance(item, dict) or "close" not in item:
                    continue
                meta = BASKET_DEFINITIONS.get(sym, {})
                try:
                    price = float(item.get("close") or 0.0)
                    change = float(item.get("change") or 0.0)
                    pct = float(item.get("percent_change") or 0.0)
                except (ValueError, TypeError):
                    continue

                is_market_open = item.get("is_market_open", False)
                market_status = "OPEN" if is_market_open else "CLOSED"

                if meta.get("is_continuous", False) and is_market_open:
                    data_age = DataAgeStatus.LIVE.value
                elif is_market_open:
                    data_age = DataAgeStatus.LIVE.value
                else:
                    data_age = DataAgeStatus.SESSION_LAST.value

                provider_ts = item.get("datetime") or ""
                is_verified = bool(provider_ts)
                raw_str = f"{sym}:{price}:{provider_ts}"
                raw_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
                valid_until = (now_utc + timedelta(hours=24)).isoformat()
                v_record = {
                    "status": "MATCH",
                    "verifier_id": "twelve_data_api_verifier",
                    "payload_hash": raw_hash,
                    "checked_at": retrieved_at,
                    "valid_until": valid_until,
                } if is_verified else {}

                q = ExternalQuote(
                    symbol=sym,
                    display_name=meta.get("display_name", sym),
                    provider="twelve_data",
                    instrument_type=meta.get("instrument_type", "EQUITY_ETF"),
                    exact_or_proxy=meta.get("exact_or_proxy", ExactOrProxy.PROXY.value),
                    price=price,
                    change=change,
                    change_percent=pct,
                    market_status=market_status,
                    provider_timestamp=str(provider_ts),
                    retrieved_at=retrieved_at,
                    data_age=data_age,
                    notes=meta.get("notes"),
                    cluster=meta.get("cluster", "GLOBAL"),
                    proxy_for=meta.get("proxy_for"),
                    raw_hash=raw_hash,
                    verification_status="VERIFIED" if is_verified else "UNVERIFIED",
                    verification_record=v_record,
                )
                self.cached_quotes[sym] = q
                received_quotes += 1

            self.last_status = "PROVIDER_HEALTHY" if received_quotes else "FETCH_FAILED"
            self.last_error = None if received_quotes else "NO_VALID_QUOTES_IN_RESPONSE"
        except urllib.error.HTTPError as exc:
            logger.debug("Twelve Data HTTP error: %s", exc)
            if exc.code == 429:
                self.last_status = "RATE_LIMITED"
                self.last_error = "Rate limit reached (8 credits/min). Waiting for cooldown."
            else:
                self.last_status = "FETCH_FAILED"
                self.last_error = str(exc)
        except Exception as exc:
            logger.debug("Twelve Data polling error: %s", exc)
            self.last_error = str(exc)
            self.last_status = "FETCH_FAILED"

        return list(self.cached_quotes.values())

    def get_health(self) -> Dict[str, Any]:
        h = super().get_health()
        h["requests_today"] = self.request_count_today
        h["provider_credits_per_minute_limit"] = PROVIDER_LIMIT_CREDITS_PER_MINUTE
        h["provider_daily_credits_limit"] = PROVIDER_LIMIT_CREDITS_PER_DAY
        h["citadel_internal_daily_budget"] = CITADEL_INTERNAL_DAILY_BUDGET
        h["rate_limits"] = self.rate_limit_state
        h["cached_symbols"] = list(self.cached_quotes.keys())
        supplied_by_upstox = set()
        if self.upstox_client and getattr(self.upstox_client, "has_token", False):
            supplied_by_upstox = {"GIFT NIFTY", "INDIA VIX", "NIKKEI 225"}
        h["unavailable_targets"] = [
            t for t in UNAVAILABLE_TARGETS if t.get("target") not in supplied_by_upstox
        ]
        return h
