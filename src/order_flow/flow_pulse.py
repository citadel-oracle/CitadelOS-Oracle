"""Video-faithful, score-free Futures episode projection for Oracle.

The kernel consumes the canonical reconciled NIFTY Futures event stream.  It
does not fetch, persist, place orders, or influence any existing engine.
"""

from __future__ import annotations

import hashlib
import math
import threading
from bisect import bisect_left, insort
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from time import perf_counter_ns
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .contracts import MarketEvent, ReconciledTradeState
from .action_contract import validate_action_contract


IST = ZoneInfo("Asia/Kolkata")
FLOW_PULSE_VERSION = "ARGUS_FLOW_PULSE_V1_20260811"
TICK_SIZE = 0.05
OPTION_QUOTE_FRESH_NS = 20_000_000_000
SEMANTIC_HISTORY = 257
SEMANTIC_TRANSITION_HISTORY = 2_048
STRUCTURAL_LEVEL_STATES = frozenset({
    "BROKE ABOVE", "BROKE BELOW", "BACK ABOVE", "BACK BELOW", "BREAK FAILED",
})
STRUCTURAL_LEVELS = frozenset({
    "PDH", "PDL", "PREVIOUS CLOSE", "OR HIGH", "OR LOW", "LVN",
})


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _robust_baseline(values: deque[float]) -> tuple[float, float]:
    """Return a rolling median/MAD baseline without manufacturing a score."""

    if not values:
        return 0.0, 0.0
    center = float(median(values))
    deviation = float(median(abs(value - center) for value in values))
    return center, deviation


@dataclass(frozen=True, slots=True)
class ReferenceLevels:
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    previous_close: float | None = None
    source_timestamp: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionBurst:
    timestamp: str
    side: str
    quantity: int
    price: float


def _latency_window() -> deque[int]:
    """Pickle-safe factory for persisted recovery checkpoints."""
    return deque(maxlen=50_000)


