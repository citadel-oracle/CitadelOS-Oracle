"""Incremental, advisory-only Oracle option decision HUD projection.

The reducer consumes canonical Order Flow features and canonical ARGUS structure.
It performs no I/O and has no execution authority.
"""

from __future__ import annotations

import hashlib
import math
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Mapping

from .contracts import DataQuality, InstrumentIdentity, MarketEvent, ReconciledTradeState
from .features import BookMetrics, clamp


EDGE_STATES = {
    "SELLING STRONG",
    "SELLING EXHAUSTED",
    "REVERSAL BUILDING",
    "BUYING BUILDING",
    "BUYING STRONG",
    "NO EDGE",
    "DATA LOCKED",
}
STRUCTURE_STATES = {"SELL STRONG", "SELL FADING", "TURNING", "BUY BUILDING", "BUY STRONG", "BALANCED"}


@dataclass(slots=True)
class _EdgeSample:
    receive_ns: int
    price: float
    spread: float
    micro_edge: float
    refill_signal: float
    classified_buy: int
    classified_sell: int
    total_delta: int


@dataclass(slots=True)
class _StableState:
    value: str
    raw_value: str | None = None
    candidate: str | None = None
    candidate_since_ns: int | None = None

    def __post_init__(self) -> None:
        if self.raw_value is None:
            self.raw_value = self.value


@dataclass(slots=True)
class _SideState:
    edge: _StableState = field(default_factory=lambda: _StableState("NO EDGE"))
    structure: _StableState = field(default_factory=lambda: _StableState("BALANCED"))
    strength: float = 0.0
    edge_evidence: dict[str, Any] = field(default_factory=dict)


