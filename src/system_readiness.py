"""Read-only deterministic open-market readiness and next-session planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from src.kronos_alpha.config import KronosAlphaConfig


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class ReadinessItem:
    component: str
    status: str
    reason: str
    required_condition: str
    last_checked: str
    blocking: bool
    warning: Optional[str]


class OpenMarketReadinessService:
    def __init__(self, *, session, argus, kronos_alpha, technical, kronos_core, athena, hermes, personal_oracle, risk, kill_switch, aegis, now_provider=None):
        self.providers = {"session":session,"argus":argus,"kronos_alpha":kronos_alpha,"technical":technical,
                          "kronos_core":kronos_core,"athena":athena,"hermes":hermes,"personal_oracle":personal_oracle,
                          "risk":risk,"kill_switch":kill_switch,"aegis":aegis}
        self.now_provider = now_provider or (lambda: datetime.now(IST))
        self.config = KronosAlphaConfig()

    def assess(self):
        now = self.now_provider(); checked = now.isoformat()
        values = {name: self._safe(provider) for name, provider in self.providers.items()}
        session = values["session"]; market_open = session.get("market_open") is True
        items = [
            self._item("Market Calendar", "READY" if session.get("session_state") != "UNKNOWN" else "NOT_READY", str(session.get("reason") or "CALENDAR_UNAVAILABLE"), "Canonical NSE session state available", checked, session.get("session_state") == "UNKNOWN"),
            self._argus(values["argus"], market_open, checked),
            self._alpha(values["kronos_alpha"], market_open, checked),
            self._technical(values["technical"], market_open, checked),
            self._item("KRONOS CORE", "READY" if values["kronos_core"].get("status") in {"AVAILABLE", "LIVE"} else "WAITING_FOR_MARKET" if not market_open else "NOT_READY", str(values["kronos_core"].get("status") or "UNAVAILABLE"), "Scanner cache exposes setup and timing", checked, market_open and values["kronos_core"].get("status") not in {"AVAILABLE", "LIVE"}),
            self._item("ATHENA", "READY" if values["athena"].get("athena_status") in {"READY","DEGRADED"} else "NOT_READY", str(values["athena"].get("recommendation") or "UNAVAILABLE"), "Authoritative risk and paper projections readable", checked, values["athena"].get("athena_status") not in {"READY","DEGRADED"}),
            self._item("HERMES", "READY_WITH_LIMITATIONS", "EXTERNAL_PROVIDER_NOT_CONFIGURED", "Cached truthful event-risk projection", checked, False, "No live HERMES provider configured"),
            self._item("Personal ORACLE", "READY_WITH_LIMITATIONS", "LIMITED_CONTEXT", "Read-only personal evidence projection", checked, False, "Historical context coverage remains limited"),
            self._item("Risk Authorization", "READY" if values["risk"].get("risk_state_available") is True else "NOT_READY", str(values["risk"].get("state_health") or "UNAVAILABLE"), "Risk limits, Paper State, and kill-switch projection healthy", checked, values["risk"].get("risk_state_available") is not True),
            self._kill(values["kill_switch"], checked),
            self._item("AEGIS API", "READY" if values["aegis"].get("status") in {"READY","DEGRADED"} else "NOT_READY", str(values["aegis"].get("status") or "UNAVAILABLE"), "GET-only advisory decision API available", checked, values["aegis"].get("status") not in {"READY","DEGRADED"}),
            self._item("Frontend Polling", "READY", "THREE_SECOND_READ_ONLY_POLLING", "No inference/provider refresh triggered by readiness", checked, False),
        ]
        blocking = [item for item in items if item.blocking]
        if blocking: overall = "BLOCKED"
        elif not market_open: overall = "WAITING_FOR_MARKET"
        elif any(item.status == "READY_WITH_LIMITATIONS" for item in items): overall = "READY_WITH_LIMITATIONS"
        else: overall = "READY"
        return {"status": overall, "generated_at": checked, "session": session,
                "items": [asdict(item) for item in items], "blocking_components": [item.component for item in blocking],
                "advisory_only": True, "provider_refresh_triggered": False, "model_inference_triggered": False,
                "broker_call_triggered": False, "schema_version": 1}

    def next_session_plan(self):
        now = self.now_provider(); session = self._safe(self.providers["session"])
        opening = session.get("next_valid_open")
        first_close = grace = None
        if opening:
            open_at = datetime.fromisoformat(str(opening))
            first_close = open_at + timedelta(minutes=5)
            grace = first_close + timedelta(seconds=self.config.provider_grace_seconds)
        steps = [
            (1,"NSE session opens", opening), (2,"First eligible 5-minute candle completes", first_close.isoformat() if first_close else None),
            (3,"Provider grace period completes", grace.isoformat() if grace else None),
            (4,"Technical Intelligence and KRONOS CORE update", grace.isoformat() if grace else None),
            (5,"ARGUS read-only option-chain refresh becomes eligible", grace.isoformat() if grace else None),
            (6,"KRONOS ALPHA first eligible inference becomes eligible", grace.isoformat() if grace else None),
            (7,"ATHENA, HERMES, and Personal ORACLE projections are read", grace.isoformat() if grace else None),
            (8,"AEGIS creates a new advisory decision", grace.isoformat() if grace else None),
            (9,"Decision appends once using semantic fingerprint", grace.isoformat() if grace else None),
            (10,"Frontend polling reads caches without triggering inference or refresh", grace.isoformat() if grace else None),
        ]
        return {"status":"WAITING_FOR_MARKET" if session.get("market_open") is not True else "READY",
                "generated_at":now.isoformat(), "session_date":str(opening)[:10] if opening else None,
                "expected_open":opening, "first_candle_close":first_close.isoformat() if first_close else None,
                "grace_complete":grace.isoformat() if grace else None, "minimum_candle_count":self.config.minimum_context,
                "grace_seconds":self.config.provider_grace_seconds,
                "steps":[{"sequence":number,"action":action,"expected_at":timestamp,"observed":False} for number,action,timestamp in steps],
                "warnings":["PLAN_ONLY_NO_LIVE_OBSERVATION","NO_PROVIDER_REFRESH","NO_MODEL_INFERENCE"], "schema_version":1}

    @staticmethod
    def _safe(provider):
        try:
            value = provider(); return value if isinstance(value, Mapping) else {}
        except Exception: return {}

    @staticmethod
    def _item(component,status,reason,condition,checked,blocking,warning=None):
        return ReadinessItem(component,status,reason,condition,checked,bool(blocking),warning)

    def _argus(self, value, market_open, checked):
        status = str(value.get("status") or "UNAVAILABLE").lower()
        if status in {"available", "live"}: return self._item("ARGUS","READY","PROVIDER_AUTH_AND_MAPPING_READY","Valid NIFTY/expiry/ATM/OI mapping",checked,False)
        if status == "stale" and not market_open: return self._item("ARGUS","READY_WITH_LIMITATIONS","STALE_CACHE_USABLE_MARKET_CLOSED","Fresh read-only chain at market open",checked,False,"Weekend cache is stale by policy")
        reason = str(value.get("reason") or "ARGUS_CACHE_UNAVAILABLE")
        if reason not in {"ARGUS_CACHE_UNAVAILABLE", "ARGUS_SOURCE_STALE"}:
            reason = "ARGUS_CACHE_UNAVAILABLE"
        return self._item("ARGUS","NOT_READY",reason,"Sanitized provider cache available",checked,market_open)

    def _technical(self, value, market_open, checked):
        features = value.get("input_features")
        required = ("ema_21", "ema_38", "vwap", "rsi_14", "adx_14", "atr_14")
        features_ready = (
            isinstance(features, Mapping)
            and all(features.get(name) is not None for name in required)
        )
        reasons = value.get("reason_codes")
        exact_failure = next(
            (
                str(candidate)
                for candidate in reasons
                if str(candidate) in {
                    "INSUFFICIENT_FEATURES",
                    "DHAN_HISTORY_UNAVAILABLE",
                }
            ),
            None,
        ) if isinstance(reasons, list) else None
        ready = features_ready and exact_failure is None
        reason = (
            exact_failure
            if exact_failure is not None
            else "INSUFFICIENT_FEATURES"
        )
        if reason not in {"INSUFFICIENT_FEATURES", "DHAN_HISTORY_UNAVAILABLE"}:
            reason = "INSUFFICIENT_FEATURES"
        return self._item(
            "Technical Intelligence",
            "READY" if ready else "WAITING_FOR_MARKET" if not market_open else "NOT_READY",
            "INDICATORS_READY" if ready else reason,
            "Cached/live technical assessment with valid closed inputs",
            checked,
            market_open and not ready,
        )

    def _alpha(self, value, market_open, checked):
        readiness = str(value.get("readiness_state") or "UNAVAILABLE")
        candle_count = int(value.get("input_candle_count") or 0)
        ready_input = candle_count >= self.config.minimum_context and readiness in {"READY_FOR_NEXT_OPEN","INPUT_READY","FORECAST_READY"}
        if ready_input and not market_open: return self._item("KRONOS ALPHA","WAITING_FOR_MARKET",readiness,"64+ closed candles and eligible candle-close grace",checked,False)
        if ready_input: return self._item("KRONOS ALPHA","READY",readiness,"Eligible closed-candle inference schedule",checked,False)
        if not market_open: return self._item("KRONOS ALPHA","WAITING_FOR_MARKET","CANDLE_CONTEXT_INSUFFICIENT","64+ authoritative closed candles",checked,False,"Input context must be collected from eligible closed candles")
        return self._item("KRONOS ALPHA","NOT_READY","CANDLE_CONTEXT_INSUFFICIENT","64+ authoritative closed candles",checked,True)

    def _kill(self, value, checked):
        state = str(value.get("state") or "UNKNOWN")
        if state == "INACTIVE": return self._item("Kill Switch","READY","INACTIVE","Authoritative persisted state readable",checked,False)
        if state == "ACTIVE": return self._item("Kill Switch","BLOCKED","ACTIVE","Operator must explicitly deactivate through internal authorized workflow",checked,True)
        return self._item("Kill Switch","BLOCKED",state,"Healthy authoritative persisted state",checked,True,"Missing/corrupt state fails closed")
