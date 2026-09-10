"""Read-only adapters from existing module projections into one AEGIS snapshot."""

from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

from .models import AegisInputSnapshot
from .policy import strategy_eligibility


IST = ZoneInfo("Asia/Kolkata")


class AegisInputBuilder:
    def __init__(self, *, technical, argus, dashboard_cache, kronos_alpha, athena, hermes, personal_oracle, risk, paper, session, now_provider=None):
        self.technical = technical; self.argus = argus; self.dashboard_cache = dashboard_cache
        self.kronos_alpha = kronos_alpha; self.athena = athena; self.hermes = hermes
        self.personal_oracle = personal_oracle; self.risk = risk; self.paper = paper; self.session = session
        self.now_provider = now_provider or (lambda: datetime.now(IST))

    def __call__(self, *, symbol, requested_side, strategy_id, live_path_requested, duplicate_request, technical_override=None, core_override=None, session_override=None, risk_decision_override=None):
        technical = _mapping(technical_override) if technical_override is not None else _mapping(self.technical(symbol)); argus = _mapping(self.argus(symbol))
        alpha = _mapping(self.kronos_alpha()); athena = _mapping(self.athena()); hermes = _mapping(self.hermes())
        personal = _mapping(self.personal_oracle()); risk = _mapping(self.risk()); paper = _mapping(self.paper()); session = _mapping(session_override) if session_override is not None else _mapping(self.session())
        core = _mapping(core_override) if core_override is not None else self._kronos_core(symbol)
        return self._compose(symbol=symbol, requested_side=requested_side, strategy_id=strategy_id,
            live_path_requested=live_path_requested, duplicate_request=duplicate_request,
            technical=technical, argus=argus, alpha=alpha, athena=athena, hermes=hermes,
            personal=personal, risk=risk, paper=paper, session=session, core=core,
            risk_decision_override=risk_decision_override)

    def from_prepared(self, *, symbol, requested_side, strategy_id, live_path_requested, duplicate_request, prepared):
        """Compose from one immutable caller-prepared snapshot without provider reads."""
        source = _mapping(prepared)
        return self._compose(symbol=symbol, requested_side=requested_side, strategy_id=strategy_id,
            live_path_requested=live_path_requested, duplicate_request=duplicate_request,
            technical=_mapping(source.get("technical")), argus=_mapping(source.get("argus")),
            alpha=_mapping(source.get("kronos_alpha")), athena=_mapping(source.get("athena")),
            hermes=_mapping(source.get("hermes")), personal=_mapping(source.get("personal_oracle")),
            risk=_mapping(source.get("risk")), paper=_mapping(source.get("paper")),
            session=_mapping(source.get("session")), core=_mapping(source.get("kronos_core")),
            risk_decision_override=source.get("risk_decision"))

    def _compose(self, *, symbol, requested_side, strategy_id, live_path_requested, duplicate_request,
                 technical, argus, alpha, athena, hermes, personal, risk, paper, session, core,
                 risk_decision_override=None):
        now = self.now_provider()
        argus_data = _mapping(argus.get("data")); argus_underlying = _mapping(argus_data.get("underlying")); argus_verdict = _mapping(argus_data.get("verdict"))
        side_outlook = _mapping(_mapping(alpha.get("outlooks")).get(requested_side.lower())) if requested_side in {"CE", "PE"} else {}
        coaching = _mapping(personal.get("coaching")); recommendations = coaching.get("recommendations") if isinstance(coaching.get("recommendations"), list) else []
        personal_recommendation = _mapping(recommendations[0]).get("state") if recommendations else None
        technical_contract = {
            "status": technical.get("oracle_status"), "bias": technical.get("directional_bias"),
            "signal": technical.get("signal"), "confidence": technical.get("confidence"),
            "regime": technical.get("regime"), "freshness": technical.get("data_status"),
            "reason_codes": technical.get("reason_codes") or [],
        }
        argus_contract = {
            "status": argus.get("status") or "UNAVAILABLE", "verdict": argus_verdict.get("bias"),
            "confidence": argus_verdict.get("confidence"), "freshness": argus.get("freshness") or "UNAVAILABLE",
            "alignment": argus_verdict.get("preferred_option_side"), "reason_codes": argus_verdict.get("reasons") or [],
        }
        alpha_contract = {
            "status": alpha.get("model_status"), "expected_direction": alpha.get("expected_direction"),
            "bullish_probability": alpha.get("bullish_probability"), "bearish_probability": alpha.get("bearish_probability"),
            "sideways_probability": alpha.get("sideways_probability"), "persistence": alpha.get("trend_persistence_probability"),
            "reversal_probability": alpha.get("reversal_probability"), "volatility": alpha.get("forecast_volatility"),
            "uncertainty": alpha.get("forecast_uncertainty"), "forecast_quality": _mapping(alpha.get("outlooks")).get("forecast_quality_score"),
            "option_buying_quality": side_outlook.get("option_buying_quality_score"), "freshness": alpha.get("cache_status"),
            "shadow": True, "direct_execution_weight": 0,
        }
        athena_contract = {"status": athena.get("athena_status"), "risk_state": athena.get("risk_state"),
                            "recommendation": athena.get("recommendation"), "recommended_size_multiplier": athena.get("recommended_size_multiplier"),
                            "headroom": athena.get("risk_headroom_percentage"), "reason_codes": athena.get("reason_codes") or []}
        hermes_contract = {"status": hermes.get("hermes_status"), "event_risk": hermes.get("overall_event_risk"),
                           "recommendation": hermes.get("recommendation"), "sentiment": hermes.get("dominant_sentiment"),
                           "next_event": hermes.get("next_major_event"), "freshness": _mapping(hermes.get("freshness_metadata")).get("snapshot_age_seconds"),
                           "reason_codes": hermes.get("reason_codes") or []}
        personal_contract = {"status": personal.get("status"), "maturity": personal.get("maturity"),
                             "context_coverage": _mapping(personal.get("coverage")).get("complete_context_percentage"),
                             "behavior_coverage": _mapping(personal.get("behavior")).get("behavioral_coverage_percentage"),
                             "recommendation": personal_recommendation, "limitations": personal.get("limitations") or []}
        eligibility = strategy_eligibility(strategy_id, symbol, "5m", str(session.get("session_state") or "UNKNOWN"), technical.get("regime"))
        required = {"technical": technical_contract["status"] not in {None, "UNAVAILABLE"},
                    "argus": argus_contract["status"] in {"available", "stale"},
                    "kronos_core": core.get("status") == "AVAILABLE", "athena": athena_contract["status"] not in {None, "UNAVAILABLE"}}
        latest_auth = _mapping(risk_decision_override) if risk_decision_override is not None else _mapping(risk.get("latest_authorization"))
        return AegisInputSnapshot(
            generated_at=now.isoformat(), symbol=symbol, timeframe="5m", strategy_id=eligibility.strategy_id,
            strategy_name=eligibility.strategy_name, strategy_version=eligibility.strategy_version,
            requested_side=requested_side, session_state=str(session.get("session_state") or "UNKNOWN"),
            session_date=str(session.get("session_date") or now.date().isoformat()), technical=technical_contract,
            argus=argus_contract, kronos_core=core, kronos_alpha=alpha_contract, athena=athena_contract,
            hermes=hermes_contract, personal_oracle=personal_contract,
            risk_authorization={"decision": latest_auth.get("decision"), "reason_code": latest_auth.get("reason_code")},
            kill_switch_active=risk.get("kill_switch_active"), kill_switch_state=str(risk.get("kill_switch_state") or "UNKNOWN"),
            live_trading_enabled=risk.get("live_trading_enabled"),
            live_path_requested=live_path_requested, paper_state_health=str(paper.get("state_health") or "UNAVAILABLE"),
            market_data_freshness=str(technical_contract["freshness"] or "UNAVAILABLE"), duplicate_request=duplicate_request,
            strategy_eligibility=eligibility, required_input_presence=required,
            source_timestamps={"technical": technical.get("market_data_as_of"), "argus": argus_underlying.get("fetched_at"),
                               "kronos_alpha": alpha.get("last_inference_at"), "athena": athena.get("generated_at"),
                               "hermes": hermes.get("generated_at"), "personal_oracle": _mapping(personal.get("behavior")).get("latest_update"),
                               "risk": risk.get("last_updated"), "paper": paper.get("last_updated")},
        )

    def _kronos_core(self, symbol):
        source = self.dashboard_cache()
        if not isinstance(source, Mapping): return {"status": "UNAVAILABLE", "setup_quality": None, "timing_state": "UNKNOWN"}
        snapshot = _mapping(source.get("snapshot")); rows = snapshot.get("scanner")
        row = next((item for item in rows if isinstance(item, Mapping) and str(item.get("symbol")).upper() == symbol), None) if isinstance(rows, list) else None
        if not isinstance(row, Mapping): return {"status": "UNAVAILABLE", "setup_quality": None, "timing_state": "UNKNOWN"}
        context = row.get("context"); kronos = getattr(context, "kronos", {}) if context is not None else {}; scores = _mapping(_mapping(kronos).get("scores"))
        return {"status": "AVAILABLE", "setup_quality": row.get("smart_score") or row.get("confidence"),
                "timing_state": "VALID" if str(row.get("pullback_signal") or "WAIT").upper() in {"BUY", "SELL"} else "WAIT",
                "trend": _mapping(kronos).get("bias") or row.get("bias"), "momentum": scores.get("momentum_score"),
                "liquidity": getattr(context, "liquidity", None), "structure": getattr(context, "structure_v2", None),
                "session_quality": row.get("regime"), "signal_age": source.get("age_seconds")}


def _mapping(value):
    return value if isinstance(value, Mapping) else {}