class OracleDecisionHudEngine:
    """One atomic CALL/PUT HUD reducer with broad engineering hysteresis."""

    FORMULA_VERSION = "ORACLE_DECISION_HUD_SHADOW_V2"
    PRESENTATION_VERSION = "ORACLE_UNIVERSAL_CONTROL_BARS_V1"
    EDGE_WINDOW = 18
    FRESH_NS = 3_000_000_000
    STRUCTURE_FRESH_NS = 20_000_000_000
    WEAK_PERSIST_NS = 1_500_000_000
    STRONG_PERSIST_NS = 750_000_000
    STRIKE_CONFIRMATIONS = 3
    STRIKE_MARGIN = 1.12

    def __init__(self) -> None:
        self._lock = RLock()
        self._samples: dict[str, deque[_EdgeSample]] = {}
        self._sides = {"call": _SideState(), "put": _SideState()}
        self._structure_rows: dict[float, dict[str, Any]] = {}
        self._focus_strike: float | None = None
        self._focus_score = 0.0
        self._challenger: float | None = None
        self._challenger_count = 0
        self._source_timestamp: str | None = None
        self._structure_receive_ns: int | None = None
        self._revision = 0
        self._display_revision = 0
        self._last_display_state: tuple[Any, ...] | None = None
        self._transitions: deque[dict[str, Any]] = deque(maxlen=256)

    def register_structure(self, projection: Mapping[str, Any], *, receive_ns: int) -> None:
        """Accept the already-computed ARGUS ATM spine; never fetch or recompute it."""
        data = _mapping(projection.get("data"))
        tactical = _mapping(data.get("tactical_edge"))
        prime = _mapping(tactical.get("argus_prime"))
        rows = prime.get("strike_spine")
        if not isinstance(rows, list):
            rows = []
        atm = _number(_mapping(data.get("underlying")).get("atm_strike"))
        pcr = _mapping(prime.get("live_pcr"))
        pcr_shift = _number(pcr.get("change_1m"))
        source_timestamp = _text(prime.get("source_event_time")) or _text(tactical.get("source_event_time"))
        parsed: dict[float, dict[str, Any]] = {}
        for raw in rows:
            row = _mapping(raw)
            strike = _number(row.get("strike"))
            if strike is None or (atm is not None and abs(strike - atm) > 100.01):
                continue
            ce, pe = _mapping(row.get("CE")), _mapping(row.get("PE"))
            if not ce or not pe:
                continue
            parsed[strike] = {
                "CE": _structure_leg(ce),
                "PE": _structure_leg(pe),
                "pcr_shift": pcr_shift,
                "atm": atm,
                "fresh": str(prime.get("freshness") or "").upper() == "FRESH"
                and str(pcr.get("freshness") or "").upper() == "FRESH",
            }
        with self._lock:
            self._structure_rows = parsed
            self._source_timestamp = source_timestamp
            self._structure_receive_ns = receive_ns
            self._select_focus(parsed, atm)
            self._refresh_structure(receive_ns)
            self._publish_if_changed(receive_ns, reason="STRUCTURE")

    def register_instruments(self, identities: tuple[InstrumentIdentity, ...]) -> None:
        """Prime one same-strike ATM pair before the first ARGUS spine arrives."""
        atm = {
            (item.strike, item.option_type)
            for item in identities
            if item.role in {"ATM_CE", "ATM_PE"} and item.strike is not None
        }
        strikes = {strike for strike, _ in atm if (strike, "CE") in atm and (strike, "PE") in atm}
        with self._lock:
            if self._focus_strike is None and len(strikes) == 1:
                self._focus_strike = float(next(iter(strikes)))

    def ingest_option(
        self,
        event: MarketEvent,
        trade: ReconciledTradeState,
        book: BookMetrics,
        *,
        now_ns: int,
    ) -> None:
        if event.option_type not in {"CE", "PE"} or event.strike is None:
            return
        spread = book.spread
        if spread is None or spread <= 0 or book.microprice is None:
            return
        total_delta = trade.delta_volume
        refill_total = book.bid_refill + book.ask_refill + book.bid_depletion + book.ask_depletion
        refill_signal = clamp(
            (book.bid_refill + book.ask_depletion - book.ask_refill - book.bid_depletion)
            / max(1.0, float(refill_total))
        )
        sample = _EdgeSample(
            receive_ns=now_ns,
            price=event.ltp,
            spread=spread,
            micro_edge=book.microprice_edge,
            refill_signal=refill_signal,
            classified_buy=trade.classified_buy_qty,
            classified_sell=trade.classified_sell_qty,
            total_delta=total_delta,
        )
        key = f"{event.strike:.2f}:{event.option_type}"
        with self._lock:
            samples = self._samples.setdefault(key, deque(maxlen=self.EDGE_WINDOW))
            samples.append(sample)
            if self._focus_strike is None:
                return
            if abs(float(event.strike) - self._focus_strike) > 0.001:
                return
            side = "call" if event.option_type == "CE" else "put"
            raw_state, strength, evidence, strong = self._edge_state(samples)
            state = self._advance(self._sides[side].edge, raw_state, now_ns, strong=strong, data_locked=False)
            self._sides[side].strength = strength
            self._sides[side].edge_evidence = evidence
            self._publish_if_changed(now_ns, reason=f"{side.upper()}_EDGE:{state}")

    def snapshot(self, *, now_ns: int, generated_at: str | None = None) -> dict[str, Any]:
        with self._lock:
            structure_stale = self._structure_receive_ns is None or now_ns - self._structure_receive_ns > self.STRUCTURE_FRESH_NS
            row = self._structure_rows.get(self._focus_strike or math.nan, {})
            fresh_structure = bool(row.get("fresh")) and not structure_stale
            edge_stale: dict[str, bool] = {}
            edge_age_seconds: dict[str, float | None] = {}
            for side in ("call", "put"):
                suffix = "CE" if side == "call" else "PE"
                samples = self._samples.get(f"{(self._focus_strike or 0):.2f}:{suffix}")
                age_ns = None if not samples else max(0, now_ns - samples[-1].receive_ns)
                edge_age_seconds[side] = round(age_ns / 1_000_000_000.0, 6) if age_ns is not None else None
                edge_stale[side] = age_ns is None or age_ns > self.FRESH_NS
            # Quality belongs to the immutable same-strike pair, never one leg.
            # A recovery becomes visible only after CE, PE and structure are all
            # complete in the same snapshot.
            data_locked = not fresh_structure or any(edge_stale.values())
            quality_reasons = []
            if structure_stale:
                quality_reasons.append("STRUCTURE_STALE")
            elif not row.get("fresh"):
                quality_reasons.append("STRUCTURE_QUALITY_LOCK")
            quality_reasons.extend(
                f"{side.upper()}_EDGE_STALE" for side, stale in edge_stale.items() if stale
            )
            sides = {}
            for side in ("call", "put"):
                suffix = "CE" if side == "call" else "PE"
                edge = "DATA LOCKED" if data_locked else self._sides[side].edge.value
                structure = "DATA LOCKED" if data_locked else self._sides[side].structure.value
                action, hero = _arbitrate(edge, structure)
                control_state = _side_control_state(edge, structure)
                sides[side] = {
                    "contract": f"{_strike_text(self._focus_strike)} {suffix}" if self._focus_strike else f"— {suffix}",
                    "edge_state": edge,
                    "raw_edge_state": self._sides[side].edge.raw_value,
                    "display_edge_state": edge,
                    "edge_strength": 0.0 if data_locked else round(self._sides[side].strength, 2),
                    "structure_state": structure,
                    "raw_structure_state": self._sides[side].structure.raw_value,
                    "display_structure_state": structure,
                    "structure_strength": 0.0 if data_locked else round(abs(_number(_mapping(row.get(suffix)).get("score")) or 0.0) * 100.0, 2),
                    "action": action,
                    "hero_state": hero,
                    # Additive presentation aliases.  EDGE and STRUCTURE remain
                    # unchanged for replay/semantic parity; the universal bars
                    # name their genuine source families directly.
                    "flow_state": edge,
                    "flow_strength": 0.0 if data_locked else round(self._sides[side].strength, 2),
                    "flow_evidence": deepcopy(self._sides[side].edge_evidence),
                    "oi_state": structure,
                    "oi_strength": 0.0 if data_locked else round(abs(_number(_mapping(row.get(suffix)).get("score")) or 0.0) * 100.0, 2),
                    "oi_evidence": deepcopy(_mapping(row.get(suffix))),
                    "control_state": control_state,
                    "explanation": _control_explanation(edge, structure),
                    "source_age_seconds": edge_age_seconds[side],
                }
            relationship = _control_relationship(
                sides["call"]["flow_state"], sides["call"]["oi_state"],
                sides["put"]["flow_state"], sides["put"]["oi_state"],
                data_locked=data_locked,
            )
            display_state = (
                self._focus_strike,
                "LOCKED" if data_locked else "GOOD",
                relationship,
                tuple(
                    (
                        sides[side]["contract"], sides[side]["display_edge_state"],
                        sides[side]["display_structure_state"], sides[side]["action"],
                        sides[side]["hero_state"],
                    )
                    for side in ("call", "put")
                ),
            )
            if display_state != self._last_display_state:
                self._display_revision += 1
                self._last_display_state = display_state
            timestamp = generated_at or datetime.now(timezone.utc).isoformat()
            seed = f"{self._revision}|{self._display_revision}|{self._focus_strike}|{sides}|{self._source_timestamp}"
            control_event_seed = f"{self._display_revision}|{self._focus_strike}|{relationship}|{self._source_timestamp}"
            return {
                "schema_version": 2,
                "formula_version": self.FORMULA_VERSION,
                "presentation_version": self.PRESENTATION_VERSION,
                "revision": self._revision,
                "raw_revision": self._revision,
                "display_revision": self._display_revision,
                "projection_id": "hud_" + hashlib.sha256(seed.encode()).hexdigest()[:20],
                "focus_strike": self._focus_strike,
                "source_timestamp": self._source_timestamp,
                "generated_at": timestamp,
                "data_quality": "LOCKED" if data_locked else "GOOD",
                "quality_reasons": quality_reasons,
                "data_lock_reason_codes": quality_reasons if data_locked else [],
                "change_reason": "|".join(quality_reasons) if data_locked else "SOURCE_PAIR_COHERENT",
                "structure_source_age_seconds": (
                    round(max(0, now_ns - self._structure_receive_ns) / 1_000_000_000.0, 6)
                    if self._structure_receive_ns is not None else None
                ),
                "relationship_state": relationship,
                "control_event_id": "control_" + hashlib.sha256(control_event_seed.encode()).hexdigest()[:20],
                "call": sides["call"],
                "put": sides["put"],
                "mode": "SHADOW_RESEARCH",
                "advisory_only": True,
                "execution_influence": "ZERO",
            }

    def transitions(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._transitions))

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def _edge_state(self, samples: deque[_EdgeSample]) -> tuple[str, float, dict[str, Any], bool]:
        if len(samples) < 4:
            return "NO EDGE", 0.0, {"status": "WARMING"}, False
        recent = list(samples)[-8:]
        start, end = recent[0], recent[-1]
        scale = max(0.05, sum(row.spread for row in recent) / len(recent) * 3.0)
        premium = clamp((end.price - start.price) / scale)
        micro = clamp(sum(row.micro_edge for row in recent) / len(recent))
        absorption = clamp(sum(row.refill_signal for row in recent) / len(recent))
        total = sum(row.total_delta for row in recent)
        known_buy = sum(row.classified_buy for row in recent)
        known_sell = sum(row.classified_sell for row in recent)
        coverage = (known_buy + known_sell) / total if total else 0.0
        optional_flow = clamp((known_buy - known_sell) / max(1, known_buy + known_sell)) if coverage >= 0.35 else 0.0
        score = clamp(0.40 * micro + 0.32 * absorption + 0.28 * premium + (0.08 * optional_flow if coverage >= 0.35 else 0.0))
        prior_price = list(samples)[max(0, len(samples) - 12)].price
        prior_progress = clamp((start.price - prior_price) / scale)
        sell_response_failed = prior_progress < -0.18 and premium > -0.18
        reversal_evidence = micro >= 0.12 and absorption >= 0.10
        if score <= -0.42 and premium <= -0.18:
            state = "SELLING STRONG"
        elif sell_response_failed and reversal_evidence:
            state = "REVERSAL BUILDING"
        elif sell_response_failed and (micro > 0.04 or absorption > 0.06):
            state = "SELLING EXHAUSTED"
        elif micro >= 0.20 and absorption >= 0.12 and premium < 0.24:
            state = "REVERSAL BUILDING"
        elif score >= 0.48 and premium >= 0.28 and micro >= 0.24:
            state = "BUYING STRONG"
        elif score >= 0.24 and premium >= 0.08:
            state = "BUYING BUILDING"
        else:
            state = "NO EDGE"
        strength = min(100.0, abs(score) * 100.0)
        evidence = {
            "microprice_divergence": round(micro, 4),
            "absorption_refill": round(absorption, 4),
            "premium_response": round(premium, 4),
            "signed_flow_confirmation": round(optional_flow, 4) if coverage >= 0.35 else None,
            "signed_coverage": round(coverage, 4),
        }
        strong = state in {"BUYING STRONG", "SELLING STRONG"}
        return state, strength, evidence, strong

    def _select_focus(self, rows: Mapping[float, Mapping[str, Any]], atm: float | None) -> None:
        candidates: list[tuple[float, float]] = []
        for strike, row in rows.items():
            ce, pe = _mapping(row.get("CE")), _mapping(row.get("PE"))
            if not row.get("fresh"):
                continue
            liquidity = min(_number(ce.get("liquidity")) or 0.0, _number(pe.get("liquidity")) or 0.0)
            load = ((_number(ce.get("load")) or 0.0) + (_number(pe.get("load")) or 0.0)) / 2.0
            proximity = max(0.0, 1.0 - abs(strike - (atm if atm is not None else strike)) / 150.0)
            score = 0.60 * load + 0.25 * liquidity + 15.0 * proximity
            candidates.append((score, strike))
        if not candidates:
            if self._focus_strike is None and atm is not None:
                self._focus_strike = atm
            return
        score, strike = max(candidates, key=lambda item: (item[0], -abs(item[1] - (atm or item[1]))))
        if self._focus_strike is None:
            self._focus_strike, self._focus_score = strike, score
            return
        if strike == self._focus_strike:
            self._focus_score = score
            self._challenger, self._challenger_count = None, 0
            return
        if score < self._focus_score * self.STRIKE_MARGIN + 4.0:
            self._challenger, self._challenger_count = None, 0
            return
        if self._challenger == strike:
            self._challenger_count += 1
        else:
            self._challenger, self._challenger_count = strike, 1
        if self._challenger_count >= self.STRIKE_CONFIRMATIONS:
            self._focus_strike, self._focus_score = strike, score
            self._challenger, self._challenger_count = None, 0
            for side in self._sides.values():
                side.edge = _StableState("NO EDGE")
                side.strength = 0.0
                side.edge_evidence = {}

    def _refresh_structure(self, now_ns: int) -> None:
        row = self._structure_rows.get(self._focus_strike or math.nan)
        if not row or not row.get("fresh"):
            return
        ce, pe = _mapping(row.get("CE")), _mapping(row.get("PE"))
        velocity_scale = max(1.0, abs(_number(ce.get("velocity")) or 0.0), abs(_number(pe.get("velocity")) or 0.0))
        acceleration_scale = max(1.0, abs(_number(ce.get("acceleration")) or 0.0), abs(_number(pe.get("acceleration")) or 0.0))
        velocity = clamp(((_number(pe.get("velocity")) or 0.0) - (_number(ce.get("velocity")) or 0.0)) / velocity_scale)
        acceleration = clamp(((_number(pe.get("acceleration")) or 0.0) - (_number(ce.get("acceleration")) or 0.0)) / acceleration_scale)
        load = clamp(((_number(pe.get("load")) or 0.0) - (_number(ce.get("load")) or 0.0)) / 100.0)
        pcr = clamp((_number(row.get("pcr_shift")) or 0.0) / 0.05)
        call_score = clamp(0.35 * velocity + 0.25 * acceleration + 0.25 * load + 0.15 * pcr)
        for side, score in (("call", call_score), ("put", -call_score)):
            raw = _structure_state(score)
            self._advance(self._sides[side].structure, raw, now_ns, strong=abs(score) >= 0.62, data_locked=False)
            leg = ce if side == "call" else pe
            leg["score"] = score

    def _advance(self, state: _StableState, candidate: str, now_ns: int, *, strong: bool, data_locked: bool) -> str:
        state.raw_value = candidate
        if data_locked:
            state.value, state.candidate, state.candidate_since_ns = candidate, None, None
            return state.value
        if candidate == state.value:
            state.candidate, state.candidate_since_ns = None, None
            return state.value
        if state.candidate != candidate:
            state.candidate, state.candidate_since_ns = candidate, now_ns
            return state.value
        required = self.STRONG_PERSIST_NS if strong else self.WEAK_PERSIST_NS
        if now_ns - (state.candidate_since_ns or now_ns) >= required:
            state.value, state.candidate, state.candidate_since_ns = candidate, None, None
        return state.value

    def _publish_if_changed(self, now_ns: int, *, reason: str) -> None:
        current = (
            self._focus_strike,
            self._sides["call"].edge.raw_value,
            self._sides["call"].edge.value,
            self._sides["call"].structure.raw_value,
            self._sides["call"].structure.value,
            self._sides["put"].edge.raw_value,
            self._sides["put"].edge.value,
            self._sides["put"].structure.raw_value,
            self._sides["put"].structure.value,
        )
        previous = self._transitions[-1].get("state") if self._transitions else None
        if current != previous:
            self._revision += 1
            self._transitions.append(
                {
                    "receive_ns": now_ns,
                    "reason": reason,
                    "source_timestamp": self._source_timestamp,
                    "focus_strike": self._focus_strike,
                    "call": {
                        "raw_edge_state": self._sides["call"].edge.raw_value,
                        "display_edge_state": self._sides["call"].edge.value,
                        "raw_structure_state": self._sides["call"].structure.raw_value,
                        "display_structure_state": self._sides["call"].structure.value,
                    },
                    "put": {
                        "raw_edge_state": self._sides["put"].edge.raw_value,
                        "display_edge_state": self._sides["put"].edge.value,
                        "raw_structure_state": self._sides["put"].structure.raw_value,
                        "display_structure_state": self._sides["put"].structure.value,
                    },
                    "state": current,
                }
            )


