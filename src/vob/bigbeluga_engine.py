"""Exact Python port of BigBeluga Smart Money Concepts Pine v5 indicator (VOB subset).

Settings used (matching TradingView reference screenshots):
    windowsis   = True
    mswindow    = 5000  (effectively all bars)
    showSwing   = True
    swingLimit  = 100
    msmode      = "Adjusted Points"
    mslen       = 5
    buildsweep  = True
    obshow      = True
    oblast      = 5
    obmode      = "Length"
    len         = 5
    obmiti      = "Close"
    overlap     = True
    wichlap     = "Recent"

Execution influence: ZERO.
advisory_only: True.
No UI logic. No order generation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants (settings)
# ---------------------------------------------------------------------------
MSLEN      = 5        # pivot length
OBMODE     = "Length" # OB construction mode
OB_LEN     = 5        # ATR multiplier numerator (len)
OB_LAST    = 5        # show last N order blocks
OBMITI     = "Close"  # mitigation method
WICHLAP    = "Recent" # overlap removal mode
BUILD_SWEEP = True
MSMODE     = "Adjusted Points"

EXECUTION_INFLUENCE = 0.0
ADVISORY_ONLY       = True


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class OBZone:
    """Order Block zone — direct analogue to Pine 'ob' type."""
    bull: bool               # True=bullish, False=bearish
    top: float               # zone upper boundary
    btm: float               # zone lower boundary
    avg: float               # midpoint
    loc: int                 # origin bar_index
    loc_time: float          # origin epoch time
    vol: float               # origin candle volume
    direction: int           # 1 if bull candle origin, -1 if bear
    is_mitigated: bool = False
    mitigation_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bull": self.bull,
            "side": "BULLISH" if self.bull else "BEARISH",
            "role": "SUPPORT" if self.bull else "RESISTANCE",
            "top": round(self.top, 2),
            "btm": round(self.btm, 2),
            "avg": round(self.avg, 2),
            "loc_time": self.loc_time,
            "vol": self.vol,
            "direction": self.direction,
            "is_mitigated": self.is_mitigated,
            "mitigation_time": self.mitigation_time,
        }


@dataclass
class MSState:
    """Market Structure state — analogue to Pine 'structure' type."""
    zn: int = 0
    zz: float = 0.0
    bos: Optional[float] = None
    choch: float = 0.0
    loc: int = 0          # structure lock bar
    temp: int = 0         # tracked extreme bar
    trend: int = 0        # +1 bull, -1 bear
    start: int = 0        # 0=init, 1=first phase, 2=running
    main: float = 0.0     # running extreme price
    xloc: int = 0         # sweep anchor
    upsweep: bool = False
    dnsweep: bool = False
    txt: Optional[str] = None
    # Pivot tracking for Adjusted Points
    php: List[float] = field(default_factory=list)  # pivot highs
    phn: List[int]   = field(default_factory=list)  # pivot high indices
    plp: List[float] = field(default_factory=list)  # pivot lows
    pln: List[int]   = field(default_factory=list)  # pivot low indices


# ---------------------------------------------------------------------------
# ATR (Wilder's Average True Range)
# ---------------------------------------------------------------------------

def compute_atr_series(candles: List[Dict], period: int = 200) -> List[float]:
    """Compute Wilder's ATR(period) for each bar, matching Pine ta.atr(200)."""
    n = len(candles)
    tr = [0.0] * n
    for i in range(n):
        h = float(candles[i]["high"])
        l = float(candles[i]["low"])
        if i == 0:
            tr[i] = h - l
        else:
            pc = float(candles[i - 1]["close"])
            tr[i] = max(h - l, abs(h - pc), abs(l - pc))

    # Pine's ta.rma-backed ATR is na until the seed window is complete.  A
    # partial-window SMA changes early order-block geometry and can leave
    # non-Pine zones in the retained arrays.
    atr = [math.nan] * n
    if n < period:
        return atr

    # Seed with the first complete `period` TRs.
    seed_end = period
    atr[seed_end - 1] = sum(tr[:seed_end]) / seed_end

    k = 1.0 / period  # Wilder's alpha = 1/period
    for i in range(seed_end, n):
        atr[i] = atr[i - 1] * (1 - k) + tr[i] * k

    return atr


