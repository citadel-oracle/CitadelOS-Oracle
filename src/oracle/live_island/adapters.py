"""Canonical Adapters Connecting Existing Oracle Engines to Live Island Events."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from src.oracle.live_island.contracts import (
    ArchetypeType,
    EventBias,
    LiveIslandEvent,
    LiveIslandTimestamps,
    NumericTrend,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.guards import StableUniverseGuard
from src.oracle.live_island.registry import DEFAULT_REGISTRY, LiveIslandRegistry

logger = logging.getLogger(__name__)


class GexAdapter:
    """Watches OptionIntelligenceEngine net GEX and emits on polarity flips (+ to - or - to +)."""

    def __init__(self, registry: LiveIslandRegistry = DEFAULT_REGISTRY) -> None:
        self.registry = registry
        self._last_gex: Optional[float] = None
        self._last_pole: Optional[str] = None  # "+GEX" | "-GEX"

    def on_gex_update(self, net_gex: float, spot_price: Optional[float] = None) -> Optional[LiveIslandEvent]:
        current_pole = "+GEX" if net_gex >= 0 else "-GEX"

        if self._last_pole is None:
            self._last_gex = net_gex
            self._last_pole = current_pole
            return None

        # Detect Polarity Flip
        if current_pole != self._last_pole:
            prev_pole = self._last_pole
            prev_cr = self._last_gex / 1e7 if abs(self._last_gex) > 100_000 else self._last_gex
            curr_cr = net_gex / 1e7 if abs(net_gex) > 100_000 else net_gex
            prev_val = f"{'+' if prev_cr >= 0 else ''}{prev_cr:.1f}Cr"
            curr_val = f"{'+' if curr_cr >= 0 else ''}{curr_cr:.1f}Cr"

            self._last_gex = net_gex
            self._last_pole = current_pole

            is_flip_to_negative = (current_pole == "-GEX")
            numeric_trend = NumericTrend.DOWN.value if is_flip_to_negative else NumericTrend.UP.value
            event_bias = EventBias.BEARISH.value if is_flip_to_negative else EventBias.BULLISH.value

            return LiveIslandEvent(
                id="gex",
                family="gex",
                title="GEX Flip",
                short_title=f"GEX {prev_pole.replace('GEX', '')} → {current_pole.replace('GEX', '')}",
                archetype=ArchetypeType.POLARITY.value,
                numeric_trend=numeric_trend,
                event_bias=event_bias,
                severity=SeverityLevel.CRITICAL.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=curr_val,
                previous_value=prev_val,
                change_percent=50.0,
                velocity=-0.95 if is_flip_to_negative else 0.95,
                acceleration=1.0,
                confidence=0.99,
                shorthand=f"GEX {prev_pole.replace('GEX', '')} → {current_pole.replace('GEX', '')}",
                secondary_value="GAMMA REGIME FLIP",
                priority_weight=4.5,  # Top priority Hero candidate
                archetype_data={
                    "prevPole": prev_pole,
                    "prevVal": prev_val,
                    "currPole": current_pole,
                    "currVal": curr_val,
                    "isCrossing": True,
                },
            )

        self._last_gex = net_gex
        return None


class BuyersWritersAdapter:
    """Watches Argus Dominance and emits when buyer/writer share changes by >= 5 percentage points."""

    def __init__(
        self,
        registry: LiveIslandRegistry = DEFAULT_REGISTRY,
        universe_guard: Optional[StableUniverseGuard] = None,
    ) -> None:
        self.registry = registry
        self.universe_guard = universe_guard
        self._last_buyer_share: Optional[float] = None
        self._last_emitted_time: float = 0.0

    def on_dominance_update(
        self,
        buyer_pct: float,
        writer_pct: float,
        constituent_strike_keys: Optional[list[str]] = None,
    ) -> Optional[LiveIslandEvent]:
        now = time.time()
        if self._last_buyer_share is None:
            self._last_buyer_share = buyer_pct
            return None

        delta_pp = buyer_pct - self._last_buyer_share
        abs_pp = abs(delta_pp)

        if abs_pp >= self.registry.buyers_writers_min_change_pp:
            # Re-arm gate
            if (now - self._last_emitted_time) < 10.0 and abs_pp < 1.0:
                return None

            prev_buyer = self._last_buyer_share
            self._last_buyer_share = buyer_pct
            self._last_emitted_time = now

            numeric_trend = NumericTrend.UP.value if delta_pp > 0 else NumericTrend.DOWN.value
            event_bias = EventBias.BULLISH.value if delta_pp > 0 else EventBias.BEARISH.value
            severity = SeverityLevel.HIGH.value if abs_pp >= 10.0 else SeverityLevel.MEDIUM.value

            sign = "+" if delta_pp >= 0 else ""
            pp_str = f"{sign}{delta_pp:.1f}pp"

            return LiveIslandEvent(
                id="buyers_writers",
                family="dominance",
                title="Buyers Dominance" if delta_pp > 0 else "Writers Dominance",
                short_title=f"Buyers {pp_str}",
                archetype=ArchetypeType.SCALAR.value,
                numeric_trend=numeric_trend,
                event_bias=event_bias,
                severity=severity,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"{buyer_pct:.1f}%",
                previous_value=f"{prev_buyer:.1f}%",
                change_percent=round(abs_pp, 1),
                change_pp=round(delta_pp, 1),
                confidence=0.94,
                shorthand=f"Buyers {prev_buyer:.0f}% → {buyer_pct:.0f}%",
                secondary_value=f"Order flow dominance shift ({pp_str})",
                priority_weight=3.2 if abs_pp < 10.0 else 4.0,
                archetype_data={
                    "oldVal": f"{prev_buyer:.1f}%",
                    "newVal": f"{buyer_pct:.1f}%",
                    "change": pp_str,
                },
            )

        return None


class BuildupAdapter:
    """Watches ArgusOptionChainEngine quad-state buildup transitions.

    Crucial: Unsuppressed counter-bias transitions.
    If the Spine is GREEN and a key strike flips to SHORT BUILDUP, show it as
    a localized contradiction / counter-bias warning rather than suppressing it.
    """

    def __init__(self) -> None:
        self._strike_states: Dict[str, str] = {}  # strike -> quad_state
        self._last_focus_strike: Optional[int] = None
        self._last_primary_flow: Optional[str] = None
        self._last_defence_flow: Optional[str] = None
        self._last_positioning: Optional[str] = None
        self._last_migration_state: Optional[str] = None
        self._last_structure_state: Optional[str] = None
        self._last_accel_arrow: Optional[str] = None
        self._last_load_intensity: Optional[float] = None

    def on_strike_spine_focus(
        self,
        best_strike_stack: Dict[str, Any],
        strike_spine: Optional[Sequence[Any]] = None,
    ) -> Optional[LiveIslandEvent]:
        """Anchors strike-specific Live Island notifications strictly to Enhanced Strike Spine focus."""
        if not isinstance(best_strike_stack, dict):
            return None

        raw_strike = best_strike_stack.get("strike") or best_strike_stack.get("strongest_structural_strike")
        if raw_strike is None:
            return None

        try:
            focus_strike = int(float(raw_strike))
        except (ValueError, TypeError):
            return None

        direction = str(best_strike_stack.get("direction") or "CALL").upper()
        primary_flow_obj = best_strike_stack.get("primary_flow") if isinstance(best_strike_stack.get("primary_flow"), dict) else {}
        primary_flow = str(primary_flow_obj.get("label") or "UNSPECIFIED")
        primary_arrow = str(primary_flow_obj.get("arrow") or "→")
        primary_load = float(primary_flow_obj.get("load") or 0.0)

        defence_flow_obj = best_strike_stack.get("defence_flow") if isinstance(best_strike_stack.get("defence_flow"), dict) else {}
        defence_flow = str(defence_flow_obj.get("label") or "UNSPECIFIED")
        defence_arrow = str(defence_flow_obj.get("arrow") or "→")
        defence_load = float(defence_flow_obj.get("load") or 0.0)

        migration_obj = best_strike_stack.get("migration") if isinstance(best_strike_stack.get("migration"), dict) else {}
        migration_state = str(migration_obj.get("state") or "SCATTERED")
        migration_label = str(migration_obj.get("label") or "No clean migration")
        structure_state = str(best_strike_stack.get("state") or "STRUCTURE")

        # Find matching row in strike_spine for positioning
        positioning = primary_flow
        for row in (strike_spine or []):
            if isinstance(row, dict):
                row_strike = row.get("strike")
                if row_strike is not None:
                    try:
                        if int(float(row_strike)) == focus_strike:
                            leg = row.get("CE" if direction == "CALL" else "PE")
                            if isinstance(leg, dict) and leg.get("positioning"):
                                positioning = str(leg.get("positioning"))
                            break
                    except (ValueError, TypeError):
                        pass

        # Meaningful change check (Requirement 4)
        is_initial = self._last_focus_strike is None
        strike_changed = (self._last_focus_strike is not None and focus_strike != self._last_focus_strike)
        flow_changed = (self._last_primary_flow is not None and primary_flow != self._last_primary_flow)
        defence_changed = (self._last_defence_flow is not None and defence_flow != self._last_defence_flow)
        positioning_changed = (self._last_positioning is not None and positioning != self._last_positioning)
        migration_changed = (self._last_migration_state is not None and migration_state != self._last_migration_state)
        structure_changed = (self._last_structure_state is not None and structure_state != self._last_structure_state)
        arrow_changed = (self._last_accel_arrow is not None and primary_arrow != self._last_accel_arrow)

        meaningful_change = (
            is_initial
            or strike_changed
            or flow_changed
            or defence_changed
            or positioning_changed
            or migration_changed
            or structure_changed
            or arrow_changed
        )

        if not meaningful_change:
            return None

        prev_strike = self._last_focus_strike
        prev_flow = self._last_primary_flow

        # Update cache
        self._last_focus_strike = focus_strike
        self._last_primary_flow = primary_flow
        self._last_defence_flow = defence_flow
        self._last_positioning = positioning
        self._last_migration_state = migration_state
        self._last_structure_state = structure_state
        self._last_accel_arrow = primary_arrow
        self._last_load_intensity = primary_load

        # Biasing
        if direction == "CALL" or "BULLISH" in structure_state or "LONG_BUILDUP" in positioning:
            event_bias = EventBias.BULLISH.value
            trend = NumericTrend.UP.value
        elif direction == "PUT" or "BEARISH" in structure_state or "SHORT_BUILDUP" in positioning:
            event_bias = EventBias.BEARISH.value
            trend = NumericTrend.DOWN.value
        else:
            event_bias = EventBias.NEUTRAL.value
            trend = NumericTrend.FLAT.value

        short_primary = primary_flow.replace("_", " ")
        short_defence = defence_flow.replace("_", " ")

        return LiveIslandEvent(
            id=f"buildup_{focus_strike}",
            family="buildup",
            title=f"Strike {focus_strike} Buildup",
            short_title=f"{focus_strike} · {short_primary}",
            archetype=ArchetypeType.LEVEL.value,
            numeric_trend=trend,
            event_bias=event_bias,
            severity=SeverityLevel.HIGH.value if (strike_changed or flow_changed) else SeverityLevel.MEDIUM.value,
            phase=PresentationPhase.IMPACT.value,
            current_value=f"{short_primary} · ACCEL {primary_arrow} LOAD {round(primary_load)}",
            previous_value=f"{prev_flow.replace('_', ' ')}" if prev_flow else "INITIAL",
            confidence=0.96,
            shorthand=f"{focus_strike} {short_primary}",
            secondary_value=f"PRIMARY: {short_primary} · DEFENCE: {short_defence}",
            priority_weight=2.8,
            archetype_data={
                "oldStrike": f"{prev_strike}" if prev_strike and prev_strike != focus_strike else short_primary,
                "newStrike": f"{focus_strike}",
                "strike": focus_strike,
                "primaryFlow": primary_flow,
                "defenceFlow": defence_flow,
                "positioning": positioning,
                "accelArrow": primary_arrow,
                "load": primary_load,
                "migration": migration_label,
            },
        )

    def on_strike_buildup(self, strike: str, new_state: str, details: Optional[Dict[str, Any]] = None) -> Optional[LiveIslandEvent]:
        prev_state = self._strike_states.get(strike)
        if prev_state is None:
            self._strike_states[strike] = new_state
            return None

        if prev_state != new_state:
            self._strike_states[strike] = new_state

            # Determine Bias
            if "LONG_BUILDUP" in new_state or "SHORT_COVERING" in new_state:
                event_bias = EventBias.BULLISH.value
                trend = NumericTrend.UP.value
            elif "SHORT_BUILDUP" in new_state or "LONG_UNWINDING" in new_state:
                event_bias = EventBias.BEARISH.value
                trend = NumericTrend.DOWN.value
            else:
                event_bias = EventBias.NEUTRAL.value
                trend = NumericTrend.FLAT.value

            return LiveIslandEvent(
                id=f"buildup_{strike}",
                family="buildup",
                title=f"Strike {strike} Buildup",
                short_title=f"{strike} {new_state.replace('_', ' ')}",
                archetype=ArchetypeType.LEVEL.value,
                numeric_trend=trend,
                event_bias=event_bias,
                severity=SeverityLevel.MEDIUM.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=new_state.replace("_", " "),
                previous_value=prev_state.replace("_", " "),
                confidence=0.91,
                shorthand=f"{strike} {prev_state[:5]} → {new_state[:5]}",
                secondary_value="STRIKE REGIME SHIFT",
                priority_weight=2.8,
                archetype_data={
                    "oldStrike": prev_state.replace("_", " "),
                    "newStrike": new_state.replace("_", " "),
                },
            )

        return None

    def on_atm_window_update(self, window: list[Any]) -> list[LiveIslandEvent]:
        events = []
        for row in window or []:
            if not isinstance(row, dict):
                continue
            strike_val = row.get("strike")
            if strike_val is None:
                continue
            strike_str = str(int(float(strike_val)))
            for side in ("ce", "pe"):
                leg = row.get(side)
                if isinstance(leg, dict):
                    positioning = leg.get("positioning")
                    if positioning and positioning != "NEUTRAL":
                        ev = self.on_strike_buildup(f"{strike_str} {side.upper()}", positioning)
                        if ev:
                            events.append(ev)
        return events


class GammaBlastAdapter:
    """Hooks ArgusPrimeProjection._gamma_blast state changes (LOADING, ARMED, CONFIRMED, ACTIVE)."""

    def __init__(self) -> None:
        self._last_state: Optional[str] = None

    def on_gamma_blast(self, blast_input: Any, intensity: str = "4.8x") -> Optional[LiveIslandEvent]:
        blast_state = blast_input
        direction = "NEUTRAL"
        if isinstance(blast_input, dict):
            blast_state = blast_input.get("state") or blast_input.get("phase")
            score = blast_input.get("score")
            direction = str(blast_input.get("direction") or "NEUTRAL")
            if score is not None and score > 0:
                intensity = f"{float(score) / 20.0:.1f}x"

        blast_state_str = str(blast_state or "")
        if blast_state_str != self._last_state and blast_state_str in ("LOADING", "ARMED", "CONFIRMED", "ACTIVE"):
            self._last_state = blast_state_str
            event_bias = EventBias.BULLISH.value if direction == "BULLISH" else (EventBias.BEARISH.value if direction == "BEARISH" else EventBias.NEUTRAL.value)

            return LiveIslandEvent(
                id="gamma_blast",
                family="gamma_blast",
                title="Gamma Blast",
                short_title=f"Γ BLAST {intensity}",
                archetype=ArchetypeType.IMPULSE.value,
                numeric_trend=NumericTrend.UP.value,
                event_bias=event_bias,
                severity=SeverityLevel.CRITICAL.value if blast_state_str in ("CONFIRMED", "ACTIVE") else SeverityLevel.HIGH.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=intensity,
                previous_value="0.0x",
                confidence=0.99,
                shorthand=f"Γ BLAST {intensity}",
                secondary_value=f"ONE-SHOT IMPULSE ({blast_state_str})",
                priority_weight=4.4 if blast_state_str in ("CONFIRMED", "ACTIVE") else 3.8,
                archetype_data={
                    "blastIntensity": intensity,
                    "impulseActive": True,
                    "blastState": blast_state_str,
                    "rateText": "IMPULSE",
                },
            )
        return None


class MaxPainAdapter:
    """Reuses Upstox REST Max Pain with native spot_price directly from the payload, evaluating mathematical alignment."""

    def __init__(self) -> None:
        self._last_max_pain: Optional[float] = None
        self._last_spot_price: Optional[float] = None
        self._last_updated_time: float = 0.0

    def on_max_pain_update(self, new_max_pain: float, spot_price: Optional[float] = None) -> Optional[LiveIslandEvent]:
        now = time.time()
        if self._last_max_pain is None:
            self._last_max_pain = new_max_pain
            self._last_spot_price = spot_price
            self._last_updated_time = now
            return None

        if new_max_pain != self._last_max_pain:
            prev_mp = self._last_max_pain
            prev_spot = self._last_spot_price
            self._last_max_pain = new_max_pain
            self._last_spot_price = spot_price
            self._last_updated_time = now

            mp_delta = new_max_pain - prev_mp
            trend = NumericTrend.UP.value if mp_delta > 0 else NumericTrend.DOWN.value

            # Determine mathematical alignment between Spot movement and Max Pain shift
            spot_delta = (spot_price - prev_spot) if (spot_price is not None and prev_spot is not None) else 0.0
            if abs(spot_delta) < 1.0 or spot_price is None or prev_spot is None:
                alignment = "FLAT / UNCONFIRMED SPOT"
                event_bias = EventBias.NEUTRAL.value
                bias_tag = "NEUTRAL"
            elif (mp_delta > 0 and spot_delta > 0):
                alignment = "ALIGNED (BULLISH SHIFT)"
                event_bias = EventBias.BULLISH.value
                bias_tag = "ALIGNED"
            elif (mp_delta < 0 and spot_delta < 0):
                alignment = "ALIGNED (BEARISH SHIFT)"
                event_bias = EventBias.BEARISH.value
                bias_tag = "ALIGNED"
            elif (mp_delta > 0 and spot_delta < 0):
                alignment = "DIVERGING (BEARISH DIVERGENCE)"
                event_bias = EventBias.RISK.value
                bias_tag = "DIVERGING"
            else:  # mp_delta < 0 and spot_delta > 0
                alignment = "DIVERGING (BULLISH DIVERGENCE)"
                event_bias = EventBias.RISK.value
                bias_tag = "DIVERGING"

            spot_str = f"Spot {spot_price:.1f} ({'+' if spot_delta >= 0 else ''}{spot_delta:.1f})" if spot_price else ""
            secondary = f"{alignment} · {spot_str}" if spot_str else alignment

            return LiveIslandEvent(
                id="max_pain",
                family="max_pain",
                title="Max Pain Shift",
                short_title=f"MP {int(prev_mp)} → {int(new_max_pain)}",
                archetype=ArchetypeType.LEVEL.value,
                numeric_trend=trend,
                event_bias=event_bias,
                severity=SeverityLevel.MEDIUM.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"{int(new_max_pain)}",
                previous_value=f"{int(prev_mp)}",
                change_percent=round(abs(mp_delta) / prev_mp * 100.0, 2),
                confidence=0.92,
                shorthand=f"MP {int(prev_mp)} → {int(new_max_pain)}",
                secondary_value=secondary,
                priority_weight=2.4,
                archetype_data={
                    "oldStrike": str(int(prev_mp)),
                    "newStrike": str(int(new_max_pain)),
                    "spotPrice": spot_price,
                    "spotDelta": spot_delta,
                    "alignment": bias_tag,
                },
            )

        return None


class SuddenOiAdapter:
    """Hooks canonical OptionBuyerIntelligence sudden_oi (new_5m_high, squeeze, extreme breadth)."""

    def __init__(self) -> None:
        self._last_emitted_key: Optional[str] = None
        self._last_emitted_time: float = 0.0

    def on_sudden_oi_update(self, sudden_oi: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        if not isinstance(sudden_oi, dict):
            return None

        now = time.time()
        call_side = sudden_oi.get("CALL") or {}
        put_side = sudden_oi.get("PUT") or {}

        call_act = float(call_side.get("current_5m_activity") or 0.0)
        put_act = float(put_side.get("current_5m_activity") or 0.0)

        call_top = call_side.get("top_strike") or {}
        put_top = put_side.get("top_strike") or {}

        is_call_extreme = bool(call_side.get("new_session_extreme") or call_top.get("new_5m_high"))
        is_put_extreme = bool(put_side.get("new_session_extreme") or put_top.get("new_5m_high"))
        is_call_squeeze = bool(call_top.get("squeeze"))
        is_put_squeeze = bool(put_top.get("squeeze"))

        call_ratio = float(call_side.get("current_to_normal_x") or 0.0)
        put_ratio = float(put_side.get("current_to_normal_x") or 0.0)

        trigger_side = None
        intensity_label = None
        top = {}

        if is_call_extreme or call_ratio >= 2.0 or is_call_squeeze:
            trigger_side = "CALL"
            top = call_top
            intensity_label = "SQUEEZE" if is_call_squeeze else "5M HIGH" if is_call_extreme else f"{call_ratio:.1f}x NORMAL"
        elif is_put_extreme or put_ratio >= 2.0 or is_put_squeeze:
            trigger_side = "PUT"
            top = put_top
            intensity_label = "SQUEEZE" if is_put_squeeze else "5M HIGH" if is_put_extreme else f"{put_ratio:.1f}x NORMAL"

        if not trigger_side:
            return None

        strike_val = top.get("strike")
        strike_str = f"{strike_val:,.0f}" if strike_val else "ATM"
        dedup_key = f"{trigger_side}:{strike_str}:{intensity_label}"

        if self._last_emitted_key == dedup_key and (now - self._last_emitted_time) < 15.0:
            return None

        self._last_emitted_key = dedup_key
        self._last_emitted_time = now

        dominant = "left" if trigger_side == "CALL" else "right"
        event_bias = EventBias.BEARISH.value if trigger_side == "PUT" else EventBias.BULLISH.value

        return LiveIslandEvent(
            id="sudden_oi",
            family="sudden_oi",
            title=f"Sudden {trigger_side} OI Surge",
            short_title=f"{strike_str} {trigger_side} {intensity_label}",
            archetype=ArchetypeType.DUAL_SIDED.value,
            numeric_trend=NumericTrend.UP.value,
            event_bias=event_bias,
            severity=SeverityLevel.HIGH.value if ("HIGH" in intensity_label or "SQUEEZE" in intensity_label) else SeverityLevel.MEDIUM.value,
            phase=PresentationPhase.IMPACT.value,
            current_value=f"{call_act if trigger_side == 'CALL' else put_act:,.0f}",
            previous_value="0",
            confidence=0.95,
            shorthand=f"{strike_str} {trigger_side} {intensity_label}",
            secondary_value=f"5M OI REGIME ({intensity_label})",
            reference_window="5m",
            priority_weight=3.9,
            archetype_data={
                "leftSide": "CALL 5M",
                "leftVal": f"{call_act:,.0f}",
                "rightSide": "PUT 5M",
                "rightVal": f"{put_act:,.0f}",
                "dominantSide": dominant,
                "rateText": "SURGING",
            },
        )


class OiShiftAdapter:
    """Hooks canonical Upstox Change-in-OI / MarketInfoService session ΔOI outputs."""

    def __init__(self) -> None:
        self._last_call_delta: Optional[float] = None
        self._last_put_delta: Optional[float] = None
        self._last_emitted_time: float = 0.0

    def on_oi_shift_update(self, oi_shift: Dict[str, Any]) -> Optional[LiveIslandEvent]:
        if not isinstance(oi_shift, dict):
            return None

        call_delta = oi_shift.get("total_call_delta_oi")
        put_delta = oi_shift.get("total_put_delta_oi")
        if call_delta is None or put_delta is None:
            return None

        call_delta = float(call_delta)
        put_delta = float(put_delta)
        now = time.time()

        if self._last_call_delta is None:
            self._last_call_delta = call_delta
            self._last_put_delta = put_delta
            return None

        step_c = abs(call_delta - self._last_call_delta)
        step_p = abs(put_delta - self._last_put_delta)

        # Trigger on material session ΔOI shift (>= 25k contracts)
        if (step_c >= 25_000 or step_p >= 25_000) and (now - self._last_emitted_time) >= 10.0:
            self._last_call_delta = call_delta
            self._last_put_delta = put_delta
            self._last_emitted_time = now

            dominant = "left" if abs(call_delta) > abs(put_delta) else "right"
            event_bias = EventBias.BEARISH.value if put_delta > call_delta else EventBias.BULLISH.value

            return LiveIslandEvent(
                id="oi_shift",
                family="oi_shift",
                title="Session OI Shift",
                short_title="Session ΔOI Shift",
                archetype=ArchetypeType.DUAL_SIDED.value,
                numeric_trend=NumericTrend.UP.value if (put_delta + call_delta) > 0 else NumericTrend.DOWN.value,
                event_bias=event_bias,
                severity=SeverityLevel.MEDIUM.value,
                phase=PresentationPhase.IMPACT.value,
                current_value=f"C:{call_delta:+,.0f} P:{put_delta:+,.0f}",
                previous_value="",
                confidence=0.91,
                shorthand="Session ΔOI Shift",
                secondary_value="OFFICIAL 1D ΔOI",
                reference_window="session",
                priority_weight=3.0,
                archetype_data={
                    "leftSide": "CALL ΔOI",
                    "leftVal": f"{call_delta:+,.0f}",
                    "rightSide": "PUT ΔOI",
                    "rightVal": f"{put_delta:+,.0f}",
                    "dominantSide": dominant,
                },
            )

        return None

