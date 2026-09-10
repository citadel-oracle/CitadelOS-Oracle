"""Dual-Lane Field-Level Reconciliation Engine for Eye Engine Option Capture."""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.sources import SourceProvenance, SourceType, DataClassification
from src.eye.option_capture.contracts import FeedLane, FieldRevisionRecord
from src.eye.contracts import PriceAtom


class FieldReconciler:
    def __init__(self):
        # contract_key -> field_name -> FieldRevisionRecord
        self.state: Dict[str, Dict[str, FieldRevisionRecord]] = {}

    def update_field(
        self,
        contract_key: str,
        field_name: str,
        value: Any,
        source_lane: FeedLane,
        exchange_time_utc: Optional[str],
        received_at_utc: str,
        available_at_utc: str,
        connection_epoch: int = 1,
    ) -> FieldRevisionRecord:

        """Applies field-level precedence rules, creating an updated FieldRevisionRecord."""
        if contract_key not in self.state:
            self.state[contract_key] = {}

        field_map = self.state[contract_key]
        prev_rev = field_map.get(field_name)

        # Epoch & Timestamp Precedence Rules:
        if prev_rev:
            # 1. Older connection epoch cannot overwrite newer connection epoch!
            if connection_epoch < prev_rev.connection_epoch:
                return prev_rev

            # 2. Older exchange timestamp within same epoch cannot overwrite newer exchange state!
            if connection_epoch == prev_rev.connection_epoch and exchange_time_utc and prev_rev.exchange_timestamp and exchange_time_utc < prev_rev.exchange_timestamp:
                return prev_rev

            # 3. Slow-lane chain snapshot cannot overwrite newer fast-lane quote fields!
            if prev_rev.source_lane == FeedLane.FAST_LANE_WEBSOCKET and source_lane == FeedLane.SLOW_LANE_OPTION_CHAIN:
                if field_name in ("best_bid", "best_ask", "last_price", "bid_quantity", "ask_quantity"):
                    if exchange_time_utc and prev_rev.exchange_timestamp and exchange_time_utc <= prev_rev.exchange_timestamp:
                        return prev_rev


        new_rev_num = (prev_rev.revision_number + 1) if prev_rev else 1
        rev = FieldRevisionRecord(
            contract_key=contract_key,
            field_name=field_name,
            field_value=value,
            source_lane=source_lane,
            exchange_timestamp=exchange_time_utc,
            received_at_utc=received_at_utc,
            available_at_utc=available_at_utc,
            revision_number=new_rev_num,
            connection_epoch=connection_epoch,
            validity_status="VALID",

        )
        field_map[field_name] = rev
        return rev

    def build_observation(
        self,
        obs_id: str,
        contract: OptionContractIdentity,
        provenance: SourceProvenance,
        as_of: datetime,
    ) -> OptionMarketObservation:
        """Synthesizes a canonical OptionMarketObservation from current reconciled field states."""
        fields = self.state.get(contract.contract_key, {})

        bid_val = fields.get("best_bid").field_value if "best_bid" in fields else None
        ask_val = fields.get("best_ask").field_value if "best_ask" in fields else None
        ltp_val = fields.get("last_price").field_value if "last_price" in fields else None
        vol_val = fields.get("volume").field_value if "volume" in fields else 0
        oi_val = fields.get("open_interest").field_value if "open_interest" in fields else 0
        bid_qty = fields.get("bid_quantity").field_value if "bid_quantity" in fields else 0
        ask_qty = fields.get("ask_quantity").field_value if "ask_quantity" in fields else 0

        bid = PriceAtom(ticks=int(round(bid_val * 100))) if isinstance(bid_val, (int, float)) and bid_val > 0 else None
        ask = PriceAtom(ticks=int(round(ask_val * 100))) if isinstance(ask_val, (int, float)) and ask_val > 0 else None
        ltp = PriceAtom(ticks=int(round(ltp_val * 100))) if isinstance(ltp_val, (int, float)) and ltp_val > 0 else None

        q_state = QuoteState.TWO_SIDED_VALID if (bid and ask and bid.ticks < ask.ticks) else QuoteState.ONE_SIDED_BID_ONLY if bid else QuoteState.NO_QUOTES

        return OptionMarketObservation(
            observation_id=obs_id,
            contract=contract,
            provenance=provenance,
            observed_at=as_of,
            available_at=as_of,
            evaluation_as_of=as_of,
            received_at=as_of,
            parsed_at=as_of,
            last_price=ltp,
            best_bid=bid,
            best_ask=ask,
            bid_quantity=bid_qty,
            ask_quantity=ask_qty,
            volume=vol_val,
            open_interest=oi_val,
            quote_state=q_state,
            is_fresh=True,
        )