# ---------------------------------------------------------------------------
# Pivot High / Pivot Low  (ta.pivothigh / ta.pivotlow in Pine)
# ---------------------------------------------------------------------------

def _pivothigh(highs: List[float], i: int, length: int) -> Optional[float]:
    """Returns the pivot high at bar i if confirmed, else None.
    Pine pivothigh(high, n, n) fires at bar i+n (i is the centre bar).
    We shift: pivot at index i is confirmed at index i+length.
    """
    # Centre bar is i - length in bar_index terms
    centre = i - length
    if centre < length:
        return None
    window = highs[centre - length: centre + length + 1]
    if len(window) < 2 * length + 1:
        return None
    val = highs[centre]
    if val == max(window):
        return val
    return None


def _pivotlow(lows: List[float], i: int, length: int) -> Optional[float]:
    centre = i - length
    if centre < length:
        return None
    window = lows[centre - length: centre + length + 1]
    if len(window) < 2 * length + 1:
        return None
    val = lows[centre]
    if val == min(window):
        return val
    return None


# ---------------------------------------------------------------------------
# find() — Pine method find() on structure
# ---------------------------------------------------------------------------

def _find(
    ms: MSState,
    candles: List[Dict],
    bar_index: int,
    use_max: bool,
    sweep: bool,
    useob: bool,
) -> int:
    """Exact port of Pine find() method.

    Returns idx (bars back from bar_index) where the extreme origin candle is.
    """
    anchor = ms.xloc if sweep else ms.loc
    search_span = (bar_index - anchor)  # number of bars back to search

    if search_span < 0:
        return 0

    # Clamp to available bars
    search_span = min(search_span, bar_index)

    high_at = lambda k: float(candles[bar_index - k]["high"])
    low_at  = lambda k: float(candles[bar_index - k]["low"])

    if use_max:
        max_val = -1.0
        idx = 0
        limit = search_span - 1 if search_span > 1 else search_span
        for k in range(0, limit + 1):
            h = high_at(k)
            # Pine assigns idx whenever max == high[i], so an equal extreme
            # encountered later in the bars-back scan replaces the earlier.
            if h >= max_val:
                max_val = h
                idx = k
        if useob and idx + 1 <= bar_index:
            if high_at(idx + 1) > high_at(idx):
                idx += 1
    else:
        min_val = 1e18
        idx = 0
        limit = search_span - 1 if search_span > 1 else search_span
        for k in range(0, limit + 1):
            l = low_at(k)
            if l <= min_val:
                min_val = l
                idx = k
        if useob and idx + 1 <= bar_index:
            if low_at(idx + 1) < low_at(idx):
                idx += 1

    return idx


# ---------------------------------------------------------------------------
# OB Construction  (fnOB)
# ---------------------------------------------------------------------------

def _build_ob(
    bull: bool,
    candles: List[Dict],
    bar_index: int,
    idx: int,          # bars back of origin
    atr_series: List[float],
) -> OBZone:
    """Exact port of fnOB() with ATR Length construction.

    Bearish OB:
        top = origin.high
        btm = max(origin.low, origin.high - ATR200_at_origin)

    Bullish OB:
        btm = origin.low
        top = min(origin.high, origin.low + ATR200_at_origin)
    """
    origin_idx = bar_index - idx
    c = candles[origin_idx]
    o_high = float(c["high"])
    o_low  = float(c["low"])
    o_open = float(c["open"])
    o_close = float(c["close"])
    o_vol  = float(c.get("volume") or 0.0)
    t_val = c.get("time") or c.get("timestamp") or 0
    if isinstance(t_val, str):
        try:
            dt = datetime.fromisoformat(t_val.replace("Z", "+00:00"))
            o_time = dt.timestamp()
        except ValueError:
            o_time = 0.0
    else:
        o_time = float(t_val)

    # ATR at origin bar — global atr = ta.atr(200) / (5/len); with len=5 → / 1.0
    atr_val = atr_series[origin_idx] if origin_idx < len(atr_series) else 0.0

    if not bull:
        top = o_high
        btm_candidate = o_high - atr_val
        btm = max(o_low, btm_candidate) if OBMODE == "Length" else o_low
    else:
        btm = o_low
        top_candidate = o_low + atr_val
        top = min(o_high, top_candidate) if OBMODE == "Length" else o_high

    avg = (top + btm) / 2.0
    direction = 1 if o_close > o_open else -1

    return OBZone(
        bull=bull,
        # Preserve Pine's full floating-point geometry internally.  Display
        # rounding belongs at the projection boundary only.
        top=top,
        btm=btm,
        avg=avg,
        loc=origin_idx,
        loc_time=o_time,
        vol=o_vol,
        direction=direction,
    )


