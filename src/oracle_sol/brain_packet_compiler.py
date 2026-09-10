"""Deterministic BrainPacket Compiler for Local Qwen 3.5 9B.

Compiles compact, bounded cognitive input packages:
- CURRENT CANONICAL STATE (Deterministic truth from Fast Lane / Snapshots)
- PREVIOUS STRUCTURED LOCAL THESIS (Prior committed state, invalidations, watch conditions)
- UNSEEN CANONICAL EVENT IDS (Lossless event identity since previous thesis cursor)
- WHAT CHANGED (Explicit mathematical/structural deltas)
- VERIFIED EXTERNAL CONTEXT (Verified regulatory, news, and world market quotes)
- EVIDENCE IDS REGISTRY (Immutable set of all valid verifiable IDs for the Evidence Gate)

Enforces:
- Coalescing: If revisions R101..R120 occur during inference, intermediate jobs drop.
  Next analysis receives latest state R120 + full union of unseen event IDs.
- Compact context: Keeps total token load typically < 2,000 tokens (avoiding 256k bloat).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.external_context.contracts import ExternalEvent, ExternalQuote
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot
from src.oracle_sol.cognitive_feature_bus import project_features


CANONICAL_SEMANTIC_METADATA: Dict[str, Dict[str, str]] = {
    "spot_price": {
        "instrument": "NIFTY_INDEX",
        "unit": "PTS",
        "producer": "NSE_CASH_INDEX",
        "semantic_scope": "UNDERLYING_PRICE_DISCOVERY",
        "limitations": "Underlying cash index. Derived from constituent basket.",
    },
    "futures_price": {
        "instrument": "NIFTY_FUTURES",
        "unit": "PTS",
        "producer": "NSE_DERIVATIVES",
        "semantic_scope": "DERIVATIVE_PRICE_DISCOVERY",
        "limitations": "Active front-month NIFTY futures contract.",
    },
    "basis": {
        "instrument": "NIFTY_FUTURES_VS_SPOT",
        "unit": "PTS",
        "producer": "CALCULATED_RELATIONSHIP",
        "semantic_scope": "BASIS_PREMIUM_DISCOUNT",
        "limitations": "Futures minus spot. Positive is carry premium, negative is discount.",
    },
    "atm_strike": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "STRIKE",
        "producer": "ATM_ROUNDER",
        "semantic_scope": "REFERENCE_STRIKE",
        "limitations": "Nearest 50-point strike to spot index.",
    },
    "ce_atm_premium": {
        "instrument": "NIFTY_ATM_CE",
        "unit": "INR",
        "producer": "DHAN_MARKET_FEED",
        "semantic_scope": "OPTION_CONTRACT_PRICING",
        "limitations": "LTP of ATM Call. May rotate when ATM shifts.",
    },
    "pe_atm_premium": {
        "instrument": "NIFTY_ATM_PE",
        "unit": "INR",
        "producer": "DHAN_MARKET_FEED",
        "semantic_scope": "OPTION_CONTRACT_PRICING",
        "limitations": "LTP of ATM Put. May rotate when ATM shifts.",
    },
    "atm_iv": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "PERCENT",
        "producer": "VOLATILITY_ENGINE",
        "semantic_scope": "IMPLIED_VOLATILITY",
        "limitations": "Annualized ATM implied volatility.",
    },
    "skew_25d": {
        "instrument": "NIFTY_OPTIONS", "unit": "IV_PERCENTAGE_POINTS",
        "producer": "OptionIntelligenceEngine", "semantic_scope": "25_DELTA_PUT_MINUS_CALL_IV",
        "limitations": "25d means 25-delta, not 25 days. Put IV minus call IV; negative means call IV exceeds put IV. Volatility context, not standalone direction.",
    },
    "skew_10d": {
        "instrument": "NIFTY_OPTIONS", "unit": "IV_PERCENTAGE_POINTS",
        "producer": "OptionIntelligenceEngine", "semantic_scope": "10_DELTA_PUT_MINUS_CALL_IV",
        "limitations": "10d means 10-delta, not 10 days. Put IV minus call IV; negative means call IV exceeds put IV. Volatility context, not standalone direction.",
    },
    "total_net_gex_inr_cr": {
        "instrument": "NIFTY_DERIVATIVES",
        "unit": "INR_CRORES",
        "producer": "GEX_CALCULATOR",
        "semantic_scope": "DEALER_GAMMA_CONTEXT",
        "limitations": "Market maker aggregate gamma exposure. Positive is dealer long gamma / pinning context. Not net call gamma. Not a standalone trade signal.",
    },
    "dealer_regime": {
        "instrument": "NIFTY_DERIVATIVES",
        "unit": "ENUM",
        "producer": "GEX_ENGINE",
        "semantic_scope": "DEALER_GAMMA_REGIME",
        "limitations": "Dealer positioning regime (e.g. LONG_GAMMA_PIN). Volatility context, not a standalone trade signal.",
    },
    "seller_absorption": {
        "instrument": "NIFTY_FUTURES",
        "unit": "RATIO_0_TO_1",
        "producer": "ORDER_FLOW_FEATURES",
        "semantic_scope": "UNDERLYING_ORDER_FLOW_RESPONSE",
        "limitations": "Underlying NIFTY futures passive order flow response. Aggressive sells absorbed by passive bid refills with poor downward progress. Does NOT represent CE/PE flow. 0.45 is threshold for SELLERS_ABSORBED; values below 0.45 are MIXED. Do not label high/low qualitatively.",
    },
    "buyer_absorption": {
        "instrument": "NIFTY_FUTURES",
        "unit": "RATIO_0_TO_1",
        "producer": "ORDER_FLOW_FEATURES",
        "semantic_scope": "UNDERLYING_ORDER_FLOW_RESPONSE",
        "limitations": "Underlying NIFTY futures passive order flow response. Aggressive buys absorbed by passive ask refills with poor upward progress. Does NOT represent CE/PE flow. 0.45 is threshold for BUYERS_ABSORBED.",
    },
    "failed_aggression": {
        "instrument": "NIFTY_FUTURES",
        "unit": "RATIO_0_TO_1",
        "producer": "ORDER_FLOW_FEATURES",
        "semantic_scope": "UNDERLYING_ORDER_FLOW_EFFICIENCY",
        "limitations": "Max of buyer and seller absorption in NIFTY futures.",
    },
    "flow_net_delta": {
        "instrument": "NIFTY_FUTURES",
        "unit": "RATIO_MINUS1_TO_1",
        "producer": "ORDER_FLOW_AGGREGATION",
        "semantic_scope": "UNDERLYING_ORDER_FLOW_DELTA",
        "limitations": "Net aggressive buy vs sell order flow in NIFTY futures. Does NOT represent option-side order flow.",
    },
    "call_oi_build": {
        "instrument": "NIFTY_CALL_OPTIONS",
        "unit": "OI_CONTRACTS_AND_MULTIPLE",
        "producer": "OPEN_INTEREST_MONITOR",
        "semantic_scope": "OPTION_POSITIONING_ACTIVITY",
        "limitations": "Open interest activity in Call strikes. Symmetrical OI change alone cannot establish directional conviction or distinguish buyer vs writer without corroborating price/premium.",
    },
    "put_oi_build": {
        "instrument": "NIFTY_PUT_OPTIONS",
        "unit": "OI_CONTRACTS_AND_MULTIPLE",
        "producer": "OPEN_INTEREST_MONITOR",
        "semantic_scope": "OPTION_POSITIONING_ACTIVITY",
        "limitations": "Open interest activity in Put strikes. Symmetrical OI change alone cannot establish directional conviction or distinguish buyer vs writer without corroborating price/premium.",
    },
    "pcr_oi": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "RATIO",
        "producer": "OPTION_CHAIN_ENGINE",
        "semantic_scope": "OPTION_POSITIONING_RATIO",
        "limitations": "Put OI / Call OI ratio. Secondary positional context, not a standalone trade signal.",
    },
    "zero_gamma": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "INDEX_POINTS",
        "producer": "GEX_CALCULATOR",
        "semantic_scope": "ZERO_GAMMA_PIVOT",
        "limitations": "Calculated index level where aggregate market maker gamma equals zero. Transition point between long and short gamma regimes.",
    },
    "buildup": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "ENUM",
        "producer": "OPTION_CHAIN_ENGINE",
        "semantic_scope": "PRICE_OI_QUADRANT_CLASSIFICATION",
        "limitations": "Heuristic classification based on price delta and OI delta (LONG_BUILDUP, SHORT_COVERING, SHORT_BUILDUP, LONG_UNWINDING). Does NOT claim proof of participant identity or writer causality.",
    },
    "closed_oi_buildup": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "ENUM",
        "producer": "OPTION_CHAIN_ENGINE",
        "semantic_scope": "HISTORICAL_PRICE_OI_QUADRANT",
        "limitations": "Heuristic classification based on closed candle price/OI movement. Heuristic label only; no writer causality.",
    },
    "oi_velocity": {
        "instrument": "STRIKE_SPINE",
        "unit": "OI_PER_MINUTE",
        "producer": "ARGUS_PRIME_KINEMATICS",
        "semantic_scope": "STRIKE_SPINE_OI_RATE_OF_CHANGE",
        "limitations": "First time derivative of strike open interest. Indicates velocity of positional accumulation.",
    },
    "oi_acceleration": {
        "instrument": "STRIKE_SPINE",
        "unit": "OI_PER_MINUTE_SQUARED",
        "producer": "ARGUS_PRIME_KINEMATICS",
        "semantic_scope": "STRIKE_SPINE_OI_ACCELERATION",
        "limitations": "Second time derivative of strike open interest.",
    },
    "oi_concentration": {
        "instrument": "STRIKE_SPINE",
        "unit": "RATIO_0_TO_1",
        "producer": "ARGUS_PRIME_KINEMATICS",
        "semantic_scope": "STRIKE_SPINE_LOAD_CONCENTRATION",
        "limitations": "Normalized distribution metric of open interest across strikes.",
    },
    "max_pain": {
        "instrument": "NIFTY_OPTIONS",
        "unit": "STRIKE",
        "producer": "SECONDARY_HELPER",
        "semantic_scope": "MAX_PAIN_STRIKE",
        "limitations": "MAX_PAIN_NOT_CURRENTLY_CANONICAL. Excluded from canonical packet. Not continuous live feed in SolEvidenceSnapshot.",
    },
    "india_vix": {
        "instrument": "INDIA_VIX",
        "unit": "PERCENT",
        "producer": "UPSTOX_MARKET_INFO",
        "semantic_scope": "VOLATILITY_INDEX",
        "limitations": "Canonical Upstox real-time quote. If feed disconnected: INDIA_VIX_UNAVAILABLE. Excluded from live packet.",
    },
}


@dataclass(frozen=True)
class BrainPacket:
    """The immutable, compact cognitive input envelope sent to LocalModelAdapter."""

    packet_id: str
    session_id: str
    revision: int
    compiled_at: str
    canonical_state: Dict[str, Any]
    what_changed: Dict[str, Any]
    unseen_event_ids: List[str]
    unseen_events_summary: List[Dict[str, Any]]
    previous_thesis: Optional[Dict[str, Any]]
    verified_external_events: List[Dict[str, Any]]
    external_quotes: List[Dict[str, Any]]
    valid_evidence_ids: List[str]
    canonical_levels: List[float] = field(default_factory=list)
    episode_id: str = ""
    temporal_relationships: List[Dict[str, Any]] = field(default_factory=list)
    aggression_response_sequence: List[Dict[str, Any]] = field(default_factory=list)
    option_continuity: Dict[str, Any] = field(default_factory=dict)
    evidence_registry: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    packet_hash: str = ""
    cognitive_features: Dict[str, Any] = field(default_factory=dict)
    specialist_context: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if isinstance(d.get("canonical_levels"), set):
            d["canonical_levels"] = sorted(list(d["canonical_levels"]))
        return d

    def resolve_evidence(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        """Resolves an evidence ID to its concrete attached payload with zero orphan tolerance."""
        res = None
        if self.evidence_registry and evidence_id in self.evidence_registry:
            res = dict(self.evidence_registry[evidence_id])
        elif evidence_id.startswith("metric:"):
            key = evidence_id.split(":", 1)[-1]
            if key in self.canonical_state and self.canonical_state[key] is not None:
                res = {
                    "field": key,
                    "value": self.canonical_state[key],
                    "source": "canonical_state",
                    "timestamp": self.compiled_at,
                    "availability": "RECORDED",
                }
            elif not self.evidence_registry and evidence_id in self.valid_evidence_ids:
                res = {
                    "field": key,
                    "value": self.canonical_state.get(key, "RECORDED_VALID_EVIDENCE"),
                    "source": "canonical_state",
                    "timestamp": self.compiled_at,
                    "availability": "RECORDED",
                }
        elif self.unseen_events_summary:
            for ev in self.unseen_events_summary:
                if isinstance(ev, dict) and ev.get("event_id") == evidence_id:
                    res = {
                        "field": ev.get("event_type", "unseen_event"),
                        "value": ev,
                        "source": "unseen_events_summary",
                        "timestamp": ev.get("timestamp_ist", self.compiled_at),
                        "availability": "RECORDED",
                    }
                    break
        elif self.unseen_event_ids and evidence_id in self.unseen_event_ids:
            res = {
                "field": "unseen_event",
                "value": evidence_id,
                "source": "unseen_event_ids",
                "timestamp": self.compiled_at,
                "availability": "RECORDED",
            }

        # Enrich with canonical semantic metadata if applicable
        if res and "field" in res and res["field"] in CANONICAL_SEMANTIC_METADATA:
            meta = CANONICAL_SEMANTIC_METADATA[res["field"]]
            if "semantic_scope" not in res:
                res["semantic_scope"] = meta.get("semantic_scope")
            if "instrument" not in res:
                res["instrument"] = meta.get("instrument")
            if "limitations" not in res:
                res["limitations"] = meta.get("limitations")
            if "unit" not in res:
                res["unit"] = meta.get("unit")
            if "producer" not in res:
                res["producer"] = meta.get("producer")
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BrainPacket:
        return cls(
            packet_id=d["packet_id"],
            session_id=d["session_id"],
            revision=d["revision"],
            compiled_at=d["compiled_at"],
            canonical_state=d["canonical_state"],
            what_changed=d["what_changed"],
            unseen_event_ids=d["unseen_event_ids"],
            unseen_events_summary=d["unseen_events_summary"],
            previous_thesis=d.get("previous_thesis"),
            verified_external_events=d.get("verified_external_events", []),
            external_quotes=d.get("external_quotes", []),
            valid_evidence_ids=d.get("valid_evidence_ids", []),
            canonical_levels=d.get("canonical_levels", []),
            episode_id=d.get("episode_id", ""),
            temporal_relationships=d.get("temporal_relationships", []),
            aggression_response_sequence=d.get("aggression_response_sequence", []),
            option_continuity=d.get("option_continuity", {}),
            evidence_registry=d.get("evidence_registry", {}),
            packet_hash=d.get("packet_hash", ""),
            cognitive_features=d.get("cognitive_features", {}),
            specialist_context=d.get("specialist_context", []),
        )


class BrainPacketCompiler:
    """Compiles deterministic BrainPackets from canonical state and event sources."""

    def __init__(self) -> None:
        self._pending_unseen_events: List[MarketEvent] = []

    def compile_packet(
        self,
        session_id: str,
        revision: int,
        current_snapshot: SolEvidenceSnapshot,
        previous_thesis: Optional[Dict[str, Any]],
        unseen_events: List[MarketEvent],
        external_events: List[ExternalEvent],
        external_quotes: List[ExternalQuote],
        episode_id: str = "",
    ) -> BrainPacket:
        now = datetime.now(timezone.utc)
        now_utc = now.isoformat()
        # Preserve the complete durable evidence frontier for cursor correctness.
        # Only the compact event bodies are bounded; discarded body duplication
        # must never silently discard event identity.
        all_unseen_events = list(unseen_events)
        unseen_events = all_unseen_events[-5:]

        def _timestamp(value: Any) -> Optional[datetime]:
            if not isinstance(value, str) or len(value) <= 10:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

        def _verified_external(item: Any, *, quote: bool = False) -> bool:
            """Keep the cognitive packet behind the same fail-closed trust boundary as the UI."""
            record = getattr(item, "verification_record", None)
            if not isinstance(record, dict):
                return False
            published = _timestamp(getattr(item, "provider_timestamp" if quote else "published_at", None))
            retrieved = _timestamp(getattr(item, "retrieved_at", None))
            checked = _timestamp(record.get("checked_at"))
            valid_until = _timestamp(record.get("valid_until"))
            raw_hash = getattr(item, "raw_hash", "")
            return bool(
                getattr(item, "verification_status", "UNVERIFIED") == "VERIFIED"
                and record.get("status") == "MATCH"
                and record.get("verifier_id")
                and raw_hash
                and record.get("payload_hash") == raw_hash
                and published
                and retrieved
                and checked
                and valid_until
                and published <= retrieved <= now
                and checked <= now <= valid_until
            )

        # ExternalContextCore intentionally retains unverified detail for audit APIs.
        # It must not cross the cognitive evidence boundary as model-grounding input.
        external_events = [event for event in external_events if _verified_external(event)]
        external_quotes = [quote for quote in external_quotes if _verified_external(quote, quote=True)]
        
        # 1. Canonical State Extraction (Compact)
        spot = getattr(current_snapshot, "spot_ltp", None) if getattr(current_snapshot, "spot_ltp", None) is not None else getattr(current_snapshot, "spot_price", None)
        fut = getattr(current_snapshot, "futures_ltp", None) if getattr(current_snapshot, "futures_ltp", None) is not None else getattr(current_snapshot, "futures_price", None)
        basis = getattr(current_snapshot, "futures_basis", None)

        flow_delta = getattr(current_snapshot, "net_delta_flow", None)
        flow_aggr = getattr(current_snapshot, "current_flow_x", None) if getattr(current_snapshot, "current_flow_x", None) is not None else getattr(current_snapshot, "flow_aggression", None)

        def _compact_oi(oi_val: Any) -> Any:
            if not isinstance(oi_val, dict):
                return oi_val
            return {
                "status": oi_val.get("status"),
                "side": oi_val.get("side"),
                "strike_scope": oi_val.get("strike_scope"),
                "current_5m_activity": oi_val.get("current_5m_activity"),
                "current_to_normal_x": oi_val.get("current_to_normal_x"),
            }

        ce_p = getattr(current_snapshot, "ce_pricing", None) or {}
        pe_p = getattr(current_snapshot, "pe_pricing", None) or {}
        ce_atm_premium = ce_p.get("ltp") if isinstance(ce_p, dict) else None
        pe_atm_premium = pe_p.get("ltp") if isinstance(pe_p, dict) else None
        ce_sec_id = ce_p.get("security_id") if isinstance(ce_p, dict) else None
        pe_sec_id = pe_p.get("security_id") if isinstance(pe_p, dict) else None
        straddle_price = getattr(current_snapshot, "atm_straddle_price", None)
        atm_iv = getattr(current_snapshot, "atm_iv", None)
        zero_gamma = getattr(current_snapshot, "zero_gamma_level", None)

        # Collect all valid canonical levels (strikes, spot, futures, zero gamma, vwap)
        canonical_levels: Set[float] = set()
        atm_strike = getattr(current_snapshot, "atm_strike", None)
        vwap = getattr(current_snapshot, "session_vwap", None)
        for level in (spot, fut, zero_gamma, vwap, atm_strike):
            if level is not None:
                canonical_levels.add(float(level))

        ladder = getattr(current_snapshot, "strike_ladder", []) or []
        for r in ladder:
            if isinstance(r, dict) and "strike" in r:
                try: canonical_levels.add(float(r["strike"]))
                except Exception: pass

        canonical_state = {
            "spot_price": spot,
            "futures_price": fut,
            "basis": basis,
            "session_vwap": vwap,
            "atm_strike": getattr(current_snapshot, "atm_strike", None),
            "ce_atm_premium": ce_atm_premium,
            "pe_atm_premium": pe_atm_premium,
            "ce_atm_security_id": ce_sec_id,
            "pe_atm_security_id": pe_sec_id,
            "straddle_price": straddle_price,
            "straddle_change_15m": getattr(current_snapshot, "straddle_change_15m", None),
            "atm_iv": atm_iv,
            "skew_25d": current_snapshot.skew_25d,
            "skew_10d": current_snapshot.skew_10d,
            "zero_gamma": zero_gamma,
            "total_net_gex_inr_cr": getattr(current_snapshot, "total_net_gex_inr_cr", None),
            "dealer_regime": getattr(current_snapshot, "dealer_regime", None),
            "flow_net_delta": flow_delta,
            "mlofi_5l": current_snapshot.mlofi_5l,
            "flow_aggression": flow_aggr,
            "cvd": getattr(current_snapshot, "cvd", None),
            "buyer_absorption": getattr(current_snapshot, "buyer_absorption", None),
            "seller_absorption": getattr(current_snapshot, "seller_absorption", None),
            "failed_aggression": getattr(current_snapshot, "failed_aggression", None),
            "price_response_efficiency": getattr(current_snapshot, "price_response_efficiency", None),
            "continuation_efficiency": getattr(current_snapshot, "continuation_efficiency", None),
            "bid_depletion": getattr(current_snapshot, "bid_depletion", None),
            "ask_depletion": getattr(current_snapshot, "ask_depletion", None),
            "bid_refill": getattr(current_snapshot, "bid_refill", None),
            "ask_refill": getattr(current_snapshot, "ask_refill", None),
            "order_flow_response_state": getattr(current_snapshot, "order_flow_response_state", None),
            # OSE composite includes VOB structure. Do not pass a label without
            # separately certified non-VOB contribution lineage.
            "ose_ssi_score": None,
            "ose_decision_window": None,
            "gex_regime": getattr(current_snapshot, "gex_regime", None),
            "call_oi_build": _compact_oi(getattr(current_snapshot, "sudden_oi_call", None)),
            "put_oi_build": _compact_oi(getattr(current_snapshot, "sudden_oi_put", None)),
            "pcr_oi": getattr(current_snapshot, "pcr_oi", None),
            "india_vix": getattr(current_snapshot, "india_vix", None),
        }

        # ── Phase C: Dual-View Option Contract Continuity ──
        def _lookup_contract_in_ladder(lad: List[Dict[str, Any]], sid: Optional[str], stk: Optional[float], side_str: str) -> Optional[float]:
            for item in lad:
                if not isinstance(item, dict):
                    continue
                if sid:
                    if side_str == "CE" and str(item.get("ce_security_id")) == str(sid):
                        return item.get("ce_ltp")
                    if side_str == "PE" and str(item.get("pe_security_id")) == str(sid):
                        return item.get("pe_ltp")
                if not sid and stk is not None and item.get("strike") == stk:
                    if side_str == "CE":
                        return item.get("ce_ltp")
                    if side_str == "PE":
                        return item.get("pe_ltp")
            return None

        prev_cs = previous_thesis.get("canonical_state", {}) if previous_thesis else {}
        prev_atm_stk = prev_cs.get("atm_strike")
        prev_ce_sid = prev_cs.get("ce_atm_security_id") or prev_cs.get("ce_security_id")
        prev_pe_sid = prev_cs.get("pe_atm_security_id") or prev_cs.get("pe_security_id")
        prev_ce_prem = prev_cs.get("ce_atm_premium")
        prev_pe_prem = prev_cs.get("pe_atm_premium")

        ce_rotated = bool(prev_ce_sid and ce_sec_id and str(prev_ce_sid) != str(ce_sec_id))
        pe_rotated = bool(prev_pe_sid and pe_sec_id and str(prev_pe_sid) != str(pe_sec_id))
        strike_rotated = bool(prev_atm_stk and atm_strike and prev_atm_stk != atm_strike)
        role_rotation_occurred = ce_rotated or pe_rotated or strike_rotated

        role_view = {
            "current_atm_strike": atm_strike,
            "current_ce_security_id": ce_sec_id,
            "current_pe_security_id": pe_sec_id,
            "atm_ce_ltp": ce_atm_premium,
            "atm_pe_ltp": pe_atm_premium,
        }

        identity_view: List[Dict[str, Any]] = []
        true_ce_delta: Optional[float] = None
        true_pe_delta: Optional[float] = None

        if prev_ce_prem is not None:
            if not ce_rotated:
                if ce_atm_premium is not None:
                    true_ce_delta = round(float(ce_atm_premium) - float(prev_ce_prem), 2)
                    identity_view.append({
                        "security_id": ce_sec_id,
                        "strike": atm_strike,
                        "side": "CE",
                        "previous_premium": prev_ce_prem,
                        "current_premium": ce_atm_premium,
                        "true_same_contract_change": true_ce_delta,
                        "role_status": "ATM_UNCHANGED",
                    })
            else:
                curr_ltp_old_ce = _lookup_contract_in_ladder(ladder, prev_ce_sid, prev_atm_stk, "CE")
                if curr_ltp_old_ce is not None:
                    true_ce_delta = round(float(curr_ltp_old_ce) - float(prev_ce_prem), 2)
                    identity_view.append({
                        "security_id": prev_ce_sid,
                        "strike": prev_atm_stk,
                        "side": "CE",
                        "previous_premium": prev_ce_prem,
                        "current_premium": curr_ltp_old_ce,
                        "true_same_contract_change": true_ce_delta,
                        "role_status": "ROTATED_OUT_OF_ATM",
                    })
                else:
                    identity_view.append({
                        "security_id": prev_ce_sid,
                        "strike": prev_atm_stk,
                        "side": "CE",
                        "previous_premium": prev_ce_prem,
                        "current_premium": None,
                        "true_same_contract_change": None,
                        "role_status": "LADDER_OUT_OF_SCOPE",
                    })

        if prev_pe_prem is not None:
            if not pe_rotated:
                if pe_atm_premium is not None:
                    true_pe_delta = round(float(pe_atm_premium) - float(prev_pe_prem), 2)
                    identity_view.append({
                        "security_id": pe_sec_id,
                        "strike": atm_strike,
                        "side": "PE",
                        "previous_premium": prev_pe_prem,
                        "current_premium": pe_atm_premium,
                        "true_same_contract_change": true_pe_delta,
                        "role_status": "ATM_UNCHANGED",
                    })
            else:
                curr_ltp_old_pe = _lookup_contract_in_ladder(ladder, prev_pe_sid, prev_atm_stk, "PE")
                if curr_ltp_old_pe is not None:
                    true_pe_delta = round(float(curr_ltp_old_pe) - float(prev_pe_prem), 2)
                    identity_view.append({
                        "security_id": prev_pe_sid,
                        "strike": prev_atm_stk,
                        "side": "PE",
                        "previous_premium": prev_pe_prem,
                        "current_premium": curr_ltp_old_pe,
                        "true_same_contract_change": true_pe_delta,
                        "role_status": "ROTATED_OUT_OF_ATM",
                    })
                else:
                    identity_view.append({
                        "security_id": prev_pe_sid,
                        "strike": prev_atm_stk,
                        "side": "PE",
                        "previous_premium": prev_pe_prem,
                        "current_premium": None,
                        "true_same_contract_change": None,
                        "role_status": "LADDER_OUT_OF_SCOPE",
                    })

        option_continuity = {
            "role_view": role_view,
            "identity_view": identity_view,
            "role_rotation": {
                "occurred": role_rotation_occurred,
                "previous_atm_strike": prev_atm_stk,
                "current_atm_strike": atm_strike,
                "previous_ce_security_id": prev_ce_sid,
                "current_ce_security_id": ce_sec_id,
                "previous_pe_security_id": prev_pe_sid,
                "current_pe_security_id": pe_sec_id,
            },
        }

        # 2. What Changed (Deterministic Neutral Relationship Deltas)
        what_changed: Dict[str, Any] = {
            "revisions_elapsed": revision - (previous_thesis.get("input_revision", 0) if previous_thesis else 0),
            "unseen_market_events_count": len(unseen_events),
        }
        if previous_thesis and "canonical_state" in previous_thesis:
            if spot and prev_cs.get("spot_price"):
                what_changed["spot_delta"] = round(spot - prev_cs["spot_price"], 2)
            if fut and prev_cs.get("futures_price"):
                what_changed["futures_delta"] = round(fut - prev_cs["futures_price"], 2)
            if basis is not None and prev_cs.get("basis") is not None:
                what_changed["basis_delta"] = round(basis - prev_cs["basis"], 2)
            if flow_delta is not None and prev_cs.get("flow_net_delta") is not None:
                what_changed["flow_delta"] = round(flow_delta - prev_cs["flow_net_delta"], 2)
            
            # Safe Same-Contract Premium Deltas (Zero Phantom Delta)
            if true_ce_delta is not None:
                what_changed["ce_premium_delta"] = true_ce_delta
                what_changed["ce_same_contract_id"] = prev_ce_sid or ce_sec_id
            elif not role_rotation_occurred and ce_atm_premium is not None and prev_ce_prem is not None:
                what_changed["ce_premium_delta"] = round(ce_atm_premium - prev_ce_prem, 2)
            else:
                what_changed["ce_premium_delta"] = None

            if true_pe_delta is not None:
                what_changed["pe_premium_delta"] = true_pe_delta
                what_changed["pe_same_contract_id"] = prev_pe_sid or pe_sec_id
            elif not role_rotation_occurred and pe_atm_premium is not None and prev_pe_prem is not None:
                what_changed["pe_premium_delta"] = round(pe_atm_premium - prev_pe_prem, 2)
            else:
                what_changed["pe_premium_delta"] = None

            if role_rotation_occurred:
                what_changed["role_rotation_alert"] = f"ATM_ROTATED_{prev_atm_stk}_TO_{atm_strike}"

            if straddle_price is not None and prev_cs.get("straddle_price") is not None:
                what_changed["straddle_delta"] = round(straddle_price - prev_cs["straddle_price"], 2)
        else:
            what_changed["status"] = "INITIAL_THESIS_BASELINE"

        # 3. Compact Unseen Events (lossless identity for recent discrete sequence)
        unseen_event_ids: List[str] = [e.event_id for e in all_unseen_events]
        compact_events = [
            {
                "event_id": e.event_id,
                "type": e.event_type,
                "time": e.timestamp_ist,
                "summary": e.summary,
            }
            for e in unseen_events
        ]

        # 4. Temporal Relationship Packet (Neutral Chronological Facts)
        temporal_relationships: List[Dict[str, Any]] = []

        if previous_thesis and "canonical_state" in previous_thesis:
            metrics_to_track = [
                ("spot_price", spot, prev_cs.get("spot_price")),
                ("futures_price", fut, prev_cs.get("futures_price")),
                ("basis", basis, prev_cs.get("basis")),
                ("flow_net_delta", flow_delta, prev_cs.get("flow_net_delta")),
                ("atm_iv", atm_iv, prev_cs.get("atm_iv")),
                ("straddle_price", straddle_price, prev_cs.get("straddle_price")),
            ]
            for m_name, curr_val, prev_val in metrics_to_track:
                if curr_val is not None and prev_val is not None:
                    chg = round(float(curr_val) - float(prev_val), 2)
                    entry = {
                        "metric": m_name,
                        "timestamp": now_utc,
                        "event_id": f"rel:{m_name}",
                        "before": prev_val,
                        "after": curr_val,
                        "change": chg,
                        "source": "SolEvidenceSnapshot",
                    }
                    temporal_relationships.append(entry)

            # Add same-contract premium response observations
            if true_ce_delta is not None:
                temporal_relationships.append({
                    "metric": "ce_contract_premium",
                    "timestamp": now_utc,
                    "event_id": "rel:ce_contract_premium",
                    "security_id": prev_ce_sid or ce_sec_id,
                    "before": prev_ce_prem,
                    "after": (prev_ce_prem + true_ce_delta) if prev_ce_prem is not None else None,
                    "change": true_ce_delta,
                    "source": "OptionContractContinuity",
                })
            if true_pe_delta is not None:
                temporal_relationships.append({
                    "metric": "pe_contract_premium",
                    "timestamp": now_utc,
                    "event_id": "rel:pe_contract_premium",
                    "security_id": prev_pe_sid or pe_sec_id,
                    "before": prev_pe_prem,
                    "after": (prev_pe_prem + true_pe_delta) if prev_pe_prem is not None else None,
                    "change": true_pe_delta,
                    "source": "OptionContractContinuity",
                })

            # Add Order Flow response observations if present
            buyer_ab = getattr(current_snapshot, "buyer_absorption", None)
            if buyer_ab is not None:
                temporal_relationships.append({
                    "metric": "buyer_absorption",
                    "timestamp": now_utc,
                    "event_id": "rel:buyer_absorption",
                    "before": prev_cs.get("buyer_absorption"),
                    "after": buyer_ab,
                    "change": round(buyer_ab - (prev_cs.get("buyer_absorption") or 0.0), 2) if prev_cs.get("buyer_absorption") is not None else None,
                    "source": "OrderFlowService",
                })

            seller_ab = getattr(current_snapshot, "seller_absorption", None)
            if seller_ab is not None:
                temporal_relationships.append({
                    "metric": "seller_absorption",
                    "timestamp": now_utc,
                    "event_id": "rel:seller_absorption",
                    "before": prev_cs.get("seller_absorption"),
                    "after": seller_ab,
                    "change": round(seller_ab - (prev_cs.get("seller_absorption") or 0.0), 2) if prev_cs.get("seller_absorption") is not None else None,
                    "source": "OrderFlowService",
                })

            failed_aggr = getattr(current_snapshot, "failed_aggression", None)
            if failed_aggr is not None:
                temporal_relationships.append({
                    "metric": "failed_aggression",
                    "timestamp": now_utc,
                    "event_id": "rel:failed_aggression",
                    "before": prev_cs.get("failed_aggression"),
                    "after": failed_aggr,
                    "change": round(failed_aggr - (prev_cs.get("failed_aggression") or 0.0), 2) if prev_cs.get("failed_aggression") is not None else None,
                    "source": "OrderFlowService",
                })

            price_eff = getattr(current_snapshot, "price_response_efficiency", None)
            if price_eff is not None:
                temporal_relationships.append({
                    "metric": "price_response_efficiency",
                    "timestamp": now_utc,
                    "event_id": "rel:price_response_efficiency",
                    "before": prev_cs.get("price_response_efficiency"),
                    "after": price_eff,
                    "change": round(price_eff - (prev_cs.get("price_response_efficiency") or 0.0), 2) if prev_cs.get("price_response_efficiency") is not None else None,
                    "source": "OrderFlowService",
                })

            dealer_reg = getattr(current_snapshot, "dealer_regime", None)
            if dealer_reg is not None:
                temporal_relationships.append({
                    "metric": "dealer_regime",
                    "timestamp": now_utc,
                    "event_id": "rel:dealer_regime",
                    "before": prev_cs.get("dealer_regime"),
                    "after": dealer_reg,
                    "change": 0.0 if prev_cs.get("dealer_regime") == dealer_reg else 1.0,
                    "source": "OptionIntelligenceEngine",
                })

        # 5. Aggression -> Price Response Sequence (Neutral Factual Sequence)
        aggression_response_sequence: List[Dict[str, Any]] = []
        for e in unseen_events:
            e_type = getattr(e, "event_type", "")
            # Only the canonical flow events emitted by EventStoryBuilder.
            # OI and SENSORIUM deltas do not establish flow aggression.
            if e_type in {"FLOW_POLARITY_FLIP", "FLOW_AGGRESSION_BURST"}:
                aggr_entry = {
                    "aggression_event_id": e.event_id,
                    "timestamp": getattr(e, "timestamp_ist", "") or now_utc,
                    "aggression_type": e_type,
                    "aggression_value": flow_delta,
                    "spot_before": previous_thesis.get("canonical_state", {}).get("spot_price") if previous_thesis else None,
                    "spot_after": spot,
                    "spot_change": what_changed.get("spot_delta"),
                    "futures_before": previous_thesis.get("canonical_state", {}).get("futures_price") if previous_thesis else None,
                    "futures_after": fut,
                    "futures_change": what_changed.get("futures_delta"),
                    "basis_before": previous_thesis.get("canonical_state", {}).get("basis") if previous_thesis else None,
                    "basis_after": basis,
                    "basis_change": what_changed.get("basis_delta"),
                    "ce_premium_before": previous_thesis.get("canonical_state", {}).get("ce_atm_premium") if previous_thesis else None,
                    "ce_premium_after": ce_atm_premium,
                    "ce_change": what_changed.get("ce_premium_delta"),
                    "pe_premium_before": previous_thesis.get("canonical_state", {}).get("pe_atm_premium") if previous_thesis else None,
                    "pe_premium_after": pe_atm_premium,
                    "pe_change": what_changed.get("pe_premium_delta"),
                    "atm_iv_before": previous_thesis.get("canonical_state", {}).get("atm_iv") if previous_thesis else None,
                    "atm_iv_after": atm_iv,
                    "subsequent_events": [ue.event_id for ue in unseen_events if ue.event_id != e.event_id],
                }
                aggression_response_sequence.append(aggr_entry)

        # 6. Verified External Events (Compact, top 4 to save token economy)
        ext_evts = [
            {
                "event_id": e.event_id,
                "tier": e.verification_tier,
                "source": e.source_name,
                "time": e.published_at,
                "headline": e.headline,
                "tags": e.market_tags,
            }
            for e in external_events[:4]
        ]

        # 7. External Quotes Basket with Truthful Session Labeling (Section 25)
        # Closed US ETF instruments during Indian market hours must be SESSION_LAST
        us_closed_proxies = {"SPY", "QQQ", "TLT", "USO", "GLD", "UUP"}
        quotes_summary = [
            {
                "symbol": q.symbol,
                "name": q.display_name,
                "price": q.price,
                "change_pct": q.change_percent,
                "nature": q.exact_or_proxy,
                "freshness": "SESSION_LAST" if (q.exact_or_proxy == "PROXY" and q.symbol in us_closed_proxies) else q.data_age,
            }
            for q in external_quotes
        ]

        # 8. Build Grounded Evidence Registry (Zero Naked/Orphan Evidence IDs)
        evidence_registry: Dict[str, Dict[str, Any]] = {}

        feature_bus = project_features(current_snapshot)
        # Existing IDs remain stable. New sensor fields have their own typed IDs;
        # source time is never replaced by packet compilation time.
        aliases = {"spot_price": "spot_ltp", "futures_price": "futures_ltp",
                   "basis": "futures_basis", "straddle_price": "atm_straddle_price",
                   "zero_gamma": "zero_gamma_level", "call_oi_build": "sudden_oi_call",
                   "put_oi_build": "sudden_oi_put"}
        # Canonical State Metrics (Only register if recorded and non-None)
        for metric_k, metric_v in canonical_state.items():
            if metric_v is not None:
                eid = f"metric:{metric_k}"
                meta = CANONICAL_SEMANTIC_METADATA.get(metric_k, {})
                evidence_registry[eid] = {
                    "field": metric_k,
                    "value": metric_v,
                    "timestamp": current_snapshot.timestamp_utc,
                    "source": "canonical_state",
                    "availability": "RECORDED",
                    "instrument": meta.get("instrument", "UNSPECIFIED"),
                    "unit": meta.get("unit", "RAW"),
                    "producer": meta.get("producer", "CANONICAL_PRODUCER"),
                    "semantic_scope": meta.get("semantic_scope", "CANONICAL_MARKET_STATE"),
                    "limitations": meta.get("limitations", "None specified"),
                }
                source_feature = feature_bus["fields"].get(aliases.get(metric_k, metric_k))
                if source_feature:
                    evidence_registry[eid].update({
                        "timestamp": source_feature["source_timestamp"],
                        "snapshot_timestamp": source_feature["snapshot_timestamp"],
                        "source_id": source_feature["source_id"],
                        "source_field": source_feature["source_field"],
                        "session_id": session_id,
                        "source_revision": source_feature["source_revision"],
                        "producer": source_feature["producer"],
                        "meaning": source_feature["meaning"],
                        "availability": source_feature["availability"],
                    })

        # Reuse established metric identities. Creating aliases for OI/GEX would
        # bypass the gate's typed identity rules; uncatalogued fields stay gaps.
        reverse_aliases = {source: target for target, source in aliases.items()}
        feature_index = {"schema_version": feature_bus["schema_version"],
            "snapshot_id": feature_bus["snapshot_id"], "market_state": feature_bus["market_state"],
            "domains": {}, "unavailable": [], "not_projected": []}
        for name, feature in feature_bus["fields"].items():
            eid = f"metric:{reverse_aliases.get(name, name)}"
            if eid in evidence_registry:
                feature_index["domains"].setdefault(feature["domain"], []).append(eid)
            elif feature["value"] is not None:
                feature_index["not_projected"].append(name)
            else:
                feature_index["unavailable"].append(name)

        # Temporal Relationships
        evidence_registry["coverage:input"] = {
            "field": "input_coverage",
            "value": {"unavailable": list(feature_index["unavailable"]),
                      "not_projected": list(feature_index["not_projected"])},
            "source": "CognitiveFeatureBus",
            "timestamp": getattr(current_snapshot, "timestamp_utc", None),
            "source_id": getattr(current_snapshot, "snapshot_id", None),
            "availability": "RECORDED_INPUT_COVERAGE",
            "semantic_scope": "NON_DIRECTIONAL_INPUT_AVAILABILITY",
            "limitations": "Missing input is not contrary market evidence, an observed market change, or a trade conclusion.",
        }
        for rel in temporal_relationships:
            eid = rel.get("event_id")
            if eid:
                evidence_registry[eid] = {
                    "field": rel.get("metric", "temporal_relationship"),
                    "value": rel,
                    "timestamp": rel.get("timestamp", now_utc),
                    "source": rel.get("source", "temporal_relationships"),
                    "availability": "RECORDED",
                }

        # Aggression Response Sequence
        for aggr in aggression_response_sequence:
            eid = aggr.get("aggression_event_id")
            if eid:
                evidence_registry[eid] = {
                    "field": "aggression_sequence",
                    "value": aggr,
                    "timestamp": aggr.get("timestamp", now_utc),
                    "source": "aggression_response_sequence",
                    "availability": "RECORDED",
                }

        # Ground the complete durable frontier, not just the short prose tail.
        for e in all_unseen_events:
            eid = e.event_id
            evidence_registry[eid] = {
                "field": getattr(e, "event_type", "unseen_event"),
                "value": e.to_dict() if hasattr(e, "to_dict") else str(e),
                "timestamp": getattr(e, "timestamp_ist", now_utc),
                "source": "unseen_events",
                "availability": "RECORDED",
            }

        # External Events
        for ee in external_events:
            evidence_registry[ee.event_id] = {
                "field": "external_event",
                "value": ee.headline,
                "timestamp": ee.published_at,
                "source": ee.source_name,
                "availability": "RECORDED",
            }

        # External Quotes
        for q in external_quotes:
            evidence_registry[f"quote:{q.symbol}"] = {
                "field": "external_quote",
                "value": q.price,
                "timestamp": now_utc,
                "source": "external_quotes",
                "availability": "RECORDED",
            }

        valid_evidence_ids = sorted(list(evidence_registry.keys()))

        # Construct deterministic packet ID and hash
        seed_content = f"{session_id}:{revision}:{len(unseen_event_ids)}:{canonical_state['spot_price']}"
        packet_hash = hashlib.sha256(seed_content.encode("utf-8")).hexdigest()
        packet_id = f"pkt_{session_id}_{revision}_{packet_hash[:8]}"

        # Compact previous thesis representation to preserve token budget
        compact_previous = None
        if previous_thesis:
            compact_previous = {
                "session_id": previous_thesis.get("session_id"),
                "thesis_evolution": previous_thesis.get("thesis_evolution"),
                "opportunity_maturity": previous_thesis.get("opportunity_maturity"),
                "counter_case": next((c.get("claim") for c in (previous_thesis.get("semantic_validation", {}).get("response", {}).get("conclusions", [])) if c.get("purpose") == "counter_case"), None),
                "unresolved_context": next((c.get("claim") for c in (previous_thesis.get("semantic_validation", {}).get("response", {}).get("conclusions", [])) if c.get("purpose") == "missing_confirmation"), None),
                "thesis_id": previous_thesis.get("thesis_id"),
                "state": previous_thesis.get("state"),
                "setup_family": previous_thesis.get("setup_family"),
                "reversal_watch": previous_thesis.get("reversal_watch"),
                "what_changed": previous_thesis.get("what_changed"),
                "canonical_state": previous_thesis.get("canonical_state"),
                "watch_next": previous_thesis.get("watch_next", [])[:3] if isinstance(previous_thesis.get("watch_next"), list) else [],
                "invalidation_conditions": previous_thesis.get("invalidation_conditions", [])[:3] if isinstance(previous_thesis.get("invalidation_conditions"), list) else [],
            }

        return BrainPacket(
            packet_id=packet_id,
            session_id=session_id,
            revision=revision,
            compiled_at=now_utc,
            canonical_state=canonical_state,
            what_changed=what_changed,
            unseen_event_ids=unseen_event_ids,
            unseen_events_summary=compact_events,
            previous_thesis=compact_previous,
            verified_external_events=ext_evts,
            external_quotes=quotes_summary,
            valid_evidence_ids=valid_evidence_ids,
            canonical_levels=sorted(list(canonical_levels)),
            episode_id=episode_id,
            temporal_relationships=temporal_relationships,
            aggression_response_sequence=aggression_response_sequence,
            option_continuity=option_continuity,
            evidence_registry=evidence_registry,
            packet_hash=packet_hash,
            cognitive_features=feature_index,
        )