def _structure_leg(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "oi": _number(value.get("oi")),
        "velocity": _number(value.get("oi_velocity")),
        "acceleration": _number(value.get("oi_acceleration")),
        "load": _number(value.get("load_intensity")),
        "liquidity": _number(value.get("liquidity_score")),
        "probable_flow": _text(value.get("probable_flow")),
        "flow_state": _text(value.get("flow_state")),
        "covering_unwind": _text(value.get("covering_unwind")),
    }


def _semantic_polarity(value: str) -> int:
    if value in {"BUYING STRONG", "BUY STRONG"}:
        return 2
    if value in {"BUYING BUILDING", "BUY BUILDING"}:
        return 1
    if value in {"SELLING STRONG", "SELL STRONG"}:
        return -2
    if value == "SELL FADING":
        return -1
    return 0


def _side_control_state(flow: str, oi: str) -> str:
    if "DATA LOCKED" in {flow, oi}:
        return "DATA LOCKED"
    flow_polarity = _semantic_polarity(flow)
    oi_polarity = _semantic_polarity(oi)
    if flow_polarity and oi_polarity and flow_polarity * oi_polarity < 0:
        return "CONFLICT"
    if flow == "SELLING EXHAUSTED":
        return "CONTROL WEAKENING"
    if flow == "REVERSAL BUILDING" or oi == "TURNING":
        return "ROTATION"
    combined = flow_polarity or oi_polarity
    if combined >= 2:
        return "BUYERS IN CONTROL"
    if combined > 0:
        return "CONTROL BUILDING"
    if combined <= -2:
        return "SELLERS IN CONTROL"
    if combined < 0:
        return "SELLING PRESSURE"
    return "BALANCED"


