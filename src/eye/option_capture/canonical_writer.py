"""Deterministic Canonical Observation & Field Revision Writer for Eye Engine Option Capture."""

import json
from pathlib import Path
from dataclasses import asdict, is_dataclass
from typing import Dict, Any

from src.eye.option_evidence.contracts import OptionMarketObservation
from src.eye.option_capture.contracts import FieldRevisionRecord


def serialize_dataclass(obj: Any) -> Any:
    """Helper to convert dataclass instances and datetime/enum objects into JSON-serializable dicts."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    if is_dataclass(obj):
        res = {}
        for k, v in asdict(obj).items():
            res[k] = serialize_dataclass(v)
        return res
    if isinstance(obj, dict):
        return {k: serialize_dataclass(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_dataclass(v) for v in obj]
    return obj


class CanonicalWriter:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.obs_file = self.session_dir / "option_observations.jsonl"
        self.field_file = self.session_dir / "field_revisions.jsonl"
        self.underlying_file = self.session_dir / "underlying_observations.jsonl"

        self.observation_count = 0
        self.field_revision_count = 0
        self.underlying_count = 0


    def write_observation(self, obs: OptionMarketObservation) -> None:
        """Writes a canonical OptionMarketObservation to jsonl."""
        self.observation_count += 1
        data = {
            "observation_id": obs.observation_id,
            "contract_key": obs.contract.contract_key,
            "observed_at": obs.observed_at.isoformat(),
            "available_at": obs.available_at.isoformat(),
            "last_price": obs.last_price.ticks / 100.0 if obs.last_price else None,
            "best_bid": obs.best_bid.ticks / 100.0 if obs.best_bid else None,
            "best_ask": obs.best_ask.ticks / 100.0 if obs.best_ask else None,
            "quote_state": obs.quote_state.value,
            "is_fresh": obs.is_fresh,
        }
        with open(self.obs_file, "a") as f:
            f.write(json.dumps(data) + "\n")

    def write_field_revision(self, rev: FieldRevisionRecord) -> None:
        """Writes a field revision record to jsonl."""
        self.field_revision_count += 1
        data = {
            "contract_key": rev.contract_key,
            "field_name": rev.field_name,
            "field_value": rev.field_value,
            "source_lane": rev.source_lane.value,
            "exchange_timestamp": rev.exchange_timestamp,
            "received_at_utc": rev.received_at_utc,
            "available_at_utc": rev.available_at_utc,
            "revision_number": rev.revision_number,
            "validity_status": rev.validity_status,
        }
        with open(self.field_file, "a") as f:
            f.write(json.dumps(data) + "\n")

    def write_underlying_observation(self, underlying_data: Dict[str, Any]) -> None:
        """Writes a synchronized underlying observation record."""
        self.underlying_count += 1
        with open(self.underlying_file, "a") as f:
            f.write(json.dumps(underlying_data) + "\n")

