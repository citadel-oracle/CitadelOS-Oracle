"""Slow Lane Option-Chain Adapter for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance
from src.eye.option_evidence.contracts import (
    OptionMarketObservation, ImpliedVolatilityObservation, GreekObservation, GreekType, GreekSource, PriceReference, QuoteState
)
from src.eye.option_evidence.quote_quality import classify_quote_quality


class SlowChainLaneAdapter:
    """Parses and ingests slow option-chain snapshots from Dhan / NSE API."""

    def parse_chain_snapshot(
        self,
        raw_snapshot: Dict[str, Any],
        contract_lookup: Any,
        observation_time: datetime,
        evaluation_time: datetime,
    ) -> List[OptionMarketObservation]:
        observations = []
        chain_data = raw_snapshot.get("data", {})
        strike_list = chain_data.get("oc", {}) or chain_data.get("strikes", {})

        prov = SourceProvenance(
            source_type=SourceType.DHAN_OPTION_CHAIN,
            data_classification=DataClassification.OPTION_CHAIN_SNAPSHOT,
            source_version="2.0.0",
            source_sequence=raw_snapshot.get("sequence"),
            source_timestamp=observation_time,
            received_at=observation_time,
            parsed_at=evaluation_time,
            raw_fingerprint=str(raw_snapshot.get("hash", "")),
        )

        for strike_key, leg_data in strike_list.items():
            for opt_type in ("ce", "pe"):
                opt_info = leg_data.get(opt_type)
                if not opt_info:
                    continue

                sec_id = str(opt_info.get("security_id") or opt_info.get("securityId", ""))
                cid = contract_lookup.get_by_security_id(sec_id)
                if not cid:
                    continue

                # Parse prices
                ltp = opt_info.get("last_price") or opt_info.get("ltp")
                last_atom = PriceAtom(ticks=int(round(float(ltp) * 100))) if ltp is not None else None

                bid = opt_info.get("top_bid_price") or opt_info.get("bid")
                bid_atom = PriceAtom(ticks=int(round(float(bid) * 100))) if bid is not None else None

                ask = opt_info.get("top_ask_price") or opt_info.get("ask")
                ask_atom = PriceAtom(ticks=int(round(float(ask) * 100))) if ask is not None else None

                bid_qty = opt_info.get("top_bid_quantity") or opt_info.get("bid_qty")
                ask_qty = opt_info.get("top_ask_quantity") or opt_info.get("ask_qty")

                oi = opt_info.get("oi") or opt_info.get("open_interest")
                prev_oi = opt_info.get("previous_oi") or opt_info.get("prev_open_interest")
                vol = opt_info.get("volume")

                # Parse vendor IV
                vendor_iv_val = opt_info.get("implied_volatility") or opt_info.get("iv")
                vendor_iv_obs = None
                if vendor_iv_val is not None and float(vendor_iv_val) > 0:
                    vendor_iv_obs = ImpliedVolatilityObservation(
                        contract_key=cid.contract_key,
                        source=SourceType.DHAN_OPTION_CHAIN,
                        value=float(vendor_iv_val),
                        unit="PERCENTAGE",
                        price_reference=PriceReference.MIDPOINT,
                        calculated_at=observation_time,
                        available_at=observation_time,
                    )

                # Parse vendor Greeks if present
                vendor_greeks = []
                for g_type in (GreekType.DELTA, GreekType.GAMMA, GreekType.THETA, GreekType.VEGA):
                    g_val = opt_info.get(g_type.value.lower())
                    if g_val is not None:
                        vendor_greeks.append(GreekObservation(
                            contract_key=cid.contract_key,
                            greek_type=g_type,
                            value=float(g_val),
                            unit="VENDOR",
                            source=GreekSource.VENDOR,
                            calculated_at=observation_time,
                            available_at=observation_time,
                        ))

                metrics = classify_quote_quality(bid_atom, ask_atom, bid_qty, ask_qty, last_atom, observation_time, evaluation_time)

                obs_id = f"OBS:CHAIN:{cid.contract_key}:{prov.source_sequence or int(observation_time.timestamp())}"

                obs = OptionMarketObservation(
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
                    previous_open_interest=prev_oi,
                    vendor_iv=vendor_iv_obs,
                    vendor_greeks=tuple(vendor_greeks),
                    quote_state=metrics.quote_state,
                    is_fresh=(metrics.quote_state != QuoteState.STALE_TWO_SIDED),
                )
                observations.append(obs)

        return observations
