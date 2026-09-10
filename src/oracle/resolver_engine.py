"""Citadel Oracle — Resolver R1 Engine.

Deterministic, zero-heuristic event synthesizer for current ITM-1 CE and PE option cards.
Operates on canonical VOB/Horsepower, discrete closed 5M OI tracking, and 5-level
book-change-derived MLOFI.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from datetime import datetime
from statistics import median
from typing import Any, Mapping
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Native Order Flow freshness rules from src/order_flow/service.py: SCORE_CONFIG
FLOW_AGING_SECONDS: float = 1.5
FLOW_TTL_SECONDS: float = 3.0
FLOW_TTL_MS: float = FLOW_TTL_SECONDS * 1000.0


def _parse_ts(val: Any) -> datetime | None:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=IST)
    if isinstance(val, str) and val:
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
        except (ValueError, TypeError):
            return None
    return None


def _flow_direction(value: Any) -> str | None:
    try:
        signed = float(value)
    except (TypeError, ValueError):
        return None
    if signed > 0.0:
        return "BUY"
    if signed < 0.0:
        return "SELL"
    return None


class ResolverEngine:
    """Production Resolver R1 state synthesis engine."""

    __slots__ = (
        "_flow_series",
        "_seen_flow_revisions",
        "_held_state",
        "_last_meaningful_event",
        "_session_id",
    )

    def __init__(self) -> None:
        # 50,000 capacity retains full 6.25 hr trading session at 2 Hz (~3.6 MB RAM)
        self._flow_series: deque[tuple[float, float, float, str, str]] = deque(maxlen=50000)
        # Deterministic FIFO deduplication cache
        self._seen_flow_revisions: OrderedDict[str, None] = OrderedDict()
        self._held_state: dict[str, dict[str, Any]] = {}
        self._last_meaningful_event: dict[str, dict[str, Any]] = {}
        self._session_id: str | None = None

    def reset_session(self, session_id: str) -> None:
        """Reset all state memory and baselines on session transition."""
        self._flow_series.clear()
        self._seen_flow_revisions.clear()
        self._held_state.clear()
        self._last_meaningful_event.clear()
        self._session_id = session_id

    @staticmethod
    def extract_vob_timeframes(horsepower: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
        """Normalize legacy flat and canonical nested Horsepower lanes.

        Canonical Horsepower publishes lanes under ``timeframes``. Its aggregate
        status can describe several zones, while the Resolver event identity and
        timestamp belong to ``latest_event``. Legacy flat lanes remain supported
        for the frozen Resolver contract and tests.
        """
        hp = horsepower if isinstance(horsepower, Mapping) else {}
        nested = hp.get("timeframes")
        source = nested if isinstance(nested, Mapping) else hp
        lanes: dict[str, dict[str, Any]] = {}
        for timeframe in ("1m", "3m", "5m"):
            raw = source.get(timeframe)
            lane = dict(raw) if isinstance(raw, Mapping) else {}
            latest = lane.get("latest_event")
            if isinstance(nested, Mapping) and isinstance(latest, Mapping):
                event = str(latest.get("event") or "")
                if event in {"SUPPORT_GONE", "RESISTANCE_OUT", "SUPPORT_BACK", "BREAKOUT_LOST"}:
                    lane["status"] = event
                    lane["event_id"] = latest.get("event_id")
                    lane["confirmed_candle"] = latest.get("confirmed_candle")
            lanes[timeframe] = lane
        return lanes

    def ingest_flow_snapshot(
        self,
        flow: Mapping[str, Any] | None,
        observed_at: datetime | None = None,
    ) -> None:
        """Ingest unique canonical flow snapshots, deduplicating loop republications deterministically."""
        if not isinstance(flow, Mapping):
            return

        revision = str(
            flow.get("revision")
            or flow.get("update_count")
            or flow.get("snapshot_id")
            or flow.get("source_timestamp")
            or ""
        )
        if not revision or revision in self._seen_flow_revisions:
            return

        diag = flow.get("diagnostics") if isinstance(flow.get("diagnostics"), Mapping) else {}
        book_pressure = diag.get("book_pressure") if isinstance(diag.get("book_pressure"), Mapping) else {}
        family_values = flow.get("family_values") if isinstance(flow.get("family_values"), Mapping) else {}
        canonical_book_pressure = (
            family_values.get("BOOK_PRESSURE")
            if isinstance(family_values.get("BOOK_PRESSURE"), Mapping)
            else {}
        )

        raw_mlofi = (
            book_pressure.get("mlofi")
            if book_pressure.get("mlofi") is not None
            else canonical_book_pressure.get("mlofi")
            if canonical_book_pressure.get("mlofi") is not None
            else flow.get("mlofi")
        )
        raw_l1_ofi = (
            book_pressure.get("l1_ofi")
            if book_pressure.get("l1_ofi") is not None
            else canonical_book_pressure.get("l1_ofi")
            if canonical_book_pressure.get("l1_ofi") is not None
            else flow.get("l1_ofi")
        )

        flow_time_str = str(flow.get("source_timestamp") or flow.get("generated_at") or "")
        flow_dt = _parse_ts(flow_time_str) or observed_at
        if raw_mlofi is None or flow_dt is None:
            return

        mlofi = float(raw_mlofi)
        l1_ofi = float(raw_l1_ofi) if raw_l1_ofi is not None else 0.0
        epoch = flow_dt.timestamp()
        time_iso = flow_dt.isoformat()

        self._flow_series.append((epoch, mlofi, l1_ofi, time_iso, revision))
        self._seen_flow_revisions[revision] = None
        if len(self._seen_flow_revisions) > 50000:
            # Deterministic FIFO eviction of oldest revision
            self._seen_flow_revisions.popitem(last=False)

    def compute_oi_diagnostics(
        self,
        prior_deltas: list[float] | None,
        current_closed_5m: dict[str, Any] | None,
        observed_at: datetime | None,
    ) -> dict[str, Any]:
        """Compute strict prior-only closed 5M OI diagnostics using canonical prior deltas."""
        default_diag = {
            "oi_delta": None,
            "oi_pct": None,
            "oi_price_delta": None,
            "oi_structure": None,
            "oi_window_closed_at": None,
            "oi_x": None,
            "oi_prior_mean": None,
            "oi_prior_median": None,
            "oi_prior_mad": None,
            "oi_session_rank": None,
            "oi_new_session_extreme": False,
            "mad_distance": None,
        }
        if not current_closed_5m or not observed_at:
            return default_diag

        current_delta = current_closed_5m.get("oi_delta")
        if current_delta is None:
            return default_diag

        abs_curr_delta = abs(float(current_delta))
        default_diag["oi_delta"] = current_delta
        default_diag["oi_pct"] = current_closed_5m.get("oi_pct")
        default_diag["oi_price_delta"] = current_closed_5m.get("price_delta")
        default_diag["oi_structure"] = current_closed_5m.get("structure")
        default_diag["oi_window_closed_at"] = current_closed_5m.get("window_closed_at")

        p_deltas = prior_deltas or []
        # FIRST OBSERVATION IS NOT AN EXTREME: If 0 prior observations, extreme must be False!
        if not p_deltas:
            default_diag["oi_session_rank"] = None
            default_diag["oi_new_session_extreme"] = False
            return default_diag

        prior_mean = round(sum(p_deltas) / len(p_deltas), 2)
        prior_median = round(float(median(p_deltas)), 2)
        prior_mad = round(float(median([abs(x - prior_median) for x in p_deltas])), 2)

        oi_x = round(abs_curr_delta / prior_median, 1) if prior_median > 0 else None
        # Factual extreme: strictly larger than all valid prior same-session observations
        oi_new_session_extreme = abs_curr_delta > max(p_deltas)
        all_deltas = p_deltas + [abs_curr_delta]
        session_rank = sum(1 for d in all_deltas if d > abs_curr_delta) + 1
        mad_dist = round(0.6745 * (abs_curr_delta - prior_median) / prior_mad, 2) if prior_mad > 0 else None

        default_diag.update({
            "oi_x": oi_x,
            "oi_prior_mean": prior_mean,
            "oi_prior_median": prior_median,
            "oi_prior_mad": prior_mad,
            "oi_session_rank": session_rank,
            "oi_new_session_extreme": oi_new_session_extreme,
            "mad_distance": mad_dist,
        })
        return default_diag

    def compute_flow_diagnostics(
        self,
        target_time: datetime | None,
        observed_at: datetime | None,
    ) -> dict[str, Any]:
        """Compute strict AS-OF prior-only flow diagnostics at target timestamp."""
        default_diag = {
            "flow_source": "5L_BOOK_CHANGE_DERIVED_MLOFI",
            "event_flow_timestamp": None,
            "event_mlofi": None,
            "event_flow_direction": None,
            "event_l1_ofi": None,
            "event_flow_x": None,
            "event_flow_baseline_sample_count": 0,
            "current_flow_timestamp": None,
            "current_mlofi": None,
            "current_flow_x": None,
            "flow_prior_median": None,
            "flow_prior_mad": None,
            "flow_baseline_sample_count": 0,
            "baseline_sample_count": 0,
            "flow_age_ms": None,
            "flow_revision": None,
            "flow_session_rank": None,
            "flow_new_session_extreme": False,
            "flow_freshness_state": "UNAVAILABLE",
        }
        if not self._flow_series:
            return default_diag

        # 1. Latest real-time current flow sample, strictly as-of observed_at.
        # The Flow transport can advance between option-chain observations;
        # retain those samples for the next observation without consuming a
        # sample whose source timestamp is still in the future for this one.
        eval_curr_time = observed_at or datetime.now(IST)
        eval_curr_epoch = eval_curr_time.timestamp()
        curr_idx: int | None = None
        for idx in range(len(self._flow_series) - 1, -1, -1):
            if self._flow_series[idx][0] <= eval_curr_epoch:
                curr_idx = idx
                break
        if curr_idx is None:
            return default_diag

        curr_matched = self._flow_series[curr_idx]
        curr_epoch, curr_mlofi_val, _, curr_iso, curr_rev = curr_matched
        default_diag["current_flow_timestamp"] = curr_iso
        default_diag["current_mlofi"] = round(curr_mlofi_val, 4)
        default_diag["flow_revision"] = curr_rev

        curr_age_ms = round((eval_curr_time.timestamp() - curr_epoch) * 1000.0, 1)
        default_diag["flow_age_ms"] = curr_age_ms

        if curr_age_ms <= FLOW_AGING_SECONDS * 1000.0:
            curr_freshness = "FRESH"
        elif curr_age_ms <= FLOW_TTL_MS:
            curr_freshness = "AGING"
        else:
            curr_freshness = "STALE"
        default_diag["flow_freshness_state"] = curr_freshness

        # Compute prior baseline for CURRENT flow sample
        prior_curr_samples = [abs(item[1]) for item in list(self._flow_series)[:curr_idx]]
        default_diag["flow_baseline_sample_count"] = len(prior_curr_samples)
        default_diag["baseline_sample_count"] = len(prior_curr_samples)
        if prior_curr_samples:
            prior_median = round(float(median(prior_curr_samples)), 4)
            prior_mad = round(float(median([abs(x - prior_median) for x in prior_curr_samples])), 4)
            default_diag["current_flow_x"] = round(abs(curr_mlofi_val) / prior_median, 1) if prior_median > 0 else None
            default_diag["flow_prior_median"] = prior_median
            default_diag["flow_prior_mad"] = prior_mad
            default_diag["flow_new_session_extreme"] = abs(curr_mlofi_val) > max(prior_curr_samples)
            all_samples = prior_curr_samples + [abs(curr_mlofi_val)]
            default_diag["flow_session_rank"] = sum(1 for m in all_samples if m > abs(curr_mlofi_val)) + 1

        # 2. Strict AS-OF Event Flow evaluation (if target_time provided)
        if target_time:
            target_epoch = target_time.timestamp()
            lo, hi = 0, len(self._flow_series) - 1
            best_idx: int | None = None
            while lo <= hi:
                mid = (lo + hi) // 2
                epoch = self._flow_series[mid][0]
                if epoch <= target_epoch:
                    best_idx = mid
                    lo = mid + 1
                else:
                    hi = mid - 1

            if best_idx is not None:
                flow_epoch, mlofi, l1_ofi, flow_iso, revision = self._flow_series[best_idx]
                event_age_ms = round((target_epoch - flow_epoch) * 1000.0, 1)
                if event_age_ms <= FLOW_TTL_MS:
                    default_diag["event_flow_timestamp"] = flow_iso
                    default_diag["event_mlofi"] = round(mlofi, 4)
                    default_diag["event_flow_direction"] = _flow_direction(mlofi)
                    default_diag["event_l1_ofi"] = round(l1_ofi, 4)
                    prior_event_samples = [abs(item[1]) for item in list(self._flow_series)[:best_idx]]
                    default_diag["event_flow_baseline_sample_count"] = len(prior_event_samples)
                    if prior_event_samples:
                        event_prior_median = round(float(median(prior_event_samples)), 4)
                        default_diag["event_flow_x"] = round(abs(mlofi) / event_prior_median, 1) if event_prior_median > 0 else None
                        default_diag["baseline_sample_count"] = len(prior_event_samples)
        else:
            # Synchronous evaluation without separate event target: event flow mirrors current if fresh/aging
            if curr_freshness != "STALE":
                default_diag["event_flow_timestamp"] = curr_iso
                default_diag["event_mlofi"] = round(curr_mlofi_val, 4)
                default_diag["event_flow_direction"] = _flow_direction(curr_mlofi_val)
                default_diag["event_l1_ofi"] = round(curr_matched[2], 4)
                default_diag["event_flow_x"] = default_diag.get("current_flow_x")
                default_diag["event_flow_baseline_sample_count"] = len(prior_curr_samples)

        return default_diag

    def synthesize_resolver_state(
        self,
        side: str,
        contract_payload: Mapping[str, Any] | None,
        oi_diag: dict[str, Any],
        flow_diag: dict[str, Any],
        flow_payload: Mapping[str, Any] | None,
        observed_at: datetime | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Synthesize deterministic single Resolver event and diagnostics for one option leg."""
        payload = contract_payload if isinstance(contract_payload, Mapping) else {}
        contract = payload.get("contract") if isinstance(payload.get("contract"), Mapping) else {}
        quote = payload.get("quote") if isinstance(payload.get("quote"), Mapping) else {}
        vob = payload.get("vob") if isinstance(payload.get("vob"), Mapping) else {}

        security_id = str(contract.get("security_id") or quote.get("security_id") or "")
        strike = contract.get("strike") or quote.get("strike")
        strike_str = f"{int(strike):,}" if strike is not None else ""

        current_session = str(observed_at.date()) if observed_at else None
        if current_session and self._session_id != current_session:
            self.reset_session(current_session)

        # 1. Structure Authority from exact contract VOB Horsepower
        raw_hp = vob.get("horsepower") if isinstance(vob.get("horsepower"), Mapping) else {}
        hp = self.extract_vob_timeframes(raw_hp)
        hp_1m = hp["1m"]
        hp_3m = hp["3m"]
        hp_5m = hp["5m"]

        status_1m = str(hp_1m.get("status") or "")
        status_3m = str(hp_3m.get("status") or "")
        status_5m = str(hp_5m.get("status") or "")

        p_1m = self._polarity(status_1m)
        p_3m = self._polarity(status_3m)
        p_5m = self._polarity(status_5m)

        # Lifecycle validity: Event confirmation candle must belong strictly to current session
        dt_1m = _parse_ts(hp_1m.get("confirmed_candle"))
        dt_3m = _parse_ts(hp_3m.get("confirmed_candle"))
        dt_5m = _parse_ts(hp_5m.get("confirmed_candle"))

        def _eligible_vob_event(polarity: str, event_time: datetime | None) -> bool:
            return bool(
                polarity != "NEUTRAL"
                and event_time is not None
                and observed_at is not None
                and str(event_time.date()) == current_session
                and event_time <= observed_at
            )

        valid_1m = _eligible_vob_event(p_1m, dt_1m)
        valid_3m = _eligible_vob_event(p_3m, dt_3m)
        valid_5m = _eligible_vob_event(p_5m, dt_5m)

        vob_label: str | None = None
        vob_direction: str | None = None
        vob_event_id: str | None = None
        vob_event_time: datetime | None = None

        # 2. Structural Alignment Hierarchy with strict lifecycle proof
        if valid_3m and valid_5m and p_3m == p_5m:
            vob_direction = p_3m
            if status_3m == "SUPPORT_GONE" and status_5m == "SUPPORT_GONE":
                vob_label = "SUPPORT GONE 3M+5M"
            elif status_3m == "RESISTANCE_OUT" and status_5m == "RESISTANCE_OUT":
                vob_label = "RES OUT 3M+5M"
            elif status_3m == "SUPPORT_BACK" and status_5m == "SUPPORT_BACK":
                vob_label = "SUPPORT BACK 3M+5M"
            elif status_3m == "BREAKOUT_LOST" and status_5m == "BREAKOUT_LOST":
                vob_label = "BREAKOUT LOST 3M+5M"
            else:
                arrow = "↑" if p_3m == "BULLISH" else "↓"
                vob_label = f"VOB ALIGN 3M+5M {arrow}"
            vob_event_id = str(hp_5m.get("event_id") or hp_3m.get("event_id") or "")
            vob_event_time = dt_5m or dt_3m

        if valid_1m and valid_3m and valid_5m and p_1m == p_3m == p_5m:
            arrow = "↑" if p_3m == "BULLISH" else "↓"
            vob_label = f"FULL VOB ALIGN {arrow}"

        elif vob_label is None and valid_1m and valid_3m and p_1m == p_3m:
            arrow = "↑" if p_3m == "BULLISH" else "↓"
            vob_label = f"VOB ALIGN 1M+3M {arrow}"
            vob_direction = p_3m
            vob_event_id = str(hp_3m.get("event_id") or hp_1m.get("event_id") or "")
            vob_event_time = dt_3m or dt_1m

        elif vob_label is None and valid_5m:
            vob_direction = p_5m
            vob_label = self._single_tf_label(status_5m, "5M")
            vob_event_id = str(hp_5m.get("event_id") or "")
            vob_event_time = dt_5m

        elif vob_label is None and valid_3m:
            vob_direction = p_3m
            vob_label = self._single_tf_label(status_3m, "3M")
            vob_event_id = str(hp_3m.get("event_id") or "")
            vob_event_time = dt_3m

        elif vob_label is None and valid_1m:
            vob_direction = p_1m
            vob_label = self._single_tf_label(status_1m, "1M")
            vob_event_id = str(hp_1m.get("event_id") or "")
            vob_event_time = dt_1m

        # 3. Flow & OI Directional Context
        event_mlofi = flow_diag.get("event_mlofi")
        event_flow_x = flow_diag.get("event_flow_x")
        current_mlofi = flow_diag.get("current_mlofi")
        current_flow_x = flow_diag.get("current_flow_x")
        flow_extreme = bool(flow_diag.get("flow_new_session_extreme"))

        oi_structure = oi_diag.get("oi_structure")
        oi_x = oi_diag.get("oi_x")
        oi_extreme = bool(oi_diag.get("oi_new_session_extreme"))

        if side.upper() == "CE":
            flow_supportive = event_mlofi is not None and event_mlofi > 0
            flow_hostile = event_mlofi is not None and event_mlofi < 0
        else:  # PE
            flow_supportive = event_mlofi is not None and event_mlofi < 0
            flow_hostile = event_mlofi is not None and event_mlofi > 0

        oi_supportive = oi_structure in ("LONG BUILDUP", "SHORT COVERING")
        oi_hostile = oi_structure in ("SHORT BUILDUP", "LONG UNWINDING")

        vob_supportive = vob_direction == "BULLISH"
        vob_hostile = vob_direction == "BEARISH"

        # 4. Label Synthesis (Max 2 Concepts) with State Memory Preservation
        held = self._held_state.get(security_id)
        final_label: str
        flow_upgrade_occurred = False
        pill_flow_x: float | None = None
        pill_mlofi: float | None = None
        pill_flow_direction: str | None = None

        if vob_label is not None:
            if event_flow_x is not None and flow_extreme:
                pill_flow_x = event_flow_x
                pill_mlofi = event_mlofi
                pill_flow_direction = _flow_direction(event_mlofi)
                direction_text = f"{pill_flow_direction} " if pill_flow_direction else ""
                final_label = f"{vob_label} · {direction_text}FLOW {event_flow_x}X"
            elif current_flow_x is not None and flow_extreme:
                # Later CURRENT Flow shock upgrades existing structural state
                pill_flow_x = current_flow_x
                pill_mlofi = current_mlofi
                pill_flow_direction = _flow_direction(current_mlofi)
                direction_text = f"{pill_flow_direction} " if pill_flow_direction else ""
                final_label = f"{vob_label} · {direction_text}FLOW {current_flow_x}X"
                flow_upgrade_occurred = True
            elif oi_x is not None and oi_extreme:
                final_label = f"{vob_label} · OI {oi_x}X"
            elif held and vob_event_id and held.get("vob_event_id") == vob_event_id and held.get("label"):
                # Retain historical shock label while the driving VOB event remains active
                final_label = held["label"]
                pill_flow_x = held.get("event_flow_x")
                pill_mlofi = held.get("event_mlofi")
                pill_flow_direction = held.get("event_flow_direction")
            else:
                final_label = vob_label
        elif oi_structure and oi_structure != "FLAT / NEUTRAL":
            short_oi = {
                "LONG BUILDUP": "LONG BUILD",
                "SHORT BUILDUP": "SHORT BUILD",
                "SHORT COVERING": "SHORT COVER",
                "LONG UNWINDING": "LONG UNWIND",
            }.get(oi_structure, oi_structure)
            if oi_x is not None and oi_extreme:
                final_label = f"{short_oi} · OI {oi_x}X"
            else:
                final_label = f"{short_oi} OI"
        else:
            final_label = f"ACTIVE RESOLVER · {strike_str} {side}" if strike_str else f"ACTIVE RESOLVER [{side}]"

        # 5. Semantic Variant & Confluence State
        variant = "cyan"
        semantic_direction = "INFO"
        confluence_state = "IDLE"

        full_aligned_bullish = vob_supportive and flow_supportive and oi_supportive
        full_aligned_bearish = vob_hostile and flow_hostile and oi_hostile

        if full_aligned_bullish:
            variant = "mint"
            semantic_direction = "BULLISH"
            confluence_state = "FULL_FRESH" if (flow_extreme or oi_extreme) else "ALIGNED_SETTLED"
        elif full_aligned_bearish:
            variant = "red"
            semantic_direction = "BEARISH"
            confluence_state = "FULL_FRESH" if (flow_extreme or oi_extreme) else "ALIGNED_SETTLED"
        elif vob_supportive or (vob_label is None and oi_supportive and flow_supportive):
            variant = "mint"
            semantic_direction = "BULLISH"
            confluence_state = "PARTIAL"
        elif vob_hostile or (vob_label is None and oi_hostile and flow_hostile):
            variant = "red"
            semantic_direction = "BEARISH"
            confluence_state = "PARTIAL"
        elif vob_label is not None or oi_structure in ("LONG BUILDUP", "SHORT BUILDUP", "SHORT COVERING", "LONG UNWINDING"):
            variant = "amber"
            semantic_direction = "NEUTRAL"
            confluence_state = "MIXED"

        # 6. State Memory & Pulse Governance
        current_time_iso = observed_at.isoformat() if observed_at else ""
        if flow_upgrade_occurred and flow_diag.get("current_flow_timestamp"):
            source_event_time = flow_diag["current_flow_timestamp"]
        else:
            source_event_time = (vob_event_time.isoformat() if vob_event_time else current_time_iso)

        # Check held state TTL (90.0 seconds according to audited architecture)
        held_expired = False
        if held and observed_at:
            held_ts = _parse_ts(held.get("source_event_time"))
            if held_ts and (observed_at - held_ts).total_seconds() > 90.0:
                held_expired = True

        if held is None or held_expired or held.get("label") != final_label or held.get("variant") != variant:
            pulse_key = f"{security_id}_{vob_event_id or 'REV'}_{int(observed_at.timestamp()) if observed_at else 0}"
            held_state = {
                "label": final_label,
                "semantic_direction": semantic_direction,
                "variant": variant,
                "confluence_state": confluence_state,
                "pulse_key": pulse_key,
                "source_event_time": source_event_time,
                "vob_event_id": vob_event_id,
                "event_flow_x": pill_flow_x,
                "event_mlofi": pill_mlofi,
                "event_flow_direction": pill_flow_direction,
                "event_oi_x": oi_x,
            }
            if security_id:
                self._held_state[security_id] = held_state
            held_previous = False
        else:
            pulse_key = held["pulse_key"]
            source_event_time = held["source_event_time"]
            confluence_state = held.get("confluence_state", confluence_state)
            held_previous = True

        # Track meaningful non-fallback events for memory retention
        is_meaningful = not final_label.startswith("ACTIVE RESOLVER")
        if is_meaningful:
            oi_window_closed_at = oi_diag.get("oi_window_closed_at")
            if vob_event_id:
                event_identity = f"VOB:{security_id}:{vob_event_id}:{final_label}"
            elif oi_window_closed_at:
                event_identity = f"OI:{security_id}:{oi_window_closed_at}:{final_label}"
            else:
                event_identity = f"STATE:{security_id}:{final_label}"
            previous_meaningful = self._last_meaningful_event.get(side.upper())
            event_timestamp = source_event_time or current_time_iso
            if (
                previous_meaningful
                and previous_meaningful.get("_event_identity") == event_identity
                and previous_meaningful.get("event_timestamp")
            ):
                # The same historical event is immutable: do not pair its held
                # label/timestamp with later OI, flow, price, or OI evidence.
                event_timestamp = previous_meaningful["event_timestamp"]
            else:
                self._last_meaningful_event[side.upper()] = {
                    "_event_identity": event_identity,
                    "security_id": security_id,
                    "strike": strike_str,
                    "side": side.upper(),
                    "label": final_label,
                    "oi_x": oi_x,
                    "flow_x": pill_flow_x,
                    "flow_direction": pill_flow_direction,
                    "variant": variant,
                    "confluence_state": confluence_state,
                    "event_timestamp": event_timestamp,
                    "event_price": contract_payload.get("quote", {}).get("ltp") if isinstance(contract_payload.get("quote"), Mapping) else None,
                    "event_oi": contract_payload.get("quote", {}).get("oi") if isinstance(contract_payload.get("quote"), Mapping) else None,
                    "reason": "VOB_FLOW_OI_SYNTHESIS",
                    "is_previous_contract": False,
                }

        last_meaningful_raw = self._last_meaningful_event.get(side.upper())
        last_meaningful_event = None
        if last_meaningful_raw:
            last_meaningful_event = dict(last_meaningful_raw)
            last_meaningful_event.pop("_event_identity", None)
            if observed_at and last_meaningful_event.get("event_timestamp"):
                try:
                    ev_dt = datetime.fromisoformat(last_meaningful_event["event_timestamp"].replace("Z", "+00:00"))
                    last_meaningful_event["age_seconds"] = round(max(0.0, (observed_at - ev_dt).total_seconds()), 1)
                except Exception:
                    last_meaningful_event["age_seconds"] = None
            if last_meaningful_event.get("security_id") and last_meaningful_event["security_id"] != security_id:
                last_meaningful_event["is_previous_contract"] = True
                last_meaningful_event["context_badge"] = f"PREVIOUS CONTRACT ({last_meaningful_event.get('strike')} {last_meaningful_event.get('side')})"
            else:
                last_meaningful_event["is_previous_contract"] = False

        resolver_event = {
            "label": final_label,
            "semantic_direction": semantic_direction,
            "variant": variant,
            "confluence_state": confluence_state,
            "pulse_key": pulse_key,
            "source_event_time": source_event_time,
            "held_previous": held_previous,
            "last_meaningful_event": last_meaningful_event,
        }

        fp_semantic = flow_payload.get("flow_pulse", {}).get("semantic", {}) if isinstance(flow_payload, Mapping) else {}
        flowpulse_pressure = fp_semantic.get("pressure")

        resolver_diagnostics = {
            "security_id": security_id,
            "session_id": current_session,
            "confluence_state": confluence_state,
            "vob_event_id": vob_event_id,
            "vob_event": vob_label,
            "vob_timeframes": {"1m": status_1m, "3m": status_3m, "5m": status_5m},
            "vob_direction": vob_direction,
            **oi_diag,
            **flow_diag,
            "flowpulse_pressure": flowpulse_pressure,
            "event_flow_direction": flow_diag.get("event_flow_direction") or _flow_direction(event_mlofi),
            "baseline_sample_count": flow_diag.get("flow_baseline_sample_count", 0),
            "pill_mlofi": pill_mlofi,
            "pill_flow_direction": pill_flow_direction,
            "pill_flow_x": pill_flow_x,
            "current_flow_x": current_flow_x,
            "held_previous": held_previous,
            "last_meaningful_event": last_meaningful_event,
            "current_confirmation_state": f"{semantic_direction}_{variant.upper()}",
            "state_reason": "VOB_FLOW_OI_SYNTHESIS",
        }

        return resolver_event, resolver_diagnostics

    @staticmethod
    def _polarity(status: str) -> str:
        if status in ("RESISTANCE_OUT", "SUPPORT_BACK"):
            return "BULLISH"
        if status in ("SUPPORT_GONE", "BREAKOUT_LOST"):
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _single_tf_label(status: str, tf: str) -> str:
        clean = {
            "SUPPORT_GONE": f"SUPPORT GONE {tf}",
            "RESISTANCE_OUT": f"RES OUT {tf}",
            "SUPPORT_BACK": f"SUPPORT BACK {tf}",
            "BREAKOUT_LOST": f"BREAKOUT LOST {tf}",
        }.get(status, f"{status} {tf}")
        return clean
