"""Exact Contract History Adapter for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.quote_quality import classify_quote_quality


class ExactHistoryAdapter:
    """Parses exact contract historical candles/quotes."""

    def parse_historical_candle(
        self,
        contract: OptionContractIdentity,
        timestamp: datetime,
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        volume: Optional[int] = None,
        open_interest: Optional[int] = None,
        source: SourceType = SourceType.LOCAL_EXACT_CONTRACT_HISTORY,
    ) -> OptionMarketObservation:
        prov = SourceProvenance(
            source_type=source,
            data_classification=DataClassification.EXACT_CONTRACT_CANDLE,
            source_version="1.0.0",
            source_timestamp=timestamp,
            received_at=timestamp,
            parsed_at=timestamp,
        )

        close_atom = PriceAtom(ticks=int(round(close_p * 100)))

        obs_id = f"OBS:HIST:{contract.contract_key}:{int(timestamp.timestamp())}"

        return OptionMarketObservation(
            observation_id=obs_id,
            contract=contract,
            provenance=prov,
            observed_at=timestamp,
            available_at=timestamp,
            evaluation_as_of=timestamp,
            received_at=timestamp,
            parsed_at=timestamp,
            last_price=close_atom,
            best_bid=None,
            best_ask=None,
            volume=volume,
            open_interest=open_interest,
            quote_state=QuoteState.NO_QUOTE,
            is_fresh=True,
        )