# ---------------------------------------------------------------------------
# Mitigation (mitigated method, obmiti="Close")
# ---------------------------------------------------------------------------

def _is_mitigated(zone: OBZone, candle: Dict) -> bool:
    """Return Pine's ``obmiti='Close'`` body-boundary mitigation result.

    In the authoritative script ``Close`` means the completed candle body
    extreme (``max(open, close)`` / ``min(open, close)``), not close alone.
    """
    o = float(candle["open"])
    c = float(candle["close"])
    if not zone.bull:
        return max(o, c) > zone.top
    else:
        return min(o, c) < zone.btm


# ---------------------------------------------------------------------------
# Overlap removal (overlap function, wichlap="Recent")
# ---------------------------------------------------------------------------

def _ranges_overlap(a_btm: float, a_top: float, b_btm: float, b_top: float) -> bool:
    """True if zones [a_btm,a_top] and [b_btm,b_top] overlap at all."""
    return (
        (a_btm > b_btm and a_btm < b_top)  # a_btm inside b
        or (a_top < b_top and a_btm > b_btm)  # a fully inside b
        or (a_top > b_top and a_btm < b_btm)  # b fully inside a
        or (a_top < b_top and a_top > b_btm)  # a_top inside b
    )


def _apply_overlap(bull_arr: List[OBZone], bear_arr: List[OBZone]) -> None:
    """Exact port of Pine overlap() with wichlap="Recent" (removes older on overlap)."""

    def _dedup_same(arr: List[OBZone]) -> None:
        if len(arr) <= 1:
            return
        to_remove = set()
        current = arr[0]  # most recent (index 0)
        for i in range(len(arr) - 1, 0, -1):
            if i in to_remove:
                continue
            stuff = arr[i]
            if _ranges_overlap(stuff.btm, stuff.top, current.btm, current.top):
                # wichlap="Recent" → v = i (remove older)
                to_remove.add(i)
        for i in sorted(to_remove, reverse=True):
            arr.pop(i)

    _dedup_same(bull_arr)
    _dedup_same(bear_arr)

    # Cross-array: bull vs most-recent bear
    if bull_arr and bear_arr:
        current_bear = bear_arr[0]
        to_remove = set()
        for i in range(len(bull_arr) - 1, -1, -1):
            if _ranges_overlap(bull_arr[i].btm, bull_arr[i].top,
                               current_bear.btm, current_bear.top):
                # wichlap="Recent" → v = 0 (remove most-recent bull)
                to_remove.add(0)
                break
        for i in sorted(to_remove, reverse=True):
            if i < len(bull_arr):
                bull_arr.pop(i)

    # Cross-array: bear vs most-recent bull
    if bear_arr and bull_arr:
        current_bull = bull_arr[0]
        to_remove = set()
        for i in range(len(bear_arr) - 1, -1, -1):
            if _ranges_overlap(bear_arr[i].btm, bear_arr[i].top,
                               current_bull.btm, current_bull.top):
                to_remove.add(0)
                break
        for i in sorted(to_remove, reverse=True):
            if i < len(bear_arr):
                bear_arr.pop(i)


# ---------------------------------------------------------------------------
# Volume % metric (Pine showmetric logic)
# ---------------------------------------------------------------------------

