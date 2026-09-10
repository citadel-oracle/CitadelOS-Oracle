"""Upstox API Client and Market Data V3 WebSocket Manager.

Provides secure token resolution from macOS Keychain, rate-limited REST methods,
and generation-safe WebSocket V3 streaming with Protobuf decoding.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import ssl
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import certifi
import requests
import websockets
from websockets.exceptions import ConnectionClosed

from src.broker.upstox_proto import DecodedUpstoxFeed, UpstoxProtoDecoder

logger = logging.getLogger(__name__)


def resolve_upstox_token(service: str = "CITADEL_UPSTOX_ANALYTICS_TOKEN", account: str = "citadel") -> Optional[str]:
    """Securely resolves Upstox token from macOS Keychain or environment without logging."""
    # Check env first for testing/CI overrides
    env_token = os.getenv(service) or os.getenv("UPSTOX_ACCESS_TOKEN")
    if env_token and len(env_token.strip()) > 20:
        return env_token.strip()

    # Query macOS Keychain
    try:
        res = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if res.returncode == 0:
            token = res.stdout.strip()
            if len(token) > 20:
                return token
    except Exception as exc:
        logger.warning("Keychain lookup for %s failed: %s", service, exc)
    return None


def get_token_fingerprint(token: Optional[str]) -> str:
    """Returns a safe cryptographic fingerprint of the token for logging."""
    if not token:
        return "NO_TOKEN"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:10]}...{digest[-6:]}"


def inspect_token_claims(token: Optional[str]) -> Dict[str, Any]:
    """Safely extracts standard JWT claims from header and payload without secrets."""
    if not token or "." not in token:
        return {"valid": False, "error": "NOT_A_JWT"}
    parts = token.split(".")
    if len(parts) < 2:
        return {"valid": False, "error": "INVALID_JWT_PARTS"}
    try:
        # Base64 url decode
        payload_b64 = parts[1] + "=="
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        iat = payload.get("iat")
        now = time.time()
        expired = exp is not None and now > exp
        days_left = ((exp - now) / 86400.0) if exp else None
        return {
            "valid": True,
            "sub": payload.get("sub"),
            "isPlusPlan": payload.get("isPlusPlan"),
            "isExtended": payload.get("isExtended"),
            "isMultiClient": payload.get("isMultiClient"),
            "issued_at": datetime.fromtimestamp(iat, tz=timezone.utc).isoformat() if iat else None,
            "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat() if exp else None,
            "expired": expired,
            "days_remaining": round(days_left, 1) if days_left is not None else None,
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


class UpstoxClient:
    """Read-only Upstox API client for market data, option chains, and WebSocket V3."""

    BASE_URL = "https://api.upstox.com/v2"
    BASE_URL_V3 = "https://api.upstox.com/v3"

    def __init__(
        self,
        token: Optional[str] = None,
        keychain_service: str = "CITADEL_UPSTOX_ANALYTICS_TOKEN",
        keychain_account: str = "citadel",
        session: Optional[requests.Session] = None,
    ) -> None:
        self._keychain_service = keychain_service
        self._keychain_account = keychain_account
        self._token = token or resolve_upstox_token(keychain_service, keychain_account)
        self._claims = inspect_token_claims(self._token)
        self._fingerprint = get_token_fingerprint(self._token)
        self._session = session or requests.Session()
        self._session.verify = certifi.where()
        self._last_auth_error: Optional[str] = None
        self._last_request_at: float = 0.0

    @property
    def has_token(self) -> bool:
        return bool(self._token and len(self._token) > 20)

    @property
    def is_token_expired(self) -> bool:
        return bool(self._claims.get("expired", True))

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def safe_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def claims(self) -> Dict[str, Any]:
        return dict(self._claims)

    @property
    def jwt_claims(self) -> Dict[str, Any]:
        return dict(self._claims)

    def _auth_headers(self) -> Dict[str, str]:
        if not self._token:
            raise RuntimeError("Upstox Analytics Token is missing or unresolved from Keychain.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _get(self, url: str, params: Optional[Any] = None, timeout: float = 8.0) -> Dict[str, Any]:
        """Performs a rate-guarded GET request."""
        self._last_request_at = time.time()
        headers = self._auth_headers()
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                self._last_auth_error = None
                return resp.json()
            elif resp.status_code == 401:
                self._last_auth_error = f"UNAUTHORIZED: {resp.text[:200]}"
                logger.error("Upstox 401 Unauthorized: %s", self._last_auth_error)
            elif resp.status_code == 429:
                logger.warning("Upstox 429 Rate Limit encountered on %s", url)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("Upstox GET error on %s: %s", url, exc)
            raise

    # -------------------------------------------------------------------------
    # WebSocket V3 Authorization
    # -------------------------------------------------------------------------
    def get_market_data_feed_authorize_url(self) -> str:
        """Obtains authorized WebSocket URL for Market Data Feed V3."""
        url = f"{self.BASE_URL_V3}/feed/market-data-feed/authorize"
        data = self._get(url)
        redirect_uri = (data.get("data") or {}).get("authorized_redirect_uri") or (data.get("data") or {}).get("authorizedRedirectUri")
        if not redirect_uri:
            raise ValueError(f"Upstox authorize endpoint did not return redirect URI: {data}")
        return str(redirect_uri)

    # -------------------------------------------------------------------------
    # REST Market Quotes & LTP
    # -------------------------------------------------------------------------
    def get_quotes(self, instrument_keys: List[str]) -> Dict[str, Any]:
        """Fetches full market quotes V3 for up to 500 instrument keys."""
        if not instrument_keys:
            return {}
        keys_str = ",".join(instrument_keys[:500])
        url = f"{self.BASE_URL}/market-quote/quotes"
        data = self._get(url, params={"instrument_key": keys_str})
        return data.get("data") or {}

    def get_ltp(self, instrument_keys: List[str]) -> Dict[str, Any]:
        """Fetches batch LTP quotes for up to 500 instrument keys."""
        if not instrument_keys:
            return {}
        keys_str = ",".join(instrument_keys[:500])
        url = f"{self.BASE_URL}/market-quote/ltp"
        data = self._get(url, params={"instrument_key": keys_str})
        return data.get("data") or {}

    # -------------------------------------------------------------------------
    # Options Contracts & Option Chain
    # -------------------------------------------------------------------------
    def get_option_contracts(self, underlying_key: str = "NSE_INDEX|Nifty 50") -> List[Dict[str, Any]]:
        """Retrieves active option contracts for an underlying symbol."""
        url = f"{self.BASE_URL}/option/contract"
        data = self._get(url, params={"instrument_key": underlying_key})
        return data.get("data") or []

    def get_option_chain(self, underlying_key: str, expiry_date: str) -> List[Dict[str, Any]]:
        """Retrieves put/call option chain with Greeks for an underlying and expiry."""
        url = f"{self.BASE_URL}/option/chain"
        data = self._get(url, params={"instrument_key": underlying_key, "expiry_date": expiry_date})
        return data.get("data") or []

    # -------------------------------------------------------------------------
    # Market Information APIs (Institutional F&O facts)
    # -------------------------------------------------------------------------
    def get_pcr(self, underlying_key: str, expiry_date: str, date_str: str, bucket_interval: int = 60) -> Dict[str, Any]:
        """Fetches Put-Call Ratio for underlying asset on date and expiry."""
        url = f"{self.BASE_URL}/market/pcr"
        params = {
            "instrument_key": underlying_key,
            "expiry": expiry_date,
            "date": date_str,
            "bucket_interval": bucket_interval,
        }
        data = self._get(url, params=params)
        return data.get("data") or {}

    def get_max_pain(self, underlying_key: str, expiry_date: str, date_str: str, bucket_interval: int = 60) -> Dict[str, Any]:
        """Fetches Max Pain strike for underlying asset on date and expiry."""
        url = f"{self.BASE_URL}/market/max-pain"
        params = {
            "instrument_key": underlying_key,
            "expiry": expiry_date,
            "date": date_str,
            "bucket_interval": bucket_interval,
        }
        data = self._get(url, params=params)
        return data.get("data") or {}

    def get_open_interest(self, underlying_key: str, expiry_date: str, date_str: str) -> Dict[str, Any]:
        """Fetches strike-wise open interest totals for underlying asset."""
        url = f"{self.BASE_URL}/market/oi"
        params = {
            "instrument_key": underlying_key,
            "expiry": expiry_date,
            "date": date_str,
        }
        data = self._get(url, params=params)
        return data.get("data") or {}

    def get_change_oi(self, underlying_key: str, expiry_date: str, date_str: str, interval: int = 1) -> Dict[str, Any]:
        """Fetches change in open interest per strike (interval in days, default 1)."""
        url = f"{self.BASE_URL}/market/change-oi"
        params = {
            "instrument_key": underlying_key,
            "expiry": expiry_date,
            "date": date_str,
            "interval": interval,
        }
        data = self._get(url, params=params)
        return data.get("data") or {}

    def get_fii_data(self, date_str: str, interval: str = "1D") -> Dict[str, Any]:
        """Fetches FII activity across index futures, index options, and cash segments."""
        url = f"{self.BASE_URL}/market/fii"
        params = [
            ("data_type", "NSE_FO|INDEX_FUTURES"),
            ("data_type", "NSE_FO|INDEX_OPTIONS"),
            ("data_type", "NSE_EQ|CASH"),
            ("interval", interval),
            ("date", date_str),
        ]
        data = self._get(url, params=params)
        return data.get("data") or {}

    def get_dii_data(self, date_str: str, interval: str = "1D") -> Dict[str, Any]:
        """Fetches DII activity in cash segment."""
        url = f"{self.BASE_URL}/market/dii"
        params = [
            ("data_type", "NSE_EQ|CASH"),
            ("interval", interval),
            ("date", date_str),
        ]
        data = self._get(url, params=params)
        return data.get("data") or {}

    # -------------------------------------------------------------------------
    # Historical / Intraday Candle APIs
    # -------------------------------------------------------------------------
    def get_intraday_candles(self, instrument_key: str, interval: str = "1") -> List[Dict[str, Any]]:
        """Fetches completed 1-minute intraday candles for instrument from Upstox V3.

        Returns list of normalized dicts with:
        {'time': epoch_sec, 'open': float, 'high': float, 'low': float, 'close': float, 'volume': float, 'open_interest': float}
        sorted ascending by time.
        """
        import urllib.parse
        encoded_key = urllib.parse.quote(instrument_key)
        url = f"{self.BASE_URL_V3}/historical-candle/intraday/{encoded_key}/minutes/{interval}"
        try:
            data = self._get(url)
        except Exception as exc:
            logger.warning("Upstox intraday candle fetch failed for %s: %s", instrument_key, exc)
            return []
        raw_candles = (data.get("data") or {}).get("candles") or []
        normalized: List[Dict[str, Any]] = []
        for c in raw_candles:
            if not isinstance(c, (list, tuple)) or len(c) < 5:
                continue
            try:
                dt = datetime.fromisoformat(str(c[0]))
                epoch = int(dt.timestamp())
                o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
                vol = float(c[5]) if len(c) > 5 and c[5] is not None else 0.0
                oi = float(c[6]) if len(c) > 6 and c[6] is not None else None
                candle = {
                    "time": epoch,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": vol,
                    "open_interest": oi,
                    "source": "UPSTOX_INTRADAY_V3",
                }
                normalized.append(candle)
            except Exception:
                continue
        return sorted(normalized, key=lambda x: x["time"])

    def get_historical_candles(self, instrument_key: str, interval: str = "1", to_date: str = "", from_date: str = "") -> List[Dict[str, Any]]:
        """Fetches historical candles from Upstox V3 historical-candle endpoint."""
        import urllib.parse
        encoded_key = urllib.parse.quote(instrument_key)
        url = f"{self.BASE_URL_V3}/historical-candle/{encoded_key}/minutes/{interval}/{to_date}/{from_date}"
        try:
            data = self._get(url)
        except Exception as exc:
            logger.warning("Upstox historical candle fetch failed for %s: %s", instrument_key, exc)
            return []
        raw_candles = (data.get("data") or {}).get("candles") or []
        normalized: List[Dict[str, Any]] = []
        for c in raw_candles:
            if not isinstance(c, (list, tuple)) or len(c) < 5:
                continue
            try:
                dt = datetime.fromisoformat(str(c[0]))
                epoch = int(dt.timestamp())
                o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
                vol = float(c[5]) if len(c) > 5 and c[5] is not None else 0.0
                oi = float(c[6]) if len(c) > 6 and c[6] is not None else None
                normalized.append({
                    "time": epoch,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": vol,
                    "open_interest": oi,
                })
            except Exception:
                continue
        return sorted(normalized, key=lambda x: x["time"])


class UpstoxMarketDataFeedV3:
    """WebSocket V3 live market data streaming client with Protobuf decoding."""

    RECONNECT_INITIAL_DELAY_SECONDS = 1.0
    RECONNECT_MAX_DELAY_SECONDS = 60.0

    def __init__(
        self,
        client: UpstoxClient,
        on_tick: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_raw_packet: Optional[Callable[[bytes], None]] = None,
        on_transport_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        subscription_mode: str = "full",
    ) -> None:
        self.client = client
        self.on_tick = on_tick
        self.on_raw_packet = on_raw_packet
        self.on_transport_event = on_transport_event
        self.subscription_mode = subscription_mode  # "full" (d5) or "full_d30"

        self._subscribed_keys: Set[str] = set()
        self._snapshot_keys: Set[str] = set()
        self._keys_lock = threading.Lock()
        self._is_running = False
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reconnect_delay = self.RECONNECT_INITIAL_DELAY_SECONDS
        self._connection_state = "DISCONNECTED"  # DISCONNECTED -> AUTHORIZING -> SOCKET_CONNECTED -> MARKET_INFO_RECEIVED -> SNAPSHOT_HYDRATING -> BASELINE_READY -> LIVE
        self._generation = 0  # Serves as feed_epoch
        self._last_tick_time: Optional[datetime] = None
        self._ticks_received_count = 0
        self._packets_received_count = 0
        self._last_error: Optional[str] = None
        self._last_disconnect_time: Optional[str] = None
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    @property
    def connection_state(self) -> str:
        return self._connection_state

    @property
    def feed_epoch(self) -> int:
        return self._generation

    @property
    def is_baseline_ready(self) -> bool:
        return self._connection_state in ("BASELINE_READY", "LIVE")

    @property
    def ticks_received_count(self) -> int:
        return self._ticks_received_count

    @property
    def last_tick_time(self) -> Optional[datetime]:
        return self._last_tick_time

    def subscribe(self, instrument_keys: List[str]) -> None:
        """Replaces the subscribed instrument keys thread-safely."""
        keys = set(k for k in instrument_keys if k and isinstance(k, str))
        with self._keys_lock:
            if keys != self._subscribed_keys:
                self._subscribed_keys = keys
                self._snapshot_keys.clear()
                # If connected, schedule dynamic subscription update
                if self._ws and self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._send_subscription(), self._loop)

    async def _send_subscription(self) -> None:
        if not self._ws or self._ws.closed:
            return
        with self._keys_lock:
            keys = list(self._subscribed_keys)
        if not keys:
            return
        payload = {
            "guid": f"citadel_v3_gen{self._generation}_{int(time.time())}",
            "method": "sub",
            "data": {
                "mode": self.subscription_mode,
                "instrumentKeys": keys,
            },
        }
        try:
            await self._ws.send(json.dumps(payload).encode("utf-8"))
            logger.info("Upstox V3 sent subscription for %d keys in mode '%s'", len(keys), self.subscription_mode)
            if self.on_transport_event:
                self.on_transport_event("UPSTOX_SUBSCRIPTION_SENT", {"count": len(keys), "mode": self.subscription_mode, "epoch": self._generation})
        except Exception as exc:
            logger.error("Failed to send Upstox subscription: %s", exc)

    async def start(self) -> None:
        """Main lifecycle loop with bounded reconnect, deterministic readiness, and generation safety."""
        if self._is_running:
            return
        self._is_running = True
        self._loop = asyncio.get_running_loop()

        while self._is_running:
            self._generation += 1
            gen = self._generation
            self._snapshot_keys.clear()
            try:
                self._connection_state = "AUTHORIZING"
                auth_url = self.client.get_market_data_feed_authorize_url()
                self._connection_state = "CONNECTING"

                async with websockets.connect(
                    auth_url,
                    ssl=self._ssl_context,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connection_state = "SOCKET_CONNECTED"
                    self._reconnect_delay = self.RECONNECT_INITIAL_DELAY_SECONDS
                    self._last_error = None
                    logger.info("Upstox V3 WebSocket connected (epoch %d)", gen)
                    if self.on_transport_event:
                        self.on_transport_event("UPSTOX_CONNECTED", {"epoch": gen})

                    # Send subscription
                    await self._send_subscription()

                    # Receive loop
                    while self._is_running and gen == self._generation:
                        try:
                            msg = await ws.recv()
                        except ConnectionClosed as cc:
                            logger.warning("Upstox V3 socket closed: code=%s, reason=%s", cc.code, cc.reason)
                            break

                        if isinstance(msg, bytes):
                            self._packets_received_count += 1
                            if self.on_raw_packet:
                                try:
                                    self.on_raw_packet(msg)
                                except Exception as cb_exc:
                                    logger.exception("Upstox raw packet callback error: %s", cb_exc)

                            try:
                                decoded = UpstoxProtoDecoder.decode_packet(msg)
                                feed_type = decoded.feed_type  # 0: initial_feed, 1: live_feed, 2: market_info

                                # Feed Readiness Lifecycle Transition
                                if feed_type == 2:
                                    if self._connection_state == "SOCKET_CONNECTED":
                                        self._connection_state = "MARKET_INFO_RECEIVED"
                                    if self.on_transport_event:
                                        self.on_transport_event("UPSTOX_MARKET_INFO", {"market_info": decoded.market_info, "epoch": gen})
                                elif feed_type == 0:
                                    # Snapshot hydration phase
                                    if self._connection_state in ("SOCKET_CONNECTED", "MARKET_INFO_RECEIVED"):
                                        self._connection_state = "SNAPSHOT_HYDRATING"
                                    for t in decoded.ticks:
                                        ikey = str(t.get("instrument_key") or "")
                                        if ikey:
                                            self._snapshot_keys.add(ikey)
                                    with self._keys_lock:
                                        expected = self._subscribed_keys
                                        if expected and len(self._snapshot_keys) >= len(expected) * 0.8:
                                            self._connection_state = "BASELINE_READY"
                                elif feed_type == 1:
                                    if self._connection_state in ("SNAPSHOT_HYDRATING", "BASELINE_READY", "SOCKET_CONNECTED", "MARKET_INFO_RECEIVED"):
                                        self._connection_state = "LIVE"

                                for tick in decoded.ticks:
                                    self._ticks_received_count += 1
                                    self._last_tick_time = datetime.now(timezone.utc)
                                    # Annotate deterministic feed lifecycle tags
                                    tick["feed_type"] = feed_type
                                    tick["feed_epoch"] = gen
                                    tick["is_snapshot"] = (feed_type == 0)
                                    tick["feed_state"] = self._connection_state
                                    if self.on_tick:
                                        self.on_tick(tick)
                            except Exception as parse_exc:
                                logger.error("Upstox Protobuf decode error: %s", parse_exc)

            except asyncio.CancelledError:
                self._is_running = False
                logger.info("Upstox V3 loop cancelled.")
                break
            except Exception as exc:
                self._last_error = str(exc)
                self._last_disconnect_time = datetime.now(timezone.utc).isoformat()
                self._connection_state = "DISCONNECTED"
                logger.error("Upstox V3 connection error: %s. Reconnecting in %.2fs...", exc, self._reconnect_delay)
                if self.on_transport_event:
                    self.on_transport_event("UPSTOX_DISCONNECTED", {"error": str(exc), "delay": self._reconnect_delay, "epoch": gen})

                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self.RECONNECT_MAX_DELAY_SECONDS, self._reconnect_delay * 1.5)
            finally:
                self._connection_state = "DISCONNECTED"
                self._ws = None

    def stop(self) -> None:
        self._is_running = False
        if self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def health(self) -> Dict[str, Any]:
        """Provides transport health status dictionary for upstream monitors."""
        with self._keys_lock:
            sub_count = len(self._subscribed_keys)
        return {
            "provider": "UPSTOX",
            "connection_state": self._connection_state,
            "feed_epoch": self._generation,
            "is_baseline_ready": self.is_baseline_ready,
            "token_fingerprint": self.client.fingerprint,
            "token_valid": self.client.has_token and not getattr(self.client, "is_token_expired", False),
            "days_remaining": self.client.claims.get("days_remaining"),
            "packets_received": self._packets_received_count,
            "ticks_received": self._ticks_received_count,
            "last_tick_time": self._last_tick_time.isoformat() if self._last_tick_time else None,
            "last_error": self._last_error,
            "last_disconnect_time": self._last_disconnect_time,
            "subscription_mode": self.subscription_mode,
            "subscribed_keys_count": sub_count,
            "snapshot_keys_count": len(self._snapshot_keys),
        }
