"""Weighted development-only evidence policy; production AEGIS is untouched."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


class DevelopmentWeightedDecisionEngine:
    WEIGHTS = {
        "technical": 30,
        "kronos_core": 20,
        "argus": 15,
        "kronos_alpha": 10,
        "chronos_2": 10,
        "athena": 5,
        "oracle": 5,
        "hermes": 5,
    }
    ALLOW_THRESHOLD = 60.0

    def __init__(self, clock=None):
        self.clock = clock or (lambda: datetime.now(IST))

    def assess(self, *, symbol, timeframe, candle_timestamp, signal, evidence, safety):
        hard_vetoes = self._hard_vetoes(signal, safety)
        direction = "BULLISH" if signal.get("signal") == "BUY" else "BEARISH" if signal.get("signal") == "SELL" else None
        votes = {
            "technical": self._directional(evidence.get("technical"), direction, "direction", "confidence"),
            "kronos_core": self._directional(evidence.get("kronos_core"), direction, "direction", "confidence"),
            "argus": self._directional(evidence.get("argus"), direction, "direction", "confidence"),
            "kronos_alpha": self._directional(evidence.get("kronos_alpha"), direction, "direction", "confidence"),
            "chronos_2": self._directional(evidence.get("chronos_2"), direction, "direction", "confidence"),
            "athena": self._categorical(evidence.get("athena"), {"CONTINUE": 100, "NORMAL": 100, "REDUCE": 60, "CAUTION": 55, "PAUSE": 20, "STOP": 0}),
            "oracle": self._categorical(evidence.get("oracle"), {"PREFER": 85, "MAINTAIN": 75, "OBSERVE": 55, "IMPROVE": 40, "AVOID": 20}),
            "hermes": self._categorical(evidence.get("hermes"), {"NORMAL": 100, "CONTINUE": 100, "CAUTION": 60, "WAIT": 20, "AVOID_NEW_TRADES": 0}),
        }
        contributions = {}
        available_weight = 0
        weighted_score = 0.0
        missing = []
        for module, weight in self.WEIGHTS.items():
            vote = votes[module]
            if vote["score"] is None:
                contributions[module] = None
                missing.append(module)
                continue
            available_weight += weight
            contribution = round(weight * vote["score"] / 100, 4)
            contributions[module] = contribution
            weighted_score += contribution
        weighted_score = round(weighted_score, 2)
        coverage = round(available_weight, 2)
        decision = "BLOCK" if hard_vetoes else "ALLOW" if weighted_score >= self.ALLOW_THRESHOLD else "WAIT"
        why_trade = [f"{name.upper()}_{votes[name]['vote']}" for name in self.WEIGHTS if contributions[name] is not None and votes[name]["score"] >= 60]
        why_not = [*hard_vetoes, *[f"{name.upper()}_UNAVAILABLE" for name in missing], *[f"{name.upper()}_{votes[name]['vote']}" for name in self.WEIGHTS if contributions[name] is not None and votes[name]["score"] < 50]]
        generated_at = self.clock().isoformat()
        fingerprint = hashlib.sha256(json.dumps({"candle": candle_timestamp, "signal": signal, "votes": votes, "safety": safety}, sort_keys=True, default=str).encode()).hexdigest()
        return {
            "schema_version": 1,
            "mode": "DEVELOPMENT",
            "decision_id": f"dev_{fingerprint[:24]}",
            "generated_at": generated_at,
            "symbol": symbol,
            "timeframe": timeframe,
            "candle_timestamp": candle_timestamp,
            "decision": decision,
            "weighted_score": weighted_score,
            "allow_threshold": self.ALLOW_THRESHOLD,
            "data_coverage_percentage": coverage,
            "module_votes": votes,
            "module_contributions": contributions,
            "missing_optional_evidence": missing,
            "hard_vetoes": hard_vetoes,
            "why_trade": why_trade if decision == "ALLOW" else [],
            "why_not_trade": why_not if decision != "ALLOW" else [],
            "confidence": weighted_score,
            "production_aegis_used": False,
            "production_state_mutated": False,
            "live_trading_enabled": False,
            "broker_submission": False,
            "input_fingerprint": fingerprint,
            "evidence": deepcopy(evidence),
        }

    @staticmethod
    def _hard_vetoes(signal, safety):
        reasons = []
        if safety.get("live_trading_enabled") is not False: reasons.append("LIVE_TRADING_STATE_UNSAFE")
        if safety.get("kill_switch_state") != "INACTIVE": reasons.append(f"KILL_SWITCH_{safety.get('kill_switch_state','UNKNOWN')}")
        if safety.get("session_state") not in {"OPEN", "SPECIAL_SESSION"}: reasons.append("MARKET_CLOSED")
        if safety.get("paper_state_health") != "HEALTHY": reasons.append("DEVELOPMENT_PAPER_STATE_UNAVAILABLE")
        if safety.get("closed_candle") is not True: reasons.append("INCOMPLETE_CANDLE")
        if safety.get("market_data_fresh") is not True: reasons.append("STALE_MARKET_DATA")
        if signal.get("signal") not in {"BUY", "SELL"}: reasons.append("NO_DIRECTIONAL_STRATEGY_SIGNAL")
        return reasons

    @staticmethod
    def _directional(data, requested, direction_key, confidence_key):
        if not isinstance(data, dict) or data.get("available") is False:
            return {"vote": "UNAVAILABLE", "score": None, "direction": None, "confidence": None}
        observed = _direction(data.get(direction_key))
        confidence = _number(data.get(confidence_key))
        if observed is None or confidence is None:
            return {"vote": "UNAVAILABLE", "score": None, "direction": observed, "confidence": confidence}
        confidence = max(0.0, min(100.0, confidence))
        if observed == "NEUTRAL": score, vote = 50.0, "NEUTRAL"
        elif observed == requested: score, vote = confidence, "ALIGNED"
        else: score, vote = 100.0 - confidence, "OPPOSED"
        return {"vote": vote, "score": round(score, 2), "direction": observed, "confidence": confidence}

    @staticmethod
    def _categorical(data, mapping):
        if not isinstance(data, dict) or data.get("available") is False:
            return {"vote": "UNAVAILABLE", "score": None, "direction": None, "confidence": None}
        value = str(data.get("recommendation") or "").upper()
        score = mapping.get(value)
        return {"vote": value or "UNAVAILABLE", "score": float(score) if score is not None else None, "direction": None, "confidence": None}


def _number(value):
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None


def _direction(value):
    text = str(value or "").upper()
    if any(token in text for token in ("BULL", "BUY", "LONG", "CE")): return "BULLISH"
    if any(token in text for token in ("BEAR", "SELL", "SHORT", "PE")): return "BEARISH"
    if any(token in text for token in ("SIDE", "NEUTRAL", "MIXED", "RANGE")): return "NEUTRAL"
    return None
