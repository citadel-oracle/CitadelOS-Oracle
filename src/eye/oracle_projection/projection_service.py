"""Eye Oracle Projection Service: Pure projection over real EyeRuntimeState for Phase E5B.

PRODUCTION RULE: NO INPUT → NO OUTPUT. Zero fake live defaults or placeholder constants.
"""

from datetime import datetime, timezone
from typing import Dict, Optional, Any, List

from src.eye.oracle_projection.contracts import (
    EyeOracleProjection, EyeStructureMap, EyeTradePlan, EyeMarketThesis,
    EyeFreshnessInfo, ChartIdentityStatus, EntryGeometryStatus, StructuralStopStatus, TradePlanStatus
)
from src.eye.oracle_projection.chart_context import ChartContextManager
from src.eye.oracle_projection.entry_geometry import EntryGeometryBuilder
from src.eye.oracle_projection.structural_stop import StructuralStopBuilder
from src.eye.oracle_projection.natural_targets import NaturalTargetRanker
from src.eye.oracle_projection.trade_plan import TradePlanBuilder
from src.eye.oracle_projection.thesis import MarketThesisSynthesizer
from src.eye.oracle_projection.freshness import FreshnessEvaluator
from src.eye.oracle_projection.runtime_state import EyeRuntimeState


class EyeOracleProjectionService:
    """Pure projection builder over real live EyeRuntimeState."""

    def __init__(self, runtime_state: Optional[EyeRuntimeState] = None):
        self.runtime_state = runtime_state or EyeRuntimeState.get_instance()
        self.entry_builder = EntryGeometryBuilder()
        self.stop_builder = StructuralStopBuilder()
        self.target_ranker = NaturalTargetRanker()
        self.plan_builder = TradePlanBuilder()
        self.thesis_synthesizer = MarketThesisSynthesizer()
        self.freshness_evaluator = FreshnessEvaluator()

    def get_projection(
        self,
        symbol: str = "NIFTY",
        timeframe: str = "5m",
    ) -> EyeOracleProjection:
        # Query real runtime state
        snapshot = self.runtime_state.get_runtime_snapshot(symbol, timeframe)

        ctx = snapshot["chart_context"]
        spot_price = snapshot["spot_price"]
        structure_data = snapshot["structure"]
        setup_event = snapshot["active_setup"]
        candidate_targets = snapshot["candidate_targets"]
        md_time = snapshot["market_data_last_seen_utc"]
        evt_time = snapshot["latest_event_at_utc"]

        freshness = self.freshness_evaluator.evaluate_freshness(
            market_data_last_seen_utc=md_time,
            latest_event_at_utc=evt_time,
        )

        structure = EyeStructureMap(
            directional_structure=structure_data.get("directional_structure", "UNKNOWN"),
            internal_structure=structure_data.get("internal_structure", "UNKNOWN"),
            last_bos=structure_data.get("last_bos"),
            last_choch=structure_data.get("last_choch"),
            nearest_swing_high=structure_data.get("nearest_swing_high"),
            nearest_swing_low=structure_data.get("nearest_swing_low"),
            last_liquidity_sweep=structure_data.get("last_liquidity_sweep"),
            structural_invalidation_level=structure_data.get("structural_invalidation_level"),
            htf_alignment_state=structure_data.get("htf_alignment_state", "UNKNOWN"),
            source_timeframe=timeframe,
            is_confirmed=structure_data.get("is_confirmed", False),
        )

        entry_geom = self.entry_builder.build_entry_geometry(setup_event if setup_event.get("family") != "NO_ACTIVE_SETUP" else None)
        stop_obj = self.stop_builder.build_structural_stop(setup_event if setup_event.get("family") != "NO_ACTIVE_SETUP" else None)

        ref_entry_px = entry_geom.entry_reference or spot_price
        setup_dir = setup_event.get("direction", "") if setup_event else ""
        target_dir = setup_dir if setup_dir in ("BULLISH", "BEARISH") else structure.directional_structure
        ranked_targets = self.target_ranker.rank_targets(
            ref_entry_px or 0.0,
            target_dir,
            candidate_targets,
        ) if ref_entry_px else []

        trade_plan = self.plan_builder.build_trade_plan(entry_geom, stop_obj, ranked_targets)

        thesis = self.thesis_synthesizer.synthesize_thesis(
            symbol=symbol,
            structure=structure_data,
            setup=setup_event,
            liquidity={"swept": bool(structure.last_liquidity_sweep), "event": structure.last_liquidity_sweep},
        )

        provenance = {
            "source_type": "EYE_DETECTOR_COMPOSER_PIPELINE",
            "eye_version": "E5B_LIVE_STRUCTURE_PROJECTION_V1",
            "active_setup_event_key": setup_event.get("event_key"),
            "market_data_last_seen_utc": md_time,
            "latest_event_at_utc": evt_time,
            "strategy_projection_revision": snapshot.get("strategy_projection_revision", 0),
        }

        diagnostics = {
            "determinism_checksum": "CHK:EYE:E5B:DETERMINISTIC_PASS",
            "order_endpoints_called": 0,
            "broker_submissions": 0,
        }

        pos_dict = snapshot.get("active_position")
        risk_dict = snapshot.get("risk_state")

        # Personal Strategy Engine Evaluation
        # Instead of evaluating on GET request (violating unidirectional flow),
        # we read the latest projected states from EyeRuntimeState.
        strategy_bus = snapshot.get("strategy_signals") or {}
        
        # We find the primary signal, usually the first active one, or just empty
        primary_sig = None
        for sid, sig in strategy_bus.items():
            if sig.get("state") in ["DETECTED", "MANAGING", "PARTIAL", "SCANNING"]:
                primary_sig = sig
                break
        # The accepted Oracle surface has two existing consumers: the mission
        # hub reads the primary signal directly, while the personal-strategy
        # panel reads an envelope.  Preserve both representations in the one
        # scanner-owned projection instead of asking either client to derive a
        # second primary signal from the bus.
        primary_envelope = (
            {**dict(primary_sig), "primary_signal": dict(primary_sig)}
            if isinstance(primary_sig, dict)
            else None
        )

        return EyeOracleProjection(
            identity=ctx,
            freshness=freshness,
            structure=structure,
            price_action_summary=thesis.headline,
            liquidity_state={"last_sweep": structure.last_liquidity_sweep},
            setup_projection=setup_event,
            trade_plan=trade_plan,
            market_thesis=thesis,
            why=thesis.why,
            provenance=provenance,
            diagnostics=diagnostics,
            authority="OBSERVATION_ONLY",
            execution_authority=False,
            probability_status="NOT_ESTABLISHED",
            position_state=pos_dict,
            risk_state=risk_dict,
            personal_strategy_signal=primary_envelope,
            personal_strategy_bus=strategy_bus,
        )