def _control_relationship(
    call_flow: str,
    call_oi: str,
    put_flow: str,
    put_oi: str,
    *,
    data_locked: bool,
) -> str:
    """Describe current cross-side control; never authorize a trade."""
    if data_locked:
        return "DATA LOCKED"
    call_flow_polarity = _semantic_polarity(call_flow)
    call_oi_polarity = _semantic_polarity(call_oi)
    put_flow_polarity = _semantic_polarity(put_flow)
    put_oi_polarity = _semantic_polarity(put_oi)
    if (
        (call_flow_polarity and call_oi_polarity and call_flow_polarity * call_oi_polarity < 0)
        or (put_flow_polarity and put_oi_polarity and put_flow_polarity * put_oi_polarity < 0)
    ):
        return "CONFLICT / ROTATION"
    call_control = call_flow_polarity or call_oi_polarity
    put_control = put_flow_polarity or put_oi_polarity
    if call_control > 0 and put_control < 0:
        return "CE TAKING CONTROL"
    if put_control > 0 and call_control < 0:
        return "PE TAKING CONTROL"
    if call_control > 0 and put_control <= 0:
        return "CONTROL ROTATING → CE"
    if put_control > 0 and call_control <= 0:
        return "CONTROL ROTATING → PE"
    if call_control * put_control > 0:
        return "CONFLICT / ROTATION"
    if call_flow in {"REVERSAL BUILDING", "BUYING BUILDING"} or put_flow == "SELLING EXHAUSTED":
        return "CONTROL ROTATING → CE"
    if put_flow in {"REVERSAL BUILDING", "BUYING BUILDING"} or call_flow == "SELLING EXHAUSTED":
        return "CONTROL ROTATING → PE"
    return "BALANCED / ROTATION"


