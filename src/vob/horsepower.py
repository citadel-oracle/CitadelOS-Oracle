"""Session-aware, close-confirmed VOB horsepower observer.

This consumes canonical candles and VOB geometry. It never forms, selects,
mitigates, scores, or trades a VOB and therefore has zero execution influence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Mapping, Sequence

EVENTS = {"SUPPORT_GONE", "SUPPORT_BACK", "RESISTANCE_OUT", "BREAKOUT_LOST"}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _text(value: Any) -> str:
    return str(value or "")


def _stamp(value: Any) -> str:
    return _text(value).replace("Z", "+00:00")


def _session_id(value: str) -> str:
    return value[:10] if len(value) >= 10 else ""


def _after(left: str, right: str) -> bool:
    return bool(left and right and _stamp(left) > _stamp(right))


@dataclass(frozen=True, slots=True)
class _Bar:
    timestamp: str
    closed_at: str
    close: float


@dataclass(frozen=True, slots=True)
class _Zone:
    zone_id: str
    role: str
    low: float
    high: float
    formed_at: str
    canonical_broken_at: str


@dataclass
class _InstrumentSession:
    session_id: str
    event_ids: set[str] = field(default_factory=set)
    watermarks: dict[str, str] = field(default_factory=dict)


@dataclass
class HorsepowerStateEngine:
    """Reconstruct current-session truth for each exact instrument identity."""

    _sessions: dict[str, _InstrumentSession] = field(default_factory=dict)
    _projection: dict[str, dict[str, Any]] = field(default_factory=dict)

    def observe(self, instrument_key: str, technical: Mapping[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        instrument = str(instrument_key)
        lanes = technical.get("vob_timeframes") if isinstance(technical.get("vob_timeframes"), Mapping) else {}
        normalized = {
            timeframe: self._normalize_lane(lanes.get(timeframe))
            for timeframe in ("1m", "3m", "5m")
        }
        session = max(
            (_session_id(bar.closed_at) for bars, _ in normalized.values() for bar in bars),
            default="",
        )
        previous = self._sessions.get(instrument)
        bootstrap = previous is None or previous.session_id != session
        if bootstrap:
            previous = _InstrumentSession(session_id=session)

        lane_outputs: dict[str, dict[str, Any]] = {}
        all_events: list[dict[str, Any]] = []
        all_ledger: list[dict[str, Any]] = []
        next_watermarks: dict[str, str] = {}
        for timeframe in ("1m", "3m", "5m"):
            bars, zones = normalized[timeframe]
            events, ledger = self._reconstruct(instrument, timeframe, bars, zones)
            watermark = bars[-1].closed_at if bars else ""
            prior_watermark = previous.watermarks.get(timeframe, "")
            for event in events:
                event["notification_eligible"] = bool(
                    not bootstrap
                    and event["event_id"] not in previous.event_ids
                    and _after(_text(event.get("confirmed_candle")), prior_watermark)
                )
            all_events.extend(events)
            all_ledger.extend(ledger)
            next_watermarks[timeframe] = watermark
            supports = sum(row["state"] == "SUPPORT_BROKEN" for row in ledger)
            resistances = sum(row["state"] == "RESISTANCE_BROKEN" for row in ledger)
            latest = events[-1] if events else None
            lane_outputs[timeframe] = {
                "status": self._lane_status(latest, supports, resistances),
                "event_id": latest.get("event_id") if latest else None,
                "latest_event": (
                    {key: deepcopy(value) for key, value in latest.items() if key != "notification_eligible"}
                    if latest else None
                ),
                "confirmed_candle": latest.get("confirmed_candle") if latest else None,
                "evaluation_watermark": watermark or None,
                "close": bars[-1].close if bars else None,
                "support_broken": supports,
                "support_total": sum(row["role"] == "SUPPORT" for row in ledger),
                "resistance_broken": resistances,
                "resistance_total": sum(row["role"] == "RESISTANCE" for row in ledger),
                "finalized_close_only": True,
            }

        all_events.sort(key=lambda row: (_stamp(row["confirmed_candle"]), row["event_id"]))
        all_ledger.sort(key=lambda row: (row["timeframe"], row["formed_at"], row["zone_id"]))
        result = {
            "instrument": instrument,
            "security_id": technical.get("security_id"),
            "session_id": session or None,
            "timeframes": lane_outputs,
            "combined": self._combined(lane_outputs),
            "pulse_1m": self._pulse(lane_outputs.get("1m", {})),
            "events": deepcopy(all_events[-64:]),
            "session_ledger": deepcopy(all_ledger[-256:]),
            "bootstrap": bootstrap,
            "bootstrap_ms": round((perf_counter() - started) * 1000.0, 3),
            "continuity": "SESSION_RECONSTRUCTED" if bootstrap else "CONTINUOUS",
            "source": "CANONICAL_VOB_LADDER_PLUS_FINALIZED_SESSION_CANDLES",
            "advisory_only": True,
            "execution_influence": 0,
        }
        self._sessions[instrument] = _InstrumentSession(
            session_id=session,
            event_ids={row["event_id"] for row in all_events},
            watermarks=next_watermarks,
        )
        self._projection[instrument] = result
        return deepcopy(result)

    @classmethod
    def _normalize_lane(cls, value: Any) -> tuple[list[_Bar], list[_Zone]]:
        lane = value if isinstance(value, Mapping) else {}
        raw_bars = lane.get("session_finalized_bars")
        if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, (str, bytes)):
            raw_bars = [lane.get("latest_finalized_bar")]
        bars_by_close: dict[str, _Bar] = {}
        for raw in raw_bars:
            if not isinstance(raw, Mapping) or raw.get("finalized") is False:
                continue
            close = _number(raw.get("close"))
            timestamp = _text(raw.get("timestamp") or raw.get("time"))
            closed_at = _text(raw.get("candle_closed_at") or timestamp)
            if close is None or not timestamp or not closed_at:
                continue
            bars_by_close[closed_at] = _Bar(timestamp, closed_at, close)
        bars = sorted(bars_by_close.values(), key=lambda row: _stamp(row.closed_at))
        current_session = _session_id(bars[-1].closed_at) if bars else ""
        if current_session:
            bars = [bar for bar in bars if _session_id(bar.closed_at) == current_session]

        zones: list[_Zone] = []
        for raw in lane.get("zone_ladder") or []:
            if not isinstance(raw, Mapping):
                continue
            zone_id = _text(raw.get("zone_id"))
            role = _text(raw.get("role")).upper()
            low, high = _number(raw.get("zone_low")), _number(raw.get("zone_high"))
            formed_at = _text(
                raw.get("confirmation_candle_time")
                or raw.get("origin_candle_time")
                or "0000-01-01T00:00:00+00:00"
            )
            canonical_broken_at = _text(raw.get("broken_at"))
            if (
                not zone_id or role not in {"SUPPORT", "RESISTANCE"}
                or low is None or high is None
                or (current_session and _session_id(formed_at) > current_session)
                # Zones canonically resolved before this session are history,
                # not members of today's opening ladder.
                or (
                    current_session and canonical_broken_at
                    and _session_id(canonical_broken_at) < current_session
                )
            ):
                continue
            zones.append(_Zone(
                zone_id, role, min(low, high), max(low, high), formed_at,
                canonical_broken_at,
            ))
        return bars, zones

    @staticmethod
    def _reconstruct(
        instrument: str, timeframe: str, bars: Sequence[_Bar], zones: Sequence[_Zone],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        ledger: list[dict[str, Any]] = []
        for zone in zones:
            broken = False
            latest_state = "ACTIVE"
            broken_at = break_close = resolved_at = resolve_close = None
            for bar in bars:
                if not _after(bar.closed_at, zone.formed_at):
                    continue
                event = None
                if zone.role == "SUPPORT" and not broken and bar.close < zone.low:
                    broken, latest_state, event = True, "SUPPORT_BROKEN", "SUPPORT_GONE"
                    broken_at, break_close = bar.closed_at, bar.close
                elif zone.role == "SUPPORT" and broken and bar.close > zone.high:
                    broken, latest_state, event = False, "SUPPORT_RECLAIMED", "SUPPORT_BACK"
                    resolved_at, resolve_close = bar.closed_at, bar.close
                elif zone.role == "RESISTANCE" and not broken and bar.close > zone.high:
                    broken, latest_state, event = True, "RESISTANCE_BROKEN", "RESISTANCE_OUT"
                    broken_at, break_close = bar.closed_at, bar.close
                elif zone.role == "RESISTANCE" and broken and bar.close < zone.low:
                    broken, latest_state, event = False, "BREAKOUT_LOST", "BREAKOUT_LOST"
                    resolved_at, resolve_close = bar.closed_at, bar.close
                if event:
                    events.append({
                        "event_id": f"{instrument}:{timeframe}:{event}:{zone.zone_id}:{bar.closed_at}",
                        "instrument": instrument,
                        "timeframe": timeframe.upper(),
                        "event": event,
                        "zone_id": zone.zone_id,
                        "zone_role": zone.role,
                        "zone_low": zone.low,
                        "zone_high": zone.high,
                        "formed_at": zone.formed_at,
                        "confirmed_candle": bar.closed_at,
                        "close": bar.close,
                    })
            ledger.append({
                "zone_id": zone.zone_id,
                "instrument": instrument,
                "timeframe": timeframe.upper(),
                "role": zone.role,
                "zone_low": zone.low,
                "zone_high": zone.high,
                "formed_at": zone.formed_at,
                "broken_at": broken_at,
                "break_close": break_close,
                "resolved_at": resolved_at,
                "resolve_close": resolve_close,
                "state": latest_state,
            })
        events.sort(key=lambda row: (_stamp(row["confirmed_candle"]), row["event_id"]))
        return events, ledger

    @staticmethod
    def _lane_status(event: Mapping[str, Any] | None, supports: int, resistances: int) -> str:
        if supports >= 2:
            return "DOUBLE_SUPPORT_GONE"
        if resistances >= 2:
            return "DOUBLE_RESISTANCE_OUT"
        if supports:
            return "SUPPORT_GONE"
        if resistances:
            return "RESISTANCE_OUT"
        if event and str(event.get("event")) in EVENTS:
            return str(event["event"])
        return "NEUTRAL"

    @staticmethod
    def _combined(lanes: Mapping[str, Mapping[str, Any]]) -> str:
        main = [lanes.get("3m", {}), lanes.get("5m", {})]
        support_lanes = sum(bool(lane.get("support_broken")) for lane in main)
        resistance_lanes = sum(bool(lane.get("resistance_broken")) for lane in main)
        if support_lanes == 2:
            return "BOTH SUPPORTS GONE · 2X WEAK"
        if resistance_lanes == 2:
            return "BOTH RESISTANCES OUT · 2X HORSEPOWER"
        if any(int(lane.get("support_broken") or 0) >= 2 for lane in main):
            return "DOUBLE SUPPORT GONE · 2X WEAK"
        if any(int(lane.get("resistance_broken") or 0) >= 2 for lane in main):
            return "DOUBLE RESISTANCE OUT · 2X HORSEPOWER"
        if support_lanes == 1:
            return "SUPPORT GONE · 1X WEAK"
        if resistance_lanes == 1:
            return "RESISTANCE OUT · 1X POWER"
        latest = max(
            (lane.get("latest_event") for lane in main if isinstance(lane.get("latest_event"), Mapping)),
            key=lambda event: _stamp(event.get("confirmed_candle")),
            default=None,
        )
        if latest and latest.get("event") == "SUPPORT_BACK":
            return "SUPPORT BACK · HORSEPOWER RETURNING ↑"
        if latest and latest.get("event") == "BREAKOUT_LOST":
            return "BREAKOUT LOST · HORSEPOWER LOST ↓"
        return "IDLE"

    @staticmethod
    def _pulse(lane: Mapping[str, Any]) -> str:
        state = str(lane.get("status") or "NEUTRAL")
        return {
            "SUPPORT_GONE": "HORSEPOWER DOWN ↓",
            "DOUBLE_SUPPORT_GONE": "HORSEPOWER DOWN ↓",
            "RESISTANCE_OUT": "HORSEPOWER UP ↑",
            "DOUBLE_RESISTANCE_OUT": "HORSEPOWER UP ↑",
            "SUPPORT_BACK": "SUPPORT BACK",
            "BREAKOUT_LOST": "BREAKOUT LOST",
        }.get(state, "NEUTRAL")

    def projection(self) -> dict[str, Any]:
        return deepcopy(self._projection)
