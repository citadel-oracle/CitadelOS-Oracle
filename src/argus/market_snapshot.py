"""Canonical full-market evidence for ARGUS PRIME.

The provider is called only by the background ARGUS producer.  V2 and React
consume its last complete immutable publication and never trigger Dhan I/O.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import urllib.request
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
from zoneinfo import ZoneInfo


class ArgusMarketSnapshotProvider:
    MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    IST = ZoneInfo("Asia/Kolkata")
    SCHEMA_VERSION = 1
    RETAINED_SOURCES = 12

    def __init__(
        self,
        dhan,
        *,
        state_path: str | Path,
        master_path: str | Path,
        clock=None,
        master_loader=None,
        refresh_ttl_seconds: float = 3.0,
    ):
        self.dhan = dhan
        self.state_path = Path(state_path)
        self.master_path = Path(master_path)
        self.clock = clock or (lambda: datetime.now(self.IST))
        self.master_loader = master_loader or self._download_master
        self.refresh_ttl_seconds = max(0.0, float(refresh_ttl_seconds))
        self._lock = Lock()
        self._dhan_dormant: bool = False
        from src.broker.upstox_client import UpstoxClient
        self.upstox = UpstoxClient()

    def refresh(self, argus_projection: Mapping[str, Any]) -> dict[str, Any]:
        """Fetch one batched full quote and atomically publish its derived evidence."""

        with self._lock:
            latest = self._load().get("current")
            if isinstance(latest, Mapping):
                try:
                    age = (
                        self.clock()
                        - datetime.fromisoformat(str(latest["fetched_at"]))
                    ).total_seconds()
                except (KeyError, TypeError, ValueError):
                    age = self.refresh_ttl_seconds
                projection_data = argus_projection.get("data")
                projection_data = (
                    projection_data if isinstance(projection_data, Mapping) else {}
                )
                projection_underlying = projection_data.get("underlying")
                projection_underlying = (
                    projection_underlying
                    if isinstance(projection_underlying, Mapping)
                    else {}
                )
                same_source = (
                    latest.get("argus_source_timestamp")
                    == projection_underlying.get("fetched_at")
                )
                if same_source and 0.0 <= age < self.refresh_ttl_seconds:
                    return deepcopy(dict(latest))
            data = argus_projection.get("data")
            data = data if isinstance(data, Mapping) else {}
            underlying = data.get("underlying")
            underlying = underlying if isinstance(underlying, Mapping) else {}
            rows = [
                row
                for row in data.get("atm_window") or []
                if isinstance(row, Mapping)
            ]
            now = self.clock()
            contract = self._resolve_near_month(now.date())
            watchlist: dict[str, dict[str, Any]] = {
                "NIFTY_FUT": {
                    "segment": "NSE_FNO",
                    "security_id": contract["security_id"],
                }
            }
            for row in rows:
                strike = self._number(row.get("strike"))
                for side in ("ce", "pe"):
                    leg = row.get(side)
                    if isinstance(leg, Mapping) and leg.get("security_id") is not None:
                        watchlist[f"{strike:g}_{side.upper()}"] = {
                            "segment": "NSE_FNO",
                            "security_id": int(leg["security_id"]),
                        }

            source_provider = "UPSTOX"
            quotes = None

            # 1. Primary Active Path: Upstox
            if self.upstox.has_token and not self.upstox.is_token_expired:
                try:
                    source_provider = "UPSTOX"
                    upstox_keys = [f"NSE_FO|{contract['security_id']}"]
                    id_to_watchlist_key = {str(contract["security_id"]): "NIFTY_FUT"}
                    for w_key, w_val in watchlist.items():
                        if w_key != "NIFTY_FUT":
                            sec_id = str(w_val.get("security_id"))
                            upstox_keys.append(f"NSE_FO|{sec_id}")
                            id_to_watchlist_key[sec_id] = w_key

                    upstox_quotes = self.upstox.get_quotes(upstox_keys)
                    quotes = {}
                    for q_val in upstox_quotes.values():
                        token = q_val.get("instrument_token") or ""
                        if "|" in token:
                            sec_id = token.split("|")[1]
                            w_key = id_to_watchlist_key.get(sec_id)
                            if w_key:
                                raw_copy = dict(q_val)
                                raw_copy["buy_quantity"] = q_val.get("total_buy_quantity")
                                raw_copy["sell_quantity"] = q_val.get("total_sell_quantity")
                                quotes[w_key] = {
                                    "security_id": int(sec_id),
                                    "raw": raw_copy,
                                }
                except Exception as exc:
                    logger.warning("Upstox quote fetch in Argus snapshot failed: %s", exc)
                    quotes = None

            # 2. Dormant / Parallel Path: Dhan (only if Upstox was unavailable and Dhan is not dormant)
            if quotes is None and not self._dhan_dormant:
                try:
                    quotes = self.dhan.get_full_quotes(watchlist)
                    futures_quote = quotes.get("NIFTY_FUT") or {}
                    raw = futures_quote.get("raw")
                    if isinstance(raw, Mapping):
                        source_provider = "DHAN_V2_MARKETFEED_QUOTE"
                    else:
                        quotes = None
                except Exception as exc:
                    err_str = str(exc).upper()
                    if "DH-901" in err_str or "EXPIRED" in err_str or "401" in err_str or "403" in err_str:
                        self._dhan_dormant = True
                        logger.warning("Dhan token expired / unauthorized (%s); marked dormant in Argus snapshot.", exc)
                    quotes = None

            if not quotes:
                raise RuntimeError("MARKET_SNAPSHOT_QUOTES_UNAVAILABLE")

            futures_quote = quotes.get("NIFTY_FUT") or {}
            raw = futures_quote.get("raw")
            if not isinstance(raw, Mapping):
                raise RuntimeError(
                    str(futures_quote.get("reason") or "MARKET_SNAPSHOT_FUTURES_QUOTE_UNAVAILABLE")
                )

            previous_state = self._load()
            previous = previous_state.get("current")
            previous = previous if isinstance(previous, Mapping) else {}
            futures = self._futures_snapshot(
                raw=raw,
                contract=contract,
                spot=self._number(underlying.get("ltp")),
                fetched_at=now,
                previous=previous.get("futures"),
            )
            if source_provider == "UPSTOX":
                futures["source"] = "UPSTOX"
                futures["quote_source"] = "UPSTOX"
            option_depth = {}
            for key, quote in quotes.items():
                if key == "NIFTY_FUT" or not isinstance(quote.get("raw"), Mapping):
                    continue
                evidence = self._quote_evidence(
                    quote["raw"], fetched_at=now
                )
                if source_provider == "UPSTOX":
                    evidence["source"] = "UPSTOX"
                option_depth[str(quote["security_id"])] = evidence
            current = {
                "schema_version": self.SCHEMA_VERSION,
                "status": "AVAILABLE",
                "fetched_at": now.isoformat(),
                "argus_source_timestamp": underlying.get("fetched_at"),
                "source": source_provider,
                "provider": "UPSTOX" if source_provider == "UPSTOX" else "DHAN",
                "futures": futures,
                "option_market_depth": option_depth,
                "option_quote_count": len(option_depth),
            }
            recent = [
                item
                for item in (
                    [previous]
                    + list(previous_state.get("recent") or [])
                )
                if isinstance(item, Mapping)
                and item.get("argus_source_timestamp")
                != current["argus_source_timestamp"]
            ]
            recent = list(
                {
                    str(item.get("argus_source_timestamp")): dict(item)
                    for item in recent
                }.values()
            )[: self.RETAINED_SOURCES]
            self._atomic_write(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "current": current,
                    "previous": previous or None,
                    "recent": recent,
                }
            )
            return deepcopy(current)

    def latest(self, argus_source_timestamp: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            state = self._load()
            candidates = [
                state.get("current"),
                *(state.get("recent") or []),
                state.get("previous"),
            ]
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                if (
                    argus_source_timestamp is None
                    or candidate.get("argus_source_timestamp")
                    == argus_source_timestamp
                ):
                    return deepcopy(dict(candidate))
            return None

    def _resolve_near_month(self, today: date) -> dict[str, Any]:
        rows = self._master_rows()
        candidates = []
        for row in rows:
            if (
                str(row.get("UNDERLYING_SYMBOL") or "").upper() != "NIFTY"
                or str(row.get("INSTRUMENT") or "").upper() != "FUTIDX"
            ):
                continue
            try:
                expiry = date.fromisoformat(str(row.get("SM_EXPIRY_DATE"))[:10])
                security_id = int(row["SECURITY_ID"])
            except (KeyError, TypeError, ValueError):
                continue
            if expiry >= today:
                candidates.append((expiry, security_id, row))
        if not candidates:
            raise RuntimeError("NIFTY_NEAR_MONTH_FUTURES_UNRESOLVED")
        expiry, security_id, row = min(candidates, key=lambda item: item[:2])
        return {
            "security_id": security_id,
            "expiry": expiry.isoformat(),
            "symbol": row.get("SYMBOL_NAME") or f"NIFTY-{expiry:%b%Y}-FUT",
            "lot_size": self._integer(row.get("LOT_SIZE")),
            "segment": "NSE_FNO",
            "source": "DHAN_INSTRUMENT_MASTER",
        }

    def _master_rows(self) -> list[dict[str, str]]:
        try:
            cached = json.loads(self.master_path.read_text(encoding="utf-8"))
            fetched = date.fromisoformat(str(cached["fetched_at"])[:10])
            rows = cached.get("rows")
            if fetched == self.clock().date() and isinstance(rows, list):
                relevant = self._relevant_master_rows(rows)
                if len(relevant) != len(rows):
                    self._atomic_write_path(
                        self.master_path,
                        {"fetched_at": cached["fetched_at"], "rows": relevant},
                    )
                return relevant
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            pass
        rows = self._relevant_master_rows(self.master_loader())
        if not rows:
            raise RuntimeError("DHAN_INSTRUMENT_MASTER_EMPTY")
        self.master_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write_path(
            self.master_path,
            {"fetched_at": self.clock().isoformat(), "rows": rows},
        )
        return rows

    @staticmethod
    def _relevant_master_rows(rows) -> list[dict[str, str]]:
        return [
            dict(row)
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("UNDERLYING_SYMBOL") or "").upper() == "NIFTY"
            and str(row.get("INSTRUMENT") or "").upper() == "FUTIDX"
        ]

    def _download_master(self):
        with urllib.request.urlopen(self.MASTER_URL, timeout=15) as response:
            text = response.read().decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def _futures_snapshot(
        self,
        *,
        raw: Mapping[str, Any],
        contract: Mapping[str, Any],
        spot: float | None,
        fetched_at: datetime,
        previous: Any,
    ) -> dict[str, Any]:
        previous = previous if isinstance(previous, Mapping) else {}
        ltp = self._number(raw.get("last_price"))
        oi = self._number(raw.get("oi"))
        volume = self._number(raw.get("volume"))
        previous_ltp = self._number(previous.get("ltp"))
        previous_oi = self._number(previous.get("oi"))
        previous_volume = self._number(previous.get("volume"))
        elapsed = self._elapsed_seconds(previous.get("fetched_at"), fetched_at)
        depth = raw.get("depth") if isinstance(raw.get("depth"), Mapping) else {}
        buy_depth = list(depth.get("buy") or [])[:5]
        sell_depth = list(depth.get("sell") or [])[:5]
        buy_qty = self._number(raw.get("buy_quantity"))
        sell_qty = self._number(raw.get("sell_quantity"))
        depth_buy = sum(self._number(item.get("quantity")) or 0.0 for item in buy_depth if isinstance(item, Mapping))
        depth_sell = sum(self._number(item.get("quantity")) or 0.0 for item in sell_depth if isinstance(item, Mapping))
        top_bid = buy_depth[0] if buy_depth else {}
        top_ask = sell_depth[0] if sell_depth else {}
        basis = ltp - spot if ltp is not None and spot is not None else None
        prior_basis = self._number(previous.get("basis"))
        snapshot = {
            "status": "AVAILABLE",
            "security_id": contract["security_id"],
            "symbol": contract["symbol"],
            "expiry": contract["expiry"],
            "lot_size": contract["lot_size"],
            "segment": contract["segment"],
            "instrument_source": contract["source"],
            "quote_source": "DHAN_V2_MARKETFEED_QUOTE",
            "source_timestamp": self._trade_time(raw.get("last_trade_time"), fetched_at),
            "fetched_at": fetched_at.isoformat(),
            "ltp": ltp,
            "previous_close": self._number((raw.get("ohlc") or {}).get("close")) if isinstance(raw.get("ohlc"), Mapping) else None,
            "average_price": self._number(raw.get("average_price")),
            "price_change": self._difference(ltp, previous_ltp),
            "price_acceleration_per_minute": self._rate(self._difference(ltp, previous_ltp), elapsed),
            "oi": self._integer(oi),
            "oi_change": self._integer(self._difference(oi, previous_oi)),
            "oi_velocity_per_minute": self._rate(self._difference(oi, previous_oi), elapsed),
            "oi_day_high": self._integer(raw.get("oi_day_high")),
            "oi_day_low": self._integer(raw.get("oi_day_low")),
            "volume": self._integer(volume),
            "volume_change": self._integer(self._difference(volume, previous_volume)),
            "volume_velocity_per_minute": self._rate(self._difference(volume, previous_volume), elapsed),
            "total_buy_quantity": self._integer(buy_qty),
            "total_sell_quantity": self._integer(sell_qty),
            "quantity_imbalance_percentage": self._imbalance(buy_qty, sell_qty),
            "best_bid_price": self._number(top_bid.get("price")) if isinstance(top_bid, Mapping) else None,
            "best_bid_quantity": self._integer(top_bid.get("quantity")) if isinstance(top_bid, Mapping) else None,
            "best_ask_price": self._number(top_ask.get("price")) if isinstance(top_ask, Mapping) else None,
            "best_ask_quantity": self._integer(top_ask.get("quantity")) if isinstance(top_ask, Mapping) else None,
            "depth_imbalance_percentage": self._imbalance(depth_buy, depth_sell),
            "five_level_depth": {"buy": buy_depth, "sell": sell_depth},
            "last_trade_quantity": self._integer(raw.get("last_quantity")),
            "last_trade_time": raw.get("last_trade_time"),
            "spot": spot,
            "basis": basis,
            "basis_change": self._difference(basis, prior_basis),
            "elapsed_seconds": elapsed,
            "prior_snapshot_available": bool(previous),
            "change_basis": "PRIOR_AUTHORITATIVE_ARGUS_FULL_QUOTE",
        }
        try:
            snapshot["source_age_seconds"] = round(
                max(
                    0.0,
                    (
                        fetched_at
                        - datetime.fromisoformat(snapshot["source_timestamp"])
                    ).total_seconds(),
                ),
                3,
            )
        except (TypeError, ValueError):
            snapshot["source_age_seconds"] = None
        return snapshot

    def _quote_evidence(
        self, raw: Mapping[str, Any], *, fetched_at: datetime
    ) -> dict[str, Any]:
        depth = raw.get("depth") if isinstance(raw.get("depth"), Mapping) else {}
        buy = list(depth.get("buy") or [])[:5]
        sell = list(depth.get("sell") or [])[:5]
        buy_total = sum(self._number(item.get("quantity")) or 0.0 for item in buy if isinstance(item, Mapping))
        sell_total = sum(self._number(item.get("quantity")) or 0.0 for item in sell if isinstance(item, Mapping))
        return {
            "source": "DHAN_V2_MARKETFEED_QUOTE",
            "source_timestamp": self._trade_time(raw.get("last_trade_time"), fetched_at),
            "fetched_at": fetched_at.isoformat(),
            "average_price": self._number(raw.get("average_price")),
            "previous_volume": None,
            "oi_day_high": self._integer(raw.get("oi_day_high")),
            "oi_day_low": self._integer(raw.get("oi_day_low")),
            "total_buy_quantity": self._integer(raw.get("buy_quantity")),
            "total_sell_quantity": self._integer(raw.get("sell_quantity")),
            "last_trade_quantity": self._integer(raw.get("last_quantity")),
            "last_trade_time": raw.get("last_trade_time"),
            "depth_imbalance_percentage": self._imbalance(buy_total, sell_total),
            "five_level_depth": {"buy": buy, "sell": sell},
        }

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _atomic_write(self, value: Mapping[str, Any]) -> None:
        self._atomic_write_path(self.state_path, value)

    @staticmethod
    def _atomic_write_path(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
            return number if number == number else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _integer(cls, value: Any) -> int | None:
        number = cls._number(value)
        return int(number) if number is not None else None

    @classmethod
    def _difference(cls, current: Any, previous: Any) -> float | None:
        left = cls._number(current)
        right = cls._number(previous)
        return left - right if left is not None and right is not None else None

    @classmethod
    def _imbalance(cls, buy: Any, sell: Any) -> float | None:
        left = cls._number(buy)
        right = cls._number(sell)
        total = (left or 0.0) + (right or 0.0)
        return round(((left or 0.0) - (right or 0.0)) / total * 100.0, 3) if total > 0 else None

    @classmethod
    def _rate(cls, delta: Any, elapsed_seconds: float | None) -> float | None:
        value = cls._number(delta)
        return round(value * 60.0 / elapsed_seconds, 3) if value is not None and elapsed_seconds and elapsed_seconds > 0 else None

    @staticmethod
    def _elapsed_seconds(previous: Any, current: datetime) -> float | None:
        try:
            value = datetime.fromisoformat(str(previous))
            return max(0.0, (current - value).total_seconds())
        except (TypeError, ValueError):
            return None

    def _trade_time(self, value: Any, fallback: datetime) -> str:
        try:
            val_str = str(value)
            if val_str.isdigit() and len(val_str) >= 10:
                epoch_s = float(val_str) / 1000.0 if len(val_str) >= 13 else float(val_str)
                return datetime.fromtimestamp(epoch_s, tz=self.IST).isoformat()
            return datetime.strptime(str(value), "%d/%m/%Y %H:%M:%S").replace(
                tzinfo=self.IST
            ).isoformat()
        except (TypeError, ValueError):
            return fallback.isoformat()