def _control_explanation(flow: str, oi: str) -> str:
    flow_text = {
        "BUYING STRONG": "flow shows sustained buying control",
        "BUYING BUILDING": "flow and premium response are improving",
        "REVERSAL BUILDING": "price response is rotating toward buyers",
        "SELLING EXHAUSTED": "selling remains but its price response is weakening",
        "SELLING STRONG": "selling pressure remains effective",
        "NO EDGE": "flow evidence is balanced",
        "DATA LOCKED": "flow evidence is not trustworthy",
    }.get(flow, "flow evidence is mixed")
    oi_text = {
        "BUY STRONG": "OI structure is strongly supportive",
        "BUY BUILDING": "OI structure is becoming supportive",
        "TURNING": "OI structure is rotating",
        "SELL FADING": "opposing OI structure is fading",
        "SELL STRONG": "OI structure remains opposing",
        "BALANCED": "OI structure is balanced",
        "DATA LOCKED": "OI evidence is not trustworthy",
    }.get(oi, "OI evidence is mixed")
    return f"{flow_text}; {oi_text}."


def _structure_state(score: float) -> str:
    if score <= -0.58:
        return "SELL STRONG"
    if score <= -0.20:
        return "SELL FADING"
    if score < -0.07:
        return "TURNING"
    if score <= 0.07:
        return "BALANCED"
    if score < 0.30:
        return "TURNING"
    if score < 0.62:
        return "BUY BUILDING"
    return "BUY STRONG"


def _arbitrate(edge: str, structure: str) -> tuple[str, str]:
    if edge in {"DATA LOCKED", "NO EDGE"}:
        return "WAIT", "DATA_LOCKED" if edge == "DATA LOCKED" else "NO_EDGE"
    if edge == "SELLING STRONG":
        return "WAIT", "SELLING_STRONG"
    if edge == "SELLING EXHAUSTED":
        return "WAIT", "SELLING_EXHAUSTED"
    if edge == "REVERSAL BUILDING":
        if structure == "SELL STRONG":
            return "WAIT", "SELLING_EXHAUSTED"
        return "READY", "REVERSAL_BUILDING"
    if edge == "BUYING BUILDING":
        if structure == "SELL STRONG":
            return "READY", "REVERSAL_BUILDING"
        return "READY+", "BUYING_BUILDING"
    if edge == "BUYING STRONG" and structure == "SELL STRONG":
        return "READY+", "BUYING_BUILDING"
    if edge == "BUYING STRONG":
        return "GO", "BUYING_STRONG"
    return "WAIT", "NO_EDGE"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strike_text(value: float | None) -> str:
    if value is None:
        return "—"
    return str(int(value)) if value.is_integer() else f"{value:g}"
