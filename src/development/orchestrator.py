"""Independent real-data development paper orchestrator."""

import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.brain.context_builder import ContextBuilder
from src.broker.dhan_client import DhanClient
from src.execution.paper_state import PaperStateUnavailable
from src.forensics import EvidenceJournal
from src.fvg.fvg_engine import FVGEngine
from src.kronos.kronos_engine import KronosEngine
from src.liquidity.liquidity_engine import LiquidityEngine
from src.orderblock.order_block_engine import OrderBlockEngine
from src.paper_trading.contracts import ContractResolutionError, OptionContractResolver
from src.paper_trading.models import ResolvedOptionContract
from src.scanner.indicator_builder import IndicatorBuilder
from src.structure.structure_engine import StructureEngine
from src.structure.structure_engine_v2 import StructureEngineV2
from src.timeframe.timeframe_engine import TimeframeEngine

from .decision import DevelopmentWeightedDecisionEngine
from .strategy import SimplePullbackDevelopment


IST = ZoneInfo("Asia/Kolkata")


class DevelopmentPaperOrchestrator:
    SCHEMA_VERSION = 1

    def __init__(self, *, candle_source, calendar, argus, module_providers, engine, risk, resolver=None, quote_client=None, strategy=None, decision_engine=None, state_path="logs/development_paper_runtime.json", evidence_path="logs/development_decision_evidence.jsonl", clock=None, interval=3, defer_runtime_load=False):
        self.candle_source = candle_source; self.calendar = calendar; self.argus = argus; self.module_providers = module_providers
        self.engine = engine; self.risk = risk; self.resolver = resolver or OptionContractResolver(); self.quote_client = quote_client or DhanClient()
        self.strategy = strategy or SimplePullbackDevelopment(); self.decision_engine = decision_engine or DevelopmentWeightedDecisionEngine()
        self.state_path = Path(state_path); self.evidence = EvidenceJournal(evidence_path); self.clock = clock or (lambda: datetime.now(IST)); self.interval = max(1, float(interval))
        self._stop = threading.Event(); self._thread = None; self._lock = threading.Lock(); self._runtime_loaded = not bool(defer_runtime_load); self._runtime = self._load_runtime() if self._runtime_loaded else self._empty()
        self.indicators = IndicatorBuilder(); self.structure = StructureEngine(); self.structure_v2 = StructureEngineV2(); self.liquidity = LiquidityEngine(); self.fvg = FVGEngine(); self.order_block = OrderBlockEngine(); self.timeframe = TimeframeEngine(); self.kronos = KronosEngine(); self.context = ContextBuilder()

    def start(self):
        if self._thread and self._thread.is_alive(): return
        if not self._runtime_loaded:
            self._runtime = self._load_runtime()
            self._runtime_loaded = True
        if not self.engine.paper_state.path.exists():
            try: self.engine.paper_state.initialize()
            except PaperStateUnavailable: pass
        self._stop.clear(); self._thread = threading.Thread(target=self._loop, name="development-paper-orchestrator", daemon=True); self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try: self.tick()
            except Exception as error: self._record("ERROR", "DEVELOPMENT_ORCHESTRATOR_ERROR", type(error).__name__)

    def tick(self):
        if not self._lock.acquire(blocking=False): return {"status": "SKIPPED", "reason": "TICK_ALREADY_RUNNING"}
        try:
            now = self.clock().astimezone(IST); session = self.calendar.status(now); self._runtime["session_state"] = session["session_state"]
            if self._runtime.get("reason") == "RUNTIME_STATE_CORRUPT": return {"status": "BLOCKED", "reason": "RUNTIME_STATE_CORRUPT"}
            try: state = self.engine.paper_state.load(now.date())
            except Exception: return self._set_state("BLOCKED", "DEVELOPMENT_PAPER_STATE_UNAVAILABLE")
            if state.open_positions and session["session_state"] not in {"OPEN", "SPECIAL_SESSION"}: return self._set_state("BLOCKED", "OVERNIGHT_POSITION_BREACH")
            self._mark_active(state, now)
            if session["session_state"] not in {"OPEN", "SPECIAL_SESSION"}: return self._set_state("WAITING", "MARKET_CLOSED")
            pending = self.engine.pending_entry()
            if pending:
                result = self._continue_pending(pending); self._record(result["status"], "PARTIAL_FILL_CONTINUATION", pending["intent"]["intent_id"]); self._write_runtime(); return result
            candles = self.candle_source.load_cache()
            if not candles: return self._set_state("WAITING", "CLOSED_CANDLE_CACHE_EMPTY")
            candle = candles[-1]
            if candle.get("closed") is not True and candle.get("is_closed") is not True: return self._set_state("BLOCKED", "INCOMPLETE_CANDLE")
            closed_at_raw = candle.get("candle_closed_at") or candle.get("timestamp")
            if not closed_at_raw:
                return self._set_state("BLOCKED", "CANDLE_MISSING_CLOSED_AT")
            closed_at = datetime.fromisoformat(str(closed_at_raw)).astimezone(IST)
            if closed_at > now: return self._set_state("BLOCKED", "CANDLE_NOT_CLOSED")
            origin = str(candle["timestamp"])
            if origin == self._runtime.get("last_evaluated_candle"): return self._set_state("MONITORING", "NO_NEW_CLOSED_CANDLE")
            self._runtime["last_evaluated_candle"] = origin
            state = self.engine.paper_state.load(now.date())
            if state.open_positions:
                self._update_underlying_excursion(candle)
                result = self._evaluate_exit(state.open_positions[0], candle, now); self._write_runtime(); return result
            if now.time() > time(15, 15): return self._set_state("WAITING", "ENTRY_WINDOW_CLOSED")
            context = self._build_context(candles); signal = self.strategy.generate(context); self._runtime["last_signal"] = dict(signal)
            evidence = self._module_evidence(context, signal, None)
            safety = self._safety(candle, closed_at, now, session)
            if signal.get("signal") not in {"BUY", "SELL"}:
                decision = self.decision_engine.assess(symbol="NIFTY", timeframe="5m", candle_timestamp=origin, signal=signal, evidence=evidence, safety=safety)
                self._persist_decision(origin, candle, signal, decision, evidence)
                self._runtime["last_decision"] = self._compact_decision(decision)
                return self._set_state("WAITING", "DEVELOPMENT_STRATEGY_WAIT")
            argus_response = self.argus.get_oi("NIFTY")
            evidence = self._module_evidence(context, signal, argus_response)
            decision = self.decision_engine.assess(symbol="NIFTY", timeframe="5m", candle_timestamp=origin, signal=signal, evidence=evidence, safety=safety)
            decision_record = self._persist_decision(origin, candle, signal, decision, evidence); replay_id = decision_record["record_id"] if decision_record else decision["decision_id"]
            self._runtime["last_decision"] = self._compact_decision(decision)
            if decision["decision"] != "ALLOW": return self._set_state("WAITING", f"DEVELOPMENT_WEIGHTED_{decision['decision']}")
            contract = self.resolver.resolve(argus_response, signal["signal"]); request_id = f"development|{origin}|{contract.security_id}"
            fetched_at = datetime.fromisoformat(argus_response["data"]["underlying"]["fetched_at"])
            risk = self.risk.authorize(request_id=request_id, contract=contract, market_timestamp=fetched_at, session_state=session["session_state"]); self._runtime["last_risk"] = risk.to_dict()
            if not risk.allowed:
                self._append("DEVELOPMENT_RISK_REJECTED", {"replay_id": replay_id, "decision": decision, "risk": risk.to_dict(), "why_not_trade": [risk.reason_code]}, candle_id=origin, idempotency_key=f"development-risk|{origin}")
                return self._set_state("WAITING", f"RISK_{risk.reason_code}")
            result = self.engine.enter(request_id=request_id, contract=contract, strategy_signal=signal, weighted_decision=decision, risk_decision=risk, candle_timestamp=origin, replay_id=replay_id)
            if result["status"] == "OPENED":
                self._runtime["active_trade_evidence"] = self._initial_excursion(candle, signal, result, replay_id, decision)
                self._append("DEVELOPMENT_TRADE_OPENED", {"timestamp": now.isoformat(), "strategy": signal["strategy"], "weighted_score": decision["weighted_score"], "module_contributions": decision["module_contributions"], "confidence": decision["confidence"], "entry": signal["entry"], "stop": signal["sl"], "target": signal["target"], "exit": None, "mfe": 0.0, "mae": 0.0, "rr": 2.0, "winner": None, "loser": None, "replay_id": replay_id, "why_trade": decision["why_trade"], "why_not_trade": []}, candle_id=origin, idempotency_key=f"development-open|{result['intent_id']}")
            self._record(result["status"], result.get("reason") or "DEVELOPMENT_PAPER_ENTRY", f"{contract.option_type} {contract.strike:g} {contract.expiry}"); self._write_runtime(); return result
        except ContractResolutionError as error:
            return self._set_state("BLOCKED", "CONTRACT_RESOLUTION_UNAVAILABLE", str(error))
        finally:
            self._lock.release()

    def _module_evidence(self, context, signal, argus_response):
        direction = "BULLISH" if signal.get("signal") == "BUY" else "BEARISH" if signal.get("signal") == "SELL" else context.kronos.get("bias")
        evidence = {
            "technical": {"available": context.indicators.get("ema_21") is not None, "direction": direction, "confidence": context.confidence, "source_timestamp": self._runtime.get("last_evaluated_candle")},
            "kronos_core": {"available": True, "direction": context.kronos.get("bias"), "confidence": context.smart_score or context.confidence, "regime": context.regime},
            "argus": self._argus_evidence(argus_response),
        }
        for name, provider in self.module_providers.items():
            try: raw = provider(); evidence[name] = self._normalize_module(name, raw)
            except Exception: evidence[name] = {"available": False, "reason": "PROVIDER_UNAVAILABLE"}
        return evidence

    @staticmethod
    def _argus_evidence(response):
        if not isinstance(response, dict): return {"available": False, "reason": "NOT_EVALUATED"}
        verdict = ((response.get("data") or {}).get("verdict") or {})
        return {"available": response.get("status") in {"available", "stale"}, "direction": verdict.get("bias"), "confidence": verdict.get("confidence"), "preferred_option_side": verdict.get("preferred_option_side"), "freshness": response.get("freshness")}

    @staticmethod
    def _normalize_module(name, raw):
        raw = raw.to_dict() if hasattr(raw, "to_dict") else raw
        if not isinstance(raw, dict): return {"available": False, "reason": "MALFORMED_PROJECTION"}
        if name == "kronos_alpha":
            probabilities = [raw.get("bullish_probability"), raw.get("bearish_probability"), raw.get("sideways_probability")]
            valid = [float(value) for value in probabilities if isinstance(value, (int, float))]
            confidence = max(valid) if valid else None
            if confidence is not None and confidence <= 1: confidence *= 100
            return {"available": raw.get("model_status") in {"READY", "STALE"}, "direction": raw.get("expected_direction"), "confidence": confidence, "source_timestamp": raw.get("last_inference_at"), "shadow": True}
        if name == "chronos_2":
            analytics = raw.get("derived_analytics") or {}
            return {"available": raw.get("status") in {"READY", "STALE", "LAST_FORECAST"}, "direction": analytics.get("directional_bias"), "confidence": analytics.get("directional_confidence"), "source_timestamp": raw.get("generated_at"), "shadow": True}
        if name == "athena": return {"available": raw.get("athena_status") not in {None, "UNAVAILABLE", "BLOCKED"}, "recommendation": raw.get("recommendation"), "risk_state": raw.get("risk_state"), "source_timestamp": raw.get("generated_at")}
        if name == "hermes": return {"available": raw.get("hermes_status") not in {None, "UNAVAILABLE", "NOT_CONFIGURED", "BLOCKED"}, "recommendation": raw.get("recommendation"), "source_timestamp": raw.get("generated_at")}
        if name == "oracle":
            coaching = raw.get("coaching") or {}; recommendations = coaching.get("recommendations") or []
            recommendation = recommendations[0].get("state") if recommendations else None
            return {"available": raw.get("status") == "available", "recommendation": recommendation, "maturity": raw.get("maturity"), "source_timestamp": (raw.get("behavior") or {}).get("latest_update")}
        return {"available": False, "reason": "UNSUPPORTED_DEVELOPMENT_EVIDENCE"}

    def _safety(self, candle, closed_at, now, session):
        try: kill = self.risk.kill_store.projection().state
        except Exception: kill = "UNKNOWN"
        try: paper_health = "HEALTHY" if self.engine.paper_state.load(now.date()) else "UNAVAILABLE"
        except Exception: paper_health = "UNAVAILABLE"
        try: live = bool(self.risk.settings_provider().get("live_trading_enabled"))
        except Exception: live = None
        age = (now - closed_at).total_seconds()
        return {"live_trading_enabled": live, "kill_switch_state": kill, "session_state": session.get("session_state"), "paper_state_health": paper_health, "closed_candle": candle.get("closed") is True or candle.get("is_closed") is True, "market_data_fresh": 0 <= age <= 600}

    def _mark_active(self, state, now):
        if not state.open_positions: return
        position = state.open_positions[0]; quote = self.quote_client.get_quote("NSE_FNO", position.instrument_id); ltp = quote.get("ltp")
        if ltp is None: self._record("DEGRADED", "OPTION_MARK_UNAVAILABLE", position.instrument_id or "unknown"); return
        self.engine.mark(position=position, price=ltp, timestamp=now.isoformat()); active = self._runtime.get("active_trade_evidence") or {}
        active["option_max"] = max(float(active.get("option_max", ltp)), float(ltp)); active["option_min"] = min(float(active.get("option_min", ltp)), float(ltp)); active["last_option_mark"] = float(ltp); self._runtime["active_trade_evidence"] = active
        if now.time() >= time(15, 20):
            contract = self._position_contract(position, float(ltp)); result = self.engine.exit(position=position, contract=contract, reason="MANDATORY_INTRADAY_SQUARE_OFF", timestamp=now.isoformat()); self._complete_trade(result, None, now.isoformat(), "MANDATORY_INTRADAY_SQUARE_OFF")

    def _update_underlying_excursion(self, candle):
        active = self._runtime.get("active_trade_evidence") or {}
        if not active: return
        active["underlying_high"] = max(float(active.get("underlying_high", candle["high"])), float(candle["high"])); active["underlying_low"] = min(float(active.get("underlying_low", candle["low"])), float(candle["low"])); active["last_underlying_close"] = float(candle["close"]); self._runtime["active_trade_evidence"] = active

    def _evaluate_exit(self, position, candle, now):
        plan = self.engine.active_plan(position.position_id)
        if not plan: return self._set_state("BLOCKED", "POSITION_PLAN_UNAVAILABLE")
        close = float(candle["close"]); reason = None
        if position.option_type == "CE":
            if close <= float(plan["underlying_stop"]): reason = "UNDERLYING_STOP_HIT"
            elif close >= float(plan["underlying_target"]): reason = "UNDERLYING_TARGET_HIT"
        elif position.option_type == "PE":
            if close >= float(plan["underlying_stop"]): reason = "UNDERLYING_STOP_HIT"
            elif close <= float(plan["underlying_target"]): reason = "UNDERLYING_TARGET_HIT"
        if not reason: return self._set_state("MONITORING", "DEVELOPMENT_POSITION_OPEN")
        refreshed = next((item for item in self.engine.paper_state.load(now.date()).open_positions if item.position_id == position.position_id), position)
        result = self.engine.exit(position=refreshed, contract=self._position_contract(refreshed, refreshed.mark_price), reason=reason, timestamp=candle["timestamp"]); self._complete_trade(result, candle, candle["timestamp"], reason); self._record(result["status"], reason, position.instrument_id or "unknown"); return result

    def _complete_trade(self, result, candle, timestamp, reason):
        active = self._runtime.get("active_trade_evidence") or {}; side = active.get("signal"); entry = float(active.get("underlying_entry", 0)); risk = float(active.get("underlying_risk", 0)); high = float(active.get("underlying_high", entry)); low = float(active.get("underlying_low", entry))
        mfe = max(0.0, high - entry) if side == "BUY" else max(0.0, entry - low); mae = max(0.0, entry - low) if side == "BUY" else max(0.0, high - entry)
        closed = result.get("closed_trade") or {}; pnl = closed.get("realized_pnl"); exit_underlying = float(candle["close"]) if candle else active.get("last_underlying_close")
        realized_r = None if not risk or exit_underlying is None else round(((float(exit_underlying) - entry) * (1 if side == "BUY" else -1)) / risk, 4)
        self._append("DEVELOPMENT_TRADE_CLOSED", {"timestamp": active.get("opened_at"), "strategy": active.get("strategy"), "weighted_score": active.get("weighted_score"), "module_contributions": active.get("module_contributions"), "confidence": active.get("confidence"), "entry": entry, "stop": active.get("stop"), "target": active.get("target"), "exit": {"timestamp": timestamp, "reason": reason, "underlying": exit_underlying, "option_price": (result.get("fill") or {}).get("price"), "realized_pnl": pnl}, "mfe": {"underlying_points": round(mfe, 4), "option_points": round(float(active.get("option_max", active.get("option_entry", 0))) - float(active.get("option_entry", 0)), 4)}, "mae": {"underlying_points": round(mae, 4), "option_points": round(float(active.get("option_entry", 0)) - float(active.get("option_min", active.get("option_entry", 0))), 4)}, "rr": {"planned": 2.0, "realized_underlying_r": realized_r}, "winner": pnl is not None and float(pnl) > 0, "loser": pnl is not None and float(pnl) < 0, "replay_id": active.get("replay_id"), "why_trade": active.get("why_trade", []), "why_not_trade": []}, candle_id=active.get("candle_id"), idempotency_key=f"development-close|{result.get('intent_id')}")
        self._runtime["active_trade_evidence"] = None

    @staticmethod
    def _initial_excursion(candle, signal, result, replay_id, decision):
        option_entry = float((result.get("fill") or {}).get("price", 0)); return {"candle_id": candle["timestamp"], "opened_at": (result.get("fill") or {}).get("timestamp"), "strategy": signal["strategy"], "signal": signal["signal"], "underlying_entry": signal["entry"], "underlying_risk": abs(float(signal["entry"]) - float(signal["sl"])), "stop": signal["sl"], "target": signal["target"], "underlying_high": float(candle["high"]), "underlying_low": float(candle["low"]), "last_underlying_close": float(candle["close"]), "option_entry": option_entry, "option_max": option_entry, "option_min": option_entry, "weighted_score": decision["weighted_score"], "module_contributions": decision["module_contributions"], "confidence": decision["confidence"], "why_trade": decision["why_trade"], "replay_id": replay_id}

    def _persist_decision(self, origin, candle, signal, decision, evidence):
        return self._append("DEVELOPMENT_DECISION", {"timestamp": decision["generated_at"], "candle": candle, "strategy": signal, "weighted_score": decision["weighted_score"], "module_contributions": decision["module_contributions"], "module_votes": decision["module_votes"], "confidence": decision["confidence"], "entry": signal.get("entry"), "stop": signal.get("sl"), "target": signal.get("target"), "exit": None, "mfe": None, "mae": None, "rr": 2.0 if signal.get("signal") in {"BUY", "SELL"} else None, "winner": None, "loser": None, "why_trade": decision["why_trade"], "why_not_trade": decision["why_not_trade"], "decision": decision["decision"], "hard_vetoes": decision["hard_vetoes"], "missing_optional_evidence": decision["missing_optional_evidence"], "evidence": evidence, "production_state_mutated": False}, candle_id=origin, idempotency_key=f"development-decision|{origin}")

    def _append(self, event, payload, **kwargs):
        try: return self.evidence.append(event, payload, **kwargs)[0]
        except Exception: return None

    def _continue_pending(self, order):
        intent = order["intent"]; meta = intent.get("metadata") or {}; quote = self.quote_client.get_quote("NSE_FNO", intent["instrument_id"]); ltp = quote.get("ltp")
        if ltp is None: return {"status": "BLOCKED", "reason": "PENDING_FILL_QUOTE_UNAVAILABLE"}
        contract = ResolvedOptionContract(str(intent["instrument_id"]), str(intent["exchange_segment"]), "NIFTY", str(meta["option_type"]), float(meta["strike"]), str(meta["expiry"]), int(intent["lot_size"]), float(ltp), None, None, None, None, "DEVELOPMENT_ORDER_INTENT", "DHAN_MARKETFEED_OHLC")
        return self.engine.continue_entry(contract)

    def _build_context(self, candles):
        indicators = self.indicators.build(candles); structure = self.structure.analyze(candles); structure_v2 = self.structure_v2.analyze(candles); liquidity = self.liquidity.analyze(candles); fvg = self.fvg.analyze(candles); order_block = self.order_block.analyze(candles); timeframe = self.timeframe.analyze(candles); kronos = self.kronos.analyze(indicators, structure, liquidity, fvg, order_block, structure_v2, timeframe)
        return self.context.build("NIFTY", indicators, kronos, structure, structure_v2, liquidity, fvg, order_block, timeframe)

    @staticmethod
    def _position_contract(position, ltp): return ResolvedOptionContract(str(position.instrument_id), "NSE_FNO", "NIFTY", str(position.option_type), float(position.strike), str(position.expiry), int(position.lot_size), float(ltp), None, None, None, None, "DEVELOPMENT_PAPER_STATE", "DHAN_MARKETFEED_OHLC")
    @staticmethod
    def _compact_decision(decision): return {key: decision.get(key) for key in ("decision_id", "decision", "weighted_score", "allow_threshold", "data_coverage_percentage", "module_votes", "module_contributions", "missing_optional_evidence", "hard_vetoes", "why_trade", "why_not_trade", "confidence", "generated_at")}

    def status(self):
        return {**self._runtime, "schema_version": 1, "mode": "DEVELOPMENT_PAPER_ONLY", "scheduler_running": bool(self._thread and self._thread.is_alive()), "production_state_mutated": False, "production_aegis_used": False, "frontend_execution": False, "broker_submission": False, "live_trading_enabled": False, "symbols": ["NIFTY"], "timeframe": "5m", "maximum_lots": 1, "maximum_open_positions": 1, "evidence_ceiling_per_day": 20, "strategy": self.strategy.name(), "strategy_profile": self.strategy.config(), "weighted_policy": {"weights": self.decision_engine.WEIGHTS, "allow_threshold": self.decision_engine.ALLOW_THRESHOLD}}
    def timeline(self, limit=20): return {"status": "available", "events": list(reversed(self._runtime.get("timeline", [])[-max(1, min(int(limit), 100)):]))}
    def position(self):
        try:
            state = self.engine.paper_state.load(); return {"status": "available", "position": state.open_positions[0].to_dict() if state.open_positions else None, "source": "ISOLATED_DEVELOPMENT_PAPER_STATE"}
        except Exception: return {"status": "unavailable", "position": None, "source": "ISOLATED_DEVELOPMENT_PAPER_STATE"}
    def pnl(self):
        try:
            state = self.engine.paper_state.load(); return {"status": "available", "trading_date": state.trading_date, "realized_pnl": state.realized_pnl, "unrealized_pnl": state.unrealized_pnl, "total_daily_pnl": state.total_daily_pnl, "open_positions": len(state.open_positions), "trades_taken": state.trades_taken, "closed_trades": len(state.closed_trades), "source": "ISOLATED_DEVELOPMENT_PAPER_STATE"}
        except Exception: return {"status": "unavailable", "realized_pnl": None, "unrealized_pnl": None, "total_daily_pnl": None, "source": "ISOLATED_DEVELOPMENT_PAPER_STATE"}
    def evidence_summary(self):
        try:
            records = self.evidence.records(); decisions = [row for row in records if row["event_type"] == "DEVELOPMENT_DECISION"]; trades = [row for row in records if row["event_type"] == "DEVELOPMENT_TRADE_CLOSED"]
            return {"status": "available", "integrity": self.evidence.verify(), "decision_count": len(decisions), "closed_trade_evidence_count": len(trades), "recent_decisions": [row["payload"] for row in decisions[-10:]], "recent_trades": [row["payload"] for row in trades[-10:]]}
        except Exception: return {"status": "unavailable", "integrity": {"valid": False}, "decision_count": None, "closed_trade_evidence_count": None, "recent_decisions": [], "recent_trades": []}
    def dashboard_snapshot_input(self):
        """Capture immutable read-only inputs for the projection process."""
        try: evidence_bytes = self.evidence.path.read_bytes() if self.evidence.path.exists() else b""
        except OSError: evidence_bytes = b""
        return {
            "generated_at": self.clock().isoformat(), "status": deepcopy(self.status()),
            "position": self.position(), "pnl": self.pnl(), "ledger": self.engine.ledger.status(),
            "timeline": self.timeline(), "evidence_bytes": evidence_bytes,
        }
    def dashboard(self): return {"generated_at": self.clock().isoformat(), "status": self.status(), "position": self.position(), "pnl": self.pnl(), "ledger": self.engine.ledger.status(), "timeline": self.timeline(), "evidence": self.evidence_summary(), "safety_labels": ["DEVELOPMENT PAPER TRADING", "NOT USED FOR PRODUCTION", "NOT USED FOR LIVE TRADING"]}

    def _set_state(self, state, reason, detail=None): self._runtime.update({"state": state, "reason": reason, "updated_at": self.clock().isoformat()}); self._record(state, reason, detail or ""); self._write_runtime(); return {"status": state, "reason": reason}
    def _record(self, status, code, detail):
        event = {"timestamp": self.clock().isoformat(), "status": str(status), "code": str(code), "detail": str(detail)[:160]}; timeline = self._runtime.setdefault("timeline", [])
        if not timeline or timeline[-1].get("code") != event["code"] or timeline[-1].get("detail") != event["detail"]: timeline.append(event); del timeline[:-500]
    def _load_runtime(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if value.get("schema_version") != 1: raise ValueError
            return value
        except FileNotFoundError: return self._empty()
        except Exception: return {**self._empty(), "state": "BLOCKED", "reason": "RUNTIME_STATE_CORRUPT"}
    def _write_runtime(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True); self._runtime["schema_version"] = 1; fd, temporary = tempfile.mkstemp(prefix=f".{self.state_path.name}.", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle: json.dump(self._runtime, handle, sort_keys=True, separators=(",", ":")); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    @staticmethod
    def _empty(): return {"schema_version": 1, "state": "NOT_STARTED", "reason": "AWAITING_LIFECYCLE_START", "updated_at": None, "last_evaluated_candle": None, "last_signal": None, "last_decision": None, "last_risk": None, "active_trade_evidence": None, "timeline": []}
