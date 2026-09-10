"""Capture Configuration Specification for Eye Engine Option Capture."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptureConfig:
    underlying_symbol: str = "NIFTY"
    exchange: str = "NSE"
    strike_interval_count: int = 10
    horizon_days: int = 30
    chain_cadence_seconds: float = 15.0
    checkpoint_interval_seconds: float = 60.0
    storage_root: Path = Path("/Users/ayushmudgal/Documents/trading/citadel_quant_engine/data/eye_option_capture/")
    authority: str = "READ_ONLY_OBSERVATION"
    execution_authority: bool = False

    def validate(self) -> None:
        assert self.execution_authority is False, "EXECUTION_AUTHORITY_MUST_BE_FALSE"
        assert self.authority == "READ_ONLY_OBSERVATION", "AUTHORITY_MUST_BE_READ_ONLY_OBSERVATION"
        assert self.underlying_symbol == "NIFTY", "ONLY_NIFTY_SUPPORTED_IN_PILOT"
