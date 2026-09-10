"""Central Coordinator (Hub) for Citadel Live Island Intelligence."""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal
import threading
import time
from typing import Any, Dict, List, Mapping, Optional

from src.broker.upstox_client import UpstoxClient, UpstoxMarketDataFeedV3
from src.oracle.live_island.adapters import (
    BuyersWritersAdapter,
    BuildupAdapter,
    GammaBlastAdapter,
    GexAdapter,
    MaxPainAdapter,
    OiShiftAdapter,
    SuddenOiAdapter,
)
from src.oracle.live_island.broadcaster import LiveIslandBroadcaster
from src.oracle.live_island.contracts import LiveIslandEvent, LiveIslandPillState
from src.oracle.live_island.detectors import (
    FastIvVelocityDetector,
    IndiaVixDetector,
    LiveOiSurgeDetector,
    LivePcrDetector,
    PremiumAccelerationDetector,
)
from src.oracle.live_island.guards import SnapshotSuppressionGuard, StableUniverseGuard
from src.oracle.live_island.journal import LiveIslandJournal
from src.oracle.live_island.reducer import LiveIslandReducer
from src.oracle.live_island.registry import DEFAULT_REGISTRY, LiveIslandRegistry

logger = logging.getLogger(__name__)


class LiveIslandIntelligenceHub:
    """Master Hub wiring feeds, detectors, adapters, guards, reducer, and broadcaster."""

    _instance: Optional[LiveIslandIntelligenceHub] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> LiveIslandIntelligenceHub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(
        self,
        registry: LiveIslandRegistry = DEFAULT_REGISTRY,
        upstox_client: Optional[UpstoxClient] = None,
    ) -> None:
        self.registry = registry
        self.client = upstox_client or UpstoxClient()

        # Guards
        self.universe_guard = StableUniverseGuard()
        self.suppression_guard = SnapshotSuppressionGuard()

        # Journal & Broadcaster
        self.journal = LiveIslandJournal(maxlen=1_000)
        self.broadcaster = LiveIslandBroadcaster()

        # Reducer
        self.reducer = LiveIslandReducer(
            registry=self.registry,
            on_state_change=self._on_reducer_state_change,
        )

        # 5 Fast Streaming Detectors
        self.vix_detector = IndiaVixDetector(
            registry=self.registry,
            suppression_guard=self.suppression_guard,
        )
        self.pcr_detector = LivePcrDetector(
            registry=self.registry,
            suppression_guard=self.suppression_guard,
            universe_guard=self.universe_guard,
        )
        self.oi_surge_detector = LiveOiSurgeDetector(
            suppression_guard=self.suppression_guard,
        )
        self.iv_velocity_detector = FastIvVelocityDetector(
            suppression_guard=self.suppression_guard,
        )
        self.premium_accel_detector = PremiumAccelerationDetector(
            suppression_guard=self.suppression_guard,
        )

        # 7 Canonical Adapters
        self.gex_adapter = GexAdapter(registry=self.registry)
        self.buyers_writers_adapter = BuyersWritersAdapter(
            registry=self.registry,
            universe_guard=self.universe_guard,
        )
        self.buildup_adapter = BuildupAdapter()
        self.gamma_blast_adapter = GammaBlastAdapter()
        self.max_pain_adapter = MaxPainAdapter()
        self.sudden_oi_adapter = SuddenOiAdapter()
        self.oi_shift_adapter = OiShiftAdapter()

        # Feed Management & Orphan Prevention
        self._feed: Optional[UpstoxMarketDataFeedV3] = None
        self._feed_thread: Optional[threading.Thread] = None
        self._feed_loop: Optional[asyncio.AbstractEventLoop] = None
        self._feed_owner_lock = threading.Lock()
        self._is_running = False
        self._tick_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Register cleanup on process exit & signals
        atexit.register(self.shutdown)
        self._register_signals()

    def _register_signals(self) -> None:
        try:
            def _signal_handler(signum, frame):
                logger.info("Signal %s received. Shutting down Live Island Hub cleanly...", signum)
                self.shutdown()

            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGTERM, _signal_handler)
                signal.signal(signal.SIGINT, _signal_handler)
        except (ValueError, AttributeError):
            pass

    def _on_reducer_state_change(self, state: LiveIslandPillState) -> None:
        """Called whenever the reducer updates its state patch."""
        self.broadcaster.broadcast_state(state)

    def on_tick(self, tick: Dict[str, Any]) -> None:
        """Processes an incoming market data tick through fast streaming detectors."""
        is_snapshot = bool(tick.get("is_snapshot", False))
        feed_epoch = int(tick.get("feed_epoch", 1))

        # Check if feed transition changed epoch
        self.suppression_guard.on_feed_epoch_change(feed_epoch)
        if tick.get("feed_state") in ("BASELINE_READY", "LIVE"):
            self.suppression_guard.set_baseline_ready(True)

        # 1. India VIX Detector
        vix_ev = self.vix_detector.on_tick(tick)
        if vix_ev:
            self._record_and_dispatch(vix_ev, "VIX_THRESHOLD_CROSSED")

        # 2. Live PCR Detector
        pcr_ev = self.pcr_detector.on_tick(tick)
        if pcr_ev:
            self._record_and_dispatch(pcr_ev, "PCR_THRESHOLD_CROSSED")

        # 3. Live OI Surge Detector
        oi_ev = self.oi_surge_detector.on_tick(tick)
        if oi_ev:
            self._record_and_dispatch(oi_ev, "STRIKE_OI_SURGE")

        # 4. Fast IV Velocity Detector
        iv_ev = self.iv_velocity_detector.on_tick(tick)
        if iv_ev:
            self._record_and_dispatch(iv_ev, "IV_VELOCITY_SPIKE")

        # 5. Particular Option Premium Acceleration Detector
        prem_ev = self.premium_accel_detector.on_tick(tick)
        if prem_ev:
            self._record_and_dispatch(prem_ev, "PREMIUM_ACCELERATION_BURST")

    def _record_and_dispatch(self, event: LiveIslandEvent, reason: str) -> None:
        self.journal.record(
            trigger_reason=reason,
            event_id=event.id,
            family=event.family,
            old_value=event.previous_value,
            new_value=event.current_value,
            numeric_trend=event.numeric_trend,
            event_bias=event.event_bias,
            rule_version=self.registry.rule_version,
            provenance=event.provenance,
            hero_decision="DISPATCHED",
            coalesced=False,
            details=event.archetype_data,
        )
        self.reducer.dispatch_event(event)

    # -------------------------------------------------------------------------
    # External Canonical Adapters Hook Methods
    # -------------------------------------------------------------------------
    def notify_gex_update(self, net_gex: float, spot_price: Optional[float] = None) -> None:
        ev = self.gex_adapter.on_gex_update(net_gex, spot_price)
        if ev:
            self._record_and_dispatch(ev, "GEX_POLARITY_FLIP")

    def notify_dominance_update(self, buyer_pct: float, writer_pct: float) -> None:
        ev = self.buyers_writers_adapter.on_dominance_update(buyer_pct, writer_pct)
        if ev:
            self._record_and_dispatch(ev, "BUYERS_WRITERS_5PP_SHIFT")

    def notify_buildup_update(self, strike: str, new_state: str) -> None:
        ev = self.buildup_adapter.on_strike_buildup(strike, new_state)
        if ev:
            self._record_and_dispatch(ev, "STRIKE_BUILDUP_TRANSITION")

    def notify_strike_spine_focus(
        self,
        best_strike_stack: Dict[str, Any],
        strike_spine: Optional[List[Any]] = None,
    ) -> None:
        ev = self.buildup_adapter.on_strike_spine_focus(best_strike_stack, strike_spine)
        if ev:
            direction = str(best_strike_stack.get("direction") or "CALL").upper()
            self.reducer.set_spine_bias("bull" if direction == "CALL" else "bear")
            self._record_and_dispatch(ev, "STRIKE_BUILDUP_TRANSITION")

    def notify_atm_window_update(self, window: list[Any]) -> None:
        events = self.buildup_adapter.on_atm_window_update(window)
        for ev in events:
            self._record_and_dispatch(ev, "STRIKE_BUILDUP_TRANSITION")

    def notify_gamma_blast(self, blast_input: Any, intensity: str = "4.8x") -> None:
        ev = self.gamma_blast_adapter.on_gamma_blast(blast_input, intensity)
        if ev:
            self._record_and_dispatch(ev, "GAMMA_BLAST_IMPULSE")

    def notify_max_pain_update(self, new_max_pain: float, spot_price: Optional[float] = None) -> None:
        ev = self.max_pain_adapter.on_max_pain_update(new_max_pain, spot_price)
        if ev:
            self._record_and_dispatch(ev, "MAX_PAIN_STRIKE_MIGRATION")

    def notify_sudden_oi(self, sudden_oi: Dict[str, Any]) -> None:
        ev = self.sudden_oi_adapter.on_sudden_oi_update(sudden_oi)
        if ev:
            self._record_and_dispatch(ev, "SUDDEN_OI_EXTREME")

    def notify_oi_shift_update(self, oi_shift: Dict[str, Any]) -> None:
        ev = self.oi_shift_adapter.on_oi_shift_update(oi_shift)
        if ev:
            self._record_and_dispatch(ev, "SESSION_OI_SHIFT")

    def set_spine_bias(self, bias: str) -> None:
        if bias in ("bear", "bull"):
            self.reducer.set_spine_bias(bias)

    # -------------------------------------------------------------------------
    # Canonical Ingestion Boundaries
    # -------------------------------------------------------------------------
    def ingest_live_analytics_snapshot(self, snapshot: Any) -> None:
        """Ingests the canonical periodic snapshot produced by live analytics worker."""
        if not isinstance(snapshot, (dict, Mapping)):
            return

        # 1. Option Buyer Intelligence (GEX + Sudden OI)
        obi = snapshot.get("option_buyer_intelligence")
        if isinstance(obi, (dict, Mapping)):
            opt_intel = obi.get("option_intelligence")
            if isinstance(opt_intel, (dict, Mapping)):
                gex = opt_intel.get("gex")
                if isinstance(gex, (dict, Mapping)):
                    net_gex = gex.get("total_net_gex_inr_cr")
                    if net_gex is not None:
                        self.notify_gex_update(float(net_gex))

            sudden_oi = obi.get("sudden_oi")
            if isinstance(sudden_oi, (dict, Mapping)):
                self.notify_sudden_oi(dict(sudden_oi))

        # 2. Argus (Dominance, ATM Buildup, Gamma Blast)
        coherent = snapshot.get("argus")
        if isinstance(coherent, (dict, Mapping)):
            data = coherent.get("data") if isinstance(coherent.get("data"), (dict, Mapping)) else coherent
            while isinstance(data, (dict, Mapping)) and "data" in data and isinstance(data["data"], (dict, Mapping)) and "tactical_edge" not in data:
                data = data["data"]

            # Dominance
            dom = data.get("dominance")
            if isinstance(dom, (dict, Mapping)):
                bp = dom.get("buyer_dominance_percentage")
                wp = dom.get("writer_dominance_percentage")
                if bp is not None and wp is not None:
                    self.notify_dominance_update(float(bp), float(wp))

            # Enhanced Strike Spine Focus (Argus Prime -> best_strike_stack & strike_spine)
            tactical = data.get("tactical_edge")
            prime = tactical.get("argus_prime") if isinstance(tactical, (dict, Mapping)) else None
            best_strike_stack = prime.get("best_strike_stack") if isinstance(prime, (dict, Mapping)) else None
            strike_spine = prime.get("strike_spine") if isinstance(prime, (dict, Mapping)) else None

            if isinstance(best_strike_stack, (dict, Mapping)) and (best_strike_stack.get("strike") is not None or best_strike_stack.get("strongest_structural_strike") is not None):
                self.notify_strike_spine_focus(dict(best_strike_stack), list(strike_spine or []))
            else:
                # Fallback for synthetic/legacy snapshots without Enhanced Strike Spine
                atm_window = data.get("atm_window")
                if isinstance(atm_window, list):
                    self.notify_atm_window_update(atm_window)

            if isinstance(prime, (dict, Mapping)):
                blast = prime.get("expiry_gamma_blast")
                if blast:
                    self.notify_gamma_blast(blast)

    def ingest_market_info(self, market_info: Any) -> None:
        """Ingests canonical REST MarketInfoService outputs (Max Pain + Session OI shift)."""
        if not isinstance(market_info, (dict, Mapping)):
            return

        mp = market_info.get("max_pain")
        spot = market_info.get("nifty_spot")
        if mp is not None:
            self.notify_max_pain_update(float(mp), float(spot) if spot is not None else None)

        oi_shift = market_info.get("oi_shift")
        if isinstance(oi_shift, (dict, Mapping)):
            self.notify_oi_shift_update(dict(oi_shift))

    # -------------------------------------------------------------------------
    # Lifecycle, Feed Management & Process Hygiene
    # -------------------------------------------------------------------------
    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()

        # Start background phase advancement tick thread
        self._tick_thread = threading.Thread(
            target=self._tick_loop,
            name="live-island-tick-worker",
            daemon=True,
        )
        self._tick_thread.start()
        logger.info("LiveIslandIntelligenceHub started.")

    def start_feed(self, symbols: Optional[List[str]] = None, mode: str = "full") -> bool:
        """Starts a single, dedicated Upstox V3 streaming market feed guarded by owner mutex."""
        with self._feed_owner_lock:
            if self._feed is not None and getattr(self._feed, "_is_running", False):
                logger.info("Upstox V3 feed already active; skipping duplicate feed startup.")
                if symbols and hasattr(self._feed, "subscribe"):
                    self._feed.subscribe(symbols)
                return True

            feed_symbols = symbols or [
                "NSE_INDEX|Nifty 50",
                "NSE_INDEX|India VIX",
            ]
            self._feed = UpstoxMarketDataFeedV3(
                client=self.client,
                on_tick=self.on_tick,
                subscription_mode="full" if mode not in ("full", "full_d30") else mode,
            )
            self._feed.subscribe(feed_symbols)

            def _run_feed_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._feed_loop = loop
                try:
                    loop.run_until_complete(self._feed.start())
                except Exception as exc:
                    logger.warning("Upstox V3 feed loop ended: %s", exc)
                finally:
                    loop.close()

            self._feed_thread = threading.Thread(
                target=_run_feed_loop,
                name="live-island-upstox-feed",
                daemon=True,
            )
            self._feed_thread.start()
            logger.info("Upstox V3 feed started in background thread with single owner lock.")
            return True

    def _tick_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.reducer.tick_phases()
            except Exception as exc:
                logger.error("Live Island tick error: %s", exc)
            time.sleep(1.0)

    def shutdown(self) -> None:
        """Ensures safe teardown and unregisters sockets so no orphaned processes remain."""
        if not self._is_running and not self._feed:
            return
        self._is_running = False
        self._stop_event.set()

        with self._feed_owner_lock:
            if self._feed:
                try:
                    self._feed.stop()
                    if self._feed_loop and self._feed_loop.is_running():
                        self._feed_loop.call_soon_threadsafe(self._feed_loop.stop)
                    if self._feed_thread and self._feed_thread.is_alive():
                        self._feed_thread.join(timeout=2.0)
                    logger.info("Live Island Upstox feed stopped.")
                except Exception as exc:
                    logger.warning("Error stopping Live Island Upstox feed: %s", exc)
                self._feed = None
                self._feed_loop = None
                self._feed_thread = None

        logger.info("LiveIslandIntelligenceHub shutdown cleanly completed.")

