"""
Full 44-Strategy Research Archetype Registry Specification (22 CALL + 22 PUT).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class StrategyArchetypeSpec:
    strategy_id: str
    hypothesis: str
    side: str  # CALL | PUT
    market_regime: str
    primary_trigger: str
    independent_confirmations: Sequence[str]
    disqualifiers: Sequence[str]
    required_features: Sequence[str]
    optional_features: Sequence[str]
    entry_lifecycle: str
    contract_selection_policy: str
    invalidation: str
    exit_hypothesis: str
    strictness: str  # Loose | Moderate | Strict | Ultra-strict | Specialist
    prime_dependency: str  # Prime-independent | Prime-assisted | Prime-required
    expected_frequency: str
    known_failure_mode: str
    forward_labels: Sequence[str]
    null_hypothesis: str
    implementation_status: str = "SPECIFIED"
    activation_classification: str = "SHADOW_EVALUABLE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "hypothesis": self.hypothesis,
            "side": self.side,
            "market_regime": self.market_regime,
            "primary_trigger": self.primary_trigger,
            "independent_confirmations": list(self.independent_confirmations),
            "disqualifiers": list(self.disqualifiers),
            "required_features": list(self.required_features),
            "optional_features": list(self.optional_features),
            "entry_lifecycle": self.entry_lifecycle,
            "contract_selection_policy": self.contract_selection_policy,
            "invalidation": self.invalidation,
            "exit_hypothesis": self.exit_hypothesis,
            "strictness": self.strictness,
            "prime_dependency": self.prime_dependency,
            "expected_frequency": self.expected_frequency,
            "known_failure_mode": self.known_failure_mode,
            "forward_labels": list(self.forward_labels),
            "null_hypothesis": self.null_hypothesis,
            "implementation_status": self.implementation_status,
            "activation_classification": self.activation_classification,
        }


CALL_ARCHETYPES_DEFINITIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("STRAT_C01_PREM_BO_PERSISTENCE", "Premium Breakout Persistence", "EXPANSION", "Premium VWAP breakout", "Loose"),
    ("STRAT_C02_PREM_RECLAIM", "Premium Reclaim key level", "CONTINUATION", "Reclaim ₹50 level", "Loose"),
    ("STRAT_C03_CROSS_SIDE_PREM_ACCEL", "Cross-Side Premium Acceleration", "EXPANSION", "CE velocity acceleration", "Moderate"),
    ("STRAT_C04_LEAD_ALIGNMENT", "Spot-Futures-Option Lead Alignment", "BUYER_DOMINANT", "Tri-lead alignment", "Moderate"),
    ("STRAT_C05_PCR_ACCEL_CONFIRMED", "PCR Acceleration Confirmed", "BUYER_DOMINANT", "PCR velocity acceleration", "Moderate"),
    ("STRAT_C06_OI_BUILD_UNWIND", "OI Build/Unwind Confirmed", "CONTINUATION", "Short covering / Long build", "Moderate"),
    ("STRAT_C07_VOB_FIRST_BREAK", "VOB First Break", "EXPANSION", "VOB structure first break", "Strict"),
    ("STRAT_C08_SAE_LIQUID_STRIKE", "SAE Liquid-Strike Momentum", "EXPANSION", "SAE rank 1 momentum", "Moderate"),
    ("STRAT_C09_VOB_BREAK_RETEST", "VOB Break-Retest Continuation", "CONTINUATION", "VOB retest confirmation", "Strict"),
    ("STRAT_C10_PRESSURE_BREADTH", "Pressure-Breadth Persistence", "BUYER_DOMINANT", "Pressure > 70 & Breadth > 70", "Moderate"),
    ("STRAT_C11_PRESSURE_DIVERGENCE", "Pressure-Breadth Divergence Reversal", "REVERSAL", "Pressure divergence", "Specialist"),
    ("STRAT_C12_CONTINUATION_SELECTOR", "Continuation-vs-Reversal Selector", "MIXED", "Regime transition trigger", "Strict"),
    ("STRAT_C13_ENTRY_SPINE_PULLBACK", "Entry-Spine Pullback", "CONTINUATION", "Spine zone pullback touch", "Moderate"),
    ("STRAT_C14_BLAST_INTEGRITY", "Blast Integrity Continuation", "EXPANSION", "Blast integrity > 80", "Strict"),
    ("STRAT_C15_MELT_AVOIDANCE_REENTRY", "Melt-Risk Avoidance Re-entry", "COMPRESSION", "Melt decay index drop", "Specialist"),
    ("STRAT_C16_PRE_REGIME_TRANSITION", "PRE Regime Transition", "EXPANSION", "PRE transition to EXPANSION", "Moderate"),
    ("STRAT_C17_PRE_REGIME_CONTINUATION", "PRE Regime Continuation", "BUYER_DOMINANT", "PRE established expansion", "Strict"),
    ("STRAT_C18_PLI_STRADDLE_EXPANSION", "PLI Straddle Expansion + CE Lead", "EXPANSION", "Straddle velocity > 0 & CE lead", "Moderate"),
    ("STRAT_C19_PLI_STRADDLE_COMPRESSION", "PLI Straddle Compression Release", "EXPANSION", "Straddle compression break", "Specialist"),
    ("STRAT_C20_SME_MIGRATION_CONTINUATION", "SME Strike Migration Continuation", "BUYER_DOMINANT", "SME upward migration", "Strict"),
    ("STRAT_C21_SME_FAILED_MIGRATION_REVERSAL", "SME Failed Migration Reversal", "REVERSAL", "SME migration failure", "Specialist"),
    ("STRAT_C22_DGP_GAMMA_ESCAPE_COMPOSITE", "DGP Gamma Escape Composite", "EXPANSION", "DGP pin escape & SAE rank 1", "Ultra-strict"),
)


def _build_full_44_archetypes() -> list[StrategyArchetypeSpec]:
    archetypes: list[StrategyArchetypeSpec] = []

    apex_mapped_ids = {
        "STRAT_C01_PREM_BO_PERSISTENCE": "ARGUS_APEX_C1_SIMPLE",
        "STRAT_C07_VOB_FIRST_BREAK": "ARGUS_APEX_C2_BALANCED",
        "STRAT_C09_VOB_BREAK_RETEST": "ARGUS_APEX_C3_STRICT",
        "STRAT_C03_CROSS_SIDE_PREM_ACCEL": "ARGUS_APEX_C4_BIG_MOVE_ESCAPE",
        "STRAT_C11_PRESSURE_DIVERGENCE": "ARGUS_APEX_C5_WALL_REVERSAL",
        "STRAT_P01_PREM_BO_PERSISTENCE": "ARGUS_APEX_P1_SIMPLE",
        "STRAT_P07_VOB_FIRST_BREAK": "ARGUS_APEX_P2_BALANCED",
        "STRAT_P09_VOB_BREAK_RETEST": "ARGUS_APEX_P3_STRICT",
        "STRAT_P03_CROSS_SIDE_PREM_ACCEL": "ARGUS_APEX_P4_BIG_MOVE_ESCAPE",
        "STRAT_P11_PRESSURE_DIVERGENCE": "ARGUS_APEX_P5_WALL_REVERSAL",
    }

    # Build 22 CALL archetypes
    for strat_id, hypothesis, regime, trigger, strictness in CALL_ARCHETYPES_DEFINITIONS:
        prime_dep = "Prime-independent" if strictness == "Loose" else ("Prime-required" if strictness in ("Strict", "Ultra-strict") else "Prime-assisted")
        status = "IMPLEMENTED" if strat_id in apex_mapped_ids else "SPECIFIED"
        classif = "RUNTIME_WIRED" if status == "IMPLEMENTED" else "SHADOW_EVALUABLE"
        archetypes.append(
            StrategyArchetypeSpec(
                strategy_id=strat_id,
                hypothesis=f"CALL: {hypothesis}",
                side="CALL",
                market_regime=regime,
                primary_trigger=trigger,
                independent_confirmations=("spot.velocity.5m", "option.premium_velocity.5m"),
                disqualifiers=("market.melt_decay_index > 75", "liquidity == POOR"),
                required_features=("spot.return.5m", "option.premium_return.5m"),
                optional_features=("market.pcr_level.5m", "strike.sae_rank.5m"),
                entry_lifecycle="Touch → Retest → Entry",
                contract_selection_policy="ATM 0-offset Call",
                invalidation="Underlying 15-point reversal",
                exit_hypothesis="Target 1 (+20% premium) or Time Exit (30m)",
                strictness=strictness,
                prime_dependency=prime_dep,
                expected_frequency="1-5 per day",
                known_failure_mode="Choppy sideways regime melt",
                forward_labels=("MFE_15m", "MAE_15m", "TargetFirstProb"),
                null_hypothesis="Call premium returns have zero predictive edge over random walks",
                implementation_status=status,
                activation_classification=classif,
            )
        )

    # Build 22 PUT mirrored archetypes
    for strat_id, hypothesis, regime, trigger, strictness in CALL_ARCHETYPES_DEFINITIONS:
        put_strat_id = strat_id.replace("STRAT_C", "STRAT_P")
        put_hypothesis = hypothesis.replace("CE", "PE").replace("CALL", "PUT")
        put_trigger = trigger.replace("CE", "PE").replace("upward", "downward")
        prime_dep = "Prime-independent" if strictness == "Loose" else ("Prime-required" if strictness in ("Strict", "Ultra-strict") else "Prime-assisted")
        status = "IMPLEMENTED" if put_strat_id in apex_mapped_ids else "SPECIFIED"
        classif = "RUNTIME_WIRED" if status == "IMPLEMENTED" else "SHADOW_EVALUABLE"

        archetypes.append(
            StrategyArchetypeSpec(
                strategy_id=put_strat_id,
                hypothesis=f"PUT: {put_hypothesis}",
                side="PUT",
                market_regime=regime,
                primary_trigger=put_trigger,
                independent_confirmations=("spot.velocity.5m", "option.premium_velocity.5m"),
                disqualifiers=("market.melt_decay_index > 75", "liquidity == POOR"),
                required_features=("spot.return.5m", "option.premium_return.5m"),
                optional_features=("market.pcr_level.5m", "strike.sae_rank.5m"),
                entry_lifecycle="Touch → Retest → Entry",
                contract_selection_policy="ATM 0-offset Put",
                invalidation="Underlying 15-point reversal",
                exit_hypothesis="Target 1 (+20% premium) or Time Exit (30m)",
                strictness=strictness,
                prime_dependency=prime_dep,
                expected_frequency="1-5 per day",
                known_failure_mode="Choppy sideways regime melt",
                forward_labels=("MFE_15m", "MAE_15m", "TargetFirstProb"),
                null_hypothesis="Put premium returns have zero predictive edge over random walks",
                implementation_status=status,
                activation_classification=classif,
            )
        )

        archetypes.append(
            StrategyArchetypeSpec(
                strategy_id=put_strat_id,
                hypothesis=f"PUT: {put_hypothesis}",
                side="PUT",
                market_regime=regime,
                primary_trigger=put_trigger,
                independent_confirmations=("spot.velocity.5m", "option.premium_velocity.5m"),
                disqualifiers=("market.melt_decay_index > 75", "liquidity == POOR"),
                required_features=("spot.return.5m", "option.premium_return.5m"),
                optional_features=("market.pcr_level.5m", "strike.sae_rank.5m"),
                entry_lifecycle="Touch → Retest → Entry",
                contract_selection_policy="ATM 0-offset Put",
                invalidation="Underlying 15-point reversal",
                exit_hypothesis="Target 1 (+20% premium) or Time Exit (30m)",
                strictness=strictness,
                prime_dependency=prime_dep,
                expected_frequency="1-5 per day",
                known_failure_mode="Choppy sideways regime melt",
                forward_labels=("MFE_15m", "MAE_15m", "TargetFirstProb"),
                null_hypothesis="Put premium returns have zero predictive edge over random walks",
                implementation_status=status,
                activation_classification=classif,
            )
        )

    return archetypes


class StrategyArchetypeRegistry:
    def __init__(self):
        self._archetypes = {a.strategy_id: a for a in _build_full_44_archetypes()}

    def get(self, strategy_id: str) -> Optional[StrategyArchetypeSpec]:
        return self._archetypes.get(strategy_id)

    def list_all(self) -> list[StrategyArchetypeSpec]:
        return list(self._archetypes.values())

    def export_universe_artifact(self, output_path: str = "artifacts/canonical_foundation/strategy_universe_44.json") -> dict[str, Any]:
        specs = self.list_all()
        artifact = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_universe_count": 44,
            "call_archetypes_count": len([s for s in specs if s.side == "CALL"]),
            "put_archetypes_count": len([s for s in specs if s.side == "PUT"]),
            "implemented_count": len([s for s in specs if s.implementation_status == "IMPLEMENTED"]),
            "specified_count": len([s for s in specs if s.implementation_status == "SPECIFIED"]),
            "archetypes": [s.to_dict() for s in specs],
            "execution_influence": "ZERO",
        }
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w") as f:
            json.dump(artifact, f, indent=2)
        return artifact

    def export_truth_matrix_artifact(self, output_path: str = "artifacts/independent_verification/strategy_44_truth_matrix.json") -> dict[str, Any]:
        specs = self.list_all()
        artifact = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_universe_count": 44,
            "runtime_wired_count": len([s for s in specs if s.activation_classification == "RUNTIME_WIRED"]),
            "shadow_evaluable_count": len([s for s in specs if s.activation_classification == "SHADOW_EVALUABLE"]),
            "spec_only_count": 0,
            "truth_matrix": [s.to_dict() for s in specs],
            "execution_influence": "ZERO",
        }
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w") as f:
            json.dump(artifact, f, indent=2)
        return artifact
