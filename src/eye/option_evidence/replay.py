"""Deterministic Offline Replay Engine for Eye Engine Phase E4A."""

from datetime import datetime
from typing import List, Dict, Tuple, Optional
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus
from src.eye.option_evidence.contracts import (
    OptionMarketObservation, SetupOptionEvidenceLink, GreekObservation, ImpliedVolatilityObservation, GreekType, GreekSource, PriceReference
)
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.quote_quality import classify_quote_quality
from src.eye.option_evidence.time_to_expiry import calculate_time_to_expiry
from src.eye.option_evidence.moneyness import classify_moneyness
from src.eye.option_evidence.liquidity import calculate_liquidity_metrics
from src.eye.option_evidence.greeks import calculate_black_scholes_greeks
from src.eye.option_evidence.iv import solve_implied_volatility
from src.eye.option_evidence.synchronization import synchronize_option_and_underlying
from src.eye.option_evidence.evidence_record import OptionEvidenceRecord
from src.eye.option_evidence.diagnostics import EvidenceDiagnosticCode


class OptionEvidenceReplayEngine:
    def __init__(self):
        self.evidence_records: List[OptionEvidenceRecord] = []
        self.evidence_links: List[SetupOptionEvidenceLink] = []
        self.last_watermark: Optional[datetime] = None

    def process_setup_and_evidence(
        self,
        candidate: SetupCandidateRecord,
        available_option_observations: List[OptionMarketObservation],
        underlying_ticks: List[Tuple[datetime, float]],
        risk_free_rate: float = 0.065,
    ) -> List[OptionEvidenceRecord]:
        """Bind option evidence to approved E3-E setup candidate without look-ahead."""
        # 1. Check setup E4 eligibility
        if candidate.setup_family not in (
            "LIQUIDITY_SWEEP_RECLAIM", "DISPLACEMENT_FVG_RETEST",
            "BREAKAWAY_FVG_CONTINUATION", "ZONE_FVG_CONFLUENCE"
        ):
            return []

        if candidate.status == CandidateStatus.INVALIDATED:
            return []

        watermark = candidate.confirmed_at
        if self.last_watermark and watermark < self.last_watermark:
            # Out of order setup confirmation
            return []
        self.last_watermark = watermark

        generated_records = []

        for obs in available_option_observations:
            # Enforce No-Look-Ahead: observation must be <= setup confirmation watermark
            sync_pair = synchronize_option_and_underlying(obs, underlying_ticks, watermark)
            if not sync_pair:
                continue

            cid = obs.contract
            underlying_p = sync_pair.underlying_price

            # Quote Quality
            q_metrics = classify_quote_quality(
                obs.best_bid, obs.best_ask, obs.bid_quantity, obs.ask_quantity,
                obs.last_price, obs.observed_at, watermark
            )

            # Time to expiry
            tte = calculate_time_to_expiry(watermark, cid.expiry_timestamp)

            # Moneyness
            m_res = classify_moneyness(
                cid, underlying_p,
                q_metrics.midpoint if q_metrics.midpoint else (obs.last_price.ticks / 100.0 if obs.last_price else None)
            )

            # Liquidity
            l_metrics = calculate_liquidity_metrics(
                obs.open_interest, obs.previous_open_interest, obs.volume,
                obs.bid_quantity, obs.ask_quantity
            )

            # Independent BS Greeks & IV
            indep_greeks = {}
            indep_iv_obs = None

            if tte.years_act_365 > 0 and q_metrics.midpoint is not None:
                iv_solved = solve_implied_volatility(
                    q_metrics.midpoint, underlying_p, cid.strike.ticks / 100.0,
                    tte.years_act_365, risk_free_rate, cid.option_type
                )
                if iv_solved is not None:
                    indep_iv_obs = ImpliedVolatilityObservation(
                        contract_key=cid.contract_key,
                        source=obs.provenance.source_type,
                        value=iv_solved,
                        unit="PERCENTAGE",
                        price_reference=PriceReference.MIDPOINT,
                        underlying_reference=underlying_p,
                        interest_rate_reference=risk_free_rate,
                        calculated_at=watermark,
                        available_at=watermark,
                    )
                    bs_dict = calculate_black_scholes_greeks(
                        underlying_p, cid.strike.ticks / 100.0, tte.years_act_365,
                        risk_free_rate, iv_solved, cid.option_type
                    )
                    for gtype, gval in bs_dict.items():
                        indep_greeks[gtype.value] = GreekObservation(
                            contract_key=cid.contract_key,
                            greek_type=gtype,
                            value=gval,
                            unit="INDEPENDENT_BS",
                            source=GreekSource.INDEPENDENT_MODEL,
                            model_id="BLACK_SCHOLES_ANALYTICAL_V1",
                            calculated_at=watermark,
                            available_at=watermark,
                        )

            dir_val = candidate.direction.value if (hasattr(candidate, "direction") and candidate.direction) else "BEARISH"

            link = SetupOptionEvidenceLink(
                schema_version="1.0.0",
                setup_key=candidate.setup_key,
                setup_record_id=candidate.record_id,
                setup_id=candidate.setup_id,
                setup_version=candidate.setup_version,
                setup_family=candidate.setup_family,
                underlying_symbol=candidate.instrument.normalized_symbol,
                setup_direction=dir_val,
                setup_timeframe="5m",
                setup_confirmation_timestamp=watermark,
                setup_availability_watermark=watermark,
                contract_key=cid.contract_key,
                option_type=cid.option_type,
                observation_ids=(obs.observation_id,),
                underlying_observation_ids=(f"UND:{int(sync_pair.underlying_timestamp.timestamp())}",),
                evidence_window_start=watermark,
                evidence_window_end=watermark,
                source_data_revision=1,
                link_status="BOUND",
                availability="CONTEMPORANEOUS",
                quality_diagnostics={"quote_state": q_metrics.quote_state.value},
            )

            rec_id = f"EVREC:{candidate.setup_key[:12]}:{cid.contract_key[:12]}"

            rec = OptionEvidenceRecord(
                schema_version="1.0.0",
                evidence_id=rec_id,
                contract=cid,
                observation=obs,
                quote_quality=q_metrics,
                time_to_expiry=tte,
                moneyness=m_res,
                liquidity=l_metrics,
                independent_greeks=indep_greeks,
                independent_iv=indep_iv_obs,
                alignment_diagnostics=None,
                evidence_link=link,
                evaluation_as_of=watermark,
            )
            generated_records.append(rec)
            self.evidence_records.append(rec)
            self.evidence_links.append(link)

        return generated_records
