"""Non-authoritative observer that records authoritative decision evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

from .journal import EvidenceJournal


NOT_EVALUATED = {"status": "NOT_EVALUATED", "reason": "UPSTREAM_DID_NOT_REACH_COMPONENT"}


def _mapping(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return deepcopy(dict(value)) if isinstance(value, Mapping) else value


class DecisionEvidenceRecorder:
    """Records evidence only; every method fails isolated from production flow."""

    def __init__(self, journal=None):
        self.journal = journal or EvidenceJournal()
        self.last_error = None

    def scheduler(self, event, *, timestamp, detail=None):
        return self._safe_append(
            "SCHEDULER_LIFECYCLE",
            {"scheduler": "REAL_MARKET_PAPER_ORCHESTRATOR", "event": str(event), "detail": detail},
            event_at=timestamp,
        )

    def paper_lifecycle(self, event, *, timestamp, candle_id=None, payload=None):
        return self._safe_append(
            "PAPER_EXECUTION_LIFECYCLE",
            {"event": str(event), **deepcopy(dict(payload or {}))},
            candle_id=candle_id,
            event_at=timestamp,
            idempotency_key=f"paper-lifecycle|{event}|{candle_id or timestamp}",
        )

    def decision_envelope(
        self,
        *,
        candle,
        context,
        signal,
        final_state,
        final_reason,
        aegis_snapshot=None,
        aegis_decision=None,
        argus=None,
        contract=None,
        risk=None,
        paper_result=None,
    ):
        candle_id = str(candle["timestamp"])
        pullback = self.pullback_conditions(context, signal)
        snapshot = _mapping(aegis_snapshot) if aegis_snapshot is not None else {}
        decision = _mapping(aegis_decision) if aegis_decision is not None else deepcopy(NOT_EVALUATED)
        risk_value = _mapping(risk) if risk is not None else {
            "status": "NOT_EVALUATED",
            "readiness": "NOT_DETERMINABLE",
            "reason": "AEGIS_OR_CONTRACT_GATE_PREVENTED_AUTHORIZATION",
        }
        paper_value = _mapping(paper_result) if paper_result is not None else deepcopy(NOT_EVALUATED)
        first_rejecting, rejection_chain = self._rejection(decision, risk_value, final_state, final_reason)
        option_candidates = self.option_candidates(argus)
        payload = {
            "envelope_version": 1,
            "immutable": True,
            "symbol": getattr(context, "symbol", "NIFTY"),
            "timeframe": "5m",
            "candle": deepcopy(dict(candle)),
            "technical": {
                "indicators": deepcopy(context.indicators),
                "structure_v1": deepcopy(context.structure_v1),
                "structure_v2": deepcopy(context.structure_v2),
                "liquidity": deepcopy(context.liquidity),
                "fvg": deepcopy(context.fvg),
                "order_block": deepcopy(context.order_block),
                "timeframe": deepcopy(context.timeframe),
                "features": deepcopy(context.features),
            },
            "kronos_core": deepcopy(context.kronos),
            "pullback_conditions": pullback,
            "strategy": deepcopy(dict(signal)),
            "modules": {
                "kronos_alpha": deepcopy(snapshot.get("kronos_alpha", NOT_EVALUATED)),
                "chronos_2": deepcopy(snapshot.get("chronos_2", {"status": "NOT_EXPOSED_TO_AEGIS", "reason": "SHADOW_ONLY"})),
                "argus": deepcopy(snapshot.get("argus", _mapping(argus) if argus is not None else NOT_EVALUATED)),
                "athena": deepcopy(snapshot.get("athena", NOT_EVALUATED)),
                "personal_oracle": deepcopy(snapshot.get("personal_oracle", NOT_EVALUATED)),
                "hermes": deepcopy(snapshot.get("hermes", NOT_EVALUATED)),
                "aegis_input": snapshot or deepcopy(NOT_EVALUATED),
                "aegis_decision": decision,
                "risk": risk_value,
                "paper_execution": paper_value,
            },
            "aegis_evidence_composition": self._aegis_composition(decision),
            "risk_readiness": risk_value,
            "contract_candidates": option_candidates,
            "resolved_contract": _mapping(contract) if contract is not None else None,
            "chronos_lead_lag": self._chronos_lead_lag(candle_id, snapshot),
            "why_no_trade": {
                "first_rejecting_module": first_rejecting,
                "rejection_chain": rejection_chain,
                "rejection_reason": str(final_reason),
                "missing_evidence": list(decision.get("missing_inputs") or []),
                "confidence": signal.get("confidence"),
                "decision_timestamp": decision.get("generated_at") or candle.get("candle_closed_at"),
            },
            "final_decision": {"state": str(final_state), "reason": str(final_reason)},
            "data_lineage": {
                "source_timestamps": deepcopy(snapshot.get("source_timestamps", {})),
                "candle_source": candle.get("source"),
                "closed_candle_only": bool(candle.get("closed") is True or candle.get("is_closed") is True),
            },
            "limitations": self._limitations(snapshot, argus),
        }
        transition = self._record_regime_transition(candle_id, context)
        record = self._safe_append(
            "CANDLE_DECISION_ENVELOPE",
            payload,
            candle_id=candle_id,
            event_at=candle.get("candle_closed_at") or candle_id,
            idempotency_key=f"decision-envelope|{candle_id}",
        )
        return {"record": record, "regime_transition": transition}

    @staticmethod
    def pullback_conditions(context, signal):
        indicators = context.indicators
        close, ema21, ema38 = indicators.get("close"), indicators.get("ema_21"), indicators.get("ema_38")
        bias = str(context.kronos.get("bias") or "UNKNOWN")
        bullish = bool(close is not None and ema21 is not None and ema38 is not None and close > ema21 > ema38)
        bearish = bool(close is not None and ema21 is not None and ema38 is not None and close < ema21 < ema38)
        return {
            "algorithm": "FROZEN_SIMPLE_PULLBACK_PRODUCTION_RULE",
            "indicators_present": all(value is not None for value in (close, ema21, ema38)),
            "kronos_bias": bias,
            "bullish_ema_alignment": bullish,
            "bearish_ema_alignment": bearish,
            "eligible": signal.get("signal") in {"BUY", "SELL"},
            "result": signal.get("reason"),
            "independent_proximity_rule": "NOT_IMPLEMENTED_IN_FROZEN_STRATEGY",
        }

    @staticmethod
    def option_candidates(argus):
        data = argus.get("data") if isinstance(argus, Mapping) else None
        if not isinstance(data, Mapping):
            return {"status": "NOT_EVALUATED", "candidates": [], "reason": "ARGUS_SNAPSHOT_UNAVAILABLE"}
        underlying = data.get("underlying") or {}
        atm = underlying.get("atm_strike")
        rows = data.get("atm_window") or []
        by_strike = {float(row["strike"]): row for row in rows if row.get("strike") is not None}
        strikes = sorted(by_strike)
        if atm is None or float(atm) not in strikes:
            return {"status": "UNAVAILABLE", "candidates": [], "reason": "ATM_STRIKE_UNAVAILABLE"}
        index = strikes.index(float(atm))
        selected = {"ATM": float(atm)}
        if index + 1 < len(strikes): selected["ATM_PLUS_1"] = strikes[index + 1]
        if index - 1 >= 0: selected["ITM_CALL_OR_OTM_PUT"] = strikes[index - 1]
        candidates = []
        for label, strike in selected.items():
            row = by_strike[strike]
            candidates.append({
                "classification": label,
                "strike": strike,
                "expiry": underlying.get("expiry"),
                "ce": deepcopy(row.get("ce")),
                "pe": deepcopy(row.get("pe")),
                "instrument_master_resolved": False,
            })
        return {
            "status": "OBSERVED_ARGUS_CANDIDATES",
            "candidates": candidates,
            "reason": "NON_SELECTED_CANDIDATES_NOT_RESOLVED_AGAINST_INSTRUMENT_MASTER",
        }

    def _record_regime_transition(self, candle_id, context):
        current = str(context.kronos.get("regime") or context.regime or "UNKNOWN")
        previous_rows = self.journal.records(event_type="KRONOS_REGIME_TRANSITION")
        previous = previous_rows[-1]["payload"].get("to_regime") if previous_rows else None
        if previous == current:
            return None
        return self._safe_append(
            "KRONOS_REGIME_TRANSITION",
            {"symbol": getattr(context, "symbol", "NIFTY"), "timeframe": "5m", "from_regime": previous, "to_regime": current, "source": "KRONOS_CORE_OUTPUT"},
            candle_id=candle_id,
            idempotency_key=f"kronos-regime|{candle_id}|{current}",
        )

    @staticmethod
    def _aegis_composition(decision):
        return {
            "component_scores": deepcopy(decision.get("component_scores", {})),
            "weighted_contributions": deepcopy(decision.get("weighted_contributions", {})),
            "hard_gate_reasons": list(decision.get("hard_gate_reasons") or []),
            "conflicts": deepcopy(decision.get("conflicts", [])),
            "dominant_reasons": list(decision.get("dominant_reasons") or []),
            "coverage_percentage": decision.get("data_coverage_percentage"),
            "input_fingerprint": decision.get("input_fingerprint"),
        }

    @staticmethod
    def _rejection(aegis, risk, state, reason):
        chain = []
        decision = str(aegis.get("decision") or "NOT_EVALUATED")
        if decision not in {"APPROVE", "APPROVE_REDUCED", "NOT_EVALUATED"}:
            chain.append({"module": "AEGIS", "decision": decision, "reasons": list(aegis.get("hard_gate_reasons") or aegis.get("dominant_reasons") or [])})
        risk_decision = str(risk.get("decision") or risk.get("status") or "NOT_EVALUATED")
        if risk_decision in {"DENY", "BLOCK", "BLOCKED"}:
            chain.append({"module": "RISK", "decision": risk_decision, "reasons": [risk.get("reason_code") or risk.get("reason")]})
        if not chain and str(state) in {"WAITING", "BLOCKED", "DENIED", "SKIPPED"}:
            chain.append({"module": "STRATEGY_OR_ORCHESTRATOR", "decision": str(state), "reasons": [str(reason)]})
        return (chain[0]["module"] if chain else None), chain

    @staticmethod
    def _chronos_lead_lag(candle_id, snapshot):
        timestamps = snapshot.get("source_timestamps") or {}
        origin = timestamps.get("chronos_2") or timestamps.get("chronos")
        if not origin:
            return {"status": "NOT_DETERMINABLE", "minutes": None, "reason": "CHRONOS_ORIGIN_NOT_EXPOSED_TO_AEGIS"}
        try:
            delta = datetime.fromisoformat(candle_id) - datetime.fromisoformat(str(origin))
            return {"status": "OBSERVED", "minutes": delta.total_seconds() / 60, "chronos_origin": origin, "decision_candle": candle_id}
        except (TypeError, ValueError):
            return {"status": "NOT_DETERMINABLE", "minutes": None, "reason": "TIMESTAMP_FORMAT_INCOMPATIBLE"}

    @staticmethod
    def _limitations(snapshot, argus):
        limitations = []
        if "chronos_2" not in snapshot:
            limitations.append("CHRONOS_2_IS_SHADOW_ONLY_AND_NOT_AN_AEGIS_INPUT")
        if argus is not None:
            limitations.append("OPTION_CHAIN_SNAPSHOT_IS_NOT_TIMESTAMP_ALIGNED_OPTION_CANDLE_HISTORY")
            limitations.append("ATM_PLUS_1_AND_ITM_CANDIDATES_ARE_OBSERVED_BUT_NOT_INSTRUMENT_MASTER_RESOLVED")
        return limitations

    def _safe_append(self, event_type, payload, **kwargs):
        try:
            record, _ = self.journal.append(event_type, payload, **kwargs)
            self.last_error = None
            return record
        except Exception as error:
            self.last_error = str(error)
            return None
