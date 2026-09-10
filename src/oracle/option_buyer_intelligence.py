"""Isolated, evidence-only preparation for the Oracle option-buyer panel.

This module consumes the already-owned ARGUS/Dhan chain publication.  It never
performs broker I/O and deliberately returns unavailable fields instead of
retaining stale values.  The caller is the existing live-analytics child.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, time, timedelta
from math import erf, exp, log, sqrt
from statistics import median
from time import perf_counter, sleep
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.oracle.resolver_engine import ResolverEngine
from src.oracle.option_intelligence import OptionIntelligenceEngine

IST = ZoneInfo("Asia/Kolkata")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(IST) if parsed.tzinfo else parsed.replace(tzinfo=IST)


def _normal(value: float) -> float:
    return (1.0 + erf(value / sqrt(2.0))) / 2.0


def black76(forward: float, strike: float, time_years: float, volatility: float, rate: float, option_type: str) -> float | None:
    """Black-76 value; exact time repricing uses this, never theta × dt."""
    if min(forward, strike, time_years, volatility) <= 0.0:
        return None
    sigma_root_t = volatility * sqrt(time_years)
    if sigma_root_t <= 0.0:
        return None
    d1 = (log(forward / strike) + 0.5 * volatility * volatility * time_years) / sigma_root_t
    d2 = d1 - sigma_root_t
    discount = exp(-rate * time_years)
    if option_type == "CE":
        return discount * (forward * _normal(d1) - strike * _normal(d2))
    if option_type == "PE":
        return discount * (strike * _normal(-d2) - forward * _normal(-d1))
    return None


def implied_volatility(price: float, forward: float, strike: float, time_years: float, rate: float, option_type: str) -> float | None:
    """Deterministic Black-76 IV inversion for cleaned smile quotes."""
    if min(price, forward, strike, time_years) <= 0.0 or option_type not in {"CE", "PE"}:
        return None
    intrinsic = exp(-rate * time_years) * (max(forward - strike, 0.0) if option_type == "CE" else max(strike - forward, 0.0))
    if price < intrinsic:
        return None
    low, high = 1e-6, 5.0
    high_price = black76(forward, strike, time_years, high, rate, option_type)
    if high_price is None or price > high_price:
        return None
    for _ in range(80):
        mid = (low + high) / 2.0
        value = black76(forward, strike, time_years, mid, rate, option_type)
        if value is None:
            return None
        if value < price:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _expiry_time(expiry: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(expiry)).replace(tzinfo=IST, hour=15, minute=30, second=0, microsecond=0)
    except (TypeError, ValueError):
        return None


def _time_to_expiry(expiry: Any, observed_at: datetime) -> float | None:
    close = _expiry_time(expiry)
    if close is None:
        return None
    seconds = (close - observed_at).total_seconds()
    return seconds / (365.0 * 24.0 * 60.0 * 60.0) if seconds > 0.0 else None


def _mid(leg: Mapping[str, Any]) -> float | None:
    bid, ask = _number(leg.get("top_bid_price")), _number(leg.get("top_ask_price"))
    return (bid + ask) / 2.0 if bid is not None and ask is not None and bid <= ask else None


def _clean_quote(leg: Any) -> tuple[float, float] | None:
    """Return an executable quote interval only when price and liquidity are valid."""
    if not isinstance(leg, Mapping):
        return None
    bid, ask = _number(leg.get("top_bid_price")), _number(leg.get("top_ask_price"))
    bid_qty, ask_qty = _number(leg.get("top_bid_quantity")), _number(leg.get("top_ask_quantity"))
    if bid is None or ask is None or bid <= 0.0 or ask <= 0.0 or bid > ask:
        return None
    # The canonical full-quote path reports quantities. Explicit zero is never
    # accepted; absent quantity remains usable for deterministic legacy tests.
    if (bid_qty is not None and bid_qty <= 0.0) or (ask_qty is not None and ask_qty <= 0.0):
        return None
    return bid, ask


def _leg_expiry(leg: Mapping[str, Any], row: Mapping[str, Any]) -> str | None:
    value = leg.get("expiry") or row.get("expiry")
    return str(value) if value else None


@dataclass
class _OptionBaseline:
    observed_at: datetime
    premium: float
    forward: float
    strike: float
    expiry: str
    fair_iv: float
    option_type: str


@dataclass(frozen=True)
class _SmilePoint:
    strike: float
    iv: float
    call_low: float
    call_high: float
    security_id: str


@dataclass(frozen=True)
class _SmileResult:
    fair_iv: float
    point_count: int
    method: str


@dataclass
class _StraddleState:
    atm: float | None = None
    continuous_value: float | None = None
    opening_value: float | None = None
    last_value: float | None = None
    call_open: float | None = None
    put_open: float | None = None
    previous_continuous: float | None = None
    call_reference: _OptionBaseline | None = None
    put_reference: _OptionBaseline | None = None


class _OiRollingTracker:
    """Discrete closed-window tracker for exact-contract OI and LTP observations.

    Thread-safe within the single OBI worker thread, memory-bounded. Compares
    the exact same security_id OI/LTP between consecutive finalized market
    boundaries (e.g. 5M: 14:50 vs 14:45, 15M: 14:45 vs 14:30).

    Between boundary closes, the displayed metrics remain fixed. Updates occur
    only when a new closed boundary finalizes.
    """

    __slots__ = ('_series',)

    def __init__(self) -> None:
        from collections import deque as _deque  # noqa: F811
        self._series: dict[str, _deque] = {}

    def record(self, security_id: str, oi: float, ltp: float, observed_at: datetime) -> None:
        """Append an observation with timezone-aware datetime. Naturally bounded."""
        if not security_id or oi is None or ltp is None or observed_at is None:
            return
        from collections import deque as _deque  # noqa: F811
        buf = self._series.get(security_id)
        if buf is None:
            buf = _deque(maxlen=25000)
            self._series[security_id] = buf
        epoch = observed_at.timestamp()
        if buf and buf[-1][0] == epoch:
            buf[-1] = (epoch, oi, ltp, observed_at)
            return
        if buf and epoch < buf[-1][0]:
            values = list(buf)
            if any(item[0] == epoch for item in values):
                return
            values.append((epoch, oi, ltp, observed_at))
            values.sort(key=lambda item: item[0])
            buf.clear()
            buf.extend(values[-buf.maxlen:])
            return
        buf.append((epoch, oi, ltp, observed_at))

    def _find_snapshot_at_or_before(
        self, buf: Any, boundary_epoch: float, max_staleness_seconds: float = 20.0
    ) -> tuple[float, float, float, Any] | None:
        """Find latest genuine observation with timestamp <= boundary_epoch.

        Strict AS-OF semantics: never selects an observation timestamped after the boundary.
        Rejects observations older than the canonical option-chain freshness threshold (20.0s,
        defined in OBI prepare at line 319: source_age <= 20.0).
        """
        best = None
        lo, hi = 0, len(buf) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            epoch = buf[mid][0]
            if epoch <= boundary_epoch:  # STRICT AS-OF: strictly at or before boundary
                staleness = boundary_epoch - epoch
                if staleness <= max_staleness_seconds:
                    if best is None or epoch > best[0]:
                        best = buf[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def closed_window_metrics(
        self,
        security_id: str,
        minutes: int,
        observed_at: datetime,
    ) -> dict[str, Any] | None:
        """Compute metrics between the most recent finalized boundary and its predecessor.

        Returns None when the security_id has insufficient boundary history.
        """
        if not security_id or not observed_at:
            return {"status": "NO_SECURITY_ID", "reason": "No security ID provided"}
        buf = self._series.get(security_id)
        if not buf:
            return {"status": "NO_HISTORY", "reason": "Contract ticks warming"}

        # Session starts at 09:15:00 IST of the observed market date
        session_start = observed_at.replace(hour=9, minute=15, second=0, microsecond=0)
        if observed_at < session_start:
            return {"status": "PRE_MARKET", "reason": "Pre-market session"}

        elapsed_minutes = int((observed_at - session_start).total_seconds() // 60)
        k = elapsed_minutes // minutes
        if k < 1:
            # First window of the session has not finalized yet
            next_close = session_start + timedelta(minutes=minutes)
            return {"status": "WAITING_FIRST_CLOSED_BOUNDARY", "reason": f"Waiting close · {next_close.strftime('%H:%M')}"}

        boundary_curr = session_start + timedelta(minutes=k * minutes)
        boundary_prev = session_start + timedelta(minutes=(k - 1) * minutes)

        # Canonical option chain freshness limit (source_age <= 20.0s)
        canonical_freshness = 20.0
        curr_snap = self._find_snapshot_at_or_before(buf, boundary_curr.timestamp(), canonical_freshness)
        prev_snap = self._find_snapshot_at_or_before(buf, boundary_prev.timestamp(), canonical_freshness)

        if curr_snap is None or prev_snap is None:
            return {"status": "WAITING_BOUNDARY_SYNC", "reason": f"Waiting sync · {boundary_curr.strftime('%H:%M')}"}

        curr_epoch, curr_oi, curr_ltp, _ = curr_snap
        prev_epoch, prev_oi, prev_ltp, _ = prev_snap

        if prev_oi <= 0:
            return {"status": "ZERO_BASE_OI", "reason": "Base OI is zero"}

        oi_delta = curr_oi - prev_oi
        oi_pct = round((oi_delta / prev_oi) * 100.0, 2)
        price_delta = round(curr_ltp - prev_ltp, 2)
        oi_delta_rounded = round(oi_delta, 2)

        # 4-quadrant classification based strictly on the closed window
        oi_up = oi_delta > 0
        price_up = price_delta > 0
        if abs(oi_delta) < 1 and abs(price_delta) < 0.01:
            structure = 'FLAT / NEUTRAL'
        elif oi_up and price_up:
            structure = 'LONG BUILDUP'
        elif oi_up and not price_up:
            structure = 'SHORT BUILDUP'
        elif not oi_up and price_up:
            structure = 'SHORT COVERING'
        else:
            structure = 'LONG UNWINDING'

        return {
            'oi_delta': oi_delta_rounded,
            'oi_pct': oi_pct,
            'price_delta': price_delta,
            'structure': structure,
            'window_closed_at': boundary_curr.strftime('%H:%M'),
            'window_prev_at': boundary_prev.strftime('%H:%M'),
            'curr_boundary_age_s': round(boundary_curr.timestamp() - curr_epoch, 2),
            'prev_boundary_age_s': round(boundary_prev.timestamp() - prev_epoch, 2),
        }

    def prior_closed_window_deltas(
        self,
        security_id: str,
        minutes: int,
        observed_at: datetime,
    ) -> list[float]:
        """Extract all valid prior closed-window absolute OI deltas for the session (strictly excluding current window k)."""
        if not security_id or not observed_at:
            return []
        buf = self._series.get(security_id)
        if not buf:
            return []
        session_start = observed_at.replace(hour=9, minute=15, second=0, microsecond=0)
        if observed_at < session_start:
            return []
        elapsed_minutes = int((observed_at - session_start).total_seconds() // 60)
        k = elapsed_minutes // minutes
        if k <= 1:
            return []
        canonical_freshness = 20.0
        prior_deltas: list[float] = []
        for i in range(1, k):
            b_c = session_start + timedelta(minutes=i * minutes)
            b_p = session_start + timedelta(minutes=(i - 1) * minutes)
            snap_c = self._find_snapshot_at_or_before(buf, b_c.timestamp(), canonical_freshness)
            snap_p = self._find_snapshot_at_or_before(buf, b_p.timestamp(), canonical_freshness)
            if snap_c is not None and snap_p is not None and snap_p[1] > 0:
                prior_deltas.append(abs(snap_c[1] - snap_p[1]))
        return prior_deltas

    def closed_window_history(
        self,
        security_id: str,
        minutes: int,
        observed_at: datetime,
        *,
        include_current: bool,
    ) -> list[dict[str, Any]]:
        """Return exact-contract valid session windows without crossing identities."""
        if not security_id or not observed_at:
            return []
        buf = self._series.get(security_id)
        if not buf:
            return []
        session_start = observed_at.replace(hour=9, minute=15, second=0, microsecond=0)
        elapsed_minutes = int((observed_at - session_start).total_seconds() // 60)
        final_index = elapsed_minutes // minutes
        stop = final_index + 1 if include_current else final_index
        history: list[dict[str, Any]] = []
        for i in range(1, max(1, stop)):
            boundary_curr = session_start + timedelta(minutes=i * minutes)
            boundary_prev = session_start + timedelta(minutes=(i - 1) * minutes)
            curr = self._find_snapshot_at_or_before(buf, boundary_curr.timestamp(), 20.0)
            prev = self._find_snapshot_at_or_before(buf, boundary_prev.timestamp(), 20.0)
            if curr is None or prev is None or prev[1] <= 0:
                continue
            oi_delta = curr[1] - prev[1]
            price_delta = curr[2] - prev[2]
            if abs(oi_delta) < 1 and abs(price_delta) < 0.01:
                structure = "FLAT / NEUTRAL"
            elif oi_delta > 0 and price_delta > 0:
                structure = "LONG BUILDUP"
            elif oi_delta > 0:
                structure = "SHORT BUILDUP"
            elif price_delta > 0:
                structure = "SHORT COVERING"
            else:
                structure = "LONG UNWINDING"
            history.append({
                "window_closed_at": boundary_curr.isoformat(),
                "oi_delta": round(oi_delta, 2),
                "price_delta": round(price_delta, 2),
                "structure": structure,
            })
        return history

    def clear_all(self) -> None:
        """Remove all tracked series (e.g. on session reset)."""
        self._series.clear()


@dataclass
class OptionBuyerIntelligenceWorker:
    """Stateful only for continuity/reference observations within this worker."""

    option_baselines: dict[str, _OptionBaseline] = field(default_factory=dict)
    option_previous: dict[str, _OptionBaseline] = field(default_factory=dict)
    straddle: _StraddleState = field(default_factory=_StraddleState)
    oi_tracker: _OiRollingTracker = field(default_factory=_OiRollingTracker)
    resolver_engine: ResolverEngine = field(default_factory=ResolverEngine)
    option_intelligence_engine: OptionIntelligenceEngine = field(default_factory=OptionIntelligenceEngine)
    rate: float = 0.0
    _hydrated: bool = field(default=False, init=False)
    _price_series: Any = field(default_factory=lambda: __import__('collections').deque(maxlen=25000), init=False)
    _straddle_series: Any = field(default_factory=lambda: __import__('collections').deque(maxlen=25000), init=False)
    _sudden_oi_core_key: tuple[Any, ...] | None = field(default=None, init=False)
    _sudden_oi_core: dict[str, Any] | None = field(default=None, init=False)
    dhan_history_client: Any = None
    instrument_master: Any = None
    _session_side_activity: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=lambda: {"CE": {}, "PE": {}}, init=False
    )
    _hydration_diagnostics: dict[str, Any] = field(default_factory=dict, init=False)

    def _hydrate_recent_durable_history(
        self,
        observed_at: datetime | None,
        current_data: Mapping[str, Any] | None = None,
    ) -> None:
        """Hydrate rolling OI, IV, and Resolver memory from recent durable session snapshots on startup."""
        if self._hydrated or observed_at is None:
            return
        self._hydrated = True
        try:
            state_root = os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/logs")
            snap_path = f"{state_root}/argus/session_snapshots/{session_date}.jsonl"
            if not os.path.exists(snap_path):
                return
            local_frames: list[tuple[datetime, float, list[Mapping[str, Any]]]] = []
            with open(snap_path, "rb") as f:
                for l in f:
                    try:
                        s = json.loads(l.decode("utf-8"))
                        t_str = s.get("observation_timestamp") or s.get("calculated_at") or s.get("source_timestamp")
                        if not t_str:
                            continue
                        dt = datetime.fromisoformat(t_str.replace("Z", "+00:00")).astimezone(IST)
                        if dt.date() != observed_at.date():
                            continue
                        spot = _number(s.get("spot"))
                        rows = s.get("option_chain_evidence", [])
                        if spot is not None and spot > 0 and isinstance(rows, list):
                            local_frames.append((dt, spot, [row for row in rows if isinstance(row, Mapping)]))
                        if spot is not None and spot > 0:
                            self._record_timed_value(self._price_series, spot, dt)
                        valid_strike_rows = [row for row in rows if _number(row.get("strike")) is not None]
                        if spot and spot > 0 and valid_strike_rows:
                            atm_row = min(valid_strike_rows, key=lambda r: abs(float(r["strike"]) - spot))
                            c_leg = atm_row.get("CE") if isinstance(atm_row.get("CE"), Mapping) else atm_row.get("ce")
                            p_leg = atm_row.get("PE") if isinstance(atm_row.get("PE"), Mapping) else atm_row.get("pe")
                            c_leg = c_leg if isinstance(c_leg, Mapping) else {}
                            p_leg = p_leg if isinstance(p_leg, Mapping) else {}
                            c_ltp, p_ltp = _number(c_leg.get("ltp")), _number(p_leg.get("ltp"))
                            c_sid = str(c_leg.get("security_id") or "")
                            p_sid = str(p_leg.get("security_id") or "")
                            if c_ltp is not None and p_ltp is not None and c_sid and p_sid:
                                self._record_timed_value(
                                    self._straddle_series,
                                    c_ltp + p_ltp,
                                    dt,
                                    identity=f"{c_sid}:{p_sid}",
                                )
                            c_iv = _number(c_leg.get("iv"))
                            p_iv = _number(p_leg.get("iv"))

                            r_c25 = min(rows, key=lambda r: abs(float((r.get("CE") or r.get("ce") or {}).get("delta") or 0.0) - 0.25)) if rows else None
                            r_p25 = min(rows, key=lambda r: abs(float((r.get("PE") or r.get("pe") or {}).get("delta") or 0.0) - (-0.25))) if rows else None
                            r_c10 = min(rows, key=lambda r: abs(float((r.get("CE") or r.get("ce") or {}).get("delta") or 0.0) - 0.10)) if rows else None
                            r_p10 = min(rows, key=lambda r: abs(float((r.get("PE") or r.get("pe") or {}).get("delta") or 0.0) - (-0.10))) if rows else None

                            c25_iv = _number((r_c25.get("CE") or r_c25.get("ce") or {}).get("iv")) if r_c25 else None
                            p25_iv = _number((r_p25.get("PE") or r_p25.get("pe") or {}).get("iv")) if r_p25 else None
                            c10_iv = _number((r_c10.get("CE") or r_c10.get("ce") or {}).get("iv")) if r_c10 else None
                            p10_iv = _number((r_p10.get("PE") or r_p10.get("pe") or {}).get("iv")) if r_p10 else None

                            skew_25 = round(p25_iv - c25_iv, 2) if (p25_iv is not None and c25_iv is not None) else None
                            skew_10 = round(p10_iv - c10_iv, 2) if (p10_iv is not None and c10_iv is not None) else None
                            atm_val = round((c_iv + p_iv) / 2.0, 2) if (c_iv is not None and p_iv is not None and c_iv > 0 and p_iv > 0) else None

                            if atm_val is not None or skew_25 is not None:
                                self.option_intelligence_engine.record_iv_skew(
                                    atm_val,
                                    skew_25,
                                    dt,
                                    c25_iv=c25_iv,
                                    p25_iv=p25_iv,
                                    c10_iv=c10_iv,
                                    p10_iv=p10_iv,
                                    skew_10d=skew_10,
                                )
                        for item in rows:
                            if not isinstance(item, Mapping):
                                continue
                            for side in ("CE", "PE", "ce", "pe"):
                                leg = item.get(side, {})
                                if isinstance(leg, Mapping):
                                    sid = str(leg.get("security_id") or "")
                                    oi = _number(leg.get("oi"))
                                    ltp = _number(leg.get("ltp"))
                                    if sid and oi is not None and ltp is not None:
                                        self.oi_tracker.record(sid, float(oi), float(ltp), dt)
                    except Exception:
                        continue
            local_frames.sort(key=lambda item: item[0])
            historical_frames: list[tuple[datetime, float, list[Mapping[str, Any]]]] = []
            if local_frames:
                historical_frames = self._backfill_same_day_dhan(
                    observed_at,
                    local_frames[0][0],
                    current_data or {},
                )
            self._rebuild_side_activity_history(historical_frames + local_frames, observed_at)
            self._hydration_diagnostics.update({
                "local_session_observations": len(local_frames),
                "local_earliest_observation": local_frames[0][0].isoformat() if local_frames else None,
                "local_latest_observation": local_frames[-1][0].isoformat() if local_frames else None,
            })
        except Exception:
            pass

    def _backfill_same_day_dhan(
        self,
        observed_at: datetime,
        first_local_at: datetime,
        current_data: Mapping[str, Any],
    ) -> list[tuple[datetime, float, list[Mapping[str, Any]]]]:
        """One bounded startup catch-up using canonical Dhan history and identities."""
        session_start = observed_at.replace(hour=9, minute=15, second=0, microsecond=0)
        cutoff = min(first_local_at.replace(second=0, microsecond=0), observed_at.replace(second=0, microsecond=0))
        if cutoff <= session_start + timedelta(minutes=1):
            return []
        started = perf_counter()
        diagnostics = {
            "backfill_from": session_start.isoformat(),
            "backfill_to": cutoff.isoformat(),
            "source": "DHAN_V2_INTRADAY_OI",
            "option_securities_fetched": 0,
            "historical_observations_recovered": 0,
            "error": None,
        }
        try:
            from src.broker.dhan_client import DhanClient
            from src.paper_trading.contracts import DhanInstrumentMaster

            client = self.dhan_history_client or DhanClient(request_timeout=15)
            master = self.instrument_master or DhanInstrumentMaster()
            underlying = current_data.get("underlying") if isinstance(current_data.get("underlying"), Mapping) else {}
            expiry = str(underlying.get("expiry") or "")
            if not expiry:
                raise ValueError("CURRENT_EXPIRY_UNAVAILABLE")
            date_text = str(observed_at.date())
            spot_response = client.get_intraday_candles(
                "IDX_I", "13", instrument="INDEX", interval="1",
                from_date=date_text, to_date=date_text,
            )
            if not spot_response.get("success"):
                raise ValueError(str(spot_response.get("error") or "DHAN_SPOT_HISTORY_UNAVAILABLE"))
            spot_points: list[tuple[datetime, float]] = []
            for candle in spot_response.get("candles") or []:
                opened_at = datetime.fromtimestamp(float(candle["time"]), tz=IST)
                finalized_at = opened_at + timedelta(minutes=1)
                close = _number(candle.get("close"))
                if close is not None and session_start < finalized_at <= cutoff and finalized_at < first_local_at:
                    spot_points.append((finalized_at, close))
                    self._record_timed_value(self._price_series, close, finalized_at)

            master_rows = [
                row for row in master._rows("NIFTY")
                if str(master._text(row, "SM_EXPIRY_DATE", "SEM_EXPIRY_DATE") or "")[:10] == expiry
                and str(master._text(row, "UNDERLYING_SYMBOL", "SM_SYMBOL_NAME") or "").upper() == "NIFTY"
                and str(master._text(row, "OPTION_TYPE", "SEM_OPTION_TYPE") or "").upper() in {"CE", "PE"}
            ]
            contracts: dict[tuple[float, str], str] = {}
            for row in master_rows:
                strike = _number(master._text(row, "STRIKE_PRICE", "SEM_STRIKE_PRICE"))
                side = str(master._text(row, "OPTION_TYPE", "SEM_OPTION_TYPE") or "").upper()
                sid = str(master._text(row, "SECURITY_ID", "SEM_SMST_SECURITY_ID") or "")
                if strike is not None and sid:
                    contracts[(strike, side)] = sid
            strikes = sorted({strike for strike, side in contracts if (strike, "CE") in contracts and (strike, "PE") in contracts})
            if len(strikes) < 5:
                raise ValueError("DHAN_INSTRUMENT_MASTER_ATM_WINDOW_UNAVAILABLE")

            frames: list[tuple[datetime, float, list[Mapping[str, Any]]]] = []
            union_security_ids: set[str] = set()
            boundary = session_start + timedelta(minutes=5)
            while boundary <= cutoff:
                spot_sample = next(((dt, value) for dt, value in reversed(spot_points) if dt <= boundary and (boundary - dt).total_seconds() <= 70.0), None)
                if spot_sample is not None:
                    spot_value = spot_sample[1]
                    atm_index = min(range(len(strikes)), key=lambda index: (abs(strikes[index] - spot_value), strikes[index]))
                    chosen = strikes[max(0, atm_index - 2):atm_index + 3]
                    if len(chosen) == 5:
                        rows = []
                        for strike in chosen:
                            ce_sid, pe_sid = contracts[(strike, "CE")], contracts[(strike, "PE")]
                            union_security_ids.update((ce_sid, pe_sid))
                            rows.append({"strike": strike, "ce": {"security_id": ce_sid}, "pe": {"security_id": pe_sid}})
                        frames.append((boundary, spot_value, rows))
                boundary += timedelta(minutes=5)

            for index, sid in enumerate(sorted(union_security_ids)):
                if index:
                    sleep(0.15)
                response = client.get_intraday_candles(
                    "NSE_FNO", sid, instrument="OPTIDX", interval="1",
                    from_date=date_text, to_date=date_text, include_oi=True,
                )
                if not response.get("success"):
                    continue
                diagnostics["option_securities_fetched"] += 1
                for candle in response.get("candles") or []:
                    opened_at = datetime.fromtimestamp(float(candle["time"]), tz=IST)
                    finalized_at = opened_at + timedelta(minutes=1)
                    oi = _number(candle.get("open_interest"))
                    close = _number(candle.get("close"))
                    if oi is None or close is None or not (
                        session_start < finalized_at <= cutoff and finalized_at < first_local_at
                    ):
                        continue
                    self.oi_tracker.record(sid, oi, close, finalized_at)
                    diagnostics["historical_observations_recovered"] += 1

            diagnostics["duration_ms"] = round((perf_counter() - started) * 1000.0, 2)
            self._hydration_diagnostics.update(diagnostics)
            return frames
        except Exception as error:
            diagnostics["error"] = str(error)
            diagnostics["duration_ms"] = round((perf_counter() - started) * 1000.0, 2)
            self._hydration_diagnostics.update(diagnostics)
            return []

    def _rebuild_side_activity_history(
        self,
        frames: list[tuple[datetime, float, list[Mapping[str, Any]]]],
        observed_at: datetime,
    ) -> None:
        session_date = observed_at.date()
        eligible_frames = sorted(
            (frame for frame in frames if frame[0].date() == session_date and frame[0] <= observed_at),
            key=lambda item: item[0],
        )
        latest_by_boundary: dict[datetime, tuple[datetime, float, list[Mapping[str, Any]]]] = {}
        boundary = observed_at.replace(hour=9, minute=20, second=0, microsecond=0)
        last_boundary = observed_at.replace(second=0, microsecond=0) - timedelta(minutes=observed_at.minute % 5)
        while boundary <= last_boundary:
            sample = next(
                (frame for frame in reversed(eligible_frames) if frame[0] <= boundary and (boundary - frame[0]).total_seconds() <= 20.0),
                None,
            )
            if sample is not None:
                latest_by_boundary[boundary] = sample
            boundary += timedelta(minutes=5)
        for boundary, (_, spot, rows) in sorted(latest_by_boundary.items()):
            selected = sorted(
                sorted([row for row in rows if _number(row.get("strike")) is not None], key=lambda row: abs(float(row["strike"]) - spot))[:5],
                key=lambda row: float(row["strike"]),
            )
            for side in ("CE", "PE"):
                self._record_side_activity(side, selected, boundary)

    def _record_side_activity(
        self,
        side: str,
        selected_rows: list[Mapping[str, Any]],
        observed_at: datetime,
    ) -> None:
        if len(selected_rows) != 5:
            return
        activities = []
        identities = []
        window_timestamp = None
        for row in selected_rows:
            sid = str(self._leg(row, side).get("security_id") or "")
            metrics = self.oi_tracker.closed_window_metrics(sid, 5, observed_at) if sid else None
            if not isinstance(metrics, Mapping) or metrics.get("oi_delta") is None:
                return
            activities.append(abs(float(metrics["oi_delta"])))
            identities.append(sid)
            window_timestamp = str(metrics.get("window_closed_at") or "")
        if not window_timestamp:
            return
        hour, minute = (int(part) for part in window_timestamp.split(":"))
        window_iso = observed_at.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
        self._session_side_activity[side][window_iso] = {
            "window_timestamp": window_iso,
            "activity": round(sum(activities), 2),
            "security_ids": identities,
        }

    @staticmethod
    def _record_timed_value(
        series: Any,
        value: float,
        observed_at: datetime,
        *,
        identity: str | None = None,
    ) -> None:
        epoch = observed_at.timestamp()
        if series and series[-1][0] == epoch:
            series[-1] = (epoch, float(value), observed_at, identity)
            return
        if series and epoch < series[-1][0]:
            values = list(series)
            if any(item[0] == epoch for item in values):
                return
            values.append((epoch, float(value), observed_at, identity))
            values.sort(key=lambda item: item[0])
            series.clear()
            series.extend(values[-series.maxlen:])
            return
        series.append((epoch, float(value), observed_at, identity))

    @staticmethod
    def _percentile(current: float | None, prior: list[float]) -> float | None:
        if current is None or not prior:
            return None
        return round(100.0 * sum(1 for value in prior if value <= current) / len(prior), 1)

    @staticmethod
    def _leg(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
        leg = row.get(side.lower())
        if not isinstance(leg, Mapping):
            leg = row.get(side.upper())
        return leg if isinstance(leg, Mapping) else {}

    def _timed_change_context(
        self,
        series: Any,
        minutes: int,
        observed_at: datetime | None,
        *,
        require_same_identity: bool = False,
    ) -> dict[str, Any]:
        if observed_at is None or not series:
            return {"change": None, "percentile": None, "source_timestamp": None, "prior_sample_count": 0}
        session_start = observed_at.replace(hour=9, minute=15, second=0, microsecond=0)
        elapsed = int((observed_at - session_start).total_seconds() // 60)
        k = elapsed // minutes
        changes: list[tuple[datetime, float]] = []
        for i in range(1, k + 1):
            current_boundary = session_start + timedelta(minutes=i * minutes)
            previous_boundary = current_boundary - timedelta(minutes=minutes)
            current = self._timed_value_at_or_before(series, current_boundary.timestamp())
            previous = self._timed_value_at_or_before(series, previous_boundary.timestamp())
            if current is None or previous is None:
                continue
            if require_same_identity:
                current_identity = current[3] if len(current) > 3 else None
                previous_identity = previous[3] if len(previous) > 3 else None
                if not current_identity or current_identity != previous_identity:
                    continue
            changes.append((current_boundary, current[1] - previous[1]))
        if not changes:
            return {"change": None, "percentile": None, "source_timestamp": None, "prior_sample_count": 0}
        boundary, change = changes[-1]
        prior = [abs(value) for _, value in changes[:-1]]
        return {
            "change": round(change, 2),
            "percentile": self._percentile(abs(change), prior),
            "source_timestamp": boundary.isoformat(),
            "prior_sample_count": len(prior),
        }

    @staticmethod
    def _timed_value_at_or_before(series: Any, boundary_epoch: float) -> tuple[Any, ...] | None:
        best = None
        for sample in reversed(series):
            if sample[0] <= boundary_epoch:
                best = sample
                break
        return best if best is not None and boundary_epoch - best[0] <= 20.0 else None

    def _side_sudden_oi(
        self,
        side: str,
        selected_rows: list[Mapping[str, Any]],
        observed_at: datetime,
        session_date: str,
    ) -> dict[str, Any]:
        current_strikes: list[dict[str, Any]] = []
        prior_by_security: dict[str, dict[str, dict[str, Any]]] = {}
        for row in selected_rows:
            leg = self._leg(row, side)
            sid = str(leg.get("security_id") or "")
            strike = _number(row.get("strike"))
            if not sid or strike is None:
                continue
            current = self.oi_tracker.closed_window_metrics(sid, 5, observed_at)
            history = self.oi_tracker.closed_window_history(sid, 5, observed_at, include_current=False)
            prior_by_security[sid] = {str(item["window_closed_at"]): item for item in history}
            if not isinstance(current, Mapping) or current.get("oi_delta") is None:
                continue
            prior_abs = [abs(float(item["oi_delta"])) for item in history]
            activity = abs(float(current["oi_delta"]))
            previous_high = max(prior_abs) if prior_abs else None
            new_high = previous_high is not None and activity > previous_high
            structure = str(current.get("structure") or "")
            price_delta = _number(current.get("price_delta"))
            current_strikes.append({
                "security_id": sid,
                "strike": strike,
                "option_type": side,
                "ltp": _number(leg.get("ltp")),
                "oi": _number(leg.get("oi")),
                "oi_delta_5m": float(current["oi_delta"]),
                "price_delta_5m": price_delta,
                "activity_5m": round(activity, 2),
                "percentile": self._percentile(activity, prior_abs),
                "prior_sample_count": len(prior_abs),
                "previous_session_high": round(previous_high, 2) if previous_high is not None else None,
                "new_5m_high": new_high,
                "state": structure,
                "window_closed_at": current.get("window_closed_at"),
                "squeeze": bool(
                    structure == "SHORT COVERING"
                    and price_delta is not None
                    and price_delta > 0.0
                    and float(current["oi_delta"]) < 0.0
                    and new_high
                ),
            })

        current_complete = len(current_strikes) == len(selected_rows) == 5
        current_activity = round(sum(item["activity_5m"] for item in current_strikes), 2) if current_complete else None
        top = max(current_strikes, key=lambda item: item["activity_5m"], default=None)
        window = top.get("window_closed_at") if top else None
        window_iso = None
        if window:
            hour, minute = (int(part) for part in str(window).split(":"))
            window_iso = observed_at.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
        common_windows: set[str] | None = None
        for item in current_strikes:
            windows = set(prior_by_security.get(item["security_id"], {}))
            common_windows = windows if common_windows is None else common_windows & windows
        side_history: list[dict[str, Any]] = []
        for window in sorted(common_windows or set()):
            components = [prior_by_security[item["security_id"]][window] for item in current_strikes]
            if len(components) == 5:
                window_timestamp = (
                    window
                    if "T" in window
                    else observed_at.replace(
                        hour=int(window.split(":")[0]), minute=int(window.split(":")[1]), second=0, microsecond=0
                    ).isoformat()
                )
                side_history.append({
                    "window_timestamp": window_timestamp,
                    "activity": sum(abs(float(component["oi_delta"])) for component in components),
                })
        prior_activity = [float(item["activity"]) for item in side_history]
        if current_complete and window_iso:
            self._record_side_activity(side, selected_rows, observed_at)
            canonical_history = [
                item for key, item in sorted(self._session_side_activity[side].items())
                if key < window_iso
            ]
            if canonical_history:
                side_history = canonical_history
                prior_activity = [float(item["activity"]) for item in side_history]
        normal = float(median(prior_activity)) if prior_activity else None
        previous_high = max(prior_activity) if prior_activity else None
        new_extreme = current_activity is not None and previous_high is not None and current_activity > previous_high

        canonical_states = {"LONG BUILDUP", "SHORT BUILDUP", "SHORT COVERING", "LONG UNWINDING"}
        counts = {state: sum(1 for item in current_strikes if item["state"] == state) for state in canonical_states}
        peak = max(counts.values(), default=0)
        leaders = sorted(state for state, count in counts.items() if count == peak and count > 0)
        dominant = leaders[0] if len(leaders) == 1 else None
        state_label = self._side_state_label(side, dominant)
        event_base = f"{session_date}:{side}:{window_iso or 'UNAVAILABLE'}"
        alerts: list[dict[str, Any]] = []
        if new_extreme:
            assert current_activity is not None and normal is not None
            side_percentile = self._percentile(current_activity, prior_activity)
            assert side_percentile is not None
            alerts.append({
                "event_id": f"{event_base}:SIDE_SESSION_EXTREME",
                "event_type": "SIDE_SESSION_EXTREME",
                "side": side,
                "title": f"🔥 {'CALL' if side == 'CE' else 'PUT'} OI SESSION EXTREME",
                "detail": f"Current {round(current_activity)} vs Normal {round(normal)} · {side_percentile:g}th percentile · {state_label} · {peak}/5",
            })
        if top and top["new_5m_high"]:
            alerts.append({
                "event_id": f"{session_date}:{top['security_id']}:{window_iso}:STRIKE_SESSION_EXTREME",
                "event_type": "STRIKE_SESSION_EXTREME",
                "side": side,
                "title": f"🔥 {top['strike']:,.0f} {side} NEW 5M OI HIGH",
                "detail": f"{top['activity_5m']:,.0f} · {top['state']} · {top['percentile'] if top['percentile'] is not None else '—'}th percentile",
            })
        if top and top["squeeze"]:
            alerts.append({
                "event_id": f"{session_date}:{top['security_id']}:{window_iso}:WRITER_SQUEEZE",
                "event_type": "WRITER_SQUEEZE",
                "side": side,
                "title": f"⚡ {top['strike']:,.0f} {side} {'CALL' if side == 'CE' else 'PUT'} SHORT-COVERING SURGE",
                "detail": "SHORT COVERING · NEW 5M HIGH",
            })
        status = "LIVE" if current_complete and prior_activity else "PARTIAL_SESSION" if current_strikes else "WARMING"
        current_to_normal = (
            round(current_activity / normal, 4)
            if current_activity is not None and normal is not None and normal > 0.0
            else None
        )
        recent_history = list(side_history)
        if current_complete and window_iso:
            current_entry = self._session_side_activity[side].get(window_iso)
            if current_entry is not None:
                recent_history.append(current_entry)
        return {
            "status": status,
            "side": side,
            "strike_scope": "ATM ±2",
            "normal_5m_activity": round(normal, 2) if normal is not None else None,
            "previous_5m_activity": round(prior_activity[-1], 2) if prior_activity else None,
            "current_5m_activity": current_activity,
            "current_to_normal_x": current_to_normal,
            "recent_5m_activity": [
                {"window_timestamp": item["window_timestamp"], "activity": round(float(item["activity"]), 2)}
                for item in recent_history[-5:]
            ],
            "percentile": self._percentile(current_activity, prior_activity),
            "previous_session_high": round(previous_high, 2) if previous_high is not None else None,
            "new_session_extreme": new_extreme,
            "dominant_state": dominant or "MIXED / NO CLEAN DOMINANT STATE",
            "state_label": state_label,
            "breadth": {"count": peak, "total": 5, "valid": len(current_strikes)},
            "read": "NEW SESSION EXTREME" if new_extreme else "NORMAL" if status == "LIVE" else status,
            "window_closed_at": window_iso,
            "prior_sample_count": len(prior_activity),
            "top_strike": top,
            "strikes": current_strikes,
            "alerts": alerts,
        }

    @staticmethod
    def _side_state_label(side: str, state: str | None) -> str:
        if state is None:
            return "MIXED / NO CLEAN DOMINANT STATE"
        owner = "CALL" if side == "CE" else "PUT"
        action = {
            "LONG BUILDUP": "BUYING / LONG BUILDUP",
            "SHORT BUILDUP": "WRITING / SHORT BUILDUP",
            "SHORT COVERING": "SHORT COVERING",
            "LONG UNWINDING": "LONG UNWINDING",
        }[state]
        return f"{owner} {action}"

    def _build_sudden_oi(
        self,
        rows: list[Mapping[str, Any]],
        underlying: Mapping[str, Any],
        forward: float | None,
        observed_at: datetime | None,
        straddle: Mapping[str, Any],
    ) -> dict[str, Any]:
        started = perf_counter()
        if observed_at is None or not rows:
            return {"schema_version": 1, "status": "UNAVAILABLE", "source_timestamp": None, "CALL": None, "PUT": None, "alerts": []}
        atm = _number(underlying.get("atm_strike")) or _number(underlying.get("spot")) or forward
        if atm is None:
            return {"schema_version": 1, "status": "UNAVAILABLE", "source_timestamp": observed_at.isoformat(), "CALL": None, "PUT": None, "alerts": []}
        valid_strike_rows = [row for row in rows if _number(row.get("strike")) is not None]
        selected = sorted(
            sorted(valid_strike_rows, key=lambda row: abs(float(row["strike"]) - atm))[:5],
            key=lambda row: float(row["strike"]),
        )
        session_date = str(observed_at.date())
        current_window = observed_at.replace(second=0, microsecond=0) - timedelta(minutes=observed_at.minute % 5)
        identity = tuple((str(self._leg(row, "CE").get("security_id") or ""), str(self._leg(row, "PE").get("security_id") or "")) for row in selected)
        core_key = (session_date, current_window.isoformat(), identity)
        if self._sudden_oi_core_key != core_key or self._sudden_oi_core is None:
            self._sudden_oi_core = {
                "CALL": self._side_sudden_oi("CE", selected, observed_at, session_date),
                "PUT": self._side_sudden_oi("PE", selected, observed_at, session_date),
            }
            self._sudden_oi_core_key = core_key
        call = deepcopy(self._sudden_oi_core["CALL"])
        put = deepcopy(self._sudden_oi_core["PUT"])
        price = self._timed_change_context(self._price_series, 2, observed_at)
        straddle_context = self._timed_change_context(
            self._straddle_series,
            5,
            observed_at,
            require_same_identity=True,
        )
        flow_diag = self.resolver_engine.compute_flow_diagnostics(None, observed_at)
        mlofi = _number(flow_diag.get("current_mlofi"))
        flow_x = _number(flow_diag.get("current_flow_x"))
        direction = "BUY" if mlofi is not None and mlofi > 0 else "SELL" if mlofi is not None and mlofi < 0 else "NEUTRAL" if mlofi == 0 else "UNAVAILABLE"
        alerts = list(call.get("alerts") or []) + list(put.get("alerts") or [])
        oi_percentiles = [value for value in (call.get("percentile"), put.get("percentile")) if isinstance(value, (int, float))]
        computed_at = datetime.now(tz=IST)
        return {
            "schema_version": 1,
            "status": "LIVE" if call["status"] == put["status"] == "LIVE" else "PARTIAL_SESSION",
            "session_date": session_date,
            "source_timestamp": observed_at.isoformat(),
            "computed_at": computed_at.isoformat(),
            "compute_duration_ms": round((perf_counter() - started) * 1000.0, 3),
            "atm_strike": atm,
            "strike_scope": "ATM ±2",
            "history_source": (
                "DHAN_V2_INTRADAY_OI + SAME_DAY_ARGUS_SESSION_SNAPSHOTS + LIVE_EXACT_SECURITY_ID_TRACKER"
                if self._hydration_diagnostics.get("option_securities_fetched")
                else "SAME_DAY_ARGUS_SESSION_SNAPSHOTS + LIVE_EXACT_SECURITY_ID_TRACKER"
            ),
            "hydration": deepcopy(self._hydration_diagnostics),
            "CALL": call,
            "PUT": put,
            "price_oi_response": {
                "nifty_price_change_2m": price["change"],
                "price_speed_percentile": price["percentile"],
                "source_timestamp": price["source_timestamp"],
                "call_oi_percentile": call.get("percentile"),
                "put_oi_percentile": put.get("percentile"),
                # No canonical price-impulse event exists.  Keep timing
                # explicitly unavailable rather than deriving lead/lag from
                # the largest recent tick plus an arbitrary coincidence band.
                "call_timing": "NO CLEAR FOLLOW",
                "put_timing": "NO CLEAR FOLLOW",
                "read": "OI ACTIVITY AT SESSION HIGH" if call.get("new_session_extreme") or put.get("new_session_extreme") else "DESCRIPTIVE PRICE ↔ OI CONTEXT",
            },
            "nifty_book": {
                "scope": "GLOBAL NIFTY FUTURES BOOK PRESSURE",
                "direction": direction,
                "mlofi": mlofi,
                "pressure_x": flow_x,
                "source_timestamp": flow_diag.get("current_flow_timestamp"),
            },
            "activity_release": {
                "price_speed_percentile": price["percentile"],
                "oi_activity_percentile": max(oi_percentiles) if oi_percentiles else None,
                "straddle_activity_percentile": straddle_context["percentile"],
                "straddle_change_5m": straddle_context["change"],
                "book_pressure_direction": direction,
                "book_pressure_x": flow_x,
                "read": "OI ACTIVITY AT SESSION HIGH" if call.get("new_session_extreme") or put.get("new_session_extreme") else "ACTIVITY CONTEXT",
            },
            "alerts": alerts,
        }

    def prepare(self, argus: Mapping[str, Any], vob: Mapping[str, Any], flow: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = argus.get("data") if isinstance(argus.get("data"), Mapping) else argus
        market = data.get("argus_market_snapshot") if isinstance(data.get("argus_market_snapshot"), Mapping) else {}
        underlying = data.get("underlying") if isinstance(data.get("underlying"), Mapping) else {}
        observed_at = _timestamp(market.get("fetched_at")) or _timestamp(underlying.get("fetched_at"))
        
        # ── Hydrate durable session history on startup ──
        if observed_at is not None and not self._hydrated:
            self._hydrate_recent_durable_history(observed_at, data)
        market_futures = market.get("futures") if isinstance(market.get("futures"), Mapping) else {}
        legacy_futures = data.get("futures") if isinstance(data.get("futures"), Mapping) else {}
        futures = market_futures or legacy_futures
        fut_bid = _number(futures.get("best_bid_price"))
        fut_ask = _number(futures.get("best_ask_price"))
        forward = (fut_bid + fut_ask) / 2.0 if fut_bid is not None and fut_ask is not None and 0.0 < fut_bid <= fut_ask else _number(futures.get("ltp"))
        chain_expiry = str(underlying.get("expiry") or "")
        raw_rows = [row for row in data.get("atm_window") or [] if isinstance(row, Mapping)]
        rows, surface_age = self._coherent_rows(raw_rows, market, observed_at)
        contracts = vob.get("current_itm1_contracts") if isinstance(vob.get("current_itm1_contracts"), Mapping) else {}
        source_age = self._quote_age(futures, observed_at)
        ce_contract = contracts.get("CE", {}).get("contract", {}) if isinstance(contracts.get("CE"), Mapping) else {}
        pe_contract = contracts.get("PE", {}).get("contract", {}) if isinstance(contracts.get("PE"), Mapping) else {}
        ce_c_expiry = str(ce_contract.get("expiry") or "")
        pe_c_expiry = str(pe_contract.get("expiry") or "")
        
        contracts_expiry_valid = (
            (not ce_c_expiry or ce_c_expiry == chain_expiry)
            and (not pe_c_expiry or pe_c_expiry == chain_expiry)
            and (not ce_c_expiry or not pe_c_expiry or ce_c_expiry == pe_c_expiry)
        )
        futures_expiry = str(futures.get("expiry") or "")
        futures_valid = bool(futures_expiry) and (futures.get("security_id") is not None or futures.get("ltp") is not None)
        expiry_valid = bool(chain_expiry) and futures_valid and contracts_expiry_valid
        valid = observed_at is not None and forward is not None and forward > 0 and bool(rows) and source_age is not None and source_age <= 20.0 and expiry_valid
        base = self._unavailable(observed_at, source_age, "MODEL_INPUT_UNAVAILABLE" if not valid else None)
        forward_quality = self._forward_quality(rows, forward, futures, chain_expiry)
        ce = self._option("CE", contracts.get("CE"), rows, forward, observed_at, chain_expiry, valid, forward_quality, base, surface_age)
        pe = self._option("PE", contracts.get("PE"), rows, forward, observed_at, chain_expiry, valid, forward_quality, base, surface_age)
        ce.update(self._direct_market_truth(contracts.get("CE"), market))
        pe.update(self._direct_market_truth(contracts.get("PE"), market))
        straddle = self._straddle(rows, forward, observed_at, valid, ce, pe)
        option_intel = self.option_intelligence_engine.evaluate(rows, forward, observed_at, chain_expiry)
        if observed_at is not None:
            spot_value = _number(underlying.get("ltp")) or _number(underlying.get("spot")) or forward
            straddle_value = _number(straddle.get("now"))
            if spot_value is not None:
                self._record_timed_value(self._price_series, spot_value, observed_at)
            if straddle_value is not None:
                atm_strike = _number(straddle.get("atm_strike"))
                atm_row = next(
                    (row for row in rows if _number(row.get("strike")) == atm_strike),
                    None,
                )
                call_leg = self._leg(atm_row, "CE") if isinstance(atm_row, Mapping) else {}
                put_leg = self._leg(atm_row, "PE") if isinstance(atm_row, Mapping) else {}
                call_sid = str(call_leg.get("security_id") or "")
                put_sid = str(put_leg.get("security_id") or "")
                if call_sid and put_sid:
                    self._record_timed_value(
                        self._straddle_series,
                        straddle_value,
                        observed_at,
                        identity=f"{call_sid}:{put_sid}",
                    )

        # ── Session Reset Order: check session before ingesting new session flow ──
        session_date = str(observed_at.date()) if observed_at else None
        if session_date and self.resolver_engine._session_id != session_date:
            self.resolver_engine.reset_session(session_date)

        # ── Ingest unique flow snapshot into Resolver ───────────────────
        flow_data = flow if isinstance(flow, Mapping) else (vob.get("flow") if isinstance(vob.get("flow"), Mapping) else (data.get("flow") if isinstance(data.get("flow"), Mapping) else (market.get("flow") if isinstance(market.get("flow"), Mapping) else None)))
        self.resolver_engine.ingest_flow_snapshot(flow_data, observed_at)

        # ── Ingest all subscribed option chain contracts into per-security OI rolling tracker ──
        if rows and observed_at is not None:
            for r in rows:
                if not isinstance(r, Mapping):
                    continue
                for l_key in ("ce", "pe", "CE", "PE"):
                    l_leg = r.get(l_key)
                    if isinstance(l_leg, Mapping):
                        l_sid = str(l_leg.get("security_id") or "")
                        l_oi = _number(l_leg.get("oi"))
                        l_ltp = _number(l_leg.get("ltp"))
                        if l_sid and l_oi is not None and l_ltp is not None:
                            self.oi_tracker.record(l_sid, l_oi, l_ltp, observed_at)

        # ── 5M / 15M closed window tracking & Resolver synthesis ─────────
        for side_key, side_result in (("CE", ce), ("PE", pe)):
            cpayload = contracts.get(side_key) if isinstance(contracts.get(side_key), Mapping) else {}
            ccontract = cpayload.get("contract") if isinstance(cpayload.get("contract"), Mapping) else {}
            cquote = cpayload.get("quote") if isinstance(cpayload.get("quote"), Mapping) else {}
            sid = str(ccontract.get("security_id") or cquote.get("security_id") or "")
            c_oi = _number(cquote.get("oi"))
            c_ltp = _number(cquote.get("ltp"))
            if sid and c_oi is not None and c_ltp is not None and observed_at is not None:
                self.oi_tracker.record(sid, c_oi, c_ltp, observed_at)
                side_result["oi_5m_change"] = self.oi_tracker.closed_window_metrics(sid, 5, observed_at)
                side_result["oi_15m_change"] = self.oi_tracker.closed_window_metrics(sid, 15, observed_at)
            else:
                side_result["oi_5m_change"] = None
                side_result["oi_15m_change"] = None

            # Compute Resolver R1 state & diagnostics using canonical prior deltas
            prior_deltas = self.oi_tracker.prior_closed_window_deltas(sid, 5, observed_at) if sid and observed_at else []
            oi_diag = self.resolver_engine.compute_oi_diagnostics(
                prior_deltas,
                side_result.get("oi_5m_change"),
                observed_at,
            )
            cvob = cpayload.get("vob") if isinstance(cpayload.get("vob"), Mapping) else {}
            chp = cvob.get("horsepower") if isinstance(cvob.get("horsepower"), Mapping) else {}
            chp_lanes = self.resolver_engine.extract_vob_timeframes(chp)
            chp_3m = chp_lanes["3m"]
            chp_5m = chp_lanes["5m"]
            vob_event_time = _timestamp(chp_5m.get("confirmed_candle") or chp_3m.get("confirmed_candle"))

            flow_diag = self.resolver_engine.compute_flow_diagnostics(vob_event_time, observed_at)
            resolver_ev, resolver_diag = self.resolver_engine.synthesize_resolver_state(
                side=side_key,
                contract_payload=cpayload,
                oi_diag=oi_diag,
                flow_diag=flow_diag,
                flow_payload=flow_data,
                observed_at=observed_at,
            )
            side_result["resolver_event"] = resolver_ev
            side_result["resolver_diagnostics"] = resolver_diag
        sudden_oi = self._build_sudden_oi(rows, underlying, forward, observed_at, straddle)
        return {
            "schema_version": 1,
            # Availability is owned by the complete Option Buyer projection,
            # not only by the optional Black-76 fair-price branch.  The
            # current option-chain IV/skew/GEX engine can be fully live while
            # fair pricing correctly fails closed (for example when the
            # futures and weekly-option expiries differ).
            "status": (
                "LIVE"
                if option_intel.get("status") == "LIVE"
                else "MODEL_DERIVED_RESEARCH" if valid else "UNAVAILABLE"
            ),
            "source_timestamp": observed_at.isoformat() if observed_at else None,
            "feed_age_seconds": source_age,
            "provenance": "CANONICAL_ARGUS_DHAN_OPTION_CHAIN + DHAN_FULL_QUOTE + EXISTING_FUTURES",
            "CE": ce,
            "PE": pe,
            "straddle": straddle,
            "sudden_oi": sudden_oi,
            "option_intelligence": option_intel,
            "fit": {"call_evidence": None, "put_evidence": None, "state": "NO_CLEAN_FIT", "provenance": "NO_INVENTED_FIT_FORMULA"},
            "capture": {"state": "STAGED_INACTIVE", "reason": "CURRENT_CANONICAL_QUOTE_HAS_5_LEVEL_DEPTH_NOT_OPTION_TRADE_TAPE_OR_20_LEVEL_BOOK"},
        }

    @staticmethod
    def _direct_market_truth(contract_payload: Any, market: Mapping[str, Any]) -> dict[str, Any]:
        """Project factual Dhan full-quote fields without inferring trade side."""
        payload = contract_payload if isinstance(contract_payload, Mapping) else {}
        contract = payload.get("contract") if isinstance(payload.get("contract"), Mapping) else {}
        quote = payload.get("quote") if isinstance(payload.get("quote"), Mapping) else {}
        security_id = str(contract.get("security_id") or quote.get("security_id") or "")
        depth_by_security = market.get("option_market_depth") if isinstance(market.get("option_market_depth"), Mapping) else {}
        evidence = depth_by_security.get(security_id) if security_id else None
        evidence = evidence if isinstance(evidence, Mapping) else {}
        five = evidence.get("five_level_depth") if isinstance(evidence.get("five_level_depth"), Mapping) else {}

        def levels(name: str) -> list[dict[str, Any]]:
            projected: list[dict[str, Any]] = []
            for raw in list(five.get(name) or [])[:5]:
                if not isinstance(raw, Mapping):
                    continue
                price, quantity, orders = _number(raw.get("price")), _number(raw.get("quantity")), _number(raw.get("orders"))
                if price is None or quantity is None or price <= 0.0 or quantity < 0.0:
                    continue
                projected.append({"price": price, "quantity": int(quantity), "orders": int(orders) if orders is not None and orders >= 0.0 else None})
            return projected

        bids, asks = levels("buy"), levels("sell")
        bid_total = sum(level["quantity"] for level in bids)
        ask_total = sum(level["quantity"] for level in asks)
        visible_total = bid_total + ask_total
        buy_share = (bid_total / visible_total) * 100.0 if visible_total > 0 else None
        biggest_bid = max(bids, key=lambda level: level["quantity"], default=None)
        biggest_ask = max(asks, key=lambda level: level["quantity"], default=None)
        return {
            "market_pressure": {
                "total_buy_quantity": int(value) if (value := _number(evidence.get("total_buy_quantity"))) is not None else None,
                "total_sell_quantity": int(value) if (value := _number(evidence.get("total_sell_quantity"))) is not None else None,
                "book_buy_share_pct": round(buy_share, 2) if buy_share is not None else None,
                "book_sell_share_pct": round(100.0 - buy_share, 2) if buy_share is not None else None,
                "last_trade_quantity": int(value) if (value := _number(evidence.get("last_trade_quantity"))) is not None else None,
                "last_trade_time": evidence.get("last_trade_time"),
                "average_trade_price": _number(evidence.get("average_price")),
                "source_timestamp": evidence.get("source_timestamp"),
                "provenance": "DHAN_V2_MARKETFEED_QUOTE",
            },
            "book": {
                "best_bid": dict(bids[0]) if bids else None,
                "best_ask": dict(asks[0]) if asks else None,
                "biggest_buy_level": dict(biggest_bid) if biggest_bid else None,
                "biggest_sell_level": dict(biggest_ask) if biggest_ask else None,
                "five_level_buy_quantity": bid_total if bids else None,
                "five_level_sell_quantity": ask_total if asks else None,
                "depth_levels": 5 if bids or asks else None,
                "provenance": "DHAN_VISIBLE_5_LEVEL_BOOK",
            },
        }

    @staticmethod
    def _quote_age(quote: Mapping[str, Any], observed_at: datetime | None) -> float | None:
        if observed_at is None:
            return None
        timestamp = _timestamp(quote.get("fetched_at") or quote.get("source_timestamp"))
        return max(0.0, (observed_at - timestamp).total_seconds()) if timestamp else _number(quote.get("source_age_seconds"))

    def _coherent_rows(self, rows: list[Mapping[str, Any]], market: Mapping[str, Any], observed_at: datetime | None) -> tuple[list[Mapping[str, Any]], float | None]:
        depth = market.get("option_market_depth") if isinstance(market.get("option_market_depth"), Mapping) else {}
        if not depth:
            return rows, None
        result: list[Mapping[str, Any]] = []
        ages: list[float] = []
        for original in rows:
            row = deepcopy(dict(original))
            for side in ("ce", "pe"):
                leg = row.get(side)
                if not isinstance(leg, Mapping):
                    continue
                evidence = depth.get(str(leg.get("security_id")))
                if not isinstance(evidence, Mapping):
                    # A partial batch is not silently mixed with the older
                    # chain quote. Quote cleaning will reject this leg.
                    row[side] = {**dict(leg), "top_bid_price": None, "top_ask_price": None}
                    continue
                five = evidence.get("five_level_depth") if isinstance(evidence.get("five_level_depth"), Mapping) else {}
                buys, sells = list(five.get("buy") or []), list(five.get("sell") or [])
                bid = buys[0] if buys and isinstance(buys[0], Mapping) else {}
                ask = sells[0] if sells and isinstance(sells[0], Mapping) else {}
                row[side] = {
                    **dict(leg),
                    "top_bid_price": bid.get("price"), "top_bid_quantity": bid.get("quantity"),
                    "top_ask_price": ask.get("price"), "top_ask_quantity": ask.get("quantity"),
                    "quote_fetched_at": evidence.get("fetched_at"),
                    "quote_source_timestamp": evidence.get("source_timestamp"),
                }
                age = self._quote_age(evidence, observed_at)
                if age is not None:
                    ages.append(age)
            result.append(row)
        return result, max(ages) if ages else None

    def _unavailable(self, observed_at: datetime | None, age: float | None, reason: str | None) -> dict[str, Any]:
        return {
            "fair_price": None, "fair_iv": None, "ask": None, "bid": None, "spread": None, "fair_advantage": None, "comparison": None,
            "time_value_left": None, "time_lost_today": None,
            "time_loss_expected": None, "actual_change": None, "premium_holding": None,
            "flow": {"buying_volume": None, "selling_volume": None, "net_flow": None, "imbalance": None, "activity_normal": None},
            "book": {"biggest_buy_orders": None, "biggest_sell_orders": None, "most_traded_price": None, "current_vs_most_traded": None, "my_buy_price": None},
            "quality": {"valid": False, "reason": reason, "source_timestamp": observed_at.isoformat() if observed_at else None, "quote_age_seconds": age, "surface_age_seconds": age, "continuity_state": "UNAVAILABLE"},
        }

    def _option(self, side: str, contract_payload: Any, rows: list[Mapping[str, Any]], forward: float | None, observed_at: datetime | None, chain_expiry: str, valid: bool, forward_quality: Mapping[str, Any], base: dict[str, Any], surface_age: float | None = None) -> dict[str, Any]:
        contract_payload = contract_payload if isinstance(contract_payload, Mapping) else {}
        contract = contract_payload.get("contract") if isinstance(contract_payload.get("contract"), Mapping) else {}
        quote = contract_payload.get("quote") if isinstance(contract_payload.get("quote"), Mapping) else {}
        strike, expiry, security_id = _number(contract.get("strike")), contract.get("expiry"), str(contract.get("security_id") or quote.get("security_id") or "")
        if strike is None or not expiry or str(expiry) != chain_expiry or not security_id:
            return dict(base)
        target = self._find_leg(rows, security_id, side)
        coherent_target = bool(target and target.get("quote_fetched_at"))
        ask = (_number(target.get("top_ask_price")) if coherent_target else None) or _number(quote.get("ask")) or (_number(target.get("top_ask_price")) if target else None)
        bid = (_number(target.get("top_bid_price")) if coherent_target else None) or _number(quote.get("bid")) or (_number(target.get("top_bid_price")) if target else None)
        premium = _number(quote.get("ltp")) or (_number(target.get("ltp")) if target else None)
        if not valid or forward is None or observed_at is None:
            result = dict(base)
            result["ask"], result["bid"] = ask, bid
            result["spread"] = round(ask - bid, 2) if ask is not None and bid is not None and bid <= ask else None
            return result
        time_years = _time_to_expiry(expiry, observed_at)
        smile = self._fair_iv(rows, strike, security_id, forward, time_years, chain_expiry)
        fair_iv = smile.fair_iv if smile else None
        sane = ask is not None and ask > 0.0 and bid is not None and bid > 0.0 and bid <= ask and premium is not None and premium > 0.0 and time_years is not None and fair_iv is not None and bool(forward_quality.get("forward_gate_valid"))
        if not sane:
            result = dict(base)
            result["ask"], result["bid"] = ask, bid
            result["spread"] = round(ask - bid, 2) if ask is not None and bid is not None and bid <= ask else None
            reason = (
                "FORWARD_PARITY_GATE_FAILED" if not bool(forward_quality.get("forward_gate_valid"))
                else "FAIR_IV_SURFACE_INVALID" if fair_iv is None
                else "TARGET_QUOTE_INVALID" if ask is None or bid is None or bid <= 0.0 or ask <= 0.0 or bid > ask
                else "MODEL_INPUT_UNAVAILABLE"
            )
            result["quality"] = {**base["quality"], **forward_quality, "surface_age_seconds": surface_age, "valid": False, "reason": reason}
            return result
        fair = black76(forward, strike, time_years, fair_iv, self.rate, side)
        if fair is None:
            return dict(base)
        current = _OptionBaseline(observed_at, premium, forward, strike, str(expiry), fair_iv, side)
        baseline = self.option_baselines.get(security_id)
        previous = self.option_previous.get(security_id)
        if baseline is None or baseline.observed_at.date() != observed_at.date():
            self.option_baselines[security_id] = current
            self.option_previous[security_id] = current
            actual_change = time_loss = time_lost_today = holding = None
        else:
            previous = previous or baseline
            time_loss = self._time_only_change(previous, observed_at)
            time_lost_today = self._time_only_change(baseline, observed_at)
            actual_change = premium - previous.premium
            holding = actual_change - time_loss if time_loss is not None else None
            self.option_previous[security_id] = current
        discount = exp(-self.rate * time_years)
        intrinsic = discount * max(forward - strike, 0.0) if side == "CE" else discount * max(strike - forward, 0.0)
        time_value_left = premium - intrinsic if premium >= intrinsic else None
        comparison = None if ask is None else ("BELOW_FAIR" if ask < fair else "INFLATED")
        return {
            "fair_price": round(fair, 2), "fair_iv": round(fair_iv * 100.0, 4), "ask": ask, "bid": bid, "spread": round(ask - bid, 2),
            "fair_advantage": round(fair - ask, 2),
            "comparison": comparison, "below_fair_pct": round(((fair - ask) / fair) * 100.0, 2) if ask is not None and ask < fair and fair else None,
            "extra_paying": round(ask - fair, 2) if ask is not None and ask > fair else None,
            "inflated_pct": round(((ask - fair) / fair) * 100.0, 2) if ask is not None and ask > fair and fair else None,
            "time_loss_expected": round(time_loss, 2) if time_loss is not None else None,
            "time_value_left": round(time_value_left, 2) if time_value_left is not None else None,
            "time_lost_today": round(time_lost_today, 2) if time_lost_today is not None else None,
            "actual_change": round(actual_change, 2) if actual_change is not None else None,
            "premium_holding": round(holding, 2) if holding is not None else None,
            "flow": base["flow"], "book": base["book"],
            "quality": {"source_timestamp": observed_at.isoformat(), "quote_age_seconds": surface_age, "surface_age_seconds": surface_age, "continuity_state": "CONTINUOUS", "forward": forward, **forward_quality, "valid": True, "fair_iv_method": smile.method, "surface_point_count": smile.point_count, "pricing_engine": "LOCAL_BLACK76", "time_value_basis": "LTP_MINUS_DISCOUNTED_FORWARD_INTRINSIC", "time_lost_today_reference": "SESSION_FIRST_VALID_OBSERVATION", "time_loss_expected_reference": "PREVIOUS_VALID_OBSERVATION", "status": "MODEL_DERIVED_RESEARCH"},
        }

    def _time_only_change(self, reference: _OptionBaseline, observed_at: datetime) -> float | None:
        initial_t = _time_to_expiry(reference.expiry, reference.observed_at)
        later_t = _time_to_expiry(reference.expiry, observed_at)
        v0 = black76(reference.forward, reference.strike, initial_t or 0.0, reference.fair_iv, self.rate, reference.option_type)
        vtime = black76(reference.forward, reference.strike, later_t or 0.0, reference.fair_iv, self.rate, reference.option_type)
        return vtime - v0 if v0 is not None and vtime is not None else None

    @staticmethod
    def _find_leg(rows: list[Mapping[str, Any]], security_id: str, side: str) -> Mapping[str, Any] | None:
        name = side.lower()
        for row in rows:
            leg = row.get(name)
            if isinstance(leg, Mapping) and str(leg.get("security_id")) == security_id:
                return leg
        return None

    def _fair_iv(self, rows: list[Mapping[str, Any]], target_strike: float, target_security_id: str, forward: float, time_years: float | None, chain_expiry: str) -> _SmileResult | None:
        if time_years is None or time_years <= 0.0:
            return None
        points: list[_SmilePoint] = []
        for row in rows:
            strike = _number(row.get("strike"))
            if strike is None:
                continue
            side = "pe" if strike < forward else "ce"
            leg = row.get(side)
            if not isinstance(leg, Mapping) or str(leg.get("security_id") or "") == target_security_id:
                continue
            explicit_expiry = _leg_expiry(leg, row)
            if explicit_expiry is not None and explicit_expiry != chain_expiry:
                continue
            quote = _clean_quote(leg)
            if quote is None:
                continue
            bid, ask = quote
            flag = "p" if side == "pe" else "c"
            iv = implied_volatility((bid + ask) / 2.0, forward, strike, time_years, self.rate, "PE" if flag == "p" else "CE")
            if iv is None or iv != iv or iv <= 0.0:
                continue
            discount = exp(-self.rate * time_years)
            parity_shift = discount * (forward - strike) if side == "pe" else 0.0
            points.append(_SmilePoint(strike, iv, bid + parity_shift, ask + parity_shift, str(leg.get("security_id") or "")))
        points.sort(key=lambda point: point.strike)
        if len(points) < 3 or not self._static_arbitrage_sane(points, forward, time_years):
            return None
        lower = [point for point in points if point.strike < target_strike]
        upper = [point for point in points if point.strike > target_strike]
        if not lower or not upper:
            return None
        lo, hi = max(lower, key=lambda point: point.strike), min(upper, key=lambda point: point.strike)
        weight = (target_strike - lo.strike) / (hi.strike - lo.strike)
        total_variance = (lo.iv * lo.iv * time_years) + weight * ((hi.iv * hi.iv * time_years) - (lo.iv * lo.iv * time_years))
        if total_variance <= 0.0:
            return None
        return _SmileResult(sqrt(total_variance / time_years), len(points), "ARBITRAGE_GATED_TOTAL_VARIANCE_INTERPOLATION_EXCLUDING_TARGET")

    def _static_arbitrage_sane(self, points: list[_SmilePoint], forward: float, time_years: float) -> bool:
        discount = exp(-self.rate * time_years)
        for point in points:
            intrinsic = discount * max(forward - point.strike, 0.0)
            if point.call_high < intrinsic or point.call_low > discount * forward:
                return False
        for left, right in zip(points, points[1:]):
            if right.call_low > left.call_high:
                return False
            width = right.strike - left.strike
            min_slope = (right.call_low - left.call_high) / width
            max_slope = (right.call_high - left.call_low) / width
            if min_slope > 0.0 or max_slope < -discount:
                return False
        for left, center, right in zip(points, points[1:], points[2:]):
            left_width, right_width = center.strike - left.strike, right.strike - center.strike
            least_left_slope = (center.call_low - left.call_high) / left_width
            greatest_right_slope = (right.call_high - center.call_low) / right_width
            if greatest_right_slope < least_left_slope:
                return False
        return True

    def _forward_quality(self, rows: list[Mapping[str, Any]], forward: float, futures: Mapping[str, Any], chain_expiry: str) -> dict[str, Any]:
        values: list[float] = []
        uncertainties: list[float] = []
        for row in rows:
            strike = _number(row.get("strike"))
            ce, pe = row.get("ce"), row.get("pe")
            if strike is None or not isinstance(ce, Mapping) or not isinstance(pe, Mapping):
                continue
            ce_expiry, pe_expiry = _leg_expiry(ce, row), _leg_expiry(pe, row)
            if ce_expiry not in {None, chain_expiry} or pe_expiry not in {None, chain_expiry}:
                continue
            ce_quote, pe_quote = _clean_quote(ce), _clean_quote(pe)
            if ce_quote is None or pe_quote is None:
                continue
            ce_bid, ce_ask = ce_quote
            pe_bid, pe_ask = pe_quote
            values.append(strike + ((ce_bid + ce_ask) - (pe_bid + pe_ask)) / 2.0)
            uncertainties.append(((ce_ask - ce_bid) + (pe_ask - pe_bid)) / 2.0)
        parity = median(values) if values else None
        parity_uncertainty = median(uncertainties) if uncertainties else None
        fut_bid, fut_ask = _number(futures.get("best_bid_price")), _number(futures.get("best_ask_price"))
        futures_uncertainty = (fut_ask - fut_bid) / 2.0 if fut_bid is not None and fut_ask is not None and 0.0 < fut_bid <= fut_ask else 0.0
        tolerance = futures_uncertainty + parity_uncertainty if parity_uncertainty is not None else None
        discrepancy = abs(forward - parity) if parity is not None else None
        valid = discrepancy is not None and tolerance is not None and discrepancy <= tolerance
        return {"forward_gate_valid": valid, "parity_forward": parity, "forward_discrepancy": discrepancy, "forward_gate_tolerance": tolerance, "forward_gate_rule": "QUOTE_INTERVAL_OVERLAP"}

    @staticmethod
    def _synthetic_forward(rows: list[Mapping[str, Any]]) -> float | None:
        values = []
        for row in rows:
            strike = _number(row.get("strike"))
            ce, pe = row.get("ce"), row.get("pe")
            if strike is not None and isinstance(ce, Mapping) and isinstance(pe, Mapping):
                ce_mid, pe_mid = _mid(ce), _mid(pe)
                if ce_mid is not None and pe_mid is not None:
                    values.append(strike + ce_mid - pe_mid)
        return median(values) if values else None

    def _straddle(self, rows: list[Mapping[str, Any]], forward: float | None, observed_at: datetime | None, valid: bool, ce: Mapping[str, Any], pe: Mapping[str, Any]) -> dict[str, Any]:
        if not valid or forward is None or observed_at is None:
            return {"now": None, "vwap": None, "premium_today": None, "state": None, "market_still_prices": None, "time_loss_expected": None, "actual_change": None, "premium_holding": None, "premium_driver": "MIXED", "continuity_state": "UNAVAILABLE"}
        atm_row = min(rows, key=lambda row: abs((_number(row.get("strike")) or forward) - forward))
        strike = _number(atm_row.get("strike"))
        call, put = atm_row.get("ce"), atm_row.get("pe")
        call_price = _number(call.get("ltp")) if isinstance(call, Mapping) else None
        put_price = _number(put.get("ltp")) if isinstance(put, Mapping) else None
        if strike is None or call_price is None or put_price is None:
            return {"now": None, "vwap": None, "premium_today": None, "state": None, "market_still_prices": None, "time_loss_expected": None, "actual_change": None, "premium_holding": None, "premium_driver": "MIXED", "continuity_state": "UNAVAILABLE"}
        raw = call_price + put_price
        state = self.straddle
        switched = state.atm is not None and state.atm != strike
        if state.continuous_value is None:
            continuous, opening = raw, raw
        elif switched:
            continuous, opening = state.continuous_value, state.opening_value
        else:
            continuous, opening = raw + (state.continuous_value - (state.last_value or raw)), state.opening_value
        if switched or state.call_open is None or state.put_open is None:
            call_open, put_open = call_price, put_price
        else:
            call_open, put_open = state.call_open, state.put_open
        call_id = str(call.get("security_id") or "") if isinstance(call, Mapping) else ""
        put_id = str(put.get("security_id") or "") if isinstance(put, Mapping) else ""
        expiry = _leg_expiry(call, atm_row) if isinstance(call, Mapping) else None
        time_years = _time_to_expiry(expiry, observed_at) if expiry else None
        call_smile = self._fair_iv(rows, strike, call_id, forward, time_years, str(expiry or "")) if call_id else None
        put_smile = self._fair_iv(rows, strike, put_id, forward, time_years, str(expiry or "")) if put_id else None
        call_current = _OptionBaseline(observed_at, call_price, forward, strike, str(expiry or ""), call_smile.fair_iv, "CE") if expiry and call_smile else None
        put_current = _OptionBaseline(observed_at, put_price, forward, strike, str(expiry or ""), put_smile.fair_iv, "PE") if expiry and put_smile else None
        time_loss = None
        actual_change = None
        holding = None
        if not switched and state.call_reference and state.put_reference and call_current and put_current:
            call_loss = self._time_only_change(state.call_reference, observed_at)
            put_loss = self._time_only_change(state.put_reference, observed_at)
            if call_loss is not None and put_loss is not None:
                time_loss = call_loss + put_loss
            if state.previous_continuous is not None:
                actual_change = continuous - state.previous_continuous
            if time_loss is not None and actual_change is not None:
                holding = actual_change - time_loss
        self.straddle = _StraddleState(
            strike, continuous, opening, raw, call_open, put_open,
            continuous, call_current, put_current,
        )
        change = continuous - opening if opening is not None else None
        call_change, put_change = call_price - call_open, put_price - put_open
        driver = "CALL" if call_change > 0 and put_change <= 0 else "PUT" if put_change > 0 and call_change <= 0 else "MIXED"
        return {"now": round(raw, 2), "vwap": None, "premium_today": round(change, 2) if change is not None else None, "state": "RISING" if change is not None and change >= 0 else "FALLING", "market_still_prices": round(raw, 2), "time_loss_expected": round(time_loss, 2) if time_loss is not None else None, "actual_change": round(actual_change, 2) if actual_change is not None else None, "premium_holding": round(holding, 2) if holding is not None else None, "premium_driver": driver, "call_change": round(call_change, 2), "put_change": round(put_change, 2), "continuity_state": "STRIKE_SWITCH_ADJUSTED" if switched else "CONTINUOUS", "atm_strike": strike}
