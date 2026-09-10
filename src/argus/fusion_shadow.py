"""Additive, non-authoritative temporal Fusion Shadow research lane.

The production Oracle remains the only decision surface.  This module only
observes projections already calculated by that runtime and publishes an
auditable research view.  It owns no market-data transport, makes no provider
calls, and deliberately has no route to execution.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import threading
from time import perf_counter
from typing import Any, Callable, Mapping


# V0.2 retains the V0.1 temporal state machine and makes its evidence
# availability/transition boundaries externally auditable.  It adds no score
# gate, decision threshold, execution path, or source of market data.
FUSION_VERSION = "ARGUS_FUSION_SHADOW_V0_2"
FUSION_SCHEMA_VERSION = 3
EXECUTION_INFLUENCE = "ZERO"

FUSION_STATES = (
    "WAIT",
    "WATCH",
    "SETUP",
    "TRIGGER",
    "RUNNER",
    "INVALIDATED",
    "DATA_LOCKED",
)

HERO_STATES = (
    "STRONG BULL TREND · CONTINUATION",
    "STRONG BEAR TREND · CONTINUATION",
    "REVERSAL BUILDING ↑",
    "REVERSAL BUILDING ↓",
    "BULL TREND WEAKENING",
    "BEAR TREND WEAKENING",
    "SIDEWAYS · NO TREND",
    "VERY VOLATILE · TWO-WAY",
    "DATA LOCKED",
)

PLAYBOOKS = (
    "FAILED_AGGRESSION_REVERSAL",
    "TREND_PULLBACK_RE_ACCELERATION",
    "BREAKOUT_EXPANSION",
    "CONTINUATION",
    "EXPIRY_FAST_MOMENTUM",
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(*values: Any) -> str:
    return " ".join(_text(value).upper() for value in values if value is not None)


def _contains(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _distribution(values: deque[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
        return round(ordered[index], 4)

    return {
        "count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": round(ordered[-1], 4),
    }


class FusionShadowEngine:
    """Incremental temporal state machine for prospective shadow research.

    Transitions are driven by explicit Oracle semantic observations -- for
    example ``PRICE HOLDING AGAINST SELLERS`` followed by a reclaim/break --
    rather than a score threshold.  It intentionally treats unavailable Flow
    or Options evidence as UNKNOWN, never as a synthetic confirming vote.
    """

    def __init__(
        self,
        *,
        recorder: Any | None = None,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.recorder = recorder
        self._now = now
        self._lock = threading.RLock()
        self._revision = 0
        self._state = "WAIT"
        self._direction: str | None = None
        self._hero_state = "SIDEWAYS · NO TREND"
        self._latest_flow: dict[str, Any] = {}
        self._latest_argus: dict[str, Any] = {}
        self._options: dict[str, Any] = {
            "state": "UNKNOWN",
            "availability": "UNKNOWN",
            "reason": "OPTIONS_NOT_YET_OBSERVED",
        }
        self._previous_options: dict[str, dict[str, Any]] = {}
        self._quotes: dict[str, dict[str, Any]] = {}
        self._state_events: deque[dict[str, Any]] = deque(maxlen=256)
        self._anchors: dict[str, dict[str, Any]] = {}
        self._premium_tracks: dict[str, dict[str, Any]] = {}
        self._trades: dict[str, dict[str, Any]] = {}
        self._trade_events: deque[dict[str, Any]] = deque(maxlen=1_024)
        self._last_valid_market_state: dict[str, Any] | None = None
        self._playbooks: dict[str, dict[str, Any]] = {
            name: {
                "family": name,
                "lifecycle": "UNPROVEN" if name == "EXPIRY_FAST_MOMENTUM" else "IDLE",
                "direction": None,
                "state_event_id": None,
                "reason": "UNPROVEN_WITHOUT_PROSPECTIVE_QUANT_EVIDENCE" if name == "EXPIRY_FAST_MOMENTUM" else "WAITING_FOR_TEMPORAL_EVIDENCE",
            }
            for name in PLAYBOOKS
        }
        self._latencies: dict[str, deque[float]] = {
            "fusion_compute_ms": deque(maxlen=4_096),
            "hero_compute_ms": deque(maxlen=4_096),
            "premium_tracker_ms": deque(maxlen=4_096),
            "playbook_compute_ms": deque(maxlen=4_096),
            "ledger_enqueue_ms": deque(maxlen=4_096),
        }
        self._last_projection: dict[str, Any] | None = None
        self._last_transition_reason = "NOT_YET_EVALUATED"
        self._last_transition_blockers: list[str] = ["OBSERVATION_NOT_YET_AVAILABLE"]

    def ingest_flow(self, projection: Mapping[str, Any] | None, *, transport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Observe an already-calculated canonical Flow/Flow Pulse projection."""

        started = perf_counter()
        with self._lock:
            self._latest_flow = _mapping(projection)
            if transport is not None:
                self._latest_flow["transport"] = _mapping(transport)
            result = self._evaluate_locked(origin="FLOW")
        self._latencies["fusion_compute_ms"].append((perf_counter() - started) * 1_000.0)
        return result

    def ingest_argus(self, projection: Mapping[str, Any] | None, *, transport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Observe an existing coherent ARGUS projection without refreshing it."""

        started = perf_counter()
        with self._lock:
            self._latest_argus = _mapping(projection)
            if transport is not None:
                self._latest_argus["transport"] = _mapping(transport)
            premium_started = perf_counter()
            self._observe_options_locked()
            self._latencies["premium_tracker_ms"].append((perf_counter() - premium_started) * 1_000.0)
            result = self._evaluate_locked(origin="OPTIONS")
        self._latencies["fusion_compute_ms"].append((perf_counter() - started) * 1_000.0)
        return result

    def projection(self) -> dict[str, Any]:
        """Return an immutable-copy presentation payload for Fast Lane only."""

        with self._lock:
            if self._last_projection is None:
                self._last_projection = self._build_projection_locked()
            return deepcopy(self._last_projection)

    def session_events(self) -> list[dict[str, Any]]:
        """Return append-only state/trade event representations for EOD readers."""

        with self._lock:
            return deepcopy([*self._state_events, *self._trade_events])

    def _evaluate_locked(self, *, origin: str) -> dict[str, Any]:
        hero_started = perf_counter()
        observation = self._observation_locked()
        desired_state, desired_direction, transition_reason = self._next_state_locked(observation)
        self._last_transition_reason = transition_reason
        self._last_transition_blockers = self._transition_blockers(
            observation, transition_reason,
        )
        desired_hero = self._hero_from_observation(observation, desired_state, desired_direction)
        self._latencies["hero_compute_ms"].append((perf_counter() - hero_started) * 1_000.0)

        state_changed = desired_state != self._state or desired_direction != self._direction
        hero_changed = desired_hero != self._hero_state
        if state_changed or hero_changed:
            prior = {
                "fusion_state": self._state,
                "direction": self._direction,
                "hero_state": self._hero_state,
            }
            self._state = desired_state
            self._direction = desired_direction
            self._hero_state = desired_hero
            self._revision += 1
            event = self._freeze_transition_locked(
                prior=prior,
                observation=observation,
                origin=origin,
                reason=transition_reason,
                state_changed=state_changed,
                hero_changed=hero_changed,
            )
            self._update_playbooks_locked(event, observation)
            if desired_state == "TRIGGER" and state_changed:
                self._open_shadow_trade_locked(event, observation)
            self._update_live_premium_tracks_locked()
            self._update_live_trades_locked(observation)
        else:
            self._update_live_premium_tracks_locked()
            self._update_live_trades_locked(observation)
            self._update_playbooks_locked(None, observation)

        # Presentation provenance only.  A closed feed must report the last
        # valid state, never infer a fresh SIDEWAYS conclusion from silence.
        if not observation["locked"] and not observation["market_closed"]:
            self._last_valid_market_state = {
                "fusion_state": self._state,
                "direction": self._direction,
                "hero_state": self._hero_state,
                "source_timestamp": observation.get("source_timestamp"),
                "calculation_timestamp": self._now(),
                "revision": self._revision,
            }

        self._last_projection = self._build_projection_locked(observation=observation)
        return deepcopy(self._last_projection)

    def _observation_locked(self) -> dict[str, Any]:
        flow = self._latest_flow
        pulse = _mapping(flow.get("flow_pulse"))
        semantic = _mapping(pulse.get("semantic"))
        reaction = _mapping(pulse.get("reaction"))
        flow_futures = _mapping(pulse.get("futures"))
        argus_data = _mapping(self._latest_argus.get("data"))
        argus_futures = _mapping(argus_data.get("futures"))
        flow_future_present = _number(flow_futures.get("ltp")) is not None
        argus_future_present = _number(argus_futures.get("ltp")) is not None
        flow_text = _upper(
            semantic.get("pressure"), semantic.get("result"), semantic.get("market"), semantic.get("speed"),
            pulse.get("what_happened"), pulse.get("headline"), pulse.get("story"), pulse.get("flow_state"),
            reaction.get("state"), reaction.get("response"), pulse.get("reversal_state"),
        )
        flow_structure_text = _upper(
            pulse.get("what_happened"), pulse.get("headline"), pulse.get("story"), pulse.get("area"),
            _mapping(pulse.get("key_level")).get("state"), _mapping(pulse.get("next_level")).get("state"),
            semantic.get("result"), reaction.get("state"),
        )
        # Never derive a structure state from raw price/volume here.  This is
        # merely a bridge for any existing canonical Futures structure label.
        canonical_structure_text = _upper(
            argus_futures.get("structure_state"), argus_futures.get("market_structure"),
            argus_futures.get("structure"), argus_futures.get("event"),
            argus_futures.get("headline"), argus_futures.get("reason"),
        )
        structure_text = _upper(flow_structure_text, canonical_structure_text)
        flow_quality = _text(flow.get("data_quality") or pulse.get("data_quality") or "UNKNOWN").upper()
        directional_state = _text(flow.get("directional_state") or "").upper()
        live_health = _mapping(pulse.get("live_health"))
        transport = _mapping(flow.get("transport") or self._latest_argus.get("transport"))
        market_session = _text(transport.get("MARKET_SESSION") or transport.get("market_session")).upper()
        market_closed = market_session == "CLOSED" or _text(transport.get("BASKET_HEALTH")).upper() == "MARKET_CLOSED"
        futures_transport_state = self._futures_transport_state(transport)
        flow_stale = flow_future_present and (
            flow_quality in {"UNUSABLE", "DATA_LOCKED"}
            or directional_state == "DATA_LOCKED"
            or futures_transport_state in {"STALE", "DEGRADED"}
            or _contains(
                _upper(flow.get("action_lock_reasons"), live_health.get("status")),
                "FUTURES_FULL_PACKET_STALE", "DATA STALE", "FUTURES STALE",
            )
        )
        argus_stale = argus_future_present and _contains(
            _upper(
                self._latest_argus.get("status"), argus_futures.get("freshness"),
                argus_futures.get("freshness_state"), argus_futures.get("status"),
                _mapping(argus_data.get("data_truth")).get("state"),
            ),
            "STALE", "LAST_GOOD", "UNAVAILABLE",
        )
        if flow_future_present and not flow_stale:
            futures, futures_source, futures_stale = flow_futures, "FLOW_PULSE", False
        elif argus_future_present:
            futures, futures_source, futures_stale = argus_futures, "ARGUS_CANONICAL", argus_stale
        elif flow_future_present:
            futures, futures_source, futures_stale = flow_futures, "FLOW_PULSE", True
        else:
            futures, futures_source, futures_stale = {}, "UNAVAILABLE", True
        future_present = bool(futures)
        futures_availability = (
            "UNKNOWN" if not future_present else "STALE" if futures_stale else "FRESH"
        )
        flow_availability = (
            "UNKNOWN" if not flow_future_present else "STALE" if flow_stale else "AVAILABLE"
        )
        options_availability = _text(self._options.get("availability") or "UNKNOWN").upper()
        if options_availability == "AVAILABLE" and _contains(
            _upper(self._latest_argus.get("status"), _mapping(argus_data.get("data_truth")).get("state")),
            "STALE", "LAST_GOOD",
        ):
            options_availability = "STALE"
        secondary_context = self._secondary_context_locked()
        ose_availability = _text(_mapping(secondary_context.get("ose")).get("availability") or "UNKNOWN").upper()
        flow_is_sole_futures_source = futures_source == "FLOW_PULSE" and not argus_future_present
        locked = not market_closed and futures_availability != "FRESH"

        seller_effective = _contains(flow_text, "SELLING STRONG", "SELLERS EFFECTIVE", "PRICE FALLING WITH SELLERS", "SELLERS WORKING")
        buyer_effective = _contains(flow_text, "BUYING STRONG", "BUYERS EFFECTIVE", "PRICE RISING WITH BUYERS", "BUYERS WORKING")
        sellers_fading = _contains(
            flow_text,
            "PRICE HOLDING AGAINST SELLERS", "SELLERS FADING", "SELLERS ABSORBED", "SELLING EXHAUSTED", "FAILED DOWNSIDE",
        )
        buyers_fading = _contains(
            flow_text,
            "PRICE HOLDING AGAINST BUYERS", "BUYERS FADING", "BUYERS ABSORBED", "BUYING EXHAUSTED", "FAILED UPSIDE",
        )
        # A response-level "PRICE HOLDING AGAINST SELLERS" opens WATCH. It is
        # not itself the later structural hold/retest needed for SETUP.
        structural_hold = _contains(
            structure_text,
            "STRUCTURE HOLD", "RETEST HOLD", "RETEST HOLDS", "LOW HOLD", "HIGHER LOW", "LOWER HIGH", "RECLAIM", "FAILED RETEST",
        )
        reclaim = _contains(structure_text, "RECLAIM", "BUYERS TAKING CONTROL", "SELLERS TAKING CONTROL")
        expansion = _contains(structure_text, "BREAKOUT", "BREAK", "EXPANSION", "RE-ACCELER", "ACCELERATION")
        failure_against_bull = _contains(structure_text, "BULLISH INVALIDATED", "RECLAIM FAILED", "DOWNSIDE BREAK")
        failure_against_bear = _contains(structure_text, "BEARISH INVALIDATED", "BREAKDOWN FAILED", "UPSIDE BREAK")

        option_state = _text(self._options.get("state") or "UNKNOWN")
        option_direction = _text(self._options.get("direction") or "") or None
        options_support_bull = options_availability == "AVAILABLE" and option_state == "SUPPORTIVE" and option_direction == "BULLISH"
        options_support_bear = options_availability == "AVAILABLE" and option_state == "SUPPORTIVE" and option_direction == "BEARISH"
        source_timestamp = (
            _text(pulse.get("source_timestamp"))
            or _text(argus_data.get("underlying") and _mapping(argus_data.get("underlying")).get("source_event_time"))
            or _text(argus_futures.get("source_timestamp"))
            or None
        )
        return {
            "locked": locked,
            "lock_reasons": self._lock_reasons(
                flow, pulse, future_present, flow_quality, directional_state,
                futures_availability == "STALE", flow_is_sole_futures_source,
            ),
            "quality": flow_quality if flow_future_present else "FUTURES_OPTIONS_LIVE_FLOW_UNKNOWN" if future_present else "UNKNOWN",
            "source_timestamp": source_timestamp,
            "receipt_timestamp": _text(pulse.get("receipt_timestamp")) or None,
            "futures": futures,
            "futures_source": futures_source,
            "futures_availability": futures_availability,
            "flow_availability": flow_availability,
            "options_availability": options_availability,
            "ose_availability": ose_availability,
            "market_session": market_session or "UNKNOWN",
            "market_closed": market_closed,
            "flow_text": flow_text,
            "structure_text": structure_text,
            "seller_effective": seller_effective,
            "buyer_effective": buyer_effective,
            "sellers_fading": sellers_fading,
            "buyers_fading": buyers_fading,
            "structural_hold": structural_hold,
            "reclaim": reclaim,
            "expansion": expansion,
            "failure_against_bull": failure_against_bull,
            "failure_against_bear": failure_against_bear,
            "options_support_bull": options_support_bull,
            "options_support_bear": options_support_bear,
            "options_state": option_state,
            "options_direction": option_direction,
            "secondary_context": secondary_context,
        }

    @staticmethod
    def _futures_transport_state(transport: Mapping[str, Any]) -> str:
        """Read the authoritative Futures receipt state, never socket-UP proxy."""

        for instrument in transport.get("instruments") or ():
            item = _mapping(instrument)
            if _text(item.get("role")).upper() == "NIFTY_FUTURE":
                return _text(item.get("freshness_state")).upper() or "UNKNOWN"
        return "UNKNOWN"

    @staticmethod
    def _lock_reasons(
        flow: Mapping[str, Any], pulse: Mapping[str, Any], future_present: bool, quality: str,
        directional_state: str, future_stale: bool, flow_is_sole_futures_source: bool,
    ) -> list[str]:
        reasons: list[str] = []
        if not future_present:
            reasons.append("FUTURES_NOT_AVAILABLE")
        if flow_is_sole_futures_source and quality in {"UNUSABLE", "DATA_LOCKED"}:
            reasons.append(f"FLOW_QUALITY_{quality}")
        if flow_is_sole_futures_source and directional_state == "DATA_LOCKED":
            reasons.append("FLOW_DIRECTIONAL_STATE_DATA_LOCKED")
        if future_stale:
            reasons.append("FUTURES_PACKET_STALE")
        if flow_is_sole_futures_source:
            for reason in flow.get("action_lock_reasons") or ():
                value = _text(reason)
                if value and value not in reasons:
                    reasons.append(value)
            if _text(pulse.get("live_health") and _mapping(pulse.get("live_health")).get("status")).upper() == "DATA STALE":
                reasons.append("FLOW_PULSE_DATA_STALE")
        return reasons

    def _next_state_locked(self, observed: Mapping[str, Any]) -> tuple[str, str | None, str]:
        if observed["market_closed"]:
            return self._state, self._direction, "MARKET_CLOSED_RETAINING_LAST_VALID_STATE"
        if observed["locked"]:
            return "DATA_LOCKED", None, "CRITICAL_REQUIRED_DATA_UNTRUSTWORTHY"

        bullish_change = bool(observed["sellers_fading"])
        bearish_change = bool(observed["buyers_fading"])
        direction = "BULLISH" if bullish_change else "BEARISH" if bearish_change else self._direction
        # Flow itself is a valid corroborating family. Options may corroborate,
        # but never become a fabricated mandatory vote when unavailable.
        corroborates_bull = bool(observed["sellers_fading"] or observed["options_support_bull"])
        corroborates_bear = bool(observed["buyers_fading"] or observed["options_support_bear"])
        corroborates = corroborates_bull if direction == "BULLISH" else corroborates_bear if direction == "BEARISH" else False

        if self._state == "DATA_LOCKED":
            if bullish_change:
                return "WATCH", "BULLISH", "REQUIRED_DATA_RESTORED_WITH_SELLERS_LOSING_EFFECTIVENESS"
            if bearish_change:
                return "WATCH", "BEARISH", "REQUIRED_DATA_RESTORED_WITH_BUYERS_LOSING_EFFECTIVENESS"
            return "WAIT", None, "REQUIRED_DATA_RESTORED; WAIT_FOR_NEW_TEMPORAL_EVIDENCE"
        if self._state in {"WAIT", "INVALIDATED"}:
            if bullish_change:
                return "WATCH", "BULLISH", "DOMINANT_SELLERS_LOSING_EFFECTIVENESS"
            if bearish_change:
                return "WATCH", "BEARISH", "DOMINANT_BUYERS_LOSING_EFFECTIVENESS"
            return "WAIT", None, "NO_MEANINGFUL_TRANSITION_EVIDENCE"
        if self._state == "WATCH":
            if direction == "BULLISH" and observed["failure_against_bull"]:
                return "INVALIDATED", direction, "BULLISH_THESIS_STRUCTURALLY_FAILED"
            if direction == "BEARISH" and observed["failure_against_bear"]:
                return "INVALIDATED", direction, "BEARISH_THESIS_STRUCTURALLY_FAILED"
            if (observed["structural_hold"] or observed["reclaim"]) and corroborates:
                return "SETUP", direction, "OLD_THESIS_WEAKENED; STRUCTURE_HOLD_OR_RECLAIM_WITH_INDEPENDENT_CORROBORATION"
            return "WATCH", direction, "WAITING_FOR_STRUCTURAL_PROOF"
        if self._state == "SETUP":
            if direction == "BULLISH" and observed["failure_against_bull"]:
                return "INVALIDATED", direction, "BULLISH_SETUP_STRUCTURALLY_FAILED"
            if direction == "BEARISH" and observed["failure_against_bear"]:
                return "INVALIDATED", direction, "BEARISH_SETUP_STRUCTURALLY_FAILED"
            if observed["expansion"] and corroborates:
                return "TRIGGER", direction, "STRUCTURAL_CONFIRMATION_WITH_TRUSTWORTHY_CONTEMPORANEOUS_EVIDENCE"
            return "SETUP", direction, "WAITING_FOR_BREAK_RECLAIM_OR_RE_ACCELERATION"
        if self._state == "TRIGGER":
            if direction == "BULLISH" and observed["failure_against_bull"]:
                return "INVALIDATED", direction, "BULLISH_TRIGGER_STRUCTURALLY_FAILED"
            if direction == "BEARISH" and observed["failure_against_bear"]:
                return "INVALIDATED", direction, "BEARISH_TRIGGER_STRUCTURALLY_FAILED"
            if observed["expansion"]:
                return "RUNNER", direction, "TRIGGER_THESIS_REMAINS_STRUCTURALLY_HEALTHY"
            return "TRIGGER", direction, "TRIGGER_REMAINS_OPEN"
        if self._state == "RUNNER":
            if direction == "BULLISH" and observed["failure_against_bull"]:
                return "INVALIDATED", direction, "BULLISH_RUNNER_STRUCTURALLY_FAILED"
            if direction == "BEARISH" and observed["failure_against_bear"]:
                return "INVALIDATED", direction, "BEARISH_RUNNER_STRUCTURALLY_FAILED"
            return "RUNNER", direction, "RUNNER_REMAINS_STRUCTURALLY_HEALTHY"
        return "WAIT", None, "STATE_RESET"

    @staticmethod
    def _transition_blockers(observed: Mapping[str, Any], reason: str) -> list[str]:
        """Explain an unchanged state without converting absence into evidence."""

        blockers = list(observed.get("lock_reasons") or ())
        if observed.get("flow_availability") == "UNKNOWN":
            blockers.append("FLOW_UNKNOWN")
        elif observed.get("flow_availability") == "STALE":
            blockers.append("FLOW_STALE")
        if observed.get("options_availability") == "UNKNOWN":
            blockers.append("OPTIONS_UNKNOWN")
        elif observed.get("options_availability") == "STALE":
            blockers.append("OPTIONS_STALE")
        elif observed.get("options_state") == "UNKNOWN":
            blockers.append("OPTIONS_RESPONSE_UNKNOWN")
        if observed.get("ose_availability") == "UNKNOWN":
            blockers.append("OSE_UNKNOWN")
        if reason in {
            "NO_MEANINGFUL_TRANSITION_EVIDENCE",
            "WAITING_FOR_STRUCTURAL_PROOF",
            "WAITING_FOR_BREAK_RECLAIM_OR_RE_ACCELERATION",
        }:
            blockers.append(reason)
        return list(dict.fromkeys(blockers))

    def _hero_from_observation(self, observed: Mapping[str, Any], fusion_state: str, direction: str | None) -> str:
        if observed["market_closed"]:
            return self._hero_state
        if observed["locked"]:
            return "DATA LOCKED"
        if fusion_state in {"WATCH", "SETUP"}:
            return "REVERSAL BUILDING ↑" if direction == "BULLISH" else "REVERSAL BUILDING ↓"
        if fusion_state in {"TRIGGER", "RUNNER"} and direction == "BULLISH":
            return "STRONG BULL TREND · CONTINUATION"
        if fusion_state in {"TRIGGER", "RUNNER"} and direction == "BEARISH":
            return "STRONG BEAR TREND · CONTINUATION"
        if observed["seller_effective"]:
            return "STRONG BEAR TREND · CONTINUATION"
        if observed["buyer_effective"]:
            return "STRONG BULL TREND · CONTINUATION"
        if observed["sellers_fading"]:
            return "BEAR TREND WEAKENING"
        if observed["buyers_fading"]:
            return "BULL TREND WEAKENING"
        flow_text = _text(observed.get("flow_text"))
        if _contains(flow_text, "TWO-WAY", "TWO WAY", "WHIPSAW"):
            return "VERY VOLATILE · TWO-WAY"
        return "SIDEWAYS · NO TREND"

    def _observe_options_locked(self) -> None:
        data = _mapping(self._latest_argus.get("data"))
        underlying = _mapping(data.get("underlying"))
        atm = _number(underlying.get("atm_strike"))
        rows = [row for row in data.get("atm_window") or () if isinstance(row, Mapping)]
        if not rows:
            self._options = {
                "state": "UNKNOWN", "availability": "UNKNOWN",
                "reason": "ATM_WINDOW_UNAVAILABLE", "direction": None, "contracts": [],
            }
            return
        rows.sort(key=lambda row: abs((_number(row.get("strike")) or 0.0) - (atm or 0.0)))
        basket = rows[:5]
        contracts: list[dict[str, Any]] = []
        current: dict[str, dict[str, Any]] = {}
        for row in basket:
            strike = _number(row.get("strike"))
            for side_key, side in (("ce", "CE"), ("pe", "PE")):
                leg = _mapping(row.get(side_key))
                security_id = _text(leg.get("security_id"))
                if not security_id:
                    continue
                quote = self._quote_from_leg(leg, strike, side, underlying)
                current[security_id] = quote
                self._quotes[security_id] = quote
                contracts.append(quote)
        if not contracts:
            self._options = {
                "state": "UNKNOWN", "availability": "UNKNOWN",
                "reason": "OPTION_QUOTES_UNAVAILABLE", "direction": None, "contracts": [],
            }
            return

        changes: list[dict[str, Any]] = []
        for security_id, quote in current.items():
            prior = self._previous_options.get(security_id)
            if prior is None:
                continue
            premium_now = _number(quote.get("mid") or quote.get("ltp"))
            premium_before = _number(prior.get("mid") or prior.get("ltp"))
            oi_now = _number(quote.get("oi"))
            oi_before = _number(prior.get("oi"))
            changes.append({
                "security_id": security_id,
                "side": quote["side"],
                "premium_direction": "UP" if premium_now is not None and premium_before is not None and premium_now > premium_before else "DOWN" if premium_now is not None and premium_before is not None and premium_now < premium_before else "UNCHANGED_OR_UNKNOWN",
                "oi_direction": "UP" if oi_now is not None and oi_before is not None and oi_now > oi_before else "DOWN" if oi_now is not None and oi_before is not None and oi_now < oi_before else "UNCHANGED_OR_UNKNOWN",
            })
        self._previous_options = current
        ce_up = any(change["side"] == "CE" and change["premium_direction"] == "UP" for change in changes)
        ce_down = any(change["side"] == "CE" and change["premium_direction"] == "DOWN" for change in changes)
        pe_up = any(change["side"] == "PE" and change["premium_direction"] == "UP" for change in changes)
        pe_down = any(change["side"] == "PE" and change["premium_direction"] == "DOWN" for change in changes)
        ce_oi_down = any(change["side"] == "CE" and change["oi_direction"] == "DOWN" for change in changes)
        pe_oi_down = any(change["side"] == "PE" and change["oi_direction"] == "DOWN" for change in changes)
        if ce_up and pe_down:
            state, direction, reason = "SUPPORTIVE", "BULLISH", "CE_PREMIUM_IMPROVING_WHILE_PE_PREMIUM_WEAKENS"
        elif ce_down and pe_up:
            state, direction, reason = "SUPPORTIVE", "BEARISH", "PE_PREMIUM_IMPROVING_WHILE_CE_PREMIUM_WEAKENS"
        elif changes:
            state, direction, reason = "CONFLICTING", None, "CE_PE_RESPONSE_NOT_DIRECTIONALLY_ALIGNED"
        else:
            state, direction, reason = "UNKNOWN", None, "NEEDS_TWO_GENUINE_OPTION_SNAPSHOTS"
        self._options = {
            "state": state,
            "availability": "AVAILABLE",
            "direction": direction,
            "reason": reason,
            "focus_strike": atm,
            "contracts": contracts,
            "changes": changes,
            "interpretation": {
                "ce_price_up_oi_down": "CONSISTENT_WITH_POSSIBLE_SHORT_COVERING" if ce_up and ce_oi_down else "NOT_OBSERVED_OR_UNKNOWN",
                "pe_price_up_oi_down": "CONSISTENT_WITH_POSSIBLE_SHORT_COVERING" if pe_up and pe_oi_down else "NOT_OBSERVED_OR_UNKNOWN",
            },
            "breadth": {
                "observed_contracts": len(contracts),
                "ce_premium_up": sum(change["side"] == "CE" and change["premium_direction"] == "UP" for change in changes),
                "pe_premium_up": sum(change["side"] == "PE" and change["premium_direction"] == "UP" for change in changes),
                "ce_oi_down": sum(change["side"] == "CE" and change["oi_direction"] == "DOWN" for change in changes),
                "pe_oi_down": sum(change["side"] == "PE" and change["oi_direction"] == "DOWN" for change in changes),
            },
            "source_timestamp": _text(underlying.get("source_event_time") or underlying.get("fetched_at")) or None,
        }
        self._update_live_premium_tracks_locked()

    @staticmethod
    def _quote_from_leg(leg: Mapping[str, Any], strike: float | None, side: str, underlying: Mapping[str, Any]) -> dict[str, Any]:
        bid = _number(leg.get("top_bid_price"))
        ask = _number(leg.get("top_ask_price"))
        ltp = _number(leg.get("ltp"))
        mid = (bid + ask) / 2.0 if bid is not None and ask is not None else ltp
        return {
            "security_id": _text(leg.get("security_id")),
            "strike": strike,
            "side": side,
            "expiry": _text(underlying.get("expiry")) or None,
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": round(ask - bid, 6) if ask is not None and bid is not None else None,
            "oi": _number(leg.get("oi")),
            "oi_change": _number(leg.get("intraday_change_oi") if leg.get("intraday_change_oi") is not None else leg.get("change_oi")),
            "volume": _number(leg.get("volume")),
            "iv": _number(leg.get("iv")),
            "lot_size": _number(leg.get("lot_size") if leg.get("lot_size") is not None else underlying.get("lot_size")),
            "source_timestamp": _text(underlying.get("source_event_time") or underlying.get("fetched_at")) or None,
        }

    def _freeze_transition_locked(
        self,
        *,
        prior: Mapping[str, Any],
        observation: Mapping[str, Any],
        origin: str,
        reason: str,
        state_changed: bool,
        hero_changed: bool,
    ) -> dict[str, Any]:
        calc_timestamp = self._now()
        state_timestamp = _text(observation.get("source_timestamp")) or calc_timestamp
        seed = "|".join((str(self._revision), self._state, str(self._direction), self._hero_state, state_timestamp, origin, reason))
        event_id = "fusion_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
        snapshot = self._state_snapshot_locked(
            state_event_id=event_id,
            state_timestamp=state_timestamp,
            calc_timestamp=calc_timestamp,
            publication_timestamp=calc_timestamp,
        )
        event = {
            "schema_version": FUSION_SCHEMA_VERSION,
            "event_type": "ARGUS_FUSION_STATE_EVENT",
            "state_event_id": event_id,
            "event_id": event_id,
            "revision": self._revision,
            "transition_kind": "FUSION_AND_HERO" if state_changed and hero_changed else "FUSION" if state_changed else "HERO",
            "from": dict(prior),
            "to": {"fusion_state": self._state, "direction": self._direction, "hero_state": self._hero_state},
            "reason": reason,
            "origin": origin,
            "state_timestamp": state_timestamp,
            "source_timestamp": observation.get("source_timestamp"),
            "receipt_timestamp": observation.get("receipt_timestamp"),
            "calculation_timestamp": calc_timestamp,
            "publication_timestamp": calc_timestamp,
            "publication_timestamp_semantics": "FUSION_READY_FOR_FAST_LANE",
            "data_quality": {"state": "LOCKED" if observation.get("locked") else observation.get("quality"), "reasons": list(observation.get("lock_reasons") or ())},
            "evidence": self._public_evidence(observation),
            "state_snapshot": snapshot,
            "fusion_version": FUSION_VERSION,
            "execution_influence": EXECUTION_INFLUENCE,
            "broker_submission": False,
        }
        self._state_events.append(event)
        if self._state in {"WATCH", "SETUP", "TRIGGER"}:
            self._anchors[self._state] = deepcopy(event)
            self._premium_tracks[event_id] = self._new_premium_track(event)
        self._update_live_premium_tracks_locked()
        self._enqueue_ledger_locked(event)
        return event

    def _state_snapshot_locked(self, *, state_event_id: str, state_timestamp: str, calc_timestamp: str, publication_timestamp: str) -> dict[str, Any]:
        data = _mapping(self._latest_argus.get("data"))
        underlying = _mapping(data.get("underlying"))
        futures_argus = _mapping(data.get("futures"))
        pulse = _mapping(self._latest_flow.get("flow_pulse"))
        futures_flow = _mapping(pulse.get("futures"))
        focus = self._focus_contracts_locked()
        availability = self._observation_locked()
        return {
            "state_event_id": state_event_id,
            "state_name": self._state,
            "timestamp": state_timestamp,
            "source_timestamp": _text(pulse.get("source_timestamp")) or _text(underlying.get("source_event_time")) or None,
            "receipt_timestamp": _text(underlying.get("receipt_timestamp")) or None,
            "calculation_timestamp": calc_timestamp,
            "publication_timestamp": publication_timestamp,
            "spot": _number(underlying.get("ltp")),
            "futures": _number(futures_flow.get("ltp")) or _number(futures_argus.get("ltp")),
            "focus_strike": self._options.get("focus_strike"),
            "focus_contracts": focus,
            "premium_breadth": deepcopy(self._options.get("breadth") or {}),
            "data_quality": {
                "futures": availability.get("futures_availability"),
                "flow": availability.get("flow_availability"),
                "options": availability.get("options_availability"),
                "ose": availability.get("ose_availability"),
            },
            "fusion_version": FUSION_VERSION,
            "evidence_version": FUSION_SCHEMA_VERSION,
        }

    def _new_premium_track(self, event: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = _mapping(event.get("state_snapshot"))
        contracts = [_mapping(value) for value in snapshot.get("focus_contracts") or () if isinstance(value, Mapping)]
        entries: dict[str, dict[str, Any]] = {}
        for quote in contracts:
            security_id = _text(quote.get("security_id"))
            if not security_id:
                continue
            entry = _number(quote.get("ask"))
            entries[security_id] = {
                "security_id": security_id,
                "side": quote.get("side"),
                "start_ask": entry,
                "start_bid": _number(quote.get("bid")),
                "start_ltp": _number(quote.get("ltp")),
                "start_mid": _number(quote.get("mid")),
                "max_live_bid": None,
                "min_live_bid": None,
                "live_bid": None,
                "live_ask": None,
                "live_ltp": None,
                "premium_since_state_percent": None,
                "max_favorable_percent": None,
                "max_adverse_percent": None,
            }
        return {"state_event_id": event.get("state_event_id"), "state": event.get("to", {}).get("fusion_state"), "entries": entries}

    def _update_live_premium_tracks_locked(self) -> None:
        for track in self._premium_tracks.values():
            for security_id, entry in _mapping(track.get("entries")).items():
                quote = self._quotes.get(str(security_id))
                if quote is None:
                    continue
                bid = _number(quote.get("bid"))
                ask = _number(quote.get("ask"))
                ltp = _number(quote.get("ltp"))
                entry["live_bid"] = bid
                entry["live_ask"] = ask
                entry["live_ltp"] = ltp
                start = _number(entry.get("start_ask"))
                if start is None or start <= 0 or bid is None:
                    continue
                entry["max_live_bid"] = max(_number(entry.get("max_live_bid")) or bid, bid)
                entry["min_live_bid"] = min(_number(entry.get("min_live_bid")) or bid, bid)
                entry["premium_since_state_percent"] = round((bid - start) / start * 100.0, 6)
                entry["max_favorable_percent"] = round((_number(entry["max_live_bid"]) - start) / start * 100.0, 6)
                entry["max_adverse_percent"] = round((_number(entry["min_live_bid"]) - start) / start * 100.0, 6)

    def _focus_contracts_locked(self) -> list[dict[str, Any]]:
        contracts = [_mapping(contract) for contract in self._options.get("contracts") or () if isinstance(contract, Mapping)]
        focus_strike = _number(self._options.get("focus_strike"))
        if focus_strike is None:
            return contracts[:2]
        focus = [contract for contract in contracts if _number(contract.get("strike")) == focus_strike]
        return focus or contracts[:2]

    def _update_playbooks_locked(self, event: Mapping[str, Any] | None, observed: Mapping[str, Any]) -> None:
        started = perf_counter()
        direction = self._direction
        lifecycle = {
            "WAIT": "IDLE",
            "WATCH": "WATCHING",
            "SETUP": "SETUP",
            "TRIGGER": "TRIGGERED",
            "RUNNER": "RUNNING",
            "INVALIDATED": "INVALIDATED",
            "DATA_LOCKED": "IDLE",
        }.get(self._state, "IDLE")
        if self._state in {"WATCH", "SETUP", "TRIGGER", "RUNNER", "INVALIDATED"}:
            family = "FAILED_AGGRESSION_REVERSAL" if self._state in {"WATCH", "SETUP"} else "BREAKOUT_EXPANSION" if self._state == "TRIGGER" else "CONTINUATION"
            playbook = self._playbooks[family]
            playbook.update({
                "lifecycle": lifecycle,
                "direction": direction,
                "state_event_id": event.get("state_event_id") if event else playbook.get("state_event_id"),
                "reason": event.get("reason") if event else "LIVE_STATE_CONTINUES",
                "data_quality": "LOCKED" if observed.get("locked") else observed.get("quality"),
            })
        if self._state == "INVALIDATED":
            for name, playbook in self._playbooks.items():
                if name != "EXPIRY_FAST_MOMENTUM" and playbook.get("lifecycle") in {"WATCHING", "SETUP", "TRIGGERED", "RUNNING"}:
                    playbook["lifecycle"] = "INVALIDATED"
                    playbook["reason"] = "FUSION_STRUCTURAL_INVALIDATION"
        self._latencies["playbook_compute_ms"].append((perf_counter() - started) * 1_000.0)

    def _open_shadow_trade_locked(self, event: Mapping[str, Any], observed: Mapping[str, Any]) -> None:
        direction = self._direction
        side = "CE" if direction == "BULLISH" else "PE" if direction == "BEARISH" else None
        contracts = [quote for quote in self._focus_contracts_locked() if quote.get("side") == side]
        contract = contracts[0] if contracts else {}
        futures = _mapping(observed.get("futures"))
        trade_id = "shadow_" + hashlib.sha256(f"{event['state_event_id']}|{side}".encode()).hexdigest()[:24]
        entry_ask = _number(contract.get("ask"))
        trade = {
            "schema_version": FUSION_SCHEMA_VERSION,
            "event_type": "ARGUS_FUSION_TRADE_OPENED",
            "trade_id": trade_id,
            "session_id": self._session_id(event.get("state_timestamp")),
            "status": "TRIGGERED" if entry_ask is not None else "TRIGGERED_UNVALIDATED",
            "setup_family": "BREAKOUT_EXPANSION",
            "direction": direction,
            "watch_time": self._anchor_timestamp("WATCH"),
            "setup_time": self._anchor_timestamp("SETUP"),
            "trigger_time": event.get("state_timestamp"),
            "state_event_id": event.get("state_event_id"),
            "contract": deepcopy(contract) if contract else None,
            "security_id": contract.get("security_id") or None,
            "strike": contract.get("strike"),
            "option_side": side,
            "lot_size": _number(contract.get("lot_size")),
            "spot": _number(_mapping(_mapping(self._latest_argus.get("data")).get("underlying")).get("ltp")),
            "futures_trigger": _number(futures.get("ltp")),
            "entry": {"ask": entry_ask, "bid": _number(contract.get("bid")), "ltp": _number(contract.get("ltp")), "mid": _number(contract.get("mid")), "spread": _number(contract.get("spread")), "truth": "ASK_FOR_HYPOTHETICAL_LONG_OPTION"},
            "structural_invalidation": _number(futures.get("invalidation")),
            "option_equivalent_invalidation": None,
            "targets": {"t1": _number(futures.get("target_1")), "t2": _number(futures.get("target_2")), "t3": None, "status": "RESEARCH_ONLY_EXISTING_STRUCTURAL_LEVELS" if any(_number(futures.get(key)) is not None for key in ("target_1", "target_2")) else "UNVALIDATED"},
            "dont_chase_reference": _number(futures.get("trigger")) if isinstance(futures.get("trigger"), (int, float)) else None,
            "hero_state": self._hero_state,
            "evidence": self._public_evidence(observed),
            "secondary_context": self._secondary_context_locked(),
            "missing_evidence": self._missing_evidence(observed, entry_ask),
            "data_quality": observed.get("quality"),
            "fusion_version": FUSION_VERSION,
            "execution_influence": EXECUTION_INFLUENCE,
            "broker_submission": False,
            "mfe_percent": None,
            "mae_percent": None,
            "shadow_pnl_rupees": None,
            "current_r": None,
            "r_milestones": {"+1R": False, "+2R": False, "+3R": False, "+4R": False, "-1R_first": False},
        }
        self._trades[trade_id] = trade
        self._append_trade_event_locked("ARGUS_FUSION_TRADE_OPENED", trade)

    def _update_live_trades_locked(self, observed: Mapping[str, Any]) -> None:
        current_futures = _number(_mapping(observed.get("futures")).get("ltp"))
        for trade in self._trades.values():
            if trade.get("status") not in {"TRIGGERED", "RUNNING", "TRIGGERED_UNVALIDATED"}:
                continue
            if current_futures is not None:
                trade["live_futures"] = current_futures
            bid = _number(self._quotes.get(_text(trade.get("security_id")), {}).get("bid"))
            entry = _number(_mapping(trade.get("entry")).get("ask"))
            changed = False
            if bid is not None and entry is not None and entry > 0:
                return_pct = (bid - entry) / entry * 100.0
                prior_mfe = _number(trade.get("mfe_percent"))
                prior_mae = _number(trade.get("mae_percent"))
                trade["live_bid"] = bid
                trade["live_premium_percent"] = round(return_pct, 6)
                lot_size = _number(trade.get("lot_size"))
                if lot_size is not None and lot_size > 0:
                    trade["shadow_pnl_rupees"] = round((bid - entry) * lot_size, 2)
                trade["mfe_percent"] = max(prior_mfe if prior_mfe is not None else return_pct, return_pct)
                trade["mae_percent"] = min(prior_mae if prior_mae is not None else return_pct, return_pct)
                changed = trade["mfe_percent"] != prior_mfe or trade["mae_percent"] != prior_mae
            futures_entry = _number(trade.get("futures_trigger"))
            invalidation = _number(trade.get("structural_invalidation"))
            direction = trade.get("direction")
            if current_futures is not None and futures_entry is not None and invalidation is not None:
                risk = abs(futures_entry - invalidation)
                if risk > 0:
                    current_r = (current_futures - futures_entry) / risk if direction == "BULLISH" else (futures_entry - current_futures) / risk
                    trade["current_r"] = round(current_r, 6)
                    milestones = _mapping(trade.get("r_milestones"))
                    prior_milestones = dict(milestones)
                    for level in (1, 2, 3, 4):
                        label = f"+{level}R"
                        milestones[label] = bool(milestones.get(label) or current_r >= level)
                    milestones["-1R_first"] = bool(milestones.get("-1R_first") or current_r <= -1)
                    trade["r_milestones"] = milestones
                    # Current R is a live field. The append-only ledger only
                    # receives a durable update when an objective R milestone
                    # or structural exit changes, not on every packet.
                    changed = changed or milestones != prior_milestones
            if self._state == "RUNNER" and trade.get("status") == "TRIGGERED":
                trade["status"] = "RUNNING"
                changed = True
            invalidated = (
                current_futures is not None and invalidation is not None and (
                    (direction == "BULLISH" and current_futures < invalidation)
                    or (direction == "BEARISH" and current_futures > invalidation)
                )
            )
            if invalidated:
                trade["status"] = "INVALIDATED"
                trade["exit"] = {"time": self._now(), "bid": bid, "reason": "UNDERLYING_STRUCTURAL_INVALIDATION"}
                changed = True
            if changed:
                self._append_trade_event_locked("ARGUS_FUSION_TRADE_UPDATE", trade)

    def _append_trade_event_locked(self, event_type: str, trade: Mapping[str, Any]) -> None:
        payload = deepcopy(dict(trade))
        payload["event_type"] = event_type
        payload["recorded_at"] = self._now()
        payload["event_id"] = "fusion_trade_" + hashlib.sha256(
            f"{payload.get('trade_id')}|{event_type}|{payload.get('recorded_at')}|{payload.get('status')}".encode()
        ).hexdigest()[:24]
        self._trade_events.append(payload)
        self._enqueue_ledger_locked(payload)

    def _enqueue_ledger_locked(self, payload: Mapping[str, Any]) -> None:
        if self.recorder is None:
            return
        started = perf_counter()
        session_id = self._session_id(payload.get("state_timestamp") or payload.get("trigger_time"))
        record = {**dict(payload), "session_id": session_id}
        try:
            self.recorder.submit(str(record.get("event_type") or "ARGUS_FUSION_EVENT"), record, str(record.get("event_id") or record.get("state_event_id") or record.get("trade_id")))
        finally:
            self._latencies["ledger_enqueue_ms"].append((perf_counter() - started) * 1_000.0)

    def _build_projection_locked(self, *, observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
        observed = dict(observation or self._observation_locked())
        events = list(self._state_events)
        latest_event = events[-1] if events else None
        anchors = {
            name: self._premium_track_view(self._anchors.get(name))
            for name in ("WATCH", "SETUP", "TRIGGER")
            if name in self._anchors
        }
        return {
            "schema_version": FUSION_SCHEMA_VERSION,
            "status": "DATA_LOCKED" if self._state == "DATA_LOCKED" else "AVAILABLE",
            "fusion_version": FUSION_VERSION,
            "revision": self._revision,
            "state_event_id": latest_event.get("state_event_id") if latest_event else None,
            "source_timestamp": observed.get("source_timestamp"),
            "calculation_timestamp": self._now(),
            "market_session": observed.get("market_session"),
            "market_closed": bool(observed.get("market_closed")),
            "last_valid_market_state": deepcopy(self._last_valid_market_state),
            "hero": {
                "state": self._hero_state,
                "plain_language": self._hero_message(observed),
                "previous_state": latest_event.get("from", {}).get("hero_state") if latest_event else None,
                "state_event_id": latest_event.get("state_event_id") if latest_event else None,
            },
            "fusion": {
                "state": self._state,
                "direction": self._direction,
                "plain_language": self._fusion_message(observed),
                "next_proof": self._next_proof(),
                "action": self._action_label(),
                "transition_reason": self._last_transition_reason,
                "transition_blockers": list(self._last_transition_blockers),
                "evidence": self._public_evidence(observed),
                "alignment_measurement": None,
                "score_authority": "NONE",
            },
            "data_quality": {
                "state": "MARKET_CLOSED" if observed.get("market_closed") else "LOCKED" if observed.get("locked") else "LIVE" if observed.get("quality") == "GOOD" else observed.get("quality"),
                "lock_reasons": list(observed.get("lock_reasons") or ()),
                "expected_instruments": _mapping(self._latest_flow.get("transport")).get("EXPECTED_INSTRUMENTS"),
                "fresh_instruments": _mapping(self._latest_flow.get("transport")).get("FRESH_INSTRUMENTS"),
                "flow_availability": observed.get("flow_availability"),
                "futures_availability": observed.get("futures_availability"),
                "options_availability": observed.get("options_availability"),
                "ose_availability": observed.get("ose_availability"),
                "futures_source": observed.get("futures_source"),
            },
            "premium_tracker": anchors,
            "playbooks": deepcopy(self._playbooks),
            "today_shadow_trades": deepcopy(list(self._trades.values())),
            "history_summary": {
                "state_event_count": len(events),
                "trade_event_count": len(self._trade_events),
                "recent_events": deepcopy(events[-16:]),
            },
            "telemetry": {name: _distribution(values) for name, values in self._latencies.items()},
            "advisory_only": True,
            "execution_influence": EXECUTION_INFLUENCE,
            "execution_authority": False,
            "broker_submission": False,
        }

    def _premium_track_view(self, event: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not event:
            return None
        event_id = _text(event.get("state_event_id"))
        return {
            "state_event": deepcopy(event),
            "live": deepcopy(self._premium_tracks.get(event_id, {})),
        }

    def _secondary_context_locked(self) -> dict[str, Any]:
        tactical = _mapping(_mapping(self._latest_argus.get("data")).get("tactical_edge"))
        prime = _mapping(tactical.get("argus_prime"))
        ose = _mapping(tactical.get("ose") or _mapping(self._latest_argus.get("data")).get("ose"))
        ose_state = _text(ose.get("state") or ose.get("status") or "UNKNOWN")
        ose_availability = (
            "UNKNOWN" if ose_state == "UNKNOWN"
            else "STALE" if _contains(_upper(ose_state, ose.get("freshness")), "STALE", "LAST_GOOD")
            else "AVAILABLE"
        )
        return {
            "prime": {"state": _text(prime.get("display_state") or prime.get("action") or "UNKNOWN"), "classification": "NEUTRAL"},
            "ose": {"state": ose_state, "availability": ose_availability, "classification": "UNKNOWN"},
            "policy": "SECONDARY_CONTEXT_NOT_A_MANDATORY_VETO",
        }

    @staticmethod
    def _public_evidence(observed: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "price_futures": {
                "availability": observed.get("futures_availability"),
                "seller_effective": bool(observed.get("seller_effective")),
                "buyer_effective": bool(observed.get("buyer_effective")),
                "structural_hold": bool(observed.get("structural_hold")),
                "reclaim": bool(observed.get("reclaim")),
                "expansion": bool(observed.get("expansion")),
            },
            "flow": {
                "availability": observed.get("flow_availability"),
                "sellers_fading": bool(observed.get("sellers_fading")),
                "buyers_fading": bool(observed.get("buyers_fading")),
                "source": "EXISTING_FLOW_PULSE_SEMANTICS",
            },
            "options": {
                "availability": observed.get("options_availability"),
                "state": observed.get("options_state"),
                "direction": observed.get("options_direction"),
                "source": "EXISTING_ARGUS_ATM_WINDOW",
            },
            "secondary_context": deepcopy(observed.get("secondary_context") or {}),
        }

    def _hero_message(self, observed: Mapping[str, Any]) -> str:
        if observed.get("locked"):
            return "Critical required data is untrustworthy. New shadow triggers are locked."
        if self._hero_state.startswith("REVERSAL BUILDING"):
            return "The prior dominant side is losing effectiveness; structure still needs proof."
        if self._hero_state.endswith("CONTINUATION"):
            return "The dominant side remains effective. Fusion can still be WAIT; do not chase an extended move."
        if "WEAKENING" in self._hero_state:
            return "The established direction is weakening, not yet reversed."
        return "No proven directional transition is active."

    def _fusion_message(self, observed: Mapping[str, Any]) -> str:
        if self._state == "DATA_LOCKED":
            return "DATA LOCKED · required Futures structure is unavailable or stale."
        if self._state == "WATCH":
            return "Dominant-side effectiveness is fading. No trade; wait for structural proof."
        if self._state == "SETUP":
            return "Old thesis weakened and structure held/reclaimed with corroboration. Prepare only."
        if self._state == "TRIGGER":
            return "A structural confirmation occurred with contemporaneous evidence. Shadow research only."
        if self._state == "RUNNER":
            return "The triggered structural thesis remains healthy."
        if self._state == "INVALIDATED":
            return "The shadow thesis failed structurally; the immutable record remains available."
        return "WAIT · no meaningful transition evidence."

    def _next_proof(self) -> str:
        if self._state == "WATCH":
            return "Structural hold or reclaim with independent corroboration."
        if self._state == "SETUP":
            return "Clean break, acceptance, or re-acceleration of current structure."
        if self._state == "TRIGGER":
            return "Continuation without structural invalidation."
        if self._state == "DATA_LOCKED":
            return "Fresh trustworthy Futures/Flow evidence."
        return "A meaningful temporal change in market behavior."

    def _action_label(self) -> str:
        if self._state == "SETUP":
            return "WAIT · PREPARE · DO NOT CHASE"
        if self._state == "TRIGGER":
            return "SHADOW TRIGGER · RESEARCH ONLY"
        if self._state == "RUNNER":
            return "SHADOW RUNNER · RESEARCH ONLY"
        if self._state == "DATA_LOCKED":
            return "NO NEW TRIGGER"
        return "WAIT"

    def _anchor_timestamp(self, state: str) -> str | None:
        event = self._anchors.get(state)
        return _text(event.get("state_timestamp")) or None if event else None

    @staticmethod
    def _session_id(timestamp: Any) -> str:
        value = _text(timestamp)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _missing_evidence(observed: Mapping[str, Any], entry_ask: float | None) -> list[str]:
        missing: list[str] = []
        if observed.get("flow_availability") != "AVAILABLE":
            missing.append(f"FLOW_{observed.get('flow_availability') or 'UNKNOWN'}")
        if observed.get("options_availability") != "AVAILABLE":
            missing.append(f"OPTIONS_{observed.get('options_availability') or 'UNKNOWN'}")
        elif observed.get("options_state") == "UNKNOWN":
            missing.append("OPTIONS_RESPONSE_UNKNOWN")
        if entry_ask is None:
            missing.append("EXECUTABLE_OPTION_ASK_UNAVAILABLE")
        futures = _mapping(observed.get("futures"))
        if _number(futures.get("invalidation")) is None:
            missing.append("STRUCTURAL_INVALIDATION_UNVALIDATED")
        if _number(futures.get("target_1")) is None:
            missing.append("TARGETS_UNVALIDATED")
        return missing
