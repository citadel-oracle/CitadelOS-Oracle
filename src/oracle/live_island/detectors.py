"""Fast Sliding-Window Detectors Consuming Canonical Streaming Upstox Ticks."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from src.oracle.live_island.contracts import (
    ArchetypeType,
    EventBias,
    LiveIslandEvent,
    LiveIslandTimestamps,
    NumericTrend,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.guards import SnapshotSuppressionGuard, StableUniverseGuard
from src.oracle.live_island.registry import DEFAULT_REGISTRY, LiveIslandRegistry

logger = logging.getLogger(__name__)


class IndiaVixDetector:
    """Sliding-window detector for India VIX material shifts (>= 2% change)."""

    def __init__(
        self,
        registry: LiveIslandRegistry = DEFAULT_REGISTRY,
        suppression_guard: Optional[SnapshotSuppressionGuard] = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.registry = registry
        self.suppression_guard = suppression_guard
        self.window_seconds = window_seconds
        self._samples: Deque[Tuple[float, float]] = deque()  # (epoch_sec, vix_ltp)
        self._last_emitted_value: Optional[float] = None
        self._last_emitted_time: float = 0.0

    def on_tick(self, tick: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        # Instrument verification
        ikey = str(tick.get("instrument_key") or "")
        if "India VIX" not in ikey and "VIX" not in ikey:
            return None

        ltp = tick.get("ltp")
        if ltp is None or ltp <= 0:
            return None

        is_snapshot = bool(tick.get("is_snapshot", False))
        feed_epoch = int(tick.get("feed_epoch", 1))

        now = time.time()
        self._samples.append((now, float(ltp)))

        # Evict samples older than window_seconds
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        # Check suppression guard
        if self.suppression_guard and self.suppression_guard.should_suppress(is_snapshot, feed_epoch):
            return None

        if len(self._samples) < 2:
            return None

        old_val = self._samples[0][1]
        new_val = self._samples[-1][1]

        if old_val <= 0:
            return None

        pct_change = ((new_val - old_val) / old_val) * 100.0
        abs_pct = abs(pct_change)

        if abs_pct >= self.registry.vix_min_change_pct:
            # Check re-arm / threshold delta
            if self._last_emitted_value is not None:
                step_pct = abs(((new_val - self._last_emitted_value) / self._last_emitted_value) * 100.0)
                if step_pct < 0.5 and (now - self._last_emitted_time) < 10.0:
                    return None

            self._last_emitted_value = new_val
            self._last_emitted_time = now

            numeric_trend = NumericTrend.UP.value if pct_change > 0 else NumericTrend.DOWN.value
            # VIX rising is bearish/risk escalation; VIX falling is bullish volatility collapse
            event_bias = EventBias.BEARISH.value if pct_change > 0 else EventBias.BULLISH.value
            severity = SeverityLevel.HIGH.value if abs_pct >= 5.0 else SeverityLevel.MEDIUM.value

            dt = max(0.1, self._samples[-1][0] - self._samples[0][0])
            velocity = round((new_val - old_val) / dt, 3)
            acceleration = round(velocity / dt, 3)

            sign = "+" if pct_change >= 0 else ""
            change_str = f"{sign}{pct_change:.1f}%"

            return LiveIslandEvent(
                id="vix",
                family="vix",
                title="India VIX Shock" if pct_change > 0 else "India VIX Relief",
                short_title=f"VIX {'↑' if pct_change > 0 else '↓'} {new_val:.2f}",
                archetype=ArchetypeType.SCALAR.value,
                numeric_trend=numeric_trend,
                event_bias=event_bias,
                severity=severity,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"{new_val:.2f}",
                previous_value=f"{old_val:.2f}",
                change_percent=round(pct_change, 2),
                velocity=velocity,
                acceleration=acceleration,
                confidence=0.98,
                shorthand=f"VIX {sign}{pct_change:.1f}%",
                secondary_value=f"Elevated vol ({change_str})" if pct_change > 0 else f"Vol calming ({change_str})",
                reference_window=f"{int(self.window_seconds)}s",
                priority_weight=2.5 if abs_pct < 5.0 else 3.8,
                timestamps=LiveIslandTimestamps(
                    feed_ts=tick.get("ltt"),
                    ingest_ts=now,
                ),
                feed_epoch=feed_epoch,
                archetype_data={
                    "oldVal": f"{old_val:.2f}",
                    "newVal": f"{new_val:.2f}",
                    "change": change_str,
                },
            )

        return None


class LivePcrDetector:
    """Sliding-window detector for streaming Put-Call Ratio shifts (>= 5% change)."""

    def __init__(
        self,
        registry: LiveIslandRegistry = DEFAULT_REGISTRY,
        suppression_guard: Optional[SnapshotSuppressionGuard] = None,
        universe_guard: Optional[StableUniverseGuard] = None,
        window_seconds: float = 120.0,
    ) -> None:
        self.registry = registry
        self.suppression_guard = suppression_guard
        self.universe_guard = universe_guard
        self.window_seconds = window_seconds
        self._strike_pe_oi: Dict[str, float] = {}
        self._strike_ce_oi: Dict[str, float] = {}
        self._history: Deque[Tuple[float, float]] = deque()  # (epoch_sec, pcr)
        self._last_emitted_pcr: Optional[float] = None
        self._last_emitted_time: float = 0.0

    def on_tick(self, tick: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        ikey = str(tick.get("instrument_key") or "")
        oi = tick.get("oi")
        if oi is None:
            return None

        # Determine CE vs PE
        if "CE" in ikey or tick.get("instrument_type") == "CE":
            self._strike_ce_oi[ikey] = float(oi)
        elif "PE" in ikey or tick.get("instrument_type") == "PE":
            self._strike_pe_oi[ikey] = float(oi)
        else:
            return None

        tot_ce = sum(self._strike_ce_oi.values())
        tot_pe = sum(self._strike_pe_oi.values())
        if tot_ce <= 0 or tot_pe <= 0:
            return None

        current_pcr = round(tot_pe / tot_ce, 3)
        now = time.time()
        self._history.append((now, current_pcr))

        cutoff = now - self.window_seconds
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        is_snapshot = bool(tick.get("is_snapshot", False))
        feed_epoch = int(tick.get("feed_epoch", 1))

        if self.suppression_guard and self.suppression_guard.should_suppress(is_snapshot, feed_epoch):
            return None

        if len(self._history) < 2:
            return None

        base_pcr = self._history[0][1]
        if base_pcr <= 0:
            return None

        pct_change = ((current_pcr - base_pcr) / base_pcr) * 100.0
        abs_pct = abs(pct_change)

        if abs_pct >= self.registry.pcr_min_change_pct:
            if self._last_emitted_pcr is not None:
                step = abs(current_pcr - self._last_emitted_pcr)
                if step < 0.02 and (now - self._last_emitted_time) < 10.0:
                    return None

            self._last_emitted_pcr = current_pcr
            self._last_emitted_time = now

            numeric_trend = NumericTrend.UP.value if pct_change > 0 else NumericTrend.DOWN.value
            event_bias = EventBias.BULLISH.value if pct_change > 0 else EventBias.BEARISH.value
            severity = SeverityLevel.HIGH.value if abs_pct >= 15.0 else SeverityLevel.MEDIUM.value

            sign = "+" if pct_change >= 0 else ""
            change_str = f"{sign}{pct_change:.1f}%"

            return LiveIslandEvent(
                id="pcr",
                family="pcr",
                title="PCR Surge" if pct_change > 0 else "PCR Drop",
                short_title=f"PCR {current_pcr:.2f}",
                archetype=ArchetypeType.SCALAR.value,
                numeric_trend=numeric_trend,
                event_bias=event_bias,
                severity=severity,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"{current_pcr:.2f}",
                previous_value=f"{base_pcr:.2f}",
                change_percent=round(pct_change, 2),
                confidence=0.95,
                shorthand=f"PCR {base_pcr:.2f} → {current_pcr:.2f}",
                secondary_value=f"OI Ratio shift ({change_str})",
                reference_window=f"{int(self.window_seconds)}s",
                priority_weight=2.2 if abs_pct < 15.0 else 3.5,
                timestamps=LiveIslandTimestamps(
                    feed_ts=tick.get("ltt"),
                    ingest_ts=now,
                ),
                feed_epoch=feed_epoch,
                archetype_data={
                    "oldVal": f"{base_pcr:.2f}",
                    "newVal": f"{current_pcr:.2f}",
                    "change": change_str,
                },
            )

        return None


class LiveOiSurgeDetector:
    """Detects rapid single-strike open interest surges, mapping to dual-sided archetype."""

    def __init__(
        self,
        suppression_guard: Optional[SnapshotSuppressionGuard] = None,
        min_surge_contracts: int = 50_000,
    ) -> None:
        self.suppression_guard = suppression_guard
        self.min_surge_contracts = min_surge_contracts
        self._strike_baseline: Dict[str, Tuple[float, float]] = {}  # ikey -> (first_oi, first_ts)
        self._last_emitted_time: float = 0.0

    def on_tick(self, tick: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        ikey = str(tick.get("instrument_key") or "")
        oi = tick.get("oi")
        if oi is None or ("CE" not in ikey and "PE" not in ikey):
            return None

        is_snapshot = bool(tick.get("is_snapshot", False))
        feed_epoch = int(tick.get("feed_epoch", 1))

        if self.suppression_guard and self.suppression_guard.should_suppress(is_snapshot, feed_epoch):
            # Seed baseline
            self._strike_baseline[ikey] = (float(oi), time.time())
            return None

        now = time.time()
        if ikey not in self._strike_baseline:
            self._strike_baseline[ikey] = (float(oi), now)
            return None

        base_oi, base_ts = self._strike_baseline[ikey]
        delta_oi = float(oi) - base_oi

        if abs(delta_oi) >= self.min_surge_contracts and (now - self._last_emitted_time) >= 5.0:
            self._last_emitted_time = now
            is_call = "CE" in ikey
            pct = (delta_oi / base_oi * 100.0) if base_oi > 0 else 0.0

            # Dual-sided archetype
            left_val = f"{'+' if delta_oi >= 0 else ''}{pct:.1f}%" if is_call else "0.0%"
            right_val = f"{'+' if delta_oi >= 0 else ''}{pct:.1f}%" if not is_call else "0.0%"
            dominant = "left" if is_call else "right"

            # Put build-up is bearish; Call build-up is bearish resistance (writing) or bullish breakout
            event_bias = EventBias.BEARISH.value if not is_call else EventBias.NEUTRAL.value

            return LiveIslandEvent(
                id="oi_surge",
                family="oi",
                title="Strike OI Surge",
                short_title=f"OI {'PE' if not is_call else 'CE'} Surge",
                archetype=ArchetypeType.DUAL_SIDED.value,
                numeric_trend=NumericTrend.UP.value if delta_oi > 0 else NumericTrend.DOWN.value,
                event_bias=event_bias,
                severity=SeverityLevel.HIGH.value if abs(delta_oi) >= 100_000 else SeverityLevel.MEDIUM.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"{'+' if delta_oi >= 0 else ''}{delta_oi:,.0f}",
                previous_value="0",
                change_percent=round(pct, 1),
                confidence=0.92,
                shorthand=f"OI Surge {ikey.split('|')[-1]}",
                secondary_value=f"{'PE' if not is_call else 'CE'} writing intensity",
                reference_window="rolling",
                priority_weight=3.0,
                timestamps=LiveIslandTimestamps(
                    feed_ts=tick.get("ltt"),
                    ingest_ts=now,
                ),
                feed_epoch=feed_epoch,
                archetype_data={
                    "leftSide": "CALL ΔOI",
                    "leftVal": left_val,
                    "rightSide": "PUT ΔOI",
                    "rightVal": right_val,
                    "dominantSide": dominant,
                },
            )

        return None


class FastIvVelocityDetector:
    """Detects rapid single-strike IV spikes or collapses (>= 5% or >= 1.5 vol points)."""

    def __init__(
        self,
        suppression_guard: Optional[SnapshotSuppressionGuard] = None,
        min_change_pct: float = 5.0,
        min_change_pts: float = 1.5,
        window_seconds: float = 60.0,
    ) -> None:
        self.suppression_guard = suppression_guard
        self.min_change_pct = min_change_pct
        self.min_change_pts = min_change_pts
        self.window_seconds = window_seconds
        self._history: Dict[str, Deque[Tuple[float, float]]] = {}  # ikey -> deque of (ts, iv)
        self._last_emitted_time: Dict[str, float] = {}

    def on_tick(self, tick: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        iv = tick.get("iv") or tick.get("implied_volatility")
        if iv is None or float(iv) <= 0:
            return None

        ikey = str(tick.get("instrument_key") or "")
        if not ikey:
            return None

        now = time.time()
        is_snapshot = bool(tick.get("is_snapshot", False))
        feed_epoch = int(tick.get("feed_epoch", 1))

        if self.suppression_guard and self.suppression_guard.should_suppress(is_snapshot, feed_epoch):
            return None

        if ikey not in self._history:
            self._history[ikey] = deque()

        hist = self._history[ikey]
        hist.append((now, float(iv)))

        # Prune older than window_seconds
        cutoff = now - self.window_seconds
        while hist and hist[0][0] < cutoff:
            hist.popleft()

        if len(hist) < 2:
            return None

        base_iv = hist[0][1]
        curr_iv = hist[-1][1]
        if base_iv <= 0:
            return None

        delta_pts = curr_iv - base_iv
        pct_change = (delta_pts / base_iv) * 100.0
        abs_pct = abs(pct_change)
        abs_pts = abs(delta_pts)

        if abs_pct >= self.min_change_pct or abs_pts >= self.min_change_pts:
            last_time = self._last_emitted_time.get(ikey, 0.0)
            if (now - last_time) < 10.0:
                return None

            self._last_emitted_time[ikey] = now
            is_call = "CE" in ikey or tick.get("instrument_type") == "CE"
            side = "CE" if is_call else "PE"
            strike = str(tick.get("strike_price") or ikey.split("|")[-1])

            numeric_trend = NumericTrend.UP.value if delta_pts > 0 else NumericTrend.DOWN.value
            event_bias = EventBias.RISK.value if delta_pts > 0 else EventBias.NEUTRAL.value
            sign = "+" if delta_pts >= 0 else ""

            return LiveIslandEvent(
                id=f"iv_{ikey}",
                family="iv_velocity",
                title=f"{strike} {side} IV Velocity",
                short_title=f"{strike} IV {'↑' if delta_pts > 0 else '↓'} {curr_iv:.1f}",
                archetype=ArchetypeType.SCALAR.value,
                numeric_trend=numeric_trend,
                event_bias=event_bias,
                severity=SeverityLevel.HIGH.value if abs_pct >= 15.0 else SeverityLevel.MEDIUM.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"{curr_iv:.1f}",
                previous_value=f"{base_iv:.1f}",
                change_percent=round(pct_change, 1),
                confidence=0.93,
                shorthand=f"{strike} IV {sign}{pct_change:.1f}%",
                secondary_value=f"IV VELOCITY ({sign}{delta_pts:.1f} vol)",
                reference_window=f"{int(self.window_seconds)}s",
                priority_weight=3.1,
                timestamps=LiveIslandTimestamps(
                    feed_ts=tick.get("ltt"),
                    ingest_ts=now,
                ),
                feed_epoch=feed_epoch,
                archetype_data={
                    "oldVal": f"{base_iv:.1f}",
                    "newVal": f"{curr_iv:.1f}",
                    "change": f"{sign}{pct_change:.1f}%",
                    "rateText": "ACCELERATING" if abs_pct >= 10.0 else "SURGING",
                },
            )

        return None


class PremiumAccelerationDetector:
    """Detects rapid option premium price acceleration (>= 10% move with positive d^2P/dt^2)."""

    def __init__(
        self,
        suppression_guard: Optional[SnapshotSuppressionGuard] = None,
        min_move_pct: float = 10.0,
        window_seconds: float = 20.0,
    ) -> None:
        self.suppression_guard = suppression_guard
        self.min_move_pct = min_move_pct
        self.window_seconds = window_seconds
        self._history: Dict[str, Deque[Tuple[float, float]]] = {}  # ikey -> deque of (ts, ltp)
        self._last_emitted_time: Dict[str, float] = {}

    def on_tick(self, tick: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        ltp = tick.get("ltp")
        if ltp is None or float(ltp) <= 0:
            return None

        ikey = str(tick.get("instrument_key") or "")
        # Only evaluate option instruments
        if "CE" not in ikey and "PE" not in ikey and tick.get("instrument_type") not in ("CE", "PE"):
            return None

        ts_val = tick.get("ltt") or tick.get("timestamp")
        if isinstance(ts_val, (int, float)):
            now = float(ts_val) / 1000.0 if ts_val > 2e9 else float(ts_val)
        else:
            now = time.time()

        is_snapshot = bool(tick.get("is_snapshot", False))
        feed_epoch = int(tick.get("feed_epoch", 1))

        if self.suppression_guard and self.suppression_guard.should_suppress(is_snapshot, feed_epoch):
            return None

        if ikey not in self._history:
            self._history[ikey] = deque()

        hist = self._history[ikey]
        hist.append((now, float(ltp)))

        # Prune samples older than window_seconds
        cutoff = now - self.window_seconds
        while hist and hist[0][0] < cutoff:
            hist.popleft()

        if len(hist) < 4:
            return None

        base_ltp = hist[0][1]
        curr_ltp = hist[-1][1]
        dt_total = hist[-1][0] - hist[0][0]
        if base_ltp <= 0 or dt_total < 0.01:
            return None

        pct_change = ((curr_ltp - base_ltp) / base_ltp) * 100.0
        if pct_change < self.min_move_pct:
            return None

        # Split history into two halves to compute velocity and acceleration
        mid_idx = len(hist) // 2
        p_start, t_start = hist[0][1], hist[0][0]
        p_mid, t_mid = hist[mid_idx][1], hist[mid_idx][0]
        p_end, t_end = hist[-1][1], hist[-1][0]

        dt1 = max(0.005, t_mid - t_start)
        dt2 = max(0.005, t_end - t_mid)

        v1 = (p_mid - p_start) / dt1
        v2 = (p_end - p_mid) / dt2
        accel = (v2 - v1) / dt_total

        # Must have positive acceleration (velocity is speeding up)
        if accel <= 0.01:
            return None

        last_time = self._last_emitted_time.get(ikey, 0.0)
        if (now - last_time) < 10.0:
            return None

        self._last_emitted_time[ikey] = now
        is_call = "CE" in ikey or tick.get("instrument_type") == "CE"
        side = "CE" if is_call else "PE"
        strike = str(tick.get("strike_price") or ikey.split("|")[-1])

        event_bias = EventBias.BULLISH.value if is_call else EventBias.BEARISH.value

        return LiveIslandEvent(
            id=f"prem_accel_{ikey}",
            family="premium_acceleration",
            title=f"{strike} {side} Premium Surge",
            short_title=f"{strike} {side} ⇈ +{pct_change:.0f}%",
            archetype=ArchetypeType.IMPULSE.value,
            numeric_trend=NumericTrend.UP.value,
            event_bias=event_bias,
            severity=SeverityLevel.HIGH.value if pct_change >= 20.0 else SeverityLevel.MEDIUM.value,
            phase=PresentationPhase.IMPACT.value,
            current_value=f"{curr_ltp:.1f}",
            previous_value=f"{base_ltp:.1f}",
            change_percent=round(pct_change, 1),
            velocity=round(v2, 2),
            acceleration=round(accel, 3),
            confidence=0.96,
            shorthand=f"{strike} {side} +{pct_change:.0f}%",
            secondary_value=f"PREMIUM ACCELERATION ({side})",
            reference_window=f"{int(self.window_seconds)}s",
            priority_weight=3.8,
            timestamps=LiveIslandTimestamps(
                feed_ts=tick.get("ltt"),
                ingest_ts=now,
            ),
            feed_epoch=feed_epoch,
            archetype_data={
                "blastIntensity": f"+{pct_change:.0f}%",
                "strike": strike,
                "side": side,
                "rateText": "ACCELERATING",
            },
        )

