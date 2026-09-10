"""Canonical Option Evidence Record Container for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Sequence
from src.eye.contracts import AuthorityType, ProbabilityStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.contracts import (
    OptionMarketObservation, GreekObservation, ImpliedVolatilityObservation, SetupOptionEvidenceLink
)
from src.eye.option_evidence.quote_quality import QuoteQualityMetrics
from src.eye.option_evidence.time_to_expiry import TimeToExpiryResult
from src.eye.option_evidence.moneyness import MoneynessResult
from src.eye.option_evidence.liquidity import LiquidityMetrics
from src.eye.option_evidence.alignment import AlignmentDiagnostics


@dataclass(frozen=True)
class OptionEvidenceRecord:
    schema_version: str
    evidence_id: str
    contract: OptionContractIdentity
    observation: OptionMarketObservation
    quote_quality: QuoteQualityMetrics
    time_to_expiry: TimeToExpiryResult
    moneyness: MoneynessResult
    liquidity: LiquidityMetrics
    independent_greeks: Dict[str, GreekObservation]
    independent_iv: Optional[ImpliedVolatilityObservation]
    alignment_diagnostics: Optional[AlignmentDiagnostics]
    evidence_link: Optional[SetupOptionEvidenceLink]
    evaluation_as_of: datetime
    authority: AuthorityType = AuthorityType.OBSERVATION_ONLY
    probability_status: ProbabilityStatus = ProbabilityStatus.NOT_ESTABLISHED
