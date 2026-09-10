"""Fast Lane Market Quote Adapter for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.quote_quality import classify_quote_quality


class FastQuoteLaneAdapter:
    """Parses and ingests fast market quote / tick packets from Dhan WebSocket or REST Market Quote."""

    def parse_market_quote(
        self,
        raw_quote: Dict[str, Any],
        contract_lookup: Any,
        observation_time: datetime,
        evaluation_time: datetime,
    ) -> Optional[OptionMarketObservation]:
        sec_id = str(raw_quote.get("security_id") or raw_quote.get("securityId", ""))
        cid = contract_lookup.get_by_security_id(sec_id)
        if not cid:
            return None

        prov = SourceProvenance(
            source_type=SourceType.DHAN_MARKET_QUOTE,
            data_classification=DataClassification.EXACT_CONTRACT_QUOTE,
            source_version="2.0.0",
            source_sequence=raw_quote.get("sequence"),
            source_timestamp=observation_time,
            received_at=observation_time,
            parsed_at=evaluation_time,
            raw_fingerprint=str(raw_quote.get("hash", "")),
        )

        ltp = raw_quote.get("last_price") or raw_quote.get("ltp")
        last_atom = PriceAtom(ticks=int(round(float(ltp) * 100))) if ltp is not None else None

        bid = raw_quote.get("best_bid") or raw_quote.get("bid")
        bid_atom = PriceAtom(ticks=int(round(float(bid) * 100))) if bid is not None else None

        ask = raw_quote.get("best_ask") or raw_quote.get("ask")
        ask_atom = PriceAtom(ticks=int(round(float(ask) * 100))) if ask is not None else None

        bid_qty = raw_quote.get("bid_quantity") or raw_quote.get("bid_qty")
        ask_qty = raw_quote.get("ask_quantity") or raw_quote.get("ask_qty")
        vol = raw_quote.get("volume")
        oi = raw_quote.get("oi") or raw_quote.get("open_interest")

        metrics = classify_quote_quality(bid_atom, ask_atom, bid_qty, ask_qty, last_atom, observation_time, evaluation_time)

        obs_id = f"OBS:QUOTE:{cid.contract_key}:{prov.source_sequence or int(observation_time.timestamp())}"

        return OptionMarketObservation(
            observation_id=obs_id,
            contract=cid,
            provenance=prov,
            observed_at=observation_time,
            available_at=observation_time,
            evaluation_as_of=evaluation_time,
            received_at=observation_time,
            parsed_at=evaluation_time,
            last_price=last_atom,
            best_bid=bid_atom,
            best_ask=ask_atom,
            bid_quantity=bid_qty,
            ask_quantity=ask_qty,
            volume=vol,
            open_interest=oi,
            quote_state=metrics.quote_state,
            is_fresh=(metrics.quote_state != QuoteState.STALE_TWO_SIDED),
        )
