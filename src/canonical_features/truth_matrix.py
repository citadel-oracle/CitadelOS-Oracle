"""
Engine Input Truth Matrix Generator.
Classifies all engine inputs into REAL_LIVE, REAL_HISTORICAL, DERIVED_REPRODUCIBLE, PARTIAL, NOT_AVAILABLE, UNSUPPORTED.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def generate_engine_input_truth_matrix(output_path: str = "artifacts/engine_closure/engine_input_truth_matrix.json") -> dict[str, Any]:
    matrix = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_inputs_audited": 19,
        "input_classifications": [
            {
                "canonical_name": "spot.return.5m",
                "engine": "PRE / PLI",
                "classification": "REAL_LIVE",
                "source": "DHAN_SPOT_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_NEUTRAL_0_0",
            },
            {
                "canonical_name": "spot.velocity.5m",
                "engine": "PRE / PLI",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "spot.return.5m first derivative",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "spot.acceleration.5m",
                "engine": "PRE / PLI",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "spot.velocity.5m second derivative",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "option.premium_return.5m",
                "engine": "PLI",
                "classification": "REAL_LIVE",
                "source": "DHAN_OPTIONS_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "FLAG_NO_DATA",
            },
            {
                "canonical_name": "option.premium_velocity.5m",
                "engine": "PLI",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "option.premium_return.5m first derivative",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "option.premium_acceleration.5m",
                "engine": "PLI",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "option.premium_velocity.5m second derivative",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "option.straddle_price.5m",
                "engine": "PLI_STRADDLE",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "ATM_CE_premium + ATM_PE_premium",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "FLAG_NO_DATA",
            },
            {
                "canonical_name": "option.straddle_velocity.5m",
                "engine": "PLI_STRADDLE",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "straddle_price first derivative",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "option.straddle_acceleration.5m",
                "engine": "PLI_STRADDLE",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "straddle_velocity second derivative",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "market.pcr_level.5m",
                "engine": "ARGUS",
                "classification": "REAL_LIVE",
                "source": "DHAN_CHAIN_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_NEUTRAL_1_0",
            },
            {
                "canonical_name": "market.pcr_change.5m",
                "engine": "ARGUS",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "pcr_level 5m delta",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_0_0",
            },
            {
                "canonical_name": "market.pressure.5m",
                "engine": "ARGUS",
                "classification": "REAL_LIVE",
                "source": "DHAN_TICK_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_50_0",
            },
            {
                "canonical_name": "market.breadth.5m",
                "engine": "ARGUS",
                "classification": "REAL_LIVE",
                "source": "DHAN_INDICES_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_50_0",
            },
            {
                "canonical_name": "market.persistence.5m",
                "engine": "ARGUS",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "trend duration score",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_50_0",
            },
            {
                "canonical_name": "market.vob_lifecycle.5m",
                "engine": "VOB",
                "classification": "REAL_LIVE",
                "source": "DHAN_SPOT_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "BALANCED",
            },
            {
                "canonical_name": "market.ose_score.5m",
                "engine": "OSE",
                "classification": "REAL_LIVE",
                "source": "DHAN_CHAIN_5M",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "DEFAULT_50_0",
            },
            {
                "canonical_name": "strike.sae_rank.5m",
                "engine": "SAE",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "SAE StrikeAttentionEngine",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "ATM_DEFAULT",
            },
            {
                "canonical_name": "strike.sme_velocity.5m",
                "engine": "SME",
                "classification": "DERIVED_REPRODUCIBLE",
                "source": "SME StrikeMigrationEngine",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "STATIONARY_0_0",
            },
            {
                "canonical_name": "gamma.dgp_proxy.5m",
                "engine": "DGP",
                "classification": "PARTIAL",
                "source": "DGP DealerGammaPressureProxy (Inferred)",
                "stale_threshold": 300.0,
                "missing_data_behaviour": "INFERRED_MIXED",
            },
        ],
        "execution_influence": "ZERO",
    }
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(matrix, f, indent=2)
    return matrix