class ArgusFlowPulseEngine:
    """Fixed-memory packet kernel whose visible state changes on market events."""

    def __init__(
        self,
        *,
        tick_size: float = TICK_SIZE,
        option_quote_fresh_ns: int = OPTION_QUOTE_FRESH_NS,
        clock_ns: Any = perf_counter_ns,
    ) -> None:
        self.tick_size = tick_size
        self.option_quote_fresh_ns = option_quote_fresh_ns
        self._clock_ns = clock_ns
        self.reference = ReferenceLevels()
        self.session_id: str | None = None
        self._events: deque[tuple[int, float, int, int, int]] = deque(maxlen=8_192)
        self._activity_2s: deque[tuple[int, float, int, int, int]] = deque()
        self._activity_6s: deque[tuple[int, float, int, int, int]] = deque()
        self._activity_2s_totals = [0, 0, 0]
        self._activity_6s_totals = [0, 0, 0]
        self._profile: dict[float, int] = defaultdict(int)
        self._profile_prices: list[float] = []
        self._profile_selected: set[float] = set()
        self._profile_selected_volume = 0
        self._profile_poc: float | None = None
        self._profile_poc_quantity = 0
        self._profile_val: float | None = None
        self._profile_vah: float | None = None
        self._lvn_candidates: set[float] = set()
        self._value_migration = "FLAT"
        self._profile_total = 0
        self._profile_snapshot: dict[str, Any] = self._empty_profile()
        self._profile_rebuilds = 0
        self._profile_revision = 0
        self._profile_change_counts = {"poc": 0, "vah": 0, "val": 0}
        self._previous_profile_levels = {"poc": None, "vah": None, "val": None}
        self._prior_profile_center: float | None = None
        self._or_high: float | None = None
        self._or_low: float | None = None
        self._or_frozen = False
        self._or_source_timestamp: str | None = None
        self._bucket_id: int | None = None
        self._bucket_side = {"BUY": 0, "SELL": 0, "UNKNOWN": 0}
        self._bucket_price = 0.0
        self._bucket_timestamp = ""
        self._bursts: deque[ExecutionBurst] = deque(maxlen=32)
        self._bars = {120: [], 180: []}
        self._forming_bars: dict[int, dict[str, Any]] = {}
        self._breaches: dict[str, dict[str, Any]] = {}
        self._level_states: dict[str, dict[str, Any]] = {}
        self._level_transition_queue: deque[dict[str, Any]] = deque(maxlen=4_096)
        self._last_level_event = "NO LEVEL EVENT YET"
        self._active_level_name: str | None = None
        self._next_level: dict[str, Any] = {
            "name": "NONE NEARBY", "price": None, "distance_points": None, "state": "FAR",
        }
        self._episode: dict[str, Any] = self._empty_episode()
        self._transition_queue: deque[dict[str, Any]] = deque()
        self._action_revision = 0
        self._semantic_revision = 0
        self._semantic = {
            "market": "BALANCED ↔",
            "pressure": "QUIET",
            "result": "FLOW NOT CLEAN ENOUGH",
            "speed": "QUIET",
        }
        self._semantic_candidates: dict[str, tuple[str, int, bool]] = {}
        self._semantic_provenance: dict[str, dict[str, Any]] = {
            name: {
                "source_revision": 0, "raw_state": value, "display_state": value,
                "change_reason": "INITIAL_STATE", "timestamp": None,
            }
            for name, value in self._semantic.items()
        }
        self._semantic_raw_history = {
            name: deque(maxlen=SEMANTIC_HISTORY)
            for name in self._semantic
        }
        self._pressure_strengths: deque[float] = deque(maxlen=SEMANTIC_HISTORY)
        self._raw_pressure_direction: str | None = None
        self._speed_activity: deque[float] = deque(maxlen=SEMANTIC_HISTORY)
        self._book_spread = self.tick_size
        self._semantic_transition_queue: deque[dict[str, Any]] = deque(
            maxlen=SEMANTIC_TRANSITION_HISTORY
        )
        self._latest: dict[str, Any] = self._empty_projection()
        self._revision = 0
        self._update_count = 0
        self._latency_ns: deque[int] = deque(maxlen=50_000)
        self._stage_latency_ns: dict[str, deque[int]] = defaultdict(_latency_window)
        # Telemetry has independent synchronization.  The trading state remains
        # single-owner; this lock only lets an observability thread take a short
        # immutable sample copy before doing percentile sorting off the packet
        # thread.
        self._telemetry_lock = threading.Lock()
        self._latest_options: dict[str, MarketEvent] = {}
        self._paper_trades: dict[str, dict[str, Any]] = {}
        self._episode_level_revisions: dict[str, list[dict[str, Any]]] = {}
        self._paper_event_queue: deque[dict[str, Any]] = deque()
        self._validation_event_queue: deque[dict[str, Any]] = deque()
        self._last_validation_identity: str | None = None

    def __getstate__(self) -> dict[str, Any]:
        """Keep v2 checkpoints compatible while excluding runtime-only locks."""

        state = dict(self.__dict__)
        state.pop("_telemetry_lock", None)
        return state

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        self.__dict__.update(dict(state))
        self._telemetry_lock = threading.Lock()

    def register_reference_levels(
        self,
        *,
        previous_day_high: float | None,
        previous_day_low: float | None,
        previous_close: float | None,
        source_timestamp: str | None = None,
    ) -> None:
        values = (previous_day_high, previous_day_low, previous_close)
        if any(value is not None and (not math.isfinite(value) or value <= 0) for value in values):
            raise ValueError("invalid Futures reference level")
        self.reference = ReferenceLevels(*values, source_timestamp)

    def register_opening_range(self, *, high: float, low: float, source_timestamp: str) -> None:
        if not all(math.isfinite(value) and value > 0 for value in (high, low)) or high < low:
            raise ValueError("invalid Futures opening range")
        self._or_high = float(high)
        self._or_low = float(low)
        self._or_frozen = True
        self._or_source_timestamp = source_timestamp

    def update(
        self,
        event: MarketEvent,
        trade: ReconciledTradeState,
        *,
        book: Any = None,
        response: Any = None,
    ) -> dict[str, Any]:
        started = self._clock_ns()
        if event.option_type in {"CE", "PE"}:
            self._latest_options[event.instrument_role] = event
            self._refresh_option_mapping()
            self._mark_paper_trades(event)
            if self._latest:
                self._latest["paper_trades"] = self.paper_trades()
            return self._latest
        if event.instrument_role != "NIFTY_FUTURE":
            return self._latest
        if self.session_id != event.session_id:
            self._reset_session(event.session_id)

        self._update_count += 1
        self._opening_range(event)
        activity = (
            event.feed_receive_ns,
            event.ltp,
            trade.classified_buy_qty,
            trade.classified_sell_qty,
            trade.unclassified_qty,
        )
        self._events.append(activity)
        self._append_activity(activity)
        profile_started = self._clock_ns()
        if trade.delta_volume > 0:
            price = self._bin(event.ltp)
            self._update_profile(price, trade.delta_volume, event.ltp)
        self._record_latency("profile_update", self._clock_ns() - profile_started)
        self._execution_burst(event, trade)
        self._update_bar(event, 120)
        self._update_bar(event, 180)
        self._record_latency("microstructure_update", self._clock_ns() - started)
        tape = self._tape_state(event.feed_receive_ns)
        reaction = self._reaction(response)
        flow = self._flow_state(event.feed_receive_ns)
        spread = getattr(book, "spread", None)
        if isinstance(spread, (int, float)) and math.isfinite(spread) and spread > 0:
            self._book_spread = float(spread)
        semantic_started = self._clock_ns()
        self._update_semantics(event, flow=flow, tape=tape, reaction=reaction)
        self._update_level_radar(event)
        self._record_latency("semantic_commit", self._clock_ns() - semantic_started)
        episode_started = self._clock_ns()
        self._evaluate_episode(event, tape=tape, reaction=reaction)
        self._update_paper_trades(event)
        self._record_latency("episode_evaluation", self._clock_ns() - episode_started)
        projection_started = self._clock_ns()
        self._latest = self._projection(event, tape=tape, reaction=reaction, flow=flow, book=book)
        self._record_latency("projection", self._clock_ns() - projection_started)
        self._record_latency(None, self._clock_ns() - started)
        return self._latest

    def latest(self) -> dict[str, Any]:
        return dict(self._latest)

    def drain_transitions(self) -> list[dict[str, Any]]:
        values = list(self._transition_queue)
        self._transition_queue.clear()
        return values

    def drain_semantic_transitions(self) -> list[dict[str, Any]]:
        values = list(self._semantic_transition_queue)
        self._semantic_transition_queue.clear()
        return values

    def drain_level_transitions(self) -> list[dict[str, Any]]:
        values = list(self._level_transition_queue)
        self._level_transition_queue.clear()
        return values

    def action_payload(self) -> dict[str, Any]:
        """Return the compact, already-current ACTION lane contract."""

        pulse = self._latest
        futures = pulse.get("futures") if isinstance(pulse.get("futures"), Mapping) else {}
        option = pulse.get("option") if isinstance(pulse.get("option"), Mapping) else None
        contract = pulse.get("action_contract") if isinstance(pulse.get("action_contract"), Mapping) else {}
        return {
            "revision": self._action_revision,
            "semantic_revision": self._semantic_revision,
            "headline": pulse.get("headline"),
            "model": pulse.get("model"),
            "story": pulse.get("story"),
            "key_level": pulse.get("key_level"),
            "trigger": futures.get("trigger"),
            "option": dict(option) if option is not None else None,
            "stop": futures.get("invalidation"),
            "target_1": futures.get("target_1"),
            "target_2": futures.get("target_2"),
            "episode_state": pulse.get("state"),
            "source_timestamp": pulse.get("source_timestamp"),
            "packet_receive_ns": pulse.get("packet_receive_ns"),
            "action_ready_ns": self._clock_ns(),
            "candidate_plan_id": contract.get("candidate_plan_id"),
            "validated_plan_id": contract.get("validated_plan_id"),
            "video_event_id": contract.get("video_event_id"),
            "episode_id": contract.get("episode_id"),
            "level_revision": (contract.get("candidate_plan") or {}).get("level_revision")
            if isinstance(contract.get("candidate_plan"), Mapping) else None,
            "plan_validation": contract.get("plan_validation"),
            "validation_reason": contract.get("validation_reason"),
        }

    def meters_payload(self) -> dict[str, Any]:
        """Return the compact coalescible meter lane; raw compute remains per event."""

        pulse = self._latest
        return {
            key: pulse.get(key)
            for key in (
                "revision", "semantic_revision", "source_timestamp", "packet_receive_ns",
                "futures", "semantic", "semantic_provenance", "flow", "tape", "profile", "levels",
                "key_level", "next_level", "what_happened", "open_range", "live_health",
                "data_quality", "paper_trades", "paper_episodes",
            )
        }

    def drain_paper_events(self) -> list[dict[str, Any]]:
        values = list(self._paper_event_queue)
        self._paper_event_queue.clear()
        return values

    def drain_validation_events(self) -> list[dict[str, Any]]:
        values = list(self._validation_event_queue)
        self._validation_event_queue.clear()
        return values

    def paper_trades(self) -> list[dict[str, Any]]:
        return [dict(value) for value in sorted(self._paper_trades.values(), key=lambda row: (str(row["entry_time"]), str(row["trade_id"])))]

    def restore_paper_trades(self, rows: list[Mapping[str, Any]]) -> None:
        """Restore only immutable advisory records from the indexed session stream."""
        for row in rows:
            trade_id = row.get("trade_id")
            if (
                isinstance(trade_id, str)
                and row.get("broker_submission") is False
                and row.get("execution_influence") == "ZERO"
            ):
                self._paper_trades[trade_id] = dict(row)

    def paper_episodes(self) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for leg in self.paper_trades():
            episode_id = str(leg["episode_id"])
            episode = grouped.setdefault(episode_id, {
                "episode_id": episode_id,
                "session_id": leg.get("session_id"),
                "model": leg.get("model"),
                "direction": leg.get("direction"),
                "area": leg.get("area"),
                "story": leg.get("story"),
                "start_time": leg.get("entry_time"),
                "terminal_time": None,
                "state": leg.get("state"),
                "futures_invalidation": leg.get("futures_invalidation"),
                "futures_target_1": leg.get("futures_target_1"),
                "futures_target_2": leg.get("futures_target_2"),
                "futures_current_price": leg.get("futures_current_price"),
                "entry_legs": [],
                "level_revisions": list(leg.get("level_revisions") or ()),
                "execution_influence": "ZERO",
                "broker_submission": False,
            })
            episode["entry_legs"].append(leg)
            episode["state"] = leg.get("state")
            episode["terminal_time"] = leg.get("exit_time") or episode["terminal_time"]
            episode["futures_current_price"] = leg.get("futures_current_price")
        return [grouped[key] for key in sorted(grouped, key=lambda item: str(grouped[item]["start_time"]))]

    def telemetry(self) -> dict[str, Any]:
        # Copy bounded windows under the telemetry-only lock, then release it
        # before the expensive exact percentile sorts.  In production this is
        # called only by OrderFlowService's asynchronous telemetry worker.
        with self._telemetry_lock:
            latency_values = tuple(self._latency_ns)
            stage_values = {
                name: tuple(samples)
                for name, samples in self._stage_latency_ns.items()
            }
            profile_rebuilds = self._profile_rebuilds
        values = sorted(latency_values)
        def q(percentile: float) -> float | None:
            if not values:
                return None
            index = min(len(values) - 1, max(0, math.ceil(percentile * len(values)) - 1))
            return round(values[index] / 1_000_000.0, 6)
        stages = {}
        for name, samples in stage_values.items():
            ordered = sorted(samples)
            stages[name] = {
                "p50_ms": round(ordered[max(0, math.ceil(0.50 * len(ordered)) - 1)] / 1_000_000.0, 6),
                "p95_ms": round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] / 1_000_000.0, 6),
                "p99_ms": round(ordered[max(0, math.ceil(0.99 * len(ordered)) - 1)] / 1_000_000.0, 6),
                "max_ms": round(ordered[-1] / 1_000_000.0, 6),
            }
        return {
            "count": len(values),
            "p50_ms": q(0.50),
            "p95_ms": q(0.95),
            "p99_ms": q(0.99),
            "max_ms": round(values[-1] / 1_000_000.0, 6) if values else None,
            "profile_rebuilds": profile_rebuilds,
            "full_history_scans_per_event": 0,
            "filesystem_calls_per_event": 0,
            "deep_copies_per_event": 0,
            "stages": stages,
        }

    def _record_latency(self, stage: str | None, elapsed_ns: int) -> None:
        """O(1) telemetry observation; percentile work is never done here."""

        with self._telemetry_lock:
            if stage is None:
                self._latency_ns.append(int(elapsed_ns))
            else:
                self._stage_latency_ns[stage].append(int(elapsed_ns))

    def _reset_session(self, session_id: str) -> None:
        telemetry_lock = self._telemetry_lock
        reference = self.reference
        options = self._latest_options
        paper_trades = {
            key: value for key, value in self._paper_trades.items()
            if value.get("session_id") == session_id
        }
        opening_range = (self._or_high, self._or_low, self._or_source_timestamp)
        # Keep the observability lock identity stable across the in-place
        # session reset so an asynchronous telemetry copy cannot race a new
        # set of bounded windows.
        with telemetry_lock:
            self.__init__(
                tick_size=self.tick_size,
                option_quote_fresh_ns=self.option_quote_fresh_ns,
                clock_ns=self._clock_ns,
            )
            self._telemetry_lock = telemetry_lock
        self.reference = reference
        self._latest_options = options
        self._paper_trades = paper_trades
        self.session_id = session_id
        if opening_range[2] and str(opening_range[2]).startswith(session_id):
            self._or_high, self._or_low, self._or_source_timestamp = opening_range
            self._or_frozen = opening_range[0] is not None and opening_range[1] is not None

    def _update_paper_trades(self, event: MarketEvent) -> None:
        state = str(self._episode.get("state") or "")
        side = self._episode.get("side")
        if state in {"EARLY BUY CE", "EARLY BUY PE", "BUY CE · CONFIRMED", "BUY PE · CONFIRMED"} and side in {"CE", "PE"}:
            validation = self._validate_candidate(event)
            if not validation["valid"]:
                self._record_validation_failure(validation, event.receive_wall_utc)
                self._mark_paper_trades(event)
                return
            entry_type = "CONFIRMED" if "CONFIRMED" in state else "AGGRESSIVE"
            option = self._selected_option(side, event)
            if option and option.get("status") == "AVAILABLE":
                episode_seed = str(self._episode.get("setup_id") or "|".join(str(value) for value in (
                    self.session_id, self._episode.get("model"), side,
                    self._episode.get("area"), self._episode.get("setup_started_at"),
                )))
                episode_id = "pulse_episode_" + hashlib.sha256(episode_seed.encode()).hexdigest()[:18]
                trade_id = "pulse_trade_" + hashlib.sha256(f"{episode_id}|{entry_type}".encode()).hexdigest()[:18]
                if trade_id not in self._paper_trades:
                    ask = float(option["ask"])
                    invalidation = self._episode.get("invalidation")
                    target_1 = self._episode.get("target_1")
                    risk = abs(event.ltp - float(invalidation)) if isinstance(invalidation, (int, float)) else None
                    reward = abs(float(target_1) - event.ltp) if isinstance(target_1, (int, float)) else None
                    self._paper_trades[trade_id] = {
                        "trade_id": trade_id,
                        "episode_id": episode_id,
                        "session_id": self.session_id,
                        "model": str(self._episode.get("model") or "UNAVAILABLE").replace(" · ", "_").replace(" ", "_"),
                        "entry_type": entry_type,
                        "direction": side,
                        "area": self._episode.get("area"),
                        "story": self._episode.get("story"),
                        "state": "OPEN",
                        "entry_time": event.receive_wall_utc,
                        "confirmation_time": event.receive_wall_utc if entry_type == "CONFIRMED" else None,
                        "t1_time": None, "t2_time": None, "exit_time": None,
                        "futures_entry_trigger": self._episode.get("trigger"),
                        "futures_entry_price": event.ltp,
                        "futures_invalidation": self._episode.get("invalidation"),
                        "futures_original_invalidation": self._episode.get("original_invalidation", self._episode.get("invalidation")),
                        "futures_current_invalidation": self._episode.get("invalidation"),
                        "futures_target_1": self._episode.get("target_1"),
                        "futures_target_2": self._episode.get("target_2"),
                        "level_lineage": dict(self._episode.get("level_lineage") or {}),
                        "level_revisions": [{
                            "timestamp": event.receive_wall_utc,
                            "invalidation": self._episode.get("invalidation"),
                            "target_1": self._episode.get("target_1"),
                            "target_2": self._episode.get("target_2"),
                            "reason": "ENTRY_LEVELS_LOCKED",
                        }],
                        "futures_current_price": event.ltp,
                        "futures_mfe": 0.0, "futures_mae": 0.0,
                        "strike": option.get("strike"), "security_id": option.get("security_id"),
                        "expiry": option.get("expiry"), "entry_ask": ask,
                        "live_bid": option.get("bid"), "live_ask": option.get("ask"),
                        "pnl_option_points": float(option["bid"]) - ask,
                        "pnl_rupees": None, "lot_size": None,
                        "mfe": max(0.0, float(option["bid"]) - ask),
                        "mae": min(0.0, float(option["bid"]) - ask),
                        "structural_rr": round(reward / risk, 6) if risk and reward is not None else None,
                        "realized_r": None,
                        "exit_bid": None,
                        "advisory_only": True, "execution_influence": "ZERO",
                        "broker_submission": False,
                    }
                    self._paper_event_queue.append(dict(self._paper_trades[trade_id]))
        self._mark_paper_trades(event)

    def _mark_paper_trades(self, event: MarketEvent) -> None:
        state = str(self._episode.get("state") or "")
        for trade in self._paper_trades.values():
            if trade["state"] in {"INVALIDATED", "EXITED"}:
                continue
            changed = False
            if event.instrument_role == "NIFTY_FUTURE":
                price = float(event.ltp)
                entry = float(trade["futures_entry_price"])
                move = price - entry if trade["direction"] == "CE" else entry - price
                trade["futures_current_price"] = price
                trade["futures_mfe"] = max(float(trade["futures_mfe"]), move)
                trade["futures_mae"] = min(float(trade["futures_mae"]), move)
                if state == "INVALID / EXIT":
                    trade["state"] = "INVALIDATED"; trade["exit_time"] = event.receive_wall_utc
                    trade["exit_bid"] = trade.get("live_bid")
                    trade["exit_reason"] = self._episode.get("reason_for_state_change"); changed = True
                elif state == "T2 HIT · EXIT":
                    trade["state"] = "EXITED"; trade["t2_time"] = event.receive_wall_utc
                    trade["exit_time"] = event.receive_wall_utc
                    trade["exit_bid"] = trade.get("live_bid")
                    trade["exit_reason"] = self._episode.get("reason_for_state_change"); changed = True
                elif state == "T1 HIT · PROTECT" and trade["t1_time"] is None:
                    trade["state"] = "T1 HIT"; trade["t1_time"] = event.receive_wall_utc; changed = True
                elif state == "RUNNER" and trade["state"] != "RUNNER":
                    trade["state"] = "RUNNER"; changed = True
                if changed and trade["state"] in {"INVALIDATED", "EXITED"}:
                    risk = abs(
                        float(trade.get("futures_entry_price") or 0)
                        - float(trade.get("futures_invalidation") or 0)
                    )
                    trade["realized_r"] = round(move / risk, 6) if risk else None
            if event.security_id == trade["security_id"]:
                top = event.depth_5[0]
                mark = float(top.bid_price)
                pnl = mark - float(trade["entry_ask"])
                trade["live_bid"] = mark; trade["live_ask"] = float(top.ask_price)
                trade["pnl_option_points"] = pnl
                if trade.get("state") in {"INVALIDATED", "EXITED"}:
                    trade["exit_bid"] = mark
                trade["mfe"] = max(float(trade["mfe"]), pnl)
                trade["mae"] = min(float(trade["mae"]), pnl)
                risk = abs(float(trade.get("futures_entry_price") or 0) - float(trade.get("futures_invalidation") or 0))
                future_move = (
                    float(trade.get("futures_current_price") or 0) - float(trade.get("futures_entry_price") or 0)
                    if trade["direction"] == "CE"
                    else float(trade.get("futures_entry_price") or 0) - float(trade.get("futures_current_price") or 0)
                )
                trade["realized_r"] = round(future_move / risk, 6) if risk and trade.get("state") in {"INVALIDATED", "EXITED"} else None
            if changed:
                self._paper_event_queue.append(dict(trade))

    def _opening_range(self, event: MarketEvent) -> None:
        timestamp = datetime.fromisoformat(event.receive_wall_utc).astimezone(IST)
        start = timestamp.replace(hour=9, minute=15, second=0, microsecond=0)
        elapsed = (timestamp - start).total_seconds()
        if 0 <= elapsed < 30 and not self._or_frozen:
            self._or_high = event.ltp if self._or_high is None else max(self._or_high, event.ltp)
            self._or_low = event.ltp if self._or_low is None else min(self._or_low, event.ltp)
        elif elapsed >= 30 and self._or_high is not None and self._or_low is not None:
            self._or_frozen = True
            if self._or_source_timestamp is None:
                self._or_source_timestamp = event.receive_wall_utc
        elif elapsed >= 30:
            # A mid-session process start must not pretend the opening range is
            # still forming. Startup recovery may populate it independently.
            self._or_frozen = True

    def _execution_burst(self, event: MarketEvent, trade: ReconciledTradeState) -> None:
        bucket = event.feed_receive_ns // 100_000_000
        if self._bucket_id is not None and bucket != self._bucket_id:
            side = max(self._bucket_side, key=self._bucket_side.get)
            quantity = sum(self._bucket_side.values())
            if quantity:
                self._bursts.append(ExecutionBurst(self._bucket_timestamp, side, quantity, self._bucket_price))
            self._bucket_side = {"BUY": 0, "SELL": 0, "UNKNOWN": 0}
        self._bucket_id = bucket
        self._bucket_price = event.ltp
        self._bucket_timestamp = event.receive_wall_utc
        self._bucket_side["BUY"] += trade.classified_buy_qty
        self._bucket_side["SELL"] += trade.classified_sell_qty
        self._bucket_side["UNKNOWN"] += trade.unclassified_qty

    def _update_bar(self, event: MarketEvent, seconds: int) -> None:
        timestamp = datetime.fromisoformat(event.receive_wall_utc).timestamp()
        bucket = int(timestamp // seconds * seconds)
        current = self._forming_bars.get(seconds)
        if current is None or current["time"] != bucket:
            if current is not None:
                self._bars[seconds].append(current)
                if len(self._bars[seconds]) > 64:
                    del self._bars[seconds][:-64]
            current = {"time": bucket, "open": event.ltp, "high": event.ltp, "low": event.ltp, "close": event.ltp}
            self._forming_bars[seconds] = current
        else:
            current["high"] = max(current["high"], event.ltp)
            current["low"] = min(current["low"], event.ltp)
            current["close"] = event.ltp

    def _update_profile(self, price: float, quantity: int, current_price: float) -> None:
        """Increment POC/value/LVN state without a session-wide profile rebuild."""

        prior_levels = (self._profile_poc, self._profile_vah, self._profile_val)
        if price not in self._profile:
            insort(self._profile_prices, price)
        self._profile[price] += quantity
        self._profile_total += quantity
        if price in self._profile_selected:
            self._profile_selected_volume += quantity
        price_quantity = self._profile[price]
        if (
            self._profile_poc is None
            or price_quantity > self._profile_poc_quantity
            or (
                price_quantity == self._profile_poc_quantity
                and abs(price - current_price) < abs(self._profile_poc - current_price)
            )
        ):
            self._profile_poc = price
            self._profile_poc_quantity = price_quantity
        assert self._profile_poc is not None
        if not self._profile_selected:
            self._include_profile_price(self._profile_poc)
        elif self._profile_poc not in self._profile_selected:
            low = min(min(self._profile_selected), self._profile_poc)
            high = max(max(self._profile_selected), self._profile_poc)
            for candidate in self._profile_prices:
                if low <= candidate <= high:
                    self._include_profile_price(candidate)
        target = self._profile_total * 0.70
        while self._profile_selected_volume < target:
            low = min(self._profile_selected)
            high = max(self._profile_selected)
            low_index = bisect_left(self._profile_prices, low)
            high_index = bisect_left(self._profile_prices, high)
            left = self._profile_prices[low_index - 1] if low_index > 0 else None
            right = self._profile_prices[high_index + 1] if high_index + 1 < len(self._profile_prices) else None
            if left is None and right is None:
                break
            if left is None:
                selected = right
            elif right is None:
                selected = left
            else:
                selected = left if self._profile[left] >= self._profile[right] else right
            assert selected is not None
            self._include_profile_price(selected)
        self._profile_val = min(self._profile_selected)
        self._profile_vah = max(self._profile_selected)
        center = (self._profile_val + self._profile_vah) / 2.0
        if self._prior_profile_center is not None:
            if center > self._prior_profile_center + self.tick_size:
                self._value_migration = "HIGHER"
            elif center < self._prior_profile_center - self.tick_size:
                self._value_migration = "LOWER"
        self._prior_profile_center = center
        self._update_local_lvn(price)
        next_profile = {
            "status": "AVAILABLE",
            "poc": self._profile_poc,
            "vah": self._profile_vah,
            "val": self._profile_val,
            "value_area_fraction": 0.70,
            "migration": self._value_migration,
            "low_volume_pocket": self._low_volume_pocket(current_price),
            "provenance": "DHAN_CUMULATIVE_VOLUME_INCREMENT_AT_PACKET_LTP_APPROXIMATION",
            "calculation": "INCREMENTAL_CONTIGUOUS_VALUE_AREA",
            "total_observed_volume": self._profile_total,
        }
        next_levels = (next_profile["poc"], next_profile["vah"], next_profile["val"])
        if next_levels != prior_levels:
            for field, prior, current in zip(("poc", "vah", "val"), prior_levels, next_levels):
                if current != prior:
                    self._profile_change_counts[field] += 1
                    self._previous_profile_levels[field] = prior
            self._profile_revision += 1
        self._profile_snapshot = next_profile

    def _include_profile_price(self, price: float) -> None:
        if price not in self._profile_selected:
            self._profile_selected.add(price)
            self._profile_selected_volume += self._profile[price]

    def _update_local_lvn(self, changed_price: float) -> None:
        if len(self._profile_prices) < 3:
            return
        index = bisect_left(self._profile_prices, changed_price)
        for position in range(max(1, index - 2), min(len(self._profile_prices) - 1, index + 3)):
            price = self._profile_prices[position]
            left = self._profile[self._profile_prices[position - 1]]
            right = self._profile[self._profile_prices[position + 1]]
            quantity = self._profile[price]
            if quantity * 2 <= min(left, right):
                self._lvn_candidates.add(price)
            else:
                self._lvn_candidates.discard(price)

    def _low_volume_pocket(self, current_price: float) -> dict[str, Any] | None:
        if not self._lvn_candidates:
            return None
        nearest = min(self._lvn_candidates, key=lambda value: abs(value - current_price))
        return {"low": nearest, "high": nearest, "kind": "LOW_VOLUME_POCKET"}

    def _append_activity(self, item: tuple[int, float, int, int, int]) -> None:
        for window, totals, horizon in (
            (self._activity_2s, self._activity_2s_totals, 2_000_000_000),
            (self._activity_6s, self._activity_6s_totals, 6_000_000_000),
        ):
            window.append(item)
            for index in range(3):
                totals[index] += item[index + 2]
            while window and item[0] - window[0][0] > horizon:
                expired = window.popleft()
                for index in range(3):
                    totals[index] -= expired[index + 2]

    def _tape_state(self, now_ns: int) -> dict[str, Any]:
        del now_ns
        current_rate = len(self._activity_2s) / 2.0
        prior_rate = max(0, len(self._activity_6s) - len(self._activity_2s)) / 4.0
        current_volume = sum(self._activity_2s_totals) / 2.0
        prior_volume = max(0, sum(self._activity_6s_totals) - sum(self._activity_2s_totals)) / 4.0
        if len(self._activity_6s) < 8:
            state = "QUIET"
        elif current_rate > prior_rate * 1.25 and current_volume > prior_volume:
            state = "FAST AGAIN" if prior_rate else "FAST"
        elif current_rate < prior_rate * 0.75:
            state = "SLOWING"
        elif current_rate <= 1:
            state = "QUIET"
        else:
            state = "FAST"
        return {
            "state": state,
            "events_per_second": round(current_rate, 3),
            "executed_volume_per_second": round(current_volume, 3),
            "prior_events_per_second": round(prior_rate, 3),
            "prior_volume_per_second": round(prior_volume, 3),
        }

    def _flow_state(self, now_ns: int) -> dict[str, Any]:
        """Expose genuine rolling Futures execution activity without scoring it."""
        del now_ns
        buy, sell, unknown = self._activity_6s_totals
        total = buy + sell + unknown
        classified = buy + sell
        recent_bursts = list(self._bursts)[-12:]
        buy_bursts = sum(item.side == "BUY" for item in recent_bursts)
        sell_bursts = sum(item.side == "SELL" for item in recent_bursts)
        unknown_bursts = sum(item.side == "UNKNOWN" for item in recent_bursts)
        if total == 0:
            state = "QUIET"
        elif classified == 0 or max(buy, sell) < total * 0.45:
            state = "MIXED"
        elif buy > sell:
            state = "BUYING FAST" if buy_bursts >= 2 else "BUYING"
        else:
            state = "SELLING FAST" if sell_bursts >= 2 else "SELLING"
        return {
            "state": state,
            "buy_volume": buy,
            "sell_volume": sell,
            "unknown_volume": unknown,
            "total_volume": total,
            "signed_coverage": round(classified / total, 6) if total else None,
            "buy_bursts": buy_bursts,
            "sell_bursts": sell_bursts,
            "unknown_bursts": unknown_bursts,
            "window_seconds": 6,
            "authority": "NIFTY_FUTURES_EXECUTION_ACTIVITY",
        }

    @staticmethod
    def _reaction(response: Any) -> str:
        state = str(getattr(response, "state", "MIXED"))
        return {
            "BUYERS_ABSORBED": "BUYING ABSORBED",
            "SELLERS_ABSORBED": "SELLING ABSORBED",
            "CLEAN_BULL": "BUYING WORKING",
            "CLEAN_BEAR": "SELLING WORKING",
        }.get(state, "NO CLEAN RESPONSE")

    def _update_semantics(
        self,
        event: MarketEvent,
        *,
        flow: Mapping[str, Any],
        tape: Mapping[str, Any],
        reaction: str,
    ) -> None:
        migration = str(self._profile_snapshot.get("migration") or "FLAT")
        market = {
            "LOWER": "ACCEPTING LOWER ↓",
            "HIGHER": "ACCEPTING HIGHER ↑",
        }.get(migration, "BALANCED ↔")
        center = None
        if isinstance(self._profile_val, (int, float)) and isinstance(self._profile_vah, (int, float)):
            center = (self._profile_val + self._profile_vah) / 2.0
        self._observe_semantic(
            "market", market, event.receive_wall_utc,
            material_value=float(center or event.ltp),
            raw_evidence={
                "poc": self._profile_poc, "vah": self._profile_vah,
                "val": self._profile_val, "migration": migration,
                "profile_revision": self._profile_revision,
            },
        )

        buy = int(flow.get("buy_volume") or 0)
        sell = int(flow.get("sell_volume") or 0)
        unknown = int(flow.get("unknown_volume") or 0)
        classified = buy + sell
        total = classified + unknown
        imbalance = (buy - sell) / classified if classified else 0.0
        self._raw_pressure_direction = "BUY" if imbalance > 0 else "SELL" if imbalance < 0 else None
        if classified:
            self._pressure_strengths.append(abs(imbalance))
        strengths = list(self._pressure_strengths)
        active_boundary = _quantile(strengths, 0.55)
        strong_boundary = _quantile(strengths, 0.85)
        if total == 0:
            pressure = "QUIET"
        elif classified == 0:
            pressure = "MIXED"
        elif abs(imbalance) < active_boundary:
            pressure = "MIXED"
        else:
            actor = "BUYERS" if imbalance > 0 else "SELLERS"
            matching_bursts = int(flow.get("buy_bursts") or 0) if imbalance > 0 else int(flow.get("sell_bursts") or 0)
            intensity = "STRONG" if abs(imbalance) >= strong_boundary and matching_bursts else "ACTIVE"
            pressure = f"{actor} {intensity}"
        self._observe_semantic(
            "pressure", pressure, event.receive_wall_utc,
            material_value=imbalance,
            raw_evidence={
                "buy_volume": buy, "sell_volume": sell, "unknown_volume": unknown,
                "signed_coverage": round(classified / total, 6) if total else None,
                "imbalance": round(imbalance, 6),
                "active_boundary": round(active_boundary, 6),
                "strong_boundary": round(strong_boundary, 6),
                "buy_bursts": flow.get("buy_bursts"), "sell_bursts": flow.get("sell_bursts"),
            },
        )

        event_rate = float(tape.get("events_per_second") or 0.0)
        volume_rate = float(tape.get("executed_volume_per_second") or 0.0)
        activity = event_rate * (1.0 + math.log1p(max(0.0, volume_rate)))
        activity_values = list(self._speed_activity)
        low_activity = _quantile(activity_values, 0.20)
        high_activity = _quantile(activity_values, 0.80)
        prior_speed = self._semantic["speed"]
        if event_rate <= 0.5 and volume_rate <= 0:
            speed = "QUIET"
        elif len(activity_values) < 8:
            speed = "NORMAL"
        elif activity >= high_activity:
            speed = "FAST AGAIN" if prior_speed in {"QUIET", "SLOWING"} else "FAST"
        elif activity <= low_activity:
            speed = "SLOWING"
        else:
            speed = "NORMAL"
        self._speed_activity.append(activity)
        self._observe_semantic(
            "speed", speed, event.receive_wall_utc,
            material_value=activity,
            raw_evidence={
                "events_per_second": event_rate,
                "executed_volume_per_second": volume_rate,
                "activity_baseline_low": round(low_activity, 6),
                "activity_baseline_high": round(high_activity, 6),
            },
        )

        stable_pressure = self._semantic["pressure"]
        if stable_pressure.startswith("SELLERS"):
            if reaction == "SELLING WORKING":
                result = "PRICE FALLING WITH SELLERS"
            elif reaction == "SELLING ABSORBED":
                result = "PRICE HOLDING AGAINST SELLERS"
            else:
                result = "FLOW NOT CLEAN ENOUGH"
        elif stable_pressure.startswith("BUYERS"):
            if reaction == "BUYING WORKING":
                result = "PRICE RISING WITH BUYERS"
            elif reaction == "BUYING ABSORBED":
                result = "PRICE HOLDING AGAINST BUYERS"
            else:
                result = "FLOW NOT CLEAN ENOUGH"
        elif stable_pressure == "MIXED":
            result = "MIXED"
        else:
            result = "FLOW NOT CLEAN ENOUGH"
        price_change = (
            event.ltp - self._activity_2s[0][1]
            if self._activity_2s else 0.0
        )
        self._observe_semantic(
            "result", result, event.receive_wall_utc,
            material_value=price_change,
            raw_evidence={
                "pressure": stable_pressure, "response_engine": reaction,
                "price_change_2s": round(price_change, 6),
            },
        )

    def _observe_semantic(
        self,
        name: str,
        candidate: str,
        timestamp: str,
        *,
        material_value: float,
        raw_evidence: Mapping[str, Any],
        immediate: bool = False,
    ) -> None:
        history = self._semantic_raw_history[name]
        center, mad = _robust_baseline(history)
        history.append(float(material_value))
        current = self._semantic[name]
        self._semantic_provenance[name] = {
            "source_revision": self._revision + 1,
            "raw_state": candidate,
            "display_state": current,
            "change_reason": "RAW_MATCHES_DISPLAY" if candidate == current else "PERSISTENCE_PENDING",
            "timestamp": timestamp,
            "why_unavailable": None if candidate else "RAW_STATE_UNAVAILABLE",
        }
        if candidate == current:
            self._semantic_candidates.pop(name, None)
            return
        warm = len(history) < 12
        robust_shift = (
            warm
            or abs(material_value - center) >= max(mad * 2.5, self.tick_size / 10)
        )
        previous_candidate, support, candidate_shift = self._semantic_candidates.get(
            name, ("", 0, False)
        )
        if previous_candidate == candidate:
            support += 1
            candidate_shift = candidate_shift or robust_shift
        else:
            support = 1
            candidate_shift = robust_shift
        self._semantic_candidates[name] = (candidate, support, candidate_shift)
        persistence = {
            "market": 4,
            "pressure": 5,
            "result": 8,
            "speed": 8,
        }.get(name, 8)
        if name == "pressure" and current.split(" ", 1)[0] == candidate.split(" ", 1)[0]:
            # ACTIVE/STRONG is display intensity, not a new directional regime.
            persistence = 12
        if not immediate and (
            support < persistence or (not candidate_shift and name != "result")
        ):
            return
        self._semantic[name] = candidate
        self._semantic_provenance[name] = {
            "source_revision": self._revision + 1,
            "raw_state": candidate,
            "display_state": candidate,
            "change_reason": (
                "STRUCTURAL_EVENT_IMMEDIATE" if immediate
                else f"ROBUST_REGIME_CHANGE_EVENT_SUPPORT_{support}"
            ),
            "timestamp": timestamp,
            "why_unavailable": None,
        }
        self._semantic_candidates.pop(name, None)
        self._semantic_revision += 1
        self._semantic_transition_queue.append({
            "plane": "SEMANTIC_DISPLAY",
            "field": name.upper(),
            "previous_state": current,
            "new_state": candidate,
            "raw_evidence": dict(raw_evidence),
            "timestamp": timestamp,
            "reason": (
                "STRUCTURAL_EVENT_IMMEDIATE" if immediate
                else f"ROBUST_REGIME_CHANGE · MEDIAN {center:.6f} · MAD {mad:.6f} · EVENT_SUPPORT {support}"
            ),
            "semantic_revision": self._semantic_revision,
        })

    def _radar_levels(self) -> dict[str, tuple[float, float, str]]:
        """name -> low/high/display name for video-relevant market-generated levels."""

        result = {name: (value, value, name) for name, value in self._levels().items()}
        for key, display_name in (("poc", "POC"), ("vah", "VAH"), ("val", "VAL")):
            value = self._profile_snapshot.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                result[display_name] = (float(value), float(value), display_name)
        pocket = self._profile_snapshot.get("low_volume_pocket")
        if isinstance(pocket, Mapping):
            low, high = pocket.get("low"), pocket.get("high")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                result["LVN"] = (float(low), float(high), "LOW-VOLUME ZONE")
        return result

    def _update_level_radar(self, event: MarketEvent) -> None:
        price = float(event.ltp)
        touch = self._radar_touch()
        candidates = self._radar_levels()
        if not candidates:
            self._next_level = {"name": "NONE NEARBY", "price": None, "distance_points": None, "state": "FAR"}
            return
        directed = candidates
        if self._raw_pressure_direction == "SELL":
            ahead = {name: value for name, value in candidates.items() if value[1] < price - touch}
            if ahead:
                directed = ahead
        elif self._raw_pressure_direction == "BUY":
            ahead = {name: value for name, value in candidates.items() if value[0] > price + touch}
            if ahead:
                directed = ahead
        nearest_name, (nearest_low, nearest_high, nearest_display) = min(
            directed.items(),
            key=lambda item: 0.0 if item[1][0] <= price <= item[1][1] else min(abs(price - item[1][0]), abs(price - item[1][1])),
        )
        for name, (low, high, display_name) in candidates.items():
            level = (low + high) / 2.0
            state = self._level_states.get(name)
            if state is None or state.get("low") != low or state.get("high") != high:
                side = "ABOVE" if price > high else "BELOW" if price < low else "AT"
                distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
                initial = "TESTING" if distance <= touch else "APPROACHING" if distance <= touch * 4 else "FAR"
                self._level_states[name] = {
                    "low": low, "high": high, "side": side, "state": initial,
                    "break_direction": None, "tested": initial == "TESTING", "display_name": display_name,
                }
                continue
            prior_side = str(state["side"])
            side = "ABOVE" if price > high else "BELOW" if price < low else "AT"
            distance = 0.0 if side == "AT" else min(abs(price - low), abs(price - high))
            next_state = str(state["state"])
            immediate = False
            if prior_side in {"ABOVE", "AT"} and side == "BELOW":
                if state.get("break_direction") == "ABOVE":
                    self._record_level_transition(name, state, "BACK BELOW", event, price, distance)
                    state["state"] = "BACK BELOW"
                    next_state = "BREAK FAILED"
                else:
                    next_state = "BROKE BELOW"
                    state["break_direction"] = "BELOW"
                immediate = True
            elif prior_side in {"BELOW", "AT"} and side == "ABOVE":
                if state.get("break_direction") == "BELOW":
                    self._record_level_transition(name, state, "BACK ABOVE", event, price, distance)
                    state["state"] = "BACK ABOVE"
                    next_state = "BREAK FAILED"
                else:
                    next_state = "BROKE ABOVE"
                    state["break_direction"] = "ABOVE"
                immediate = True
            elif side == "AT" or distance <= touch:
                next_state = "TESTING"
                state["tested"] = True
            elif state.get("break_direction") == side and distance >= touch * 2:
                next_state = f"HOLDING {side}"
            elif state.get("state") == "BREAK FAILED" and distance >= touch * 2:
                next_state = "RECLAIMED"
                state["break_direction"] = None
            elif state.get("tested") and side == prior_side and distance >= touch * 2:
                next_state = "REJECTED"
                state["tested"] = False
            elif state.get("state") in {"RECLAIMED", "REJECTED"} and distance > touch:
                # Keep the structural outcome visible until price starts a new test.
                next_state = str(state["state"])
            elif distance <= touch * (6 if state.get("state") == "APPROACHING" else 4):
                next_state = "APPROACHING"
            else:
                next_state = "FAR"
            state["side"] = side
            if next_state != state["state"]:
                self._record_level_transition(name, state, next_state, event, price, distance)
                state["state"] = next_state
                if immediate:
                    state["last_structural_timestamp"] = event.receive_wall_utc
        active = self._active_level_name
        if active in candidates and str(self._level_states[active]["state"]) not in {"FAR", "REJECTED", "RECLAIMED"}:
            nearest_name = active
            nearest_low, nearest_high, nearest_display = candidates[active]
        nearest = self._level_states[nearest_name]
        distance = 0.0 if nearest_low <= price <= nearest_high else min(abs(price - nearest_low), abs(price - nearest_high))
        self._next_level = {
            "name": nearest_display,
            "price": nearest_low if nearest_low == nearest_high else None,
            "low": nearest_low,
            "high": nearest_high,
            "distance_points": round(distance, 2),
            "state": nearest["state"],
        }
        if str(nearest["state"]) in {
            "APPROACHING", "TESTING", "BROKE ABOVE", "BROKE BELOW",
            "HOLDING ABOVE", "HOLDING BELOW", "BACK ABOVE", "BACK BELOW", "BREAK FAILED",
        }:
            self._active_level_name = nearest_name
        elif self._active_level_name == nearest_name:
            self._active_level_name = None

    def _record_level_transition(
        self,
        name: str,
        state: Mapping[str, Any],
        next_state: str,
        event: MarketEvent,
        price: float,
        distance: float,
    ) -> None:
        display_name = str(state.get("display_name") or name)
        previous = str(state.get("state") or "FAR")
        if next_state == "BREAK FAILED":
            sentence = (
                f"BACK ABOVE {display_name} → SELLERS FAILED"
                if price > float(state["high"])
                else f"BACK BELOW {display_name} → BUYERS FAILED"
            )
        elif next_state in {"BACK ABOVE", "BACK BELOW"}:
            sentence = f"{next_state} {display_name}"
        elif next_state == "REJECTED" and price < float(state["low"]):
            sentence = f"{display_name} REJECTED → BUYERS FAILED"
        elif next_state == "REJECTED":
            sentence = f"{display_name} REJECTED → SELLERS FAILED"
        else:
            sentence = f"{display_name} {next_state}"
        if self._active_level_name is None or self._active_level_name == name:
            self._last_level_event = sentence
        self._level_transition_queue.append({
            "level": name, "display_name": display_name,
            "previous_state": previous, "new_state": next_state,
            "price": price, "level_low": state.get("low"), "level_high": state.get("high"),
            "distance_points": round(distance, 2), "timestamp": event.receive_wall_utc,
            "reason": sentence,
            "action_worthy": name in STRUCTURAL_LEVELS and next_state in STRUCTURAL_LEVEL_STATES,
        })

    def _levels(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for name, value in (
            ("PDH", self.reference.previous_day_high),
            ("PDL", self.reference.previous_day_low),
            ("PREVIOUS CLOSE", self.reference.previous_close),
            ("OR HIGH", self._or_high if self._or_frozen else None),
            ("OR LOW", self._or_low if self._or_frozen else None),
        ):
            if isinstance(value, (int, float)) and math.isfinite(value):
                result[name] = float(value)
        return result

    def _evaluate_episode(self, event: MarketEvent, *, tape: Mapping[str, Any], reaction: str) -> None:
        price = event.ltp
        levels = self._levels()
        timestamp = event.receive_wall_utc
        current_state = self._episode["state"]
        active_side = self._episode.get("side")
        invalidation = self._episode.get("invalidation")
        target_1 = self._episode.get("target_1")
        target_2 = self._episode.get("target_2")

        if current_state in {"INVALID / EXIT", "T2 HIT · EXIT"}:
            # A closed episode may only re-arm from market behaviour observed
            # after the close; stale breach/retest memory cannot create a new leg.
            self._breaches.clear()
            self._transition(
                "NO TRADE", timestamp, "PRIOR VIDEO EPISODE CLOSED · WAIT FOR NEW SETUP",
                model=None, side=None, candidate_side=None, area=None, trigger=None,
                invalidation=None, target_1=None, target_2=None, setup_id=None,
                setup_started_at=None, original_invalidation=None,
                level_lineage=None, t1_hit_timestamp=None, price=price,
            )
            return

        if not self._or_frozen and current_state == "NO TRADE":
            self._transition(
                "WATCH", timestamp, "30S OPENING RANGE BUILDING",
                model="OPENING RANGE", side=None, area="OPENING RANGE", price=price,
            )
            return

        if active_side == "CE" and isinstance(invalidation, (int, float)) and price < invalidation:
            self._transition("INVALID / EXIT", timestamp, "FUTURES INVALIDATION BROKE", price=price)
            return
        if active_side == "PE" and isinstance(invalidation, (int, float)) and price > invalidation:
            self._transition("INVALID / EXIT", timestamp, "FUTURES INVALIDATION BROKE", price=price)
            return
        if current_state in {"BUY CE · CONFIRMED", "BUY PE · CONFIRMED", "T1 HIT · PROTECT", "RUNNER"} and self._is_forward_target(target_2, active_side):
            hit_t2 = price >= target_2 if active_side == "CE" else price <= target_2
            if hit_t2:
                self._transition("T2 HIT · EXIT", timestamp, "SECOND STRUCTURAL TARGET COMPLETED", price=price)
                return
        if (
            current_state in {"BUY CE · CONFIRMED", "BUY PE · CONFIRMED", "HOLD"}
            and self._episode.get("t1_hit_timestamp") is None
            and isinstance(target_1, (int, float))
        ):
            hit = self._is_forward_target(target_1, active_side) and (price >= target_1 if active_side == "CE" else price <= target_1)
            if hit:
                protected = self._commit_t1_protection(timestamp, event.event_id)
                self._transition(
                    "T1 HIT · PROTECT" if protected else "RUNNER",
                    timestamp,
                    "FIRST STRUCTURAL TARGET REACHED" if protected
                    else "FIRST STRUCTURAL TARGET REACHED · PROTECTION LEVEL UNAVAILABLE",
                    t1_hit_timestamp=timestamp,
                    price=price,
                )
                return
        if current_state in {"BUY CE · CONFIRMED", "BUY PE · CONFIRMED", "HOLD"}:
            if self._episode.get("model") == "MODEL 2 · TREND" and active_side in {"CE", "PE"} and self._model_two_structure_failed(active_side, reaction, tape):
                self._transition(
                    "INVALID / EXIT", timestamp,
                    "TREND STRUCTURE FAILED · OPPOSING EXECUTION RESPONSE CONFIRMED",
                    price=price,
                )
            return
        migration = self._profile_snapshot.get("migration")
        if current_state == "T1 HIT · PROTECT" and active_side in {"CE", "PE"}:
            continuation = migration == ("HIGHER" if active_side == "CE" else "LOWER")
            if continuation:
                self._transition("RUNNER", timestamp, f"VALUE {migration} · STRUCTURE INTACT", price=price)
            elif self._episode.get("model") == "MODEL 2 · TREND" and self._model_two_structure_failed(active_side, reaction, tape):
                self._transition("INVALID / EXIT", timestamp, "TREND STRUCTURE FAILED AFTER TRIM", price=price)
            return
        if current_state == "RUNNER" and active_side in {"CE", "PE"}:
            failed = migration == ("LOWER" if active_side == "CE" else "HIGHER")
            if failed:
                self._transition("INVALID / EXIT", timestamp, "VALUE MIGRATION REVERSED · RUNNER OFF", price=price)
            return
        if current_state in {"EARLY BUY CE", "EARLY BUY PE", "WATCH"} and self._episode.get("model") == "MODEL 2 · TREND":
            side = self._episode.get("side")
            pocket = self._profile_snapshot.get("low_volume_pocket")
            if side in {"CE", "PE"} and isinstance(pocket, Mapping):
                low, high = float(pocket["low"]), float(pocket["high"])
                if low - self.tick_size * 2 <= price <= high + self.tick_size * 2:
                    self._episode["continuation_pocket"] = dict(pocket)
                    self._episode["continuation_pocket_retested"] = True
            completed = self._bars[120]
            structural_level = None
            entry_bucket = self._episode.get("entry_bucket_2m")
            eligible_bars = [bar for bar in completed if isinstance(entry_bucket, int) and bar["time"] >= entry_bucket]
            if eligible_bars:
                structural_level = eligible_bars[-1]["low" if side == "PE" else "high"]
            structural_break = isinstance(structural_level, (int, float)) and (
                price < structural_level - self.tick_size if side == "PE" else price > structural_level + self.tick_size
            )
            response_confirms = reaction == ("SELLING WORKING" if side == "PE" else "BUYING WORKING")
            if self._episode.get("continuation_pocket_retested") and structural_break and (
                response_confirms or str(tape.get("state")).startswith("FAST")
            ):
                self._transition(
                    f"BUY {side} · CONFIRMED", timestamp,
                    "LOW BROKE → BUYERS FAILED → SELLERS BACK" if side == "PE" else "HIGH BROKE → SELLERS FAILED → BUYERS BACK",
                    trigger=structural_level,
                    target_1=self._forward_from_price(self._nearest_structure(side), side, price),
                    target_2=self._forward_from_price(self._next_value_target(side), side, price),
                    price=price,
                )
                return
            extension_level = self._episode.get("target_2")
            extended = isinstance(extension_level, (int, float)) and (
                price <= extension_level if side == "PE" else price >= extension_level
            )
            if current_state.startswith("EARLY BUY") and extended:
                self._transition(
                    "WATCH", timestamp, "MOVE EXTENDED · WAIT FOR FRESH STRUCTURAL BREAK",
                    candidate_side=None, price=price,
                )
            return
        if current_state == "WATCH" and self._episode.get("candidate_side") in {"CE", "PE"}:
            side = self._episode["candidate_side"]
            trigger = self._episode.get("trigger")
            held = isinstance(trigger, (int, float)) and (price > trigger if side == "CE" else price < trigger)
            reaction_confirms = reaction == ("BUYING WORKING" if side == "CE" else "SELLING WORKING")
            if held and reaction_confirms:
                self._transition(
                    f"EARLY BUY {side}", timestamp, f"{side} REJECTION HELD · {reaction}",
                    side=side, candidate_side=None, entry_price=price, price=price,
                )
            elif not held:
                self._transition(
                    "NO TRADE", timestamp, "LEVEL REJECTION NOT CONFIRMED",
                    model=None, side=None, candidate_side=None, trigger=None, invalidation=None,
                    target_1=None, target_2=None, price=price,
                )
            return
        if current_state in {"EARLY BUY CE", "EARLY BUY PE"} and self._episode.get("model") == "MODEL 1 · RANGE":
            trigger = self._episode.get("trigger")
            side = self._episode.get("side")
            held = isinstance(trigger, (int, float)) and (price > trigger if side == "CE" else price < trigger)
            reaction_confirms = reaction == ("BUYING WORKING" if side == "CE" else "SELLING WORKING")
            if held and (reaction_confirms or str(tape.get("state")).startswith("FAST")):
                self._transition(f"BUY {side} · CONFIRMED", timestamp, f"{side} RECLAIM / REJECTION HELD · {reaction}", price=price)
            return
        for name, level in levels.items():
            low_role = name in {"PDL", "OR LOW"}
            high_role = name in {"PDH", "OR HIGH"}
            prior = self._breaches.get(name)
            if prior is None:
                if price != level:
                    self._breaches[name] = {
                        "direction": "BELOW" if price < level else "ABOVE",
                        "break_side": None,
                        "level": level,
                        "time": timestamp,
                        "extreme": price,
                        "retested": False,
                        "tests": 0,
                        "near_active": False,
                    }
                continue
            if prior["direction"] == "BELOW":
                old_extreme = prior["extreme"]
                if price < level:
                    if price >= level - self.tick_size * 2 and not prior.get("near_active"):
                        prior["tests"] = int(prior.get("tests") or 0) + 1
                        prior["near_active"] = True
                    elif price <= level - self.tick_size * 4:
                        prior["near_active"] = False
                if price >= level:
                    prior["direction"] = "ABOVE"
                    if prior.get("break_side") == "BELOW" and low_role:
                        self._start_model_one(
                            "CE", name, level, timestamp, price,
                            "LOW BROKE → SELLERS FAILED → LOW RECLAIMED",
                            invalidation=float(old_extreme), event_id=event.event_id,
                        )
                        prior["break_side"] = None
                        return
                    prior["break_side"] = "ABOVE"
                    prior["extreme"] = price
                    if not low_role and int(prior.get("tests") or 0) >= 2:
                        self._start_continuation(
                            "CE", name, level, timestamp, price,
                            invalidation=float(old_extreme), event_id=event.event_id,
                        )
                        prior["tests"] = 0
                        return
                elif price > old_extreme + self.tick_size:
                    prior["retested"] = True
                elif price < old_extreme:
                    prior["extreme"] = price
                    if prior.get("break_side") == "BELOW" and prior.get("retested"):
                        self._start_continuation(
                            "PE", name, float(old_extreme), timestamp, price,
                            invalidation=float(level), event_id=event.event_id,
                        )
                        return
            else:
                old_extreme = prior["extreme"]
                if price > level:
                    if price <= level + self.tick_size * 2 and not prior.get("near_active"):
                        prior["tests"] = int(prior.get("tests") or 0) + 1
                        prior["near_active"] = True
                    elif price >= level + self.tick_size * 4:
                        prior["near_active"] = False
                if price <= level:
                    prior["direction"] = "BELOW"
                    if prior.get("break_side") == "ABOVE" and high_role:
                        self._start_model_one(
                            "PE", name, level, timestamp, price,
                            "HIGH BROKE → BUYERS FAILED → HIGH REJECTED",
                            invalidation=float(old_extreme), event_id=event.event_id,
                        )
                        prior["break_side"] = None
                        return
                    prior["break_side"] = "BELOW"
                    prior["extreme"] = price
                    if not high_role and int(prior.get("tests") or 0) >= 2:
                        self._start_continuation(
                            "PE", name, level, timestamp, price,
                            invalidation=float(old_extreme), event_id=event.event_id,
                        )
                        prior["tests"] = 0
                        return
                elif price < old_extreme - self.tick_size:
                    prior["retested"] = True
                elif price > old_extreme:
                    prior["extreme"] = price
                    if prior.get("break_side") == "ABOVE" and prior.get("retested"):
                        self._start_continuation(
                            "CE", name, float(old_extreme), timestamp, price,
                            invalidation=float(level), event_id=event.event_id,
                        )
                        return

        if current_state == "NO TRADE" and levels:
            nearest = min(levels.items(), key=lambda item: abs(price - item[1]))
            if abs(price - nearest[1]) <= max(self.tick_size, self._current_spread()):
                self._transition("WATCH", timestamp, f"WATCHING {nearest[0]}", model="MODEL 1 · RANGE", area=nearest[0], price=price)

    def _start_model_one(
        self,
        side: str,
        name: str,
        level: float,
        timestamp: str,
        price: float,
        story: str,
        *,
        invalidation: float | None = None,
        event_id: str | None = None,
    ) -> None:
        profile = self._profile_snapshot
        raw_t1 = profile.get("poc")
        raw_t2 = profile.get("vah") if side == "CE" else profile.get("val")
        t1 = self._forward_from_price(raw_t1, side, price)
        t2 = self._forward_from_price(raw_t2, side, price)
        setup_id = self._setup_id("MODEL 1 · RANGE", side, name, timestamp)
        lineage = {
            "trigger": self._level_lineage(name, level, event_id, "FAILED AUCTION RECLAIM/REJECTION LEVEL"),
            "original_invalidation": self._level_lineage(
                "BREACH_EXTREME", invalidation, event_id, "STRUCTURAL FAILURE BEYOND THE FAILED-AUCTION EXTREME",
            ),
            "target_1": self._target_lineage("POC", raw_t1, t1, event_id, "RANGE MIDPOINT / POC"),
            "target_2": self._target_lineage(
                "VAH" if side == "CE" else "VAL", raw_t2, t2, event_id, "OPPOSITE VALUE EDGE",
            ),
        }
        self._transition(
            "WATCH", timestamp, story, model="MODEL 1 · RANGE", side=None, candidate_side=side,
            area=f"{name} · {level:.2f}", trigger=level, invalidation=invalidation,
            original_invalidation=invalidation, target_1=t1, target_2=t2,
            level_lineage=lineage, t1_hit_timestamp=None, price=price,
            setup_id=setup_id, setup_started_at=timestamp,
        )

    def _start_continuation(
        self,
        side: str,
        name: str,
        level: float,
        timestamp: str,
        price: float,
        *,
        invalidation: float | None = None,
        event_id: str | None = None,
    ) -> None:
        migration = self._profile_snapshot.get("migration")
        aligned = migration == ("HIGHER" if side == "CE" else "LOWER")
        model = "MODEL 2 · TREND" if aligned else "MODEL 1 · RANGE"
        story = "HIGH BROKE → SELLERS FAILED → BUYERS BACK" if side == "CE" else "LOW BROKE → BUYERS FAILED → SELLERS BACK"
        setup_id = self._setup_id(model, side, name, timestamp)
        raw_t1 = self._nearest_structure(side)
        raw_t2 = self._next_value_target(side)
        target_1 = self._forward_from_price(raw_t1, side, price)
        target_2 = self._forward_from_price(raw_t2, side, price)
        lineage = {
            "trigger": self._level_lineage(name, level, event_id, "CONTINUATION BREAK/RETEST LEVEL"),
            "original_invalidation": self._level_lineage(
                name, invalidation, event_id, "OPPOSITE SIDE OF THE OBSERVED BREAK/RETEST STRUCTURE",
            ),
            "target_1": self._target_lineage("LOCAL_STRUCTURE", raw_t1, target_1, event_id, "NEXT DIRECTIONAL 2M/3M STRUCTURE"),
            "target_2": self._target_lineage(
                "VAH" if side == "CE" else "VAL", raw_t2, target_2, event_id, "NEXT DIRECTIONAL VALUE EDGE",
            ),
        }
        self._transition(
            f"EARLY BUY {side}", timestamp, story, model=model, side=side,
            area=f"{name} · {level:.2f}", trigger=level, invalidation=invalidation,
            original_invalidation=invalidation, target_1=target_1, target_2=target_2,
            level_lineage=lineage, t1_hit_timestamp=None,
            continuation_pocket=self._profile_snapshot.get("low_volume_pocket"),
            continuation_pocket_retested=False,
            entry_bucket_2m=int(datetime.fromisoformat(timestamp).timestamp() // 120 * 120),
            setup_id=setup_id, setup_started_at=timestamp,
            entry_price=price, price=price,
        )

    def _level_lineage(
        self, level_type: str, value: Any, event_id: str | None, why_selected: str,
    ) -> dict[str, Any]:
        return {
            "level_type": level_type,
            "level_value": float(value) if isinstance(value, (int, float)) else None,
            "source_revision": self._profile_revision,
            "event_id": event_id,
            "why_selected": why_selected,
        }

    def _target_lineage(
        self,
        level_type: str,
        source_value: Any,
        selected_value: float | None,
        event_id: str | None,
        why_selected: str,
    ) -> dict[str, Any]:
        reason = why_selected if selected_value is not None else f"{why_selected} · UNAVAILABLE ON FORWARD SIDE"
        return {
            **self._level_lineage(level_type, selected_value, event_id, reason),
            "source_level_value": float(source_value) if isinstance(source_value, (int, float)) else None,
        }

    def _episode_id(self) -> str | None:
        setup_id = self._episode.get("setup_id")
        if not setup_id:
            return None
        return "pulse_episode_" + hashlib.sha256(str(setup_id).encode()).hexdigest()[:18]

    def _commit_t1_protection(self, timestamp: str, event_id: str) -> bool:
        side = self._episode.get("side")
        entry = self._episode.get("entry_price")
        trigger = self._episode.get("trigger")
        original = self._episode.get("original_invalidation", self._episode.get("invalidation"))
        directional = (
            side == "CE"
            and all(isinstance(value, (int, float)) for value in (original, trigger, entry))
            and float(original) < float(trigger) < float(entry)
        ) or (
            side == "PE"
            and all(isinstance(value, (int, float)) for value in (original, trigger, entry))
            and float(entry) < float(trigger) < float(original)
        )
        episode_id = self._episode_id()
        if not directional or episode_id is None:
            return False
        revision = {
            "timestamp": timestamp,
            "invalidation": float(trigger),
            "original_invalidation": float(original),
            "reason": "T1_PROTECTION_COMMITTED",
            "source_event_id": event_id,
            "source_revision": self._profile_revision,
        }
        revisions = self._episode_level_revisions.setdefault(episode_id, [])
        if not any(item.get("reason") == "T1_PROTECTION_COMMITTED" for item in revisions):
            revisions.append(revision)
        self._episode["invalidation"] = float(trigger)
        lineage = dict(self._episode.get("level_lineage") or {})
        lineage["current_invalidation"] = self._level_lineage(
            "ENTRY_TRIGGER", trigger, event_id, "T1 REACHED · PROTECT AT ENTRY TRIGGER",
        )
        self._episode["level_lineage"] = lineage
        for trade in self._paper_trades.values():
            if trade.get("episode_id") == episode_id:
                trade_revisions = trade.setdefault("level_revisions", [])
                if not any(item.get("reason") == "T1_PROTECTION_COMMITTED" for item in trade_revisions):
                    trade_revisions.append(dict(revision))
                trade["futures_current_invalidation"] = float(trigger)
        return True

    def _model_two_structure_failed(self, side: str, reaction: str, tape: Mapping[str, Any]) -> bool:
        structure = self._structure(120)
        opposite_structure = "LOWER HIGH · LOWER LOW" if side == "CE" else "HIGHER HIGH · HIGHER LOW"
        opposite_response = "SELLING WORKING" if side == "CE" else "BUYING WORKING"
        opposite_flow = "SELL" if side == "CE" else "BUY"
        recent = list(self._bursts)[-3:]
        flow_confirms = bool(recent) and max(
            ("BUY", "SELL", "UNKNOWN"),
            key=lambda value: sum(item.quantity for item in recent if item.side == value),
        ) == opposite_flow and str(tape.get("state")) in {"FAST", "FAST AGAIN"}
        return structure == opposite_structure and (reaction == opposite_response or flow_confirms)

    def _is_forward_target(self, target: Any, side: str | None) -> bool:
        if not isinstance(target, (int, float)) or side not in {"CE", "PE"} or not self._events:
            return False
        entry = self._episode.get("entry_price")
        if not isinstance(entry, (int, float)):
            return True
        return target > entry if side == "CE" else target < entry

    @staticmethod
    def _forward_from_price(target: Any, side: str, price: float) -> float | None:
        if not isinstance(target, (int, float)):
            return None
        return float(target) if (target > price if side == "CE" else target < price) else None

    def _setup_id(self, model: str, side: str, area: str, timestamp: str) -> str:
        seed = f"{self.session_id}|{model}|{side}|{area}|{timestamp}"
        return "pulse_setup_" + hashlib.sha256(seed.encode()).hexdigest()[:18]

    def _pocket_retest_failed(self, side: str, price: float, pocket: Mapping[str, Any]) -> bool:
        low, high = float(pocket["low"]), float(pocket["high"])
        key = f"POCKET_{side}"
        state = self._breaches.setdefault(key, {"retested": False})
        if low - self.tick_size <= price <= high + self.tick_size:
            state["retested"] = True
            return False
        return bool(state["retested"] and (price < low if side == "PE" else price > high))

    def _transition(self, state: str, timestamp: str, reason: str, **updates: Any) -> None:
        if state == self._episode["state"]:
            self._episode.update(updates)
            return
        prior = self._episode["state"]
        self._episode.update(updates)
        self._episode.update({"state": state, "transition_timestamp": timestamp, "reason_for_state_change": reason})
        self._episode["story"] = reason
        self._episode["transition_count"] += 1
        self._action_revision += 1
        self._transition_queue.append({"from": prior, "to": state, "timestamp": timestamp, "reason": reason, **self._episode})

    def _projection(
        self,
        event: MarketEvent,
        *,
        tape: Mapping[str, Any],
        reaction: str,
        flow: Mapping[str, Any] | None = None,
        book: Any = None,
    ) -> dict[str, Any]:
        self._revision += 1
        option_started = self._clock_ns()
        option = self._selected_option(self._episode.get("side"), event)
        self._record_latency("option_mapping", self._clock_ns() - option_started)
        bursts = [asdict(item) for item in list(self._bursts)[-3:]]
        flow_snapshot = dict(flow or self._flow_state(event.feed_receive_ns))
        headline = self._headline()
        validation = self._validate_candidate(event)
        if not validation["valid"]:
            self._record_validation_failure(validation, event.receive_wall_utc)
        story = self._display_story()
        next_level = dict(self._next_level)
        key_level = self._key_level(next_level)
        open_range = self._open_range(event)
        snapshot = {
            "schema_version": 1,
            "formula_version": FLOW_PULSE_VERSION,
            "revision": self._revision,
            "semantic_revision": self._semantic_revision,
            "action_revision": self._action_revision,
            "session_id": event.session_id,
            "source_timestamp": event.receive_wall_utc,
            "packet_receive_ns": event.feed_receive_ns,
            "source_security_id": event.security_id,
            "state": self._episode["state"] if validation["valid"] else "WATCH · PLAN INVALID",
            "headline": headline if validation["valid"] else "NO TRADE",
            "model": self._episode.get("model"),
            "side": self._episode.get("side"),
            "story": story,
            "what_happened": self._last_level_event if self._last_level_event != "NO LEVEL EVENT YET" else story,
            "area": self._episode.get("area") or key_level.get("label") or self._area_label(event.ltp),
            "key_level": key_level,
            "next_level": next_level,
            "open_range": open_range,
            "futures": {
                "ltp": event.ltp,
                "trigger": (self._episode.get("trigger") or self._trigger_text(event.ltp)) if validation["valid"] else None,
                "trigger_text": self._trigger_text(float(self._episode.get("trigger") or event.ltp)),
                "invalidation": self._episode.get("invalidation") if validation["valid"] else None,
                "target_1": self._episode.get("target_1") if validation["valid"] else None,
                "target_2": self._episode.get("target_2") if validation["valid"] else None,
                "security_id": event.security_id,
            },
            "option": option,
            "levels": {
                **self._levels(),
                "opening_range_frozen": self._or_frozen,
                "opening_range_available": self._or_high is not None and self._or_low is not None,
                "opening_range_source_timestamp": self._or_source_timestamp,
                "source_timestamp": self.reference.source_timestamp,
            },
            "profile": {
                **self._profile_snapshot,
                "revision": self._profile_revision,
                "previous_poc": self._previous_profile_levels["poc"],
                "previous_vah": self._previous_profile_levels["vah"],
                "previous_val": self._previous_profile_levels["val"],
                "poc_update_count": self._profile_change_counts["poc"],
                "vah_update_count": self._profile_change_counts["vah"],
                "val_update_count": self._profile_change_counts["val"],
            },
            "value_state": self._profile_snapshot.get("migration", "UNAVAILABLE"),
            "semantic": dict(self._semantic),
            "semantic_provenance": {name: dict(value) for name, value in self._semantic_provenance.items()},
            "semantic_transitions": list(self._semantic_transition_queue)[-16:],
            "level_transitions": list(self._level_transition_queue)[-16:],
            "execution_bursts": bursts,
            "flow_state": flow_snapshot["state"],
            "flow": flow_snapshot,
            "reaction": reaction,
            "tape": dict(tape),
            "structure": {"2m": self._structure(120), "3m": self._structure(180)},
            "book_context": {
                "microprice": getattr(book, "microprice", None),
                "ofi": getattr(book, "l1_ofi", None),
                "mlofi": getattr(book, "mlofi", None),
            },
            "delta": {
                "coverage": None,
                "provenance": "CONSERVATIVE_SIGNED_SUBSET; UNKNOWN_PRESERVED",
                "authority": "SUPPORTING_ONLY",
            },
            "data_quality": "GOOD" if event.data_quality.value == "GOOD" else "DEGRADED",
            "action_contract": validation,
            "live_health": {
                "status": "LIVE",
                "source_advancing": True,
                "last_packet_age_ms": 0.0,
                "last_packet_timestamp": event.receive_wall_utc,
                "last_semantic_revision": self._semantic_revision,
                "last_action_revision": self._action_revision,
            },
            "advisory_only": True,
            "execution_influence": "ZERO",
            "score_authority": "NONE",
            "transition_count": self._episode["transition_count"],
            "update_count": self._update_count,
            "paper_trades": self.paper_trades(),
            "paper_episodes": self.paper_episodes(),
        }
        serialization_started = self._clock_ns()
        seed = "|".join(str(value) for value in (
            event.event_id, self._revision, self._semantic_revision, self._action_revision,
            self._profile_revision, self._episode.get("state"), event.ltp,
        ))
        snapshot["snapshot_id"] = "pulse_" + hashlib.sha256(seed.encode()).hexdigest()[:20]
        self._record_latency("payload_build", self._clock_ns() - serialization_started)
        return snapshot

    def _validate_candidate(self, event: MarketEvent) -> dict[str, Any]:
        validation_started = self._clock_ns()
        episode_id = self._episode_id()
        candidate = {
            **self._episode,
            "entry_price": self._episode.get("entry_price", event.ltp),
            "episode_id": episode_id,
            "video_event_id": event.event_id,
            "semantic_revision": self._semantic_revision,
            "level_revision": self._profile_revision,
            "timestamp": event.receive_wall_utc,
            "level_revisions": self._active_level_revisions(episode_id),
        }
        result = validate_action_contract(candidate).to_dict()
        self._record_latency("candidate_validation", self._clock_ns() - validation_started)
        result["candidate_plan"] = candidate
        result["valid"] = result["plan_validation"] == "PASS"
        result["video_event_id"] = event.event_id
        result["episode_id"] = episode_id
        result["timestamp"] = event.receive_wall_utc
        return result

    def _active_level_revisions(self, episode_id: str | None) -> list[dict[str, Any]]:
        if episode_id and episode_id in self._episode_level_revisions:
            return list(self._episode_level_revisions[episode_id])
        for trade in self._paper_trades.values():
            if episode_id and trade.get("episode_id") == episode_id:
                return list(trade.get("level_revisions") or ())
        return []

    def _record_validation_failure(self, validation: Mapping[str, Any], timestamp: str) -> None:
        identity = str(validation.get("candidate_plan_id") or "")
        if not identity or identity == self._last_validation_identity:
            return
        self._last_validation_identity = identity
        self._validation_event_queue.append({
            "PLAN_VALIDATION": "FAIL",
            "VALIDATION_REASON": validation.get("validation_reason"),
            "CANDIDATE_PLAN_ID": identity,
            "VIDEO_EVENT_ID": validation.get("video_event_id"),
            "EPISODE_ID": validation.get("episode_id"),
            "TIMESTAMP": timestamp,
            "candidate_plan": validation.get("candidate_plan"),
            "execution_influence": "ZERO",
        })

    def _refresh_option_mapping(self) -> None:
        if not self._latest or not self._episode.get("side"):
            return
        current = self._events[-1][0] if self._events else None
        self._latest["option"] = self._selected_option(self._episode.get("side"), current)

    def _selected_option(self, side: str | None, current: MarketEvent | int | None) -> dict[str, Any] | None:
        if side not in {"CE", "PE"}:
            return None
        event = self._latest_options.get(f"ATM_{side}")
        if event is None:
            return None
        top = event.depth_5[0]
        current_ns = current.feed_receive_ns if isinstance(current, MarketEvent) else current
        age_ns = max(0, int(current_ns) - event.feed_receive_ns) if isinstance(current_ns, int) else None
        quote_fresh = age_ns is not None and age_ns <= self.option_quote_fresh_ns
        executable = top.ask_price > top.bid_price > 0
        return {
            "strike": event.strike,
            "option_type": side,
            "security_id": event.security_id,
            "expiry": event.expiry,
            "bid": top.bid_price,
            "ask": top.ask_price,
            "spread": top.ask_price - top.bid_price,
            "source_timestamp": event.receive_wall_utc,
            "age_ms": round(age_ns / 1_000_000.0, 3) if age_ns is not None else None,
            "status": "AVAILABLE" if executable and quote_fresh else "STALE" if executable else "UNAVAILABLE",
        }

    def _nearest_structure(self, side: str) -> float | None:
        levels = []
        for seconds in (120, 180):
            for bar in self._bars[seconds][-8:]:
                levels.append(bar["high"] if side == "CE" else bar["low"])
        if not levels or not self._events:
            return None
        price = self._events[-1][1]
        valid = [value for value in levels if value > price] if side == "CE" else [value for value in levels if value < price]
        return min(valid) if side == "CE" and valid else max(valid) if valid else None

    def _next_value_target(self, side: str) -> float | None:
        return self._profile_snapshot.get("vah" if side == "CE" else "val")

    def _structure(self, seconds: int) -> str:
        bars = self._bars[seconds]
        if len(bars) < 3:
            return "BUILDING"
        first, middle, last = bars[-3:]
        if last["high"] > middle["high"] > first["high"] and last["low"] > middle["low"] > first["low"]:
            return "HIGHER HIGH · HIGHER LOW"
        if last["high"] < middle["high"] < first["high"] and last["low"] < middle["low"] < first["low"]:
            return "LOWER HIGH · LOWER LOW"
        return "MIXED"

    def _headline(self) -> str:
        state = str(self._episode.get("state") or "NO TRADE")
        if state in {"INVALID / EXIT", "T2 HIT · EXIT"}:
            return "EXIT"
        if state == "T1 HIT · PROTECT":
            return "PROTECT"
        if state in {"HOLD", "RUNNER"}:
            return "HOLD"
        if state.startswith("EARLY BUY "):
            return state
        if state.startswith("BUY ") and "CONFIRMED" in state:
            return state.split(" ·", 1)[0]
        if state == "WATCH" and self._episode.get("candidate_side") in {"CE", "PE"}:
            return "SETUP FORMING"
        if state == "WATCH":
            return "WATCH"
        if str(self._next_level.get("state")) in {"APPROACHING", "TESTING", "RETESTING"}:
            return "WATCH"
        return "NO TRADE"

    def _display_story(self) -> str:
        episode_story = str(self._episode.get("story") or "")
        if episode_story and episode_story not in {"NO VIDEO MODEL", "NO_VIDEO_MODEL"}:
            return episode_story
        name = str(self._next_level.get("name") or "NONE NEARBY")
        state = str(self._next_level.get("state") or "FAR")
        if name != "NONE NEARBY" and state != "FAR":
            return f"{name} {state}"
        if self._last_level_event != "NO LEVEL EVENT YET":
            return self._last_level_event
        return "WATCHING MARKET-GENERATED LEVELS"

    @staticmethod
    def _key_level(next_level: Mapping[str, Any]) -> dict[str, Any]:
        name = str(next_level.get("name") or "NONE NEARBY")
        low, high = next_level.get("low"), next_level.get("high")
        price = next_level.get("price")
        if isinstance(price, (int, float)):
            label = f"{name} {float(price):.2f}"
        elif isinstance(low, (int, float)) and isinstance(high, (int, float)):
            label = f"{name} {float(low):.2f}–{float(high):.2f}"
        else:
            label = name
        return {**dict(next_level), "label": label}

    def _open_range(self, event: MarketEvent) -> dict[str, Any]:
        timestamp = datetime.fromisoformat(event.receive_wall_utc).astimezone(IST)
        start = timestamp.replace(hour=9, minute=15, second=0, microsecond=0)
        freeze = start.replace(second=30)
        close = timestamp.replace(hour=15, minute=30, second=0, microsecond=0)
        if timestamp >= close:
            status = "SESSION CLOSED · LAST LIVE"
        elif timestamp < freeze and not self._or_frozen:
            status = "OPEN RANGE BUILDING"
        elif self._or_high is not None and self._or_low is not None:
            status = "SET"
        else:
            status = "RECOVERY REQUIRED"
        if self._or_high is not None and self._or_low is not None:
            label = f"OPEN RANGE {self._or_low:.2f}–{self._or_high:.2f} · SET"
            if timestamp >= close:
                label += " · SESSION CLOSED · LAST LIVE"
        elif status == "OPEN RANGE BUILDING":
            label = status
        else:
            label = "OPEN RANGE UNAVAILABLE · RECOVERY REQUIRED"
        return {
            "status": status, "label": label,
            "high": self._or_high, "low": self._or_low,
            "frozen": self._or_frozen,
            "source_timestamp": self._or_source_timestamp,
        }

    def _area_label(self, price: float) -> str:
        levels = self._levels()
        for name in ("vah", "val"):
            value = self._profile_snapshot.get(name)
            if isinstance(value, (int, float)) and math.isfinite(value):
                levels[name.upper()] = float(value)
        if not levels:
            return "LEVELS BUILDING"
        name, value = min(levels.items(), key=lambda item: abs(price - item[1]))
        return f"{name} · {value:.2f}"

    def _trigger_text(self, price: float) -> str:
        side = self._episode.get("side")
        return f"{'ABOVE' if side == 'CE' else 'BELOW' if side == 'PE' else 'AT'} {price:.2f}"

    def _current_spread(self) -> float:
        # Preserve the accepted video episode boundary exactly.
        return self.tick_size

    def _radar_touch(self) -> float:
        # A crossed/sparse five-level book must not turn a transient quote gap
        # into a many-point structural display zone.
        return min(max(self.tick_size, self._book_spread), self.tick_size * 4)

    def _bin(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, 2)

    @staticmethod
    def _empty_profile() -> dict[str, Any]:
        return {"status": "BUILDING", "poc": None, "vah": None, "val": None, "migration": "UNAVAILABLE", "low_volume_pocket": None, "value_area_fraction": 0.70}

    @staticmethod
    def _empty_episode() -> dict[str, Any]:
        return {
            "state": "NO TRADE", "model": None, "side": None, "candidate_side": None,
            "story": "NO VIDEO MODEL", "area": None, "trigger": None,
            "invalidation": None, "original_invalidation": None,
            "target_1": None, "target_2": None, "level_lineage": None,
            "t1_hit_timestamp": None, "transition_timestamp": None,
            "reason_for_state_change": "NO_VIDEO_MODEL", "transition_count": 0,
        }

    @staticmethod
    def _empty_projection() -> dict[str, Any]:
        return {"status": "UNAVAILABLE", "state": "WATCH · DATA PARTIAL", "reason": "FUTURES_PACKET_NOT_READY", "advisory_only": True, "execution_influence": "ZERO", "score_authority": "NONE"}
