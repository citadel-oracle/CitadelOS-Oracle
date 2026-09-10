"""
Trial Registry for Backtest Trials & Walk-Forward Evaluations.

Records every backtest trial (strategy ID, variant, commit, parameters, dataset, fold, metrics) append-only.
EXECUTION INFLUENCE: ZERO.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    strategy_id: str
    code_commit: str
    feature_version: str
    parameter_hash: str
    dataset_hash: str
    instrument: str
    date_range: str
    fold: str
    cost_model: str
    result_state: str  # VALIDATION_READY | INSUFFICIENT_SAMPLE | NEGATIVE_EXPECTANCY | UNSTABLE_ACROSS_FOLDS | OOS_VALIDATED
    trades_count: int
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    timestamp: str


class TrialRegistry:
    """Manages trial records for quant validation trials."""

    def __init__(self, registry_file: str = "logs/quant_validation/trial_registry.jsonl"):
        self.registry_path = Path(registry_file)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    def register_trial(self, record: TrialRecord) -> Dict[str, Any]:
        data = asdict(record)
        with open(self.registry_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        return data

    def list_trials(self, strategy_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        trials = []
        with open(self.registry_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if strategy_id is None or item.get("strategy_id") == strategy_id:
                        trials.append(item)
        return trials

    def export_summary_artifact(self, output_path: str = "artifacts/runtime_quant_leap/trial_registry_summary.json") -> Dict[str, Any]:
        trials = self.list_trials()
        artifact = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_trials_recorded": len(trials),
            "trials": trials,
            "execution_influence": "ZERO",
        }
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w") as f:
            json.dump(artifact, f, indent=2)
        return artifact