def _compute_vol_pct(arr: List[OBZone], max_show: int) -> List[float]:
    """Return volume % among last max_show OBs (matching Pine metric calculation)."""
    seq = min(max_show, len(arr))
    if seq == 0:
        return []
    total_vol = sum(arr[i].vol for i in range(seq))
    if total_vol == 0:
        return [0.0] * seq
    return [math.floor((arr[i].vol / total_vol) * 100) for i in range(seq)]


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class BigBelugaVOBEngine:
    """Exact BigBeluga SMC OB engine (advisory only, execution influence ZERO)."""

    EXECUTION_INFLUENCE = 0.0
    ADVISORY_ONLY       = True

    def __init__(self, persistence_path: Optional[Path] = None):
        self.persistence_path = Path(persistence_path) if persistence_path else None
        # Per-timeframe state
        self._state: Dict[str, _TFState] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_1m_candles(
        self,
        candles_1m: List[Dict],
        current_nifty_price: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Resample 1m candles to 3m/5m/15m/1h and run BigBeluga replay."""
        from src.vob.engine import NiftyVOBEngine  # reuse resampler
        _helper = NiftyVOBEngine()
        valid_1m = [
            {**c, "timestamp": c.get("timestamp") or c.get("time")}
            for c in candles_1m
            if c.get("timestamp") or c.get("time")
        ]
        valid_1m = [
            c for c in valid_1m
            if all(c.get(k) is not None for k in ("open", "high", "low", "close"))
        ]

        tf_candles = {
            "3m":  _helper._resample_1m(valid_1m, 3),
            "5m":  _helper._resample_1m(valid_1m, 5),
            "15m": _helper._resample_1m(valid_1m, 15),
            "1h":  _helper._resample_1m(valid_1m, 60),
        }

        spot = current_nifty_price
        if spot is None and valid_1m:
            spot = float(valid_1m[-1]["close"])

        return self.analyze_all(tf_candles, current_nifty_price=spot, now=now)

    def analyze_all(
        self,
        tf_candles: Dict[str, List[Dict]],
        current_nifty_price: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Run BigBeluga replay on all timeframes and return structured result."""
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        spot = current_nifty_price or 0.0
        tf_results: Dict[str, Dict] = {}

        for tf, candles in tf_candles.items():
            tf_results[tf] = self._analyze_tf(tf, candles, spot, now_iso)

        self._save()

        # Top-level nearest support/resistance (across all TFs — BigBeluga primary = most recent)
        all_bull = [r["nearest_bullish_support"]    for r in tf_results.values() if r.get("nearest_bullish_support")]
        all_bear = [r["nearest_bearish_resistance"] for r in tf_results.values() if r.get("nearest_bearish_resistance")]

        # Sort by most recent origin (largest loc_time = most recent)
        all_bull.sort(key=lambda z: z["loc_time"], reverse=True)
        all_bear.sort(key=lambda z: z["loc_time"], reverse=True)
        nearest_support    = all_bull[0] if all_bull else None
        nearest_resistance = all_bear[0] if all_bear else None

        confluence = self._compute_confluence(tf_results, spot)

        return {
            "symbol":             "NIFTY",
            "current_nifty_spot": spot,
            "execution_influence": self.EXECUTION_INFLUENCE,
            "advisory_only":      self.ADVISORY_ONLY,
            "calculated_at":      now_iso,
            "nearest_support":    nearest_support,
            "nearest_resistance": nearest_resistance,
            "strongest_confluence": confluence,
            "timeframes":         tf_results,
        }

    # ------------------------------------------------------------------
    # Internal per-TF replay
    # ------------------------------------------------------------------

    def _analyze_tf(
        self,
        tf: str,
        candles: List[Dict],
        spot: float,
        now_iso: str,
    ) -> Dict[str, Any]:
        if len(candles) < MSLEN * 2 + 2:
            return {
                "timeframe": tf,
                "current_nifty_price": spot,
                "nearest_bullish_support": None,
                "nearest_bearish_resistance": None,
                "status": "INSUFFICIENT_DATA",
                "evaluated_through": None,
            }

        # Full deterministic replay on this TF's candles
        bull_arr, bear_arr = self._replay(tf, candles)

        # Primary zone = most recent unmitigated OB (index 0 in array)
        nearest_bull = None
        nearest_bear = None
        for z in bull_arr:
            if not z.is_mitigated:
                nearest_bull = z
                break
        for z in bear_arr:
            if not z.is_mitigated:
                nearest_bear = z
                break

        # Volume % metric
        active_bull = [z for z in bull_arr if not z.is_mitigated][:OB_LAST]
        active_bear = [z for z in bear_arr if not z.is_mitigated][:OB_LAST]
        bull_vol_pct = _compute_vol_pct(active_bull, OB_LAST)
        bear_vol_pct = _compute_vol_pct(active_bear, OB_LAST)

        # Enrich with vol_pct
        def _enrich(zone: Optional[OBZone], arr: List[OBZone], pcts: List[float]) -> Optional[Dict]:
            if zone is None:
                return None
            d = zone.to_dict()
            try:
                idx = arr.index(zone)
                d["vol_pct"] = pcts[idx] if idx < len(pcts) else 0
            except ValueError:
                d["vol_pct"] = 0
            d["timeframe"] = tf
            d["strength_score"] = d["vol_pct"]  # display alias
            d["zone_low"]  = d["btm"]
            d["zone_high"] = d["top"]
            d["status"]    = "MITIGATED" if d["is_mitigated"] else "ACTIVE"
            return d

        evaluated_through = None
        if candles:
            last_ts = candles[-1].get("timestamp") or candles[-1].get("time")
            if isinstance(last_ts, (int, float)):
                from zoneinfo import ZoneInfo
                evaluated_through = datetime.fromtimestamp(float(last_ts), tz=ZoneInfo("Asia/Kolkata")).isoformat()
            else:
                evaluated_through = str(last_ts)

        return {
            "timeframe":                 tf,
            "current_nifty_price":       spot,
            "nearest_bullish_support":   _enrich(nearest_bull, active_bull, bull_vol_pct),
            "nearest_bearish_resistance":_enrich(nearest_bear, active_bear, bear_vol_pct),
            "all_bull_obs":              [_enrich(z, active_bull, bull_vol_pct) for z in active_bull],
            "all_bear_obs":              [_enrich(z, active_bear, bear_vol_pct) for z in active_bear],
            "evaluated_through":         evaluated_through,
        }

    # ------------------------------------------------------------------
    # BigBeluga structure state machine replay (bar-by-bar)
    # ------------------------------------------------------------------

    def _replay(
        self,
        tf: str,
        candles: List[Dict],
    ) -> Tuple[List[OBZone], List[OBZone]]:
        """Run the full BigBeluga BOS/CHoCH state machine on candle series.

        Returns (bull_obs, bear_obs) — most recent OB at index 0.
        """
        n = len(candles)
        highs  = [float(c["high"])  for c in candles]
        lows   = [float(c["low"])   for c in candles]
        opens  = [float(c["open"])  for c in candles]
        closes = [float(c["close"]) for c in candles]

        atr_series = compute_atr_series(candles, period=200)

        ms = MSState()
        bull_arr: List[OBZone] = []
        bear_arr: List[OBZone] = []

        up = highs[0]
        dn = lows[0]

        for i in range(n):
            h, l, o, c = highs[i], lows[i], opens[i], closes[i]
            crossup = False
            crossdn = False

            if h > up:
                up = h; dn = l; crossup = True
            if l < dn:
                up = h; dn = l; crossdn = True

            # Pivot high/low detection (fires mslen bars after the centre bar)
            ph = _pivothigh(highs, i, MSLEN)
            pl = _pivotlow(lows, i, MSLEN)

            centre_bar = i - MSLEN
            if ph is not None:
                ms.phn.insert(0, centre_bar)
                ms.php.insert(0, ph)
                ms.phn = ms.phn[:1]
                ms.php = ms.php[:1]
            if pl is not None:
                ms.pln.insert(0, centre_bar)
                ms.plp.insert(0, pl)
                ms.pln = ms.pln[:1]
                ms.plp = ms.plp[:1]

            # Prune stale pivots
            if ms.php and h > ms.php[0]:
                ms.php.clear(); ms.phn.clear()
            if ms.plp and l < ms.plp[0]:
                ms.plp.clear(); ms.pln.clear()

            # Init
            if ms.start == 0:
                # Pine positional construction is
                # structure.new(..., bos=high, choch=low, ..., start=1,
                # main=na).  Execution then continues into the start==1
                # branch on this same bar.
                ms.bos   = h
                ms.choch = l
                ms.loc   = i
                ms.temp  = i
                ms.xloc  = i
                ms.main  = math.nan
                ms.start = 1
                ms.trend = 0
                up = h; dn = l

            ms.upsweep = False
            ms.dnsweep = False

            if ms.start == 1:
                # Calculate active OB variables on current bar i
                idbull = _find(ms, candles, i, use_max=False, sweep=False, useob=True)
                idbear = _find(ms, candles, i, use_max=True, sweep=False, useob=True)
                btmP   = self._btmP(candles, i, idbear, atr_series)
                topP   = self._topP(candles, i, idbull, atr_series)

                # Phase 1: wait for first CHoCH
                if l <= ms.choch and c >= ms.choch and BUILD_SWEEP:
                    ms.dnsweep = True; ms.choch = l; ms.xloc = i
                elif h >= ms.bos and c <= ms.bos and BUILD_SWEEP:
                    ms.upsweep = True; ms.bos = h; ms.xloc = i
                elif c <= ms.choch:
                    # Pine: blob.fnOB(true, topP, idbull)
                    ob = _build_ob(True, candles, i, idbull, atr_series)
                    ob.top = topP
                    ob.avg = (ob.top + ob.btm) / 2
                    bull_arr.insert(0, ob)
                    ms.trend = -1; ms.choch = ms.bos; ms.bos = None
                    ms.start = 2; ms.loc = i; ms.main = l; ms.temp = i; ms.xloc = i
                elif c >= ms.bos:
                    # Pine: brob.fnOB(false, btmP, idbear)
                    ob = _build_ob(False, candles, i, idbear, atr_series)
                    ob.btm = btmP
                    ob.avg = (ob.top + ob.btm) / 2
                    bear_arr.insert(0, ob)
                    ms.trend = 1; ms.bos = None
                    ms.start = 2; ms.loc = i; ms.main = h; ms.temp = i; ms.xloc = i

            elif ms.start == 2:
                # Calculate active OB variables on current bar i
                idbull = _find(ms, candles, i, use_max=False, sweep=False, useob=True)
                idbear = _find(ms, candles, i, use_max=True, sweep=False, useob=True)
                btmP   = self._btmP(candles, i, idbear, atr_series)
                topP   = self._topP(candles, i, idbull, atr_series)

                if ms.trend == -1:
                    # Bearish trend: track lower lows
                    if l <= ms.main:
                        ms.main = l; ms.temp = i

                    # Adjusted Points: update CHoCH if pivot high is below current CHoCH
                    # Pine parses ``bar_index % mslen * 2 == 0`` as
                    # ``(bar_index % mslen) * 2 == 0``.
                    if i % MSLEN == 0 and ms.bos is not None and MSMODE == "Adjusted Points":
                        if ms.php and ms.php[0] < ms.choch:
                            ms.choch = ms.php[0]
                            ms.loc   = ms.phn[0]
                            ms.xloc  = ms.phn[0]
                            ms.temp  = ms.phn[0]

                    # Set BOS level on two consecutive up bars
                    if ms.bos is None and crossup and c > o and closes[i - 1] > opens[i - 1] if i > 0 else False:
                        ms.bos = ms.main; ms.loc = ms.temp; ms.xloc = ms.loc

                    # BOS sweep
                    if ms.bos is not None and l <= ms.bos and c >= ms.bos and BUILD_SWEEP:
                        ms.dnsweep = True; ms.bos = l; ms.xloc = i
                    elif ms.bos is not None and c <= ms.bos:
                        # BOS confirmed down
                        ob = _build_ob(False, candles, i, idbear, atr_series)
                        ob.btm = btmP
                        ob.avg = (ob.top + ob.btm) / 2
                        bear_arr.insert(0, ob)
                        # Find new CHoCH
                        id2 = _find(ms, candles, i, use_max=True, sweep=False, useob=False)
                        ms.bos   = None
                        ms.choch = highs[i - id2] if (i - id2) >= 0 else h
                        ms.loc   = i - id2

                    # CHoCH sweep
                    if h >= ms.choch and c <= ms.choch and BUILD_SWEEP:
                        ms.upsweep = True; ms.choch = h; ms.xloc = i
                    elif c >= ms.choch:
                        # CHoCH up — trend reversal
                        ob = _build_ob(True, candles, i, idbull, atr_series)
                        ob.top = topP
                        ob.avg = (ob.top + ob.btm) / 2
                        bull_arr.insert(0, ob)
                        # New CHoCH
                        if ms.bos is None:
                            id2 = _find(ms, candles, i, use_max=False, sweep=False, useob=False)
                            ms.choch = lows[i - id2] if (i - id2) >= 0 else l
                        else:
                            ms.choch = ms.bos
                        ms.bos  = None; ms.main = h; ms.trend = 1; ms.loc = i; ms.xloc = i; ms.temp = i

                else:  # trend == 1
                    # Bullish trend: track higher highs
                    if h >= ms.main:
                        ms.main = h; ms.temp = i

                    # Adjusted Points: update CHoCH if pivot low is above current CHoCH
                    if i % MSLEN == 0 and ms.bos is not None and MSMODE == "Adjusted Points":
                        if ms.plp and ms.plp[0] > ms.choch:
                            ms.choch = ms.plp[0]
                            ms.loc   = ms.pln[0]
                            ms.xloc  = ms.pln[0]
                            ms.temp  = ms.pln[0]

                    # Set BOS level on two consecutive down bars
                    if ms.bos is None and crossdn and c < o and closes[i - 1] < opens[i - 1] if i > 0 else False:
                        ms.bos = ms.main; ms.loc = ms.temp; ms.xloc = ms.loc

                    # BOS sweep
                    if ms.bos is not None and h >= ms.bos and c <= ms.bos and BUILD_SWEEP:
                        ms.upsweep = True; ms.bos = h; ms.xloc = i
                    elif ms.bos is not None and c >= ms.bos:
                        # BOS confirmed up
                        ob = _build_ob(True, candles, i, idbull, atr_series)
                        ob.top = topP
                        ob.avg = (ob.top + ob.btm) / 2
                        bull_arr.insert(0, ob)
                        id2 = _find(ms, candles, i, use_max=False, sweep=False, useob=False)
                        ms.bos   = None
                        ms.choch = lows[i - id2] if (i - id2) >= 0 else l
                        ms.loc   = i - id2

                    # CHoCH sweep
                    if l <= ms.choch and c >= ms.choch and BUILD_SWEEP:
                        ms.dnsweep = True; ms.choch = l; ms.xloc = i
                    elif c <= ms.choch:
                        # CHoCH down — trend reversal
                        ob = _build_ob(False, candles, i, idbear, atr_series)
                        ob.btm = btmP
                        ob.avg = (ob.top + ob.btm) / 2
                        bear_arr.insert(0, ob)

                        if ms.bos is None:
                            id2 = _find(ms, candles, i, use_max=True, sweep=False, useob=False)
                            ms.choch = highs[i - id2] if (i - id2) >= 0 else h
                        else:
                            ms.choch = ms.bos
                        ms.bos  = None; ms.main = l; ms.trend = -1; ms.loc = i; ms.xloc = i; ms.temp = i

            # -- Mitigation check on each completed bar --
            if candles[i].get("closed") is not False:  # completed candles
                for zone in bull_arr:
                    if not zone.is_mitigated and _is_mitigated(zone, candles[i]):
                        zone.is_mitigated    = True
                        t_val = candles[i].get("time") or candles[i].get("timestamp") or 0
                        if isinstance(t_val, str):
                            try:
                                dt = datetime.fromisoformat(t_val.replace("Z", "+00:00"))
                                zone.mitigation_time = dt.timestamp()
                            except ValueError:
                                zone.mitigation_time = 0.0
                        else:
                            zone.mitigation_time = float(t_val)
                for zone in bear_arr:
                    if not zone.is_mitigated and _is_mitigated(zone, candles[i]):
                        zone.is_mitigated    = True
                        t_val = candles[i].get("time") or candles[i].get("timestamp") or 0
                        if isinstance(t_val, str):
                            try:
                                dt = datetime.fromisoformat(t_val.replace("Z", "+00:00"))
                                zone.mitigation_time = dt.timestamp()
                            except ValueError:
                                zone.mitigation_time = 0.0
                        else:
                            zone.mitigation_time = float(t_val)

            # -- Overlap removal after each bar (matching Pine barstate.isconfirmed) --
            # Apply overlap to the actual active arrays.  Retain mitigated
            # objects only as Citadel audit history; they cannot participate
            # in Pine display/selection or volume metrics.
            active_bull = [z for z in bull_arr if not z.is_mitigated]
            active_bear = [z for z in bear_arr if not z.is_mitigated]
            _apply_overlap(active_bull, active_bear)
            active_bull_ids = {id(z) for z in active_bull}
            active_bear_ids = {id(z) for z in active_bear}
            bull_arr[:] = [z for z in bull_arr if z.is_mitigated or id(z) in active_bull_ids]
            bear_arr[:] = [z for z in bear_arr if z.is_mitigated or id(z) in active_bear_ids]

        return bull_arr, bear_arr

    # ------------------------------------------------------------------
    # ATR-Length zone boundary helpers
    # ------------------------------------------------------------------

    def _btmP(self, candles: List[Dict], bar_i: int, idx: int, atr_series: List[float]) -> float:
        """btmP for bearish OB (obmode=Length)."""
        origin_i = bar_i - idx
        if origin_i < 0 or origin_i >= len(candles):
            return float(candles[bar_i]["low"])
        o_high = float(candles[origin_i]["high"])
        o_low  = float(candles[origin_i]["low"])
        atr_v  = atr_series[origin_i] if origin_i < len(atr_series) else 0.0
        return max(o_low, o_high - atr_v)

    def _topP(self, candles: List[Dict], bar_i: int, idx: int, atr_series: List[float]) -> float:
        """topP for bullish OB (obmode=Length)."""
        origin_i = bar_i - idx
        if origin_i < 0 or origin_i >= len(candles):
            return float(candles[bar_i]["high"])
        o_high = float(candles[origin_i]["high"])
        o_low  = float(candles[origin_i]["low"])
        atr_v  = atr_series[origin_i] if origin_i < len(atr_series) else 0.0
        return min(o_high, o_low + atr_v)

    # ------------------------------------------------------------------
    # Confluence (same as existing engine)
    # ------------------------------------------------------------------

    def _compute_confluence(self, tf_results: Dict, spot: float) -> Dict:
        bull_zones = [
            r["nearest_bullish_support"]
            for r in tf_results.values()
            if r.get("nearest_bullish_support") and not r["nearest_bullish_support"].get("is_mitigated")
        ]
        bear_zones = [
            r["nearest_bearish_resistance"]
            for r in tf_results.values()
            if r.get("nearest_bearish_resistance") and not r["nearest_bearish_resistance"].get("is_mitigated")
        ]
        return {
            "bullish": self._best_overlap(bull_zones, spot, "BULLISH"),
            "bearish": self._best_overlap(bear_zones, spot, "BEARISH"),
        }

    def _best_overlap(self, zones: List[Dict], spot: float, side: str) -> Optional[Dict]:
        if len(zones) < 2:
            return None
        best = None
        best_score = -1.0
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                z1, z2 = zones[i], zones[j]
                if z1.get("timeframe") == z2.get("timeframe"):
                    continue
                low_i  = max(z1["zone_low"],  z2["zone_low"])
                high_i = min(z1["zone_high"], z2["zone_high"])
                if low_i <= high_i:
                    tfs    = sorted({z1["timeframe"], z2["timeframe"]})
                    has_1h = "1h"  in tfs
                    has_15m= "15m" in tfs
                    if len(tfs) >= 3 and has_1h:
                        tier, score = "ULTRA STRONG", 95.0
                    elif has_15m and has_1h:
                        tier, score = "ULTRA STRONG", 90.0
                    elif len(tfs) >= 3:
                        tier, score = "VERY STRONG", 85.0
                    else:
                        tier, score = "STRONG", 75.0
                    if score > best_score:
                        best_score = score
                        dist = round(abs(spot - (high_i if side == "BULLISH" else low_i)), 2)
                        best = {
                            "side": side, "tier": tier,
                            "confluence_score": score,
                            "overlap_low":  round(low_i, 2),
                            "overlap_high": round(high_i, 2),
                            "participating_timeframes": tfs,
                            "distance_points": dist,
                            "distance_percent": round((dist / spot) * 100.0, 2) if spot > 0 else 0.0,
                        }
        return best

    # ------------------------------------------------------------------
    # Persistence (save/load replay result — not state machine, to allow fast re-query)
    # ------------------------------------------------------------------

    def _save(self) -> None:
        pass  # State machine is stateless replay — no intermediate state to persist

    def _load(self) -> None:
        pass


class _TFState:
    """Placeholder — state is recomputed from full candle replay each call."""
    pass
