"""Deterministic AEGIS advisory orchestration with absolute safety vetoes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from .ledger import AegisDecisionLedger, AegisLedgerError
from .models import AegisConflict, AegisDecision, AegisInputSnapshot, fingerprint
from .policy import CONFLICT_PENALTIES, STALE_PENALTY, THRESHOLDS, WEIGHTS


IST = ZoneInfo("Asia/Kolkata")


class AegisService:
    def __init__(self, input_provider: Callable[..., AegisInputSnapshot], ledger=None, now_provider=None):
        self.input_provider = input_provider
        self.ledger = ledger or AegisDecisionLedger()
        self.now_provider = now_provider or (lambda: datetime.now(IST))
        self._latest: dict[tuple[str, str, str], AegisDecision] = {}
        self._read_projections: dict[tuple[str, str, str], AegisDecision] = {}

    def assess(self, symbol, requested_side="NONE", strategy_id="simple_pullback", live_path_requested=False, duplicate_request=False):
        snapshot = self.input_provider(
            symbol=str(symbol).upper(), requested_side=str(requested_side or "NONE").upper(),
            strategy_id=strategy_id, live_path_requested=bool(live_path_requested), duplicate_request=bool(duplicate_request),
        )
        semantic_fingerprint = fingerprint(snapshot.semantic_dict())
        key = (snapshot.symbol, snapshot.requested_side, snapshot.strategy_id)
        cached = self._latest.get(key)
        if cached and cached.input_fingerprint == semantic_fingerprint:
            return cached
        decision = self._decide(snapshot, semantic_fingerprint)
        try: self.ledger.append(decision)
        except AegisLedgerError: pass
        self._latest[key] = decision
        return decision

    def assess_snapshot(self, snapshot: AegisInputSnapshot):
        """Assess a caller-built typed snapshot without refreshing any provider."""
        semantic_fingerprint=fingerprint(snapshot.semantic_dict()); key=(snapshot.symbol,snapshot.requested_side,snapshot.strategy_id); cached=self._latest.get(key)
        if cached and cached.input_fingerprint==semantic_fingerprint: return cached
        decision=self._decide(snapshot,semantic_fingerprint)
        try: self.ledger.append(decision)
        except AegisLedgerError: pass
        self._latest[key]=decision; return decision

    def project(self, symbol, requested_side="NONE", strategy_id="simple_pullback", live_path_requested=False, duplicate_request=False):
        """Build a deterministic advisory projection without writing the audit ledger."""
        snapshot = self.input_provider(
            symbol=str(symbol).upper(), requested_side=str(requested_side or "NONE").upper(),
            strategy_id=strategy_id, live_path_requested=bool(live_path_requested), duplicate_request=bool(duplicate_request),
        )
        return self.project_snapshot(snapshot)

    def project_snapshot(self, snapshot: AegisInputSnapshot):
        """Project a caller-built snapshot without mutating lifecycle state."""
        semantic_fingerprint = fingerprint(snapshot.semantic_dict())
        key = (snapshot.symbol, snapshot.requested_side, snapshot.strategy_id)
        persisted = self._latest.get(key)
        if persisted and persisted.input_fingerprint == semantic_fingerprint:
            return persisted
        cached = self._read_projections.get(key)
        if cached and cached.input_fingerprint == semantic_fingerprint:
            return cached
        decision = self._decide(snapshot, semantic_fingerprint)
        self._read_projections[key] = decision
        return decision

    def status(self):
        decision = self.latest_advisory("NIFTY")
        return {"status": "READY" if decision.get("input_status") == "AVAILABLE" else "DEGRADED",
                "role": "ADVISORY_INTELLIGENCE", "mode": "ADVISORY", "advisory_only": True,
                "execution_permission": False, "execution_influence": "ZERO",
                "independent_paper_safety_authoritative": True,
                "schema_version": 1, "latest_decision": decision}

    @staticmethod
    def readiness():
        """Static GET-surface readiness; never builds inputs or appends a decision."""
        return {"status": "READY", "role": "ADVISORY_INTELLIGENCE", "mode": "ADVISORY",
                "advisory_only": True, "execution_permission": False, "execution_influence": "ZERO",
                "independent_paper_safety_authoritative": True, "schema_version": 1}

    def conflicts(self, symbol, requested_side="NONE", strategy_id="simple_pullback"):
        decision = self.latest_advisory(symbol, requested_side, strategy_id)
        return {"status": "available" if decision.get("input_status") != "UNAVAILABLE" else "unavailable",
                "symbol": decision.get("symbol"), "conflicts": list(decision.get("conflicts") or [])[:3]}

    def history(self, limit=25):
        try: rows = self.ledger.history(limit)
        except AegisLedgerError: return {"status": "unavailable", "decisions": [], "error": "AEGIS_LEDGER_UNAVAILABLE"}
        return {"status": "available", "decisions": rows, "limit": max(1, min(int(limit), 100))}

    def _decide(self, snapshot, input_fingerprint):
        hard_decision, gate_status, gate_reasons = self._hard_gates(snapshot)
        scores, contributions, coverage = self._scores(snapshot)
        conflicts = self._conflicts(snapshot)
        conflict_penalty = sum(item.score_impact for item in conflicts)
        available_weight = sum(WEIGHTS[name] for name, score in scores.items() if score is not None)
        base_score = sum(value for value in contributions.values() if value is not None)
        score = round(max(0.0, min(100.0, base_score / available_weight * 100 - conflict_penalty)), 2) if available_weight else None
        decision = hard_decision or self._threshold_decision(score, snapshot.requested_side)
        athena_size = _bounded(snapshot.athena.get("recommended_size_multiplier"), default=0.0)
        size = 0.0 if decision in {"BLOCK", "WAIT", "REJECT"} else athena_size if decision == "APPROVE" else min(athena_size, 0.75)
        missing = tuple(sorted(name for name, present in snapshot.required_input_presence.items() if not present))
        warnings = ["ADVISORY_ONLY", "NO_EXECUTION_PERMISSION", "INDEPENDENT_PAPER_SAFETY_APPLIES"]
        if snapshot.kronos_alpha.get("status") not in {"READY", "AVAILABLE"}: warnings.append("KRONOS_ALPHA_CONTEXT_UNAVAILABLE_OR_SHADOW")
        if coverage < 100: warnings.append("PARTIAL_DATA_COVERAGE")
        reasons = tuple(dict.fromkeys([*gate_reasons, *(code for conflict in conflicts for code in conflict.reason_codes)]))[:12]
        quality = "HIGH" if coverage >= 90 and not conflicts else "MEDIUM" if coverage >= 65 else "LOW"
        maturity = "DETERMINISTIC_ADVISORY_V1"
        decision_id = fingerprint({"input": input_fingerprint, "decision": decision})[:24]
        return AegisDecision(
            decision_id=decision_id, generated_at=self.now_provider().isoformat(), symbol=snapshot.symbol,
            timeframe=snapshot.timeframe, strategy_id=snapshot.strategy_id, strategy_name=snapshot.strategy_name,
            strategy_version=snapshot.strategy_version, requested_side=snapshot.requested_side,
            decision=decision, decision_score=score, decision_quality=quality,
            data_coverage_percentage=coverage, hard_gate_status=gate_status,
            hard_gate_reasons=tuple(gate_reasons), hard_gate_details=self._gate_details(snapshot),
            component_scores=scores, weighted_contributions=contributions,
            component_details=self._component_details(snapshot), conflicts=tuple(conflicts[:10]),
            recommended_size_multiplier=round(max(0.0, min(athena_size, size)), 2),
            dominant_reasons=reasons, warnings=tuple(warnings), missing_inputs=missing,
            maturity=maturity, advisory_only=True, execution_permission=False,
            risk_authorization_required=False, live_trading_enabled=snapshot.live_trading_enabled,
            source_timestamps=snapshot.source_timestamps, input_fingerprint=input_fingerprint,
            input_snapshot=snapshot.to_dict(),
        )

    def latest_advisory(self, symbol, requested_side="NONE", strategy_id="simple_pullback"):
        """Return only a previously prepared advisory; never refresh providers."""
        key = (str(symbol).upper(), str(requested_side or "NONE").upper(), str(strategy_id))
        decision = self._latest.get(key) or self._read_projections.get(key)
        if decision is not None:
            return decision.to_dict()
        now = self.now_provider().isoformat()
        return {
            "decision_id": None, "generated_at": now, "calculation_timestamp": now,
            "symbol": key[0], "requested_side": key[1], "strategy_id": key[2],
            "decision": "WAIT", "recommendation": "PAUSE", "would_recommend": "PAUSE",
            "dominant_reasons": ["AEGIS_ADVISORY_NOT_PREPARED"], "confidence": None,
            "decision_score": None, "input_snapshot": None, "input_snapshot_version": None,
            "input_fingerprint": None, "mode": "ADVISORY", "advisory_only": True,
            "execution_permission": False, "recommendation_is_execution_decision": False,
            "execution_influence": "ZERO", "input_status": "UNAVAILABLE",
            "freshness": "UNAVAILABLE", "stale_reason": None,
            "unavailable_reason": "AEGIS_ADVISORY_NOT_PREPARED",
        }

    @staticmethod
    def _gate_details(s):
        latest = str(s.risk_authorization.get("decision") or "NOT_EVALUATED").upper()
        missing = [name for name, present in s.required_input_presence.items() if not present]
        return {
            "kill_switch": {"state": "ACTIVE" if s.kill_switch_active is True else s.kill_switch_state, "reason": "KILL_SWITCH_ACTIVE" if s.kill_switch_active is True or s.kill_switch_state == "ACTIVE" else "NO_ACTIVE_KILL_SWITCH" if s.kill_switch_state == "INACTIVE" else f"KILL_SWITCH_{s.kill_switch_state}"},
            "risk_authorization": {"state": latest, "reason": s.risk_authorization.get("reason_code") or "PAPER_ENGINE_RISK_STATUS_NOT_REPORTED"},
            "market_session": {"state": s.session_state, "reason": "MARKET_OPEN" if s.session_state in {"OPEN", "SPECIAL_SESSION"} else "MARKET_CLOSED"},
            "strategy_eligibility": {"state": "ELIGIBLE" if s.strategy_eligibility.eligible else "INELIGIBLE", "reason": s.strategy_eligibility.reason_codes[0]},
            "freshness": {"state": s.market_data_freshness, "reason": "CRITICAL_MARKET_DATA_STALE" if s.market_data_freshness == "STALE" else "MARKET_DATA_FRESHNESS_ACCEPTABLE"},
            "critical_input_health": {"state": "HEALTHY" if not missing else "DEGRADED", "reason": "ALL_MANDATORY_INPUTS_PRESENT" if not missing else f"MISSING_{missing[0].upper()}"},
        }

    @staticmethod
    def _component_details(s):
        return {
            "technical": {"status": s.technical.get("status"), "freshness": s.technical.get("freshness"), "top_reason": (s.technical.get("reason_codes") or ["TECHNICAL_EVIDENCE"])[0]},
            "kronos_core": {"status": s.kronos_core.get("status"), "freshness": s.kronos_core.get("signal_age"), "top_reason": s.kronos_core.get("timing_state") or "TIMING_UNKNOWN"},
            "argus": {"status": s.argus.get("status"), "freshness": s.argus.get("freshness"), "top_reason": (s.argus.get("reason_codes") or ["ARGUS_EVIDENCE"])[0]},
            "personal_oracle": {"status": s.personal_oracle.get("status"), "freshness": s.personal_oracle.get("maturity"), "top_reason": (s.personal_oracle.get("limitations") or ["PERSONAL_EVIDENCE"])[0]},
            "hermes": {"status": s.hermes.get("status"), "freshness": s.hermes.get("freshness"), "top_reason": (s.hermes.get("reason_codes") or ["HERMES_EVIDENCE"])[0]},
            "athena": {"status": s.athena.get("status"), "freshness": "CURRENT_PROJECTION", "top_reason": (s.athena.get("reason_codes") or ["ATHENA_EVIDENCE"])[0]},
        }

    def _hard_gates(self, s):
        if s.kill_switch_active is True or s.kill_switch_state == "ACTIVE": return "BLOCK", "BLOCK", ["KILL_SWITCH_ACTIVE"]
        if s.kill_switch_state in {"UNKNOWN", "CORRUPT"}: return "BLOCK", "BLOCK", [f"KILL_SWITCH_{s.kill_switch_state}"]
        if str(s.risk_authorization.get("decision") or "").upper() == "DENY": return "BLOCK", "BLOCK", ["RISK_AUTHORIZATION_DENY"]
        if s.live_path_requested and s.live_trading_enabled is not True: return "BLOCK", "BLOCK", ["LIVE_TRADING_DISABLED"]
        if s.duplicate_request: return "BLOCK", "BLOCK", ["DUPLICATE_REQUEST"]
        if s.paper_state_health not in {"HEALTHY"} or s.kill_switch_state not in {"ACTIVE", "INACTIVE", "UNKNOWN", "CORRUPT"} or s.live_trading_enabled is None:
            return "BLOCK", "MALFORMED", ["CRITICAL_SYSTEM_STATE_UNAVAILABLE"]
        if s.session_state not in {"OPEN", "SPECIAL_SESSION"}: return "WAIT", "WAIT", ["MARKET_CLOSED"]
        if not s.strategy_eligibility.eligible: return "REJECT", "REJECT", list(s.strategy_eligibility.reason_codes)
        mandatory_missing = [name for name in s.strategy_eligibility.required_modules if not s.required_input_presence.get(name, False)]
        if mandatory_missing: return "WAIT", "WAIT", [f"MANDATORY_{name.upper()}_UNAVAILABLE" for name in mandatory_missing]
        if s.market_data_freshness == "STALE": return "WAIT", "WAIT", ["CRITICAL_MARKET_DATA_STALE"]
        if str(s.athena.get("recommendation") or "").upper() in {"PAUSE", "STOP"}: return "WAIT", "WAIT", ["ATHENA_PAUSE"]
        if not _hermes_provider_unconfigured(s.hermes) and str(s.hermes.get("recommendation") or "").upper() in {"WAIT", "AVOID_NEW_TRADES"}: return "WAIT", "WAIT", ["HERMES_EVENT_WAIT"]
        side_direction = _side_direction(s.requested_side)
        technical_direction = _direction(s.technical.get("signal") or s.technical.get("bias"))
        if side_direction and technical_direction and side_direction != technical_direction: return "REJECT", "REJECT", ["OPPOSITE_TECHNICAL_SIGNAL"]
        argus_direction = _direction(s.argus.get("verdict")); argus_confidence = _number(s.argus.get("confidence")) or 0
        if side_direction and argus_direction and side_direction != argus_direction and argus_confidence >= 80:
            return "REJECT", "REJECT", ["MANDATORY_ARGUS_STRONGLY_OPPOSITE"]
        core_direction = _direction(s.kronos_core.get("trend")); technical_confidence = _number(s.technical.get("confidence")) or 0
        if technical_direction and core_direction and technical_direction != core_direction and technical_confidence >= 75:
            return "WAIT", "WAIT", ["HIGH_CONFIDENCE_MODULE_CONFLICT"]
        if str(s.kronos_core.get("timing_state") or "").upper() in {"INVALID", "WAIT", "BLOCKED"}: return "REJECT", "REJECT", ["KRONOS_TIMING_INVALID"]
        if s.requested_side == "CE" and side_direction != "BULLISH" or s.requested_side == "PE" and side_direction != "BEARISH":
            return "REJECT", "REJECT", ["OPTION_SIDE_DIRECTION_MISMATCH"]
        reversal = _number(s.kronos_alpha.get("reversal_probability")); persistence = _number(s.kronos_alpha.get("persistence"))
        if reversal is not None and persistence is not None and reversal >= 0.65 and persistence < 0.5: return "REJECT", "REJECT", ["HIGH_REVERSAL_LOW_PERSISTENCE"]
        quality = _number(s.kronos_alpha.get("option_buying_quality"))
        if quality is not None and quality < s.strategy_eligibility.minimum_option_buying_quality: return "REJECT", "REJECT", ["OPTION_BUYING_QUALITY_LOW"]
        if s.requested_side == "NONE": return "WAIT", "WAIT", ["ASSESSMENT_ONLY_NO_REQUESTED_SIDE"]
        return None, "CLEAR", []

    def _scores(self, s):
        aligned = _side_direction(s.requested_side)
        scores = {
            "technical": self._technical_score(s.technical, aligned),
            "kronos_core": _bounded_or_none(s.kronos_core.get("setup_quality")),
            "argus": self._directional_score(s.argus.get("confidence"), s.argus.get("verdict"), aligned),
            "personal_oracle": self._oracle_score(s.personal_oracle),
            "hermes": self._hermes_score(s.hermes),
            "athena": _bounded_or_none((_number(s.athena.get("recommended_size_multiplier")) or 0) * 100) if s.athena.get("status") else None,
        }
        freshness = {"technical": s.technical.get("freshness"), "argus": s.argus.get("freshness")}
        for name, state in freshness.items():
            if scores[name] is not None and str(state).upper() == "STALE": scores[name] = round(scores[name] * STALE_PENALTY, 2)
        contributions = {name: round(score * WEIGHTS[name] / 100, 4) if score is not None else None for name, score in scores.items()}
        coverage = round(sum(WEIGHTS[name] for name, score in scores.items() if score is not None), 2)
        return scores, contributions, coverage

    @staticmethod
    def _technical_score(data, direction):
        confidence = _bounded_or_none(data.get("confidence"))
        return AegisService._directional_score(confidence, data.get("signal") or data.get("bias"), direction)

    @staticmethod
    def _directional_score(confidence, verdict, direction):
        confidence = _bounded_or_none(confidence)
        if confidence is None: return None
        observed = _direction(verdict)
        if not direction or not observed: return max(50.0, confidence)
        return confidence if observed == direction else max(0.0, 100.0 - confidence)

    @staticmethod
    def _oracle_score(data):
        recommendation = str(data.get("recommendation") or "").upper()
        return {"PREFER": 80.0, "MAINTAIN": 75.0, "OBSERVE": 55.0, "IMPROVE": 40.0, "AVOID": 20.0}.get(recommendation)

    @staticmethod
    def _hermes_score(data):
        if _hermes_provider_unconfigured(data):
            return None
        recommendation = str(data.get("recommendation") or "").upper()
        return {"NORMAL": 100.0, "CONTINUE": 100.0, "CAUTION": 60.0, "WAIT": 20.0, "AVOID_NEW_TRADES": 0.0}.get(recommendation)

    def _conflicts(self, s):
        conflicts = []
        requested = _side_direction(s.requested_side); technical = _direction(s.technical.get("signal") or s.technical.get("bias"))
        modules = [("ARGUS", _direction(s.argus.get("verdict"))), ("KRONOS_CORE", _direction(s.kronos_core.get("trend")))]
        for module, direction in modules:
            if technical and direction and technical != direction:
                conflicts.append(self._conflict(f"technical-{module.lower()}", ("TECHNICAL", module), f"Technical direction conflicts with {module}.", "HIGH", "Wait for alignment.", ("DIRECTION_CONFLICT",)))
        if requested and technical and requested != technical:
            conflicts.append(self._conflict("side-technical", ("REQUESTED_SIDE", "TECHNICAL"), "Requested side opposes Technical direction.", "CRITICAL", "Reject the requested side.", ("SIDE_DIRECTION_CONFLICT",)))
        reversal = _number(s.kronos_alpha.get("reversal_probability")); uncertainty = _number(s.kronos_alpha.get("uncertainty"))
        if reversal is not None and reversal >= .65 or uncertainty is not None and uncertainty >= .65:
            conflicts.append(self._conflict("alpha-risk", ("TECHNICAL", "KRONOS_ALPHA"), "Shadow forecast indicates elevated reversal or uncertainty.", "MEDIUM", "Reduce decision quality; KRONOS ALPHA retains zero direct weight.", ("ALPHA_CONTEXT_RISK",)))
        if not _hermes_provider_unconfigured(s.hermes) and str(s.hermes.get("recommendation") or "").upper() in {"WAIT", "AVOID_NEW_TRADES"}:
            conflicts.append(self._conflict("hermes-event", ("SETUP", "HERMES"), "Setup overlaps elevated event risk.", "CRITICAL", "Wait for event risk to clear.", ("EVENT_RISK_CONFLICT",)))
        if str(s.athena.get("recommendation") or "").upper() in {"REDUCE", "PAUSE", "STOP"}:
            severity = "HIGH" if str(s.athena.get("recommendation")).upper() in {"PAUSE", "STOP"} else "MEDIUM"
            conflicts.append(self._conflict("athena-risk", ("SETUP", "ATHENA"), "Setup strength conflicts with current risk guidance.", severity, "Use Athena size cap or wait.", ("RISK_GUIDANCE_CONFLICT",)))
        return sorted(conflicts, key=lambda item: (-{"LOW":1,"MEDIUM":2,"HIGH":3,"CRITICAL":4}[item.severity], item.conflict_id))

    @staticmethod
    def _conflict(identifier, modules, description, severity, resolution, reasons):
        return AegisConflict(identifier, modules, description, severity, resolution, CONFLICT_PENALTIES[severity], reasons)

    @staticmethod
    def _threshold_decision(score, side):
        if side == "NONE": return "WAIT"
        if score is None: return "WAIT"
        if score >= THRESHOLDS["approve"]: return "APPROVE"
        if score >= THRESHOLDS["approve_reduced"]: return "APPROVE_REDUCED"
        if score >= THRESHOLDS["wait"]: return "WAIT"
        return "REJECT"


def _number(value):
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None

def _bounded(value, default=0.0):
    number = _number(value); return max(0.0, min(1.0, number if number is not None else default))

def _bounded_or_none(value):
    number = _number(value); return max(0.0, min(100.0, number)) if number is not None else None

def _direction(value):
    text = str(value or "").upper()
    if any(token in text for token in ("BULL", "BUY", "LONG", "CE")): return "BULLISH"
    if any(token in text for token in ("BEAR", "SELL", "SHORT", "PE")): return "BEARISH"
    return None

def _side_direction(side):
    return "BULLISH" if side in {"CE", "LONG"} else "BEARISH" if side in {"PE", "SHORT"} else None

def _hermes_provider_unconfigured(data):
    reasons = {str(value).upper() for value in (data.get("reason_codes") or [])}
    return str(data.get("status") or "").upper() in {"UNAVAILABLE", "NOT_CONFIGURED"} and "EXTERNAL_PROVIDER_NOT_CONFIGURED" in reasons
