"""Eye Engine Real Live Runtime State Service for Phase E5B."""

from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional, Sequence, Any, Mapping

from src.eye.contracts import EyeEventRecord, LifecycleState, InstrumentIdentity, EventDirection, PriceAtom
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector
from src.eye.composer.matcher import SetupComposer
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus

from src.eye.oracle_projection.chart_context import ChartContextManager
from src.eye.oracle_projection.contracts import EyeChartContext, ChartIdentityStatus


class EyeRuntimeState:
    """Long-lived backend runtime service owning real atomic detector & composer state."""

    _instance: Optional["EyeRuntimeState"] = None
    _global_lock = Lock()

    @classmethod
    def get_instance(cls) -> "EyeRuntimeState":
        with cls._global_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._lock = Lock()
        self._chart_mgr = ChartContextManager()

        # State per symbol
        self._bars: Dict[str, List[DetectorBar]] = {}
        self._detectors: Dict[str, Dict[str, Any]] = {}
        self._composers: Dict[str, SetupComposer] = {}

        # Latest computed structure and setup per symbol
        self._latest_structure: Dict[str, Dict[str, Any]] = {}
        self._latest_active_setup: Dict[str, Dict[str, Any]] = {}
        self._latest_targets: Dict[str, List[Dict[str, Any]]] = {}
        self._market_data_last_seen: Dict[str, str] = {}
        self._latest_event_at: Dict[str, str] = {}
        self._active_position: Optional[Dict[str, Any]] = None
        self._risk_state: Optional[Dict[str, Any]] = None
        self._latest_strategy_signals: Dict[str, Dict[str, Any]] = {}
        self._strategy_projection_revision: int = 0

    def set_active_position(self, pos_dict: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            self._active_position = pos_dict

    def set_risk_state(self, risk_dict: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            self._risk_state = risk_dict

    def set_strategy_signal(
        self,
        strategy_id: str,
        signal: Dict[str, Any],
        *,
        source_timestamp: float,
        source_revision: int,
    ) -> None:
        """Publish scanner-owned strategy state for read-only Oracle consumption."""
        with self._lock:
            self._strategy_projection_revision += 1
            self._latest_strategy_signals[str(strategy_id)] = {
                **dict(signal),
                "source_timestamp": source_timestamp,
                "source_revision": source_revision,
                "projection_revision": self._strategy_projection_revision,
            }

    def update_tradingview_context(self, symbol: str, timeframe: str, chart_state: Optional[Dict[str, Any]] = None) -> EyeChartContext:
        """Updates active TradingView context and epoch."""
        if isinstance(chart_state, Mapping):
            return self._chart_mgr.resolve_tradingview_context(chart_state)
        return self._chart_mgr.resolve_context(symbol, timeframe)

    def ingest_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: DetectorBar,
        instrument: Optional[InstrumentIdentity] = None,
    ) -> None:
        """Ingests a single canonical DetectorBar into real detectors and composer."""
        normalized_symbol = str(symbol).strip().upper()
        inst = instrument or InstrumentIdentity(
            raw_symbol=normalized_symbol,
            normalized_symbol=normalized_symbol,
            exchange="NSE",
            instrument_type="UNDERLYING_INDEX",
            underlying=normalized_symbol,
            source="DHAN",
            market="NSE",
        )

        with self._lock:
            if normalized_symbol not in self._bars:
                self._bars[normalized_symbol] = []
                self._detectors[normalized_symbol] = {
                    "swing": SwingStateDetector(),
                    "structure": StructureBreakDetector(),
                    "liquidity": LiquidityDetector(),
                    "displacement": DisplacementDetector(),
                    "fvg": FVGClusterDetector(),
                }
                self._composers[normalized_symbol] = SetupComposer(get_e3_setup_definitions())

            self._bars[normalized_symbol].append(bar)
            sub_bars = self._bars[normalized_symbol]
            bar_time = bar.expected_close_time.isoformat()
            self._market_data_last_seen[normalized_symbol] = bar_time

            ctx = DetectorContext(instrument=inst, timeframe=timeframe, as_of=bar.expected_close_time)
            detectors = self._detectors[normalized_symbol]
            composer = self._composers[normalized_symbol]

            # 1. Run atomic detectors
            new_events: List[EyeEventRecord] = []
            for d_name, detector in detectors.items():
                res = detector.detect(sub_bars, ctx)
                if res and res.records:
                    new_events.extend(res.records)

            # 2. Feed events into SetupComposer
            confirmed_candidates: List[SetupCandidateRecord] = []
            for evt in new_events:
                evt_dt = getattr(evt, "detected_at", getattr(evt, "observed_at", None))
                if evt_dt and hasattr(evt_dt, "isoformat"):
                    self._latest_event_at[normalized_symbol] = evt_dt.isoformat()
                candidates = composer.process_event(evt)
                for cand in candidates:
                    if cand.status == CandidateStatus.CONFIRMED:
                        confirmed_candidates.append(cand)

            # 3. Update structure map from latest events
            struct_dir = "UNKNOWN"
            last_bos = None
            last_choch = None
            last_sweep = None
            sl_level = None

            for evt in reversed(new_events):
                if "BOS" in evt.event_key:
                    last_bos = evt.event_key
                    struct_dir = "BULLISH" if evt.direction == EventDirection.BULLISH else "BEARISH"
                elif "CHOCH" in evt.event_key:
                    last_choch = evt.event_key
                    struct_dir = "BULLISH" if evt.direction == EventDirection.BULLISH else "BEARISH"
                elif "SWEEP" in evt.event_key:
                    last_sweep = evt.event_key
                    if evt.geometry and "extreme" in evt.geometry:
                        sl_level = evt.geometry["extreme"]

            self._latest_structure[normalized_symbol] = {
                "directional_structure": struct_dir,
                "internal_structure": f"{struct_dir}_BOS" if last_bos else "UNKNOWN",
                "last_bos": last_bos,
                "last_choch": last_choch,
                "nearest_swing_high": sub_bars[-1].high.value if sub_bars else None,
                "nearest_swing_low": sub_bars[-1].low.value if sub_bars else None,
                "last_liquidity_sweep": last_sweep,
                "structural_invalidation_level": sl_level,
                "htf_alignment_state": f"ALIGNED_{struct_dir}" if struct_dir != "UNKNOWN" else "UNKNOWN",
                "source_timeframe": timeframe,
                "is_confirmed": True,
            }

            # 4. Update active setup state
            if confirmed_candidates:
                latest_cand = confirmed_candidates[-1]
                cand_dir = latest_cand.direction.value if hasattr(latest_cand.direction, "value") else str(latest_cand.direction)
                entry_ref = sub_bars[-1].close.value if sub_bars else None
                sw_extreme = sl_level if sl_level is not None else (sub_bars[-1].low.value if cand_dir == "BULLISH" else sub_bars[-1].high.value) if sub_bars else None
                self._latest_active_setup[normalized_symbol] = {
                    "family": latest_cand.setup_family,
                    "direction": cand_dir,
                    "lifecycle": latest_cand.status.value if hasattr(latest_cand.status, "value") else str(latest_cand.status),
                    "event_key": latest_cand.record_id,
                    "setup_key": latest_cand.setup_key,
                    "fvg_low": None,
                    "fvg_high": None,
                    "sweep_extreme": sw_extreme,
                    "entry_reference": entry_ref,
                    "reclaim_price": entry_ref,
                }
            elif normalized_symbol not in self._latest_active_setup:
                self._latest_active_setup[normalized_symbol] = {
                    "family": "NO_ACTIVE_SETUP",
                    "direction": "UNKNOWN",
                    "lifecycle": "NO_ACTIVE_SETUP",
                    "event_key": None,
                }

    def get_runtime_snapshot(self, symbol: str, timeframe: str = "5m") -> Dict[str, Any]:
        """Returns real runtime state snapshot for symbol."""
        normalized_symbol = str(symbol).strip().upper()
        # Preserve a previously accepted exact-option chart selection.  Reads
        # must be side-effect free for chart identity and never turn the
        # operator's option chart into a generic underlying chart.
        ctx = self._chart_mgr.active_context(
            underlying=normalized_symbol,
            timeframe=timeframe,
        ) or self._chart_mgr.resolve_context(normalized_symbol, timeframe)

        with self._lock:
            bars = self._bars.get(normalized_symbol, [])
            last_bar = bars[-1] if bars else None

            spot = last_bar.close.value if last_bar else None
            md_time = self._market_data_last_seen.get(normalized_symbol)
            evt_time = self._latest_event_at.get(normalized_symbol, md_time)

            struct = self._latest_structure.get(
                normalized_symbol,
                {
                    "directional_structure": "UNKNOWN",
                    "internal_structure": "UNKNOWN",
                    "last_bos": None,
                    "last_choch": None,
                    "nearest_swing_high": None,
                    "nearest_swing_low": None,
                    "last_liquidity_sweep": None,
                    "structural_invalidation_level": None,
                    "htf_alignment_state": "UNKNOWN",
                    "source_timeframe": timeframe,
                    "is_confirmed": False,
                },
            )

            setup = self._latest_active_setup.get(
                normalized_symbol,
                {
                    "family": "NO_ACTIVE_SETUP",
                    "direction": "UNKNOWN",
                    "lifecycle": "NO_ACTIVE_SETUP",
                    "event_key": None,
                },
            )

            targets = []
            if struct.get("nearest_swing_high") is not None:
                targets.append({"price": float(struct["nearest_swing_high"]), "target_type": "SWING_HIGH", "timeframe": timeframe, "event_key": "EVT:TARGET:SH"})
            if struct.get("nearest_swing_low") is not None:
                targets.append({"price": float(struct["nearest_swing_low"]), "target_type": "SWING_LOW", "timeframe": timeframe, "event_key": "EVT:TARGET:SL"})

            return {
                "chart_context": ctx,
                "spot_price": spot,
                "structure": struct,
                "active_setup": setup,
                "candidate_targets": targets,
                "market_data_last_seen_utc": md_time,
                "latest_event_at_utc": evt_time,
                "active_position": self._active_position,
                "risk_state": self._risk_state,
                "strategy_signals": dict(self._latest_strategy_signals),
                "strategy_projection_revision": self._strategy_projection_revision,
            }
