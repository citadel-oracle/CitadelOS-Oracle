import json
import os
import time
import threading
from datetime import datetime
from pathlib import Path

import requests

from src.risk.authorization import (
    RiskAuthorizationRequest,
    RiskAuthorizationService,
)


class BrokerMutationBlockedError(RuntimeError):
    """Raised before any network call when a live broker mutation is disabled."""

    def __init__(self, message, decision=None):
        super().__init__(message)
        self.decision = decision


class DhanClient:

    MIN_OPTION_CHAIN_INTERVAL_SECONDS = 3.0
    _option_chain_lock = threading.Lock()
    _last_option_chain_request_monotonic = 0.0
    _option_chain_request_count = 0

    READ_ONLY_POST_PREFIXES = (
        "/marketfeed/",
        "/charts/",
    )

    READ_ONLY_POST_ENDPOINTS = (
        "/optionchain",
        "/optionchain/expirylist",
    )

    def __init__(self, access_token=None, client_id=None, risk_authorizer=None, request_timeout=10):
        if access_token is None or client_id is None:
            from pathlib import Path
            import dotenv
            env_file = Path(".env")
            if env_file.exists():
                dotenv.load_dotenv(env_file)
            access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
            client_id = client_id or os.getenv("DHAN_CLIENT_ID")

        self.access_token = access_token
        self.client_id = client_id
        self.settings = self._load_settings()
        self.live_trading_enabled = self.settings.get("live_trading_enabled") is True
        self.risk_authorizer = risk_authorizer or RiskAuthorizationService(
            config_provider=self._load_settings
        )
        self.last_risk_decision = None
        self.request_timeout = float(request_timeout)
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be positive")

        if not self.access_token:
            raise ValueError("DHAN_ACCESS_TOKEN missing in .env")

        self.base_url = "https://api.dhan.co/v2"

        self.headers = {
            "access-token": self.access_token,
            "client-id": self.client_id or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_fund_limit(self):
        return self._get("/fundlimit")

    def get_quote(self, segment, security_id):
        payload = {segment: [int(security_id)]}
        data = self._post("/marketfeed/ohlc", payload)

        try:
            item = data["data"][segment][str(security_id)]
            ohlc = item.get("ohlc") or {}
            ltp = float(item["last_price"])
            previous_close = float(ohlc["close"])
            return {
                "ltp": ltp,
                "previous_close": previous_close,
                "change_percent": self._change_percent(ltp, previous_close),
                "ohlc": ohlc,
                "updated": "LIVE",
                "raw": item,
            }
        except Exception:
            return {
                "ltp": None,
                "previous_close": None,
                "change_percent": None,
                "ohlc": None,
                "updated": "NA",
                "raw": data,
            }

    def get_multiple_quotes(self, watchlist):
        payload = {}

        for _, item in watchlist.items():
            segment = item["segment"]
            security_id = int(item["security_id"])
            payload.setdefault(segment, []).append(security_id)

        data = self._post("/marketfeed/ohlc", payload)
        results = {}

        for symbol, item in watchlist.items():
            segment = item["segment"]
            security_id = str(item["security_id"])

            try:
                quote = data["data"][segment][security_id]
                ohlc = quote.get("ohlc") or {}
                ltp = float(quote["last_price"])
                previous_close = float(ohlc["close"])
                results[symbol] = {
                    "ltp": ltp,
                    "previous_close": previous_close,
                    "change_percent": self._change_percent(ltp, previous_close),
                    "ohlc": ohlc,
                    "updated": "LIVE",
                    "segment": segment,
                    "security_id": security_id,
                    "raw": quote,
                }
            except Exception:
                results[symbol] = {
                    "ltp": None,
                    "previous_close": None,
                    "change_percent": None,
                    "ohlc": None,
                    "updated": "NA",
                    "segment": segment,
                    "security_id": security_id,
                    "raw": data,
                }

        return results

    def get_full_quotes(self, watchlist):
        """Return Dhan's authoritative full-quote payload for a named watchlist."""

        payload = {}
        for item in watchlist.values():
            segment = str(item["segment"])
            security_id = int(item["security_id"])
            payload.setdefault(segment, []).append(security_id)

        response = self._post("/marketfeed/quote", payload)
        data = response.get("data") if isinstance(response, dict) else None
        results = {}
        for symbol, item in watchlist.items():
            segment = str(item["segment"])
            security_id = str(item["security_id"])
            quote = (
                (data.get(segment) or {}).get(security_id)
                if isinstance(data, dict)
                else None
            )
            results[symbol] = {
                "status": "AVAILABLE" if isinstance(quote, dict) else "UNAVAILABLE",
                "segment": segment,
                "security_id": security_id,
                "raw": dict(quote) if isinstance(quote, dict) else None,
                "reason": (
                    None
                    if isinstance(quote, dict)
                    else str(
                        response.get("errorMessage")
                        or response.get("errorCode")
                        or "DHAN_FULL_QUOTE_UNAVAILABLE"
                    )
                ),
            }
        return results

    @staticmethod
    def _change_percent(ltp, previous_close):
        if previous_close <= 0:
            return None

        return round(((ltp - previous_close) / previous_close) * 100, 2)

    def get_ltp(self):
        return self.get_quote("IDX_I", "13")

    def get_intraday_candles(
        self,
        segment,
        security_id,
        instrument="INDEX",
        interval="1",
        from_date=None,
        to_date=None,
    ):
        if from_date is None:
            from_date = datetime.now().strftime("%Y-%m-%d")
        if to_date is None:
            to_date = datetime.now().strftime("%Y-%m-%d")

        payload = {
            "securityId": str(security_id),
            "exchangeSegment": segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        }

        data = self._post("/charts/intraday", payload)

        try:
            if not isinstance(data, dict):
                raise ValueError("DHAN_HISTORY_RESPONSE_INVALID")
            if data.get("errorCode") or data.get("errorType"):
                return {
                    "success": False,
                    "candles": [],
                    "error": ":".join(
                        str(value)
                        for value in (
                            data.get("errorCode"),
                            data.get("errorMessage"),
                        )
                        if value
                    ) or "DHAN_HISTORY_UNAVAILABLE",
                    "raw": data,
                }
            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])
            volumes = data.get("volume", [])
            timestamps = data.get("timestamp", [])
            if not all(
                isinstance(values, list)
                for values in (opens, highs, lows, closes, volumes, timestamps)
            ):
                raise ValueError("DHAN_HISTORY_SCHEMA_INVALID")
            if not (
                len(opens)
                == len(highs)
                == len(lows)
                == len(closes)
                == len(timestamps)
            ):
                raise ValueError("DHAN_HISTORY_LENGTH_MISMATCH")

            candles = []

            for i in range(len(closes)):
                candles.append({
                    "time": timestamps[i] if i < len(timestamps) else None,
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": float(volumes[i]) if i < len(volumes) else None,
                })

            return {
                "success": True,
                "candles": candles,
                "raw": data,
            }

        except Exception as e:
            return {
                "success": False,
                "candles": [],
                "error": str(e),
                "raw": data,
            }

    def get_option_expiries(self, segment, security_id):
        return self._post(
            "/optionchain/expirylist",
            {
                "UnderlyingScrip": int(security_id),
                "UnderlyingSeg": segment,
            },
        )

    def get_option_chain(self, segment, security_id, expiry):
        with DhanClient._option_chain_lock:
            now = time.monotonic()
            elapsed = now - DhanClient._last_option_chain_request_monotonic
            if elapsed < DhanClient.MIN_OPTION_CHAIN_INTERVAL_SECONDS:
                time.sleep(DhanClient.MIN_OPTION_CHAIN_INTERVAL_SECONDS - elapsed)
            DhanClient._last_option_chain_request_monotonic = time.monotonic()
            DhanClient._option_chain_request_count += 1
        return self._post(
            "/optionchain",
            {
                "UnderlyingScrip": int(security_id),
                "UnderlyingSeg": segment,
                "Expiry": str(expiry),
            },
        )

    def place_order(self, payload, risk_context=None):
        return self._post("/orders", payload, risk_context=risk_context)

    def modify_order(self, order_id, payload, risk_context=None):
        return self._request(
            "PUT",
            f"/orders/{order_id}",
            payload,
            risk_context=risk_context,
        )

    def cancel_order(self, order_id, risk_context=None):
        return self._request(
            "DELETE",
            f"/orders/{order_id}",
            risk_context=risk_context,
        )

    def get_orders(self):
        return self._get("/orders")

    def get_order(self, order_id):
        return self._get(f"/orders/{order_id}")

    def get_order_by_correlation_id(self, correlation_id):
        return self._get(f"/orders/external/{correlation_id}")

    def get_trades(self, order_id=None):
        return self._get(f"/trades/{order_id}" if order_id else "/trades")

    def get_positions(self):
        return self._get("/positions")

    def get_profile(self):
        return self._get("/profile")

    def renew_token(self):
        """Renew active Dhan access token and update in-memory client and .env file."""
        response = self._request(
            "GET",
            "/RenewToken",
            headers={"access-token": self.access_token, "dhanClientId": self.client_id or ""},
        )
        token = (response.get("token") or response.get("accessToken")) if isinstance(response, dict) else None
        if token:
            self.access_token = token
            self.headers["access-token"] = token
            env_path = Path(".env")
            if env_path.exists():
                try:
                    content = env_path.read_text(encoding="utf-8")
                    lines = content.splitlines()
                    new_lines = []
                    found = False
                    for line in lines:
                        if line.startswith("DHAN_ACCESS_TOKEN="):
                            new_lines.append(f"DHAN_ACCESS_TOKEN={token}")
                            found = True
                        else:
                            new_lines.append(line)
                    if not found:
                        new_lines.append(f"DHAN_ACCESS_TOKEN={token}")
                    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                except Exception:
                    pass
        return response

    def _get(self, endpoint):
        return self._request("GET", endpoint)

    def _post(self, endpoint, payload, risk_context=None):
        return self._request(
            "POST", endpoint, payload, risk_context=risk_context
        )

    def _request(self, method, endpoint, payload=None, risk_context=None, headers=None):
        method = method.upper()

        if method != "GET" and not self._is_read_only_request(method, endpoint):
            self._assert_mutation_allowed(
                method,
                endpoint,
                payload=payload,
                risk_context=risk_context,
            )

        try:
            request_args = {
                "headers": headers or self.headers,
                "timeout": self.request_timeout,
            }

            if payload is not None:
                request_args["json"] = payload

            request_method = {
                "GET": requests.get,
                "POST": requests.post,
                "PUT": requests.put,
                "DELETE": requests.delete,
                "PATCH": requests.patch,
            }.get(method)

            if request_method is None:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response = request_method(
                f"{self.base_url}{endpoint}",
                **request_args,
            )
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def _is_read_only_request(self, method, endpoint):
        return method == "POST" and (
            endpoint in self.READ_ONLY_POST_ENDPOINTS
            or endpoint.startswith(self.READ_ONLY_POST_PREFIXES)
        )

    def _assert_mutation_allowed(
        self,
        method,
        endpoint,
        payload=None,
        risk_context=None,
    ):
        self.settings = self._load_settings()
        self.live_trading_enabled = self.settings.get("live_trading_enabled") is True

        request = RiskAuthorizationRequest.from_broker_mutation(
            method=method,
            endpoint=endpoint,
            payload=payload,
            risk_context=risk_context,
        )
        decision = self.risk_authorizer.authorize(request)
        self.last_risk_decision = decision

        if decision.allowed:
            return

        raise BrokerMutationBlockedError(
            "Dhan broker mutation blocked: "
            f"{decision.reason_code} - {decision.reason} "
            f"before {method} {endpoint}.",
            decision=decision,
        )

    @staticmethod
    def _load_settings():
        settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.json"

        try:
            with settings_path.open("r") as settings_file:
                return json.load(settings_file)
        except Exception:
            return {}
