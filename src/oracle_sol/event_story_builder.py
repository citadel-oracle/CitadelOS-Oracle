"""Deterministic Market Event Story Builder (P0.3B Live-Hardened).

Translates canonical microstructural snapshot deltas into discrete,
chronologically ordered factual events with 128-bit collision-safe deterministic IDs,
full temporal sensorium delta tracking, non-interpretive factual event naming,
and strict two-phase atomic compilation (compile_events -> commit_baseline).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.oracle_sol.contracts import (
    MarketEvent,
    MarketEventType,
    SolEvidenceSnapshot,
    SystemStatus,
)
from src.oracle_sol.provenance_guard import ProvenanceGuard


class MarketEventStoryBuilder:
    """Deterministic factual event compiler comparing successive canonical snapshots."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self.storage_dir = Path(storage_dir or "data/sol_shadow")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._last_snapshot: Optional[SolEvidenceSnapshot] = None
        self._current_session_date: Optional[str] = None

        self.baseline_store_status = "OK"
        self.last_successful_baseline_write_utc: Optional[str] = None
        self.last_baseline_error: Optional[str] = None

    def _get_baseline_file(self, session_date: str) -> Path:
        return self.storage_dir / f"sol_last_snapshot_{session_date}.json"

    def reset_session(self, session_date: str) -> None:
        """Reset comparison baseline when rotating to a new market session date."""
        self._current_session_date = session_date
        self._last_snapshot = None

    def hydrate_last_snapshot(self, session_date: str) -> bool:
        """Hydrate comparison baseline from disk across restarts."""
        self._current_session_date = session_date
        snap_file = self._get_baseline_file(session_date)
        if not snap_file.exists():
            return False
        try:
            with open(snap_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            from src.oracle_sol.contracts import SolEvidenceSnapshot, SystemStatus
            sys_stat = SystemStatus(d.get("system_status", "UNAVAILABLE"))
            self._last_snapshot = SolEvidenceSnapshot(
                snapshot_id=d["snapshot_id"],
                canonical_snapshot_id=d.get("canonical_snapshot_id"),
                market_session_date=d.get("market_session_date", session_date),
                identity_quality=d.get("identity_quality", "CANONICAL_AUTHENTIC"),
                replay_stable=d.get("replay_stable", True),
                timestamp_utc=d["timestamp_utc"],
                timestamp_ist=d["timestamp_ist"],
                system_status=sys_stat,
                upstream_source_health=d.get("upstream_source_health", {}),
                dhan_quote_age_ms=d.get("dhan_quote_age_ms"),
                order_flow_age_ms=d.get("order_flow_age_ms"),
                option_chain_age_ms=d.get("option_chain_age_ms"),
                spot_ltp=d.get("spot_ltp"),
                futures_ltp=d.get("futures_ltp"),
                futures_basis=d.get("futures_basis"),
                session_vwap=d.get("session_vwap"),
                spot_to_vwap_pts=d.get("spot_to_vwap_pts"),
                active_expiry=d.get("active_expiry"),
                atm_strike=d.get("atm_strike"),
                futures_security_id=d.get("futures_security_id"),
                sudden_oi_call=d.get("sudden_oi_call"),
                sudden_oi_put=d.get("sudden_oi_put"),
                strike_ladder=d.get("strike_ladder", []),
                mlofi_5l=d.get("mlofi_5l"),
                current_flow_x=d.get("current_flow_x"),
                mlofi_session_extreme=d.get("mlofi_session_extreme"),
                ce_pricing=d.get("ce_pricing"),
                pe_pricing=d.get("pe_pricing"),
                atm_straddle_price=d.get("atm_straddle_price"),
                straddle_change_5m=d.get("straddle_change_5m"),
                atm_iv=d.get("atm_iv"),
                skew_25d=d.get("skew_25d"),
                skew_10d=d.get("skew_10d"),
                expected_move_pts=d.get("expected_move_pts"),
                net_gex_inr=d.get("net_gex_inr"),
                highest_gex_strike=d.get("highest_gex_strike"),
                zero_gamma_level=d.get("zero_gamma_level"),
                availability_matrix=d.get("availability_matrix", {}),
                source_hashes=d.get("source_hashes", {}),
                vob_free_verified=d.get("vob_free_verified", "ZERO_VOB_ALLOWLIST_CONFIRMED"),
            )
            self.baseline_store_status = "OK"
            return True
        except Exception as exc:
            self.baseline_store_status = "DEGRADED"
            self.last_baseline_error = f"Baseline hydration error: {str(exc)}"
            return False

    def commit_baseline(self, snapshot: SolEvidenceSnapshot) -> None:
        """Commit and persist current snapshot as the active comparison baseline."""
        snap_file = self._get_baseline_file(snapshot.market_session_date)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=snap_file.parent,
                prefix=f".{snap_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                temp_path = Path(f.name)
                json.dump(snapshot.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, snap_file)
            temp_path = None
            directory_fd = os.open(snap_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._last_snapshot = snapshot
            self.last_successful_baseline_write_utc = datetime.now(timezone.utc).isoformat()
            self.baseline_store_status = "OK"
            self.last_baseline_error = None
        except Exception as exc:
            self.baseline_store_status = "ERROR"
            self.last_baseline_error = f"Baseline write error: {str(exc)}"
            raise
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _make_deterministic_event_id(
        self, snapshot_id: str, event_type: str, instrument: str, state_payload: Dict[str, Any]
    ) -> str:
        """Derive 128-bit collision-safe deterministic ID from snapshot, type, instrument, and state hash."""
        clean_snap = snapshot_id.replace("snap_", "")[:16]
        clean_inst = instrument.replace(" ", "_").replace(":", "_").replace("-", "_")
        state_encoded = json.dumps(state_payload, sort_keys=True, default=str).encode("utf-8")
        state_hash = hashlib.sha256(state_encoded).hexdigest()[:16]
        return f"evt_{clean_snap}_{event_type}_{clean_inst}_{state_hash}"

    def compile_events(
        self, current: SolEvidenceSnapshot
    ) -> List[MarketEvent]:
        """Compile factual market events by comparing current snapshot against baseline WITHOUT committing baseline."""
        events: List[MarketEvent] = []
        session_date = current.market_session_date

        if self._current_session_date is not None and self._current_session_date != session_date:
            self.reset_session(session_date)

        self._current_session_date = session_date
        last = self._last_snapshot

        if last is None:
            # Initial baseline registration event for this market session
            spot_str = f"{current.spot_ltp:.2f}" if current.spot_ltp is not None else "UNAVAILABLE"
            atm_str = f"{current.atm_strike:.0f}" if current.atm_strike is not None else "UNAVAILABLE"
            supporting = {
                "spot_ltp": current.spot_ltp,
                "atm_strike": current.atm_strike,
                "system_status": current.system_status.value,
                "mlofi_5l": current.mlofi_5l,
                "chronology_mode": "BASELINE_REGISTRATION",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "STATE_TRANSITION", "NIFTY", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type=MarketEventType.STATE_TRANSITION.value,
                instrument="NIFTY",
                summary=f"Session baseline established. Spot: {spot_str}, ATM: {atm_str}, System: {current.system_status.value}",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(current.to_dict()),
            )
            events.append(evt)
            return events

        # If identical snapshot is presented again, emit zero events (idempotent delta)
        if current.snapshot_id == last.snapshot_id:
            if ProvenanceGuard.compute_sha256(current.to_dict()) != ProvenanceGuard.compute_sha256(last.to_dict()):
                raise ValueError(
                    f"Snapshot identity collision: snapshot_id '{current.snapshot_id}' has different payloads."
                )
            return []

        # 1. Spot movement
        if current.spot_ltp is not None and last.spot_ltp is not None and current.spot_ltp != last.spot_ltp:
            spot_delta = current.spot_ltp - last.spot_ltp
            vwap_dist = f"{current.spot_to_vwap_pts:+.2f} pts" if current.spot_to_vwap_pts is not None else "UNAVAILABLE"
            supporting = {
                "before_spot": last.spot_ltp,
                "after_spot": current.spot_ltp,
                "spot_delta": spot_delta,
                "spot_to_vwap_pts": current.spot_to_vwap_pts,
                "session_vwap": current.session_vwap,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "SPOT_MOVE", "NIFTY_INDEX", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type=MarketEventType.SPOT_MOVE.value,
                instrument="NIFTY_INDEX",
                summary=f"Spot moved {spot_delta:+.2f} pts from {last.spot_ltp:.2f} to {current.spot_ltp:.2f} (VWAP dist: {vwap_dist}).",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        # 2. Futures movement & Basis Shift
        if current.futures_ltp is not None and last.futures_ltp is not None and current.futures_ltp != last.futures_ltp:
            fut_delta = current.futures_ltp - last.futures_ltp
            supporting = {
                "before_futures": last.futures_ltp,
                "after_futures": current.futures_ltp,
                "futures_delta": fut_delta,
                "basis": current.futures_basis,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "FUTURES_MOVE", "NIFTY_FUTURES", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type=MarketEventType.FUTURES_MOVE.value,
                instrument="NIFTY_FUTURES",
                security_id=current.futures_security_id,
                summary=f"Futures LTP moved {fut_delta:+.2f} pts from {last.futures_ltp:.2f} to {current.futures_ltp:.2f}.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        if current.futures_basis is not None and last.futures_basis is not None and current.futures_basis != last.futures_basis:
            basis_delta = current.futures_basis - last.futures_basis
            supporting = {
                "before_basis": last.futures_basis,
                "after_basis": current.futures_basis,
                "basis_delta": basis_delta,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "BASIS_SHIFT", "NIFTY_BASIS", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type="BASIS_SHIFT",
                instrument="NIFTY_BASIS",
                summary=f"Futures basis changed {basis_delta:+.2f} pts from {last.futures_basis:+.2f} to {current.futures_basis:+.2f}.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        # 3. ATM Strike Migration
        if current.atm_strike is not None and last.atm_strike is not None and current.atm_strike != last.atm_strike:
            supporting = {
                "before_atm": last.atm_strike,
                "after_atm": current.atm_strike,
                "spot_ltp": current.spot_ltp,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "ATM_MIGRATION", "NIFTY_CHAIN", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type=MarketEventType.ATM_MIGRATION.value,
                instrument="NIFTY_CHAIN",
                summary=f"ATM strike shifted from {last.atm_strike:.0f} to {current.atm_strike:.0f}.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        # 4. Sudden OI Surges
        for side, side_data in (("CALL", current.sudden_oi_call), ("PUT", current.sudden_oi_put)):
            if isinstance(side_data, dict) and side_data.get("new_session_extreme") is True:
                last_side = last.sudden_oi_call if side == "CALL" else last.sudden_oi_put
                if not (isinstance(last_side, dict) and last_side.get("new_session_extreme") is True):
                    top_strike = side_data.get("top_strike")
                    pct = side_data.get("percentile")
                    strike_str = f"{top_strike:.0f}" if isinstance(top_strike, (int, float)) else "UNAVAILABLE"
                    pct_str = f"{pct:.1f}th" if isinstance(pct, (int, float)) else "UNAVAILABLE"
                    supporting = {
                        "side": side,
                        "top_strike": top_strike,
                        "percentile": pct,
                        "delta_oi": side_data.get("delta_oi"),
                        "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
                    }
                    evt_id = self._make_deterministic_event_id(
                        current.snapshot_id, "SUDDEN_OI_SURGE", f"NIFTY_{side}", supporting
                    )
                    evt = MarketEvent(
                        event_id=evt_id,
                        session_date=session_date,
                        timestamp_utc=current.timestamp_utc,
                        timestamp_ist=current.timestamp_ist,
                        event_type=MarketEventType.SUDDEN_OI_SURGE.value,
                        instrument=f"NIFTY_{side}",
                        strike=float(top_strike) if isinstance(top_strike, (int, float)) else None,
                        summary=f"Sudden {side} OI surge at strike {strike_str} ({pct_str} percentile).",
                        supporting_values=supporting,
                        provenance_hash=ProvenanceGuard.compute_sha256(supporting),
                    )
                    events.append(evt)

        # 5. Order Flow Polarity Flip or Magnitude Shifts
        if current.mlofi_5l is not None and last.mlofi_5l is not None:
            if (last.mlofi_5l > 0 and current.mlofi_5l < 0) or (last.mlofi_5l < 0 and current.mlofi_5l > 0):
                supporting = {
                    "before_mlofi": last.mlofi_5l,
                    "after_mlofi": current.mlofi_5l,
                    "is_session_extreme": current.mlofi_session_extreme,
                    "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
                }
                evt_id = self._make_deterministic_event_id(
                    current.snapshot_id, "FLOW_POLARITY_FLIP", "NIFTY_FUTURES", supporting
                )
                evt = MarketEvent(
                    event_id=evt_id,
                    session_date=session_date,
                    timestamp_utc=current.timestamp_utc,
                    timestamp_ist=current.timestamp_ist,
                    event_type=MarketEventType.FLOW_POLARITY_FLIP.value,
                    instrument="NIFTY_FUTURES",
                    summary=f"MLOFI order flow shifted polarity from {last.mlofi_5l:+.2f} to {current.mlofi_5l:+.2f}.",
                    supporting_values=supporting,
                    provenance_hash=ProvenanceGuard.compute_sha256(supporting),
                )
                events.append(evt)
            elif current.mlofi_session_extreme is True and last.mlofi_session_extreme is not True:
                supporting = {
                    "mlofi_5l": current.mlofi_5l,
                    "mlofi_session_extreme": True,
                    "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
                }
                evt_id = self._make_deterministic_event_id(
                    current.snapshot_id, "FLOW_AGGRESSION_BURST", "NIFTY_FUTURES", supporting
                )
                evt = MarketEvent(
                    event_id=evt_id,
                    session_date=session_date,
                    timestamp_utc=current.timestamp_utc,
                    timestamp_ist=current.timestamp_ist,
                    event_type=MarketEventType.FLOW_AGGRESSION_BURST.value,
                    instrument="NIFTY_FUTURES",
                    summary=f"MLOFI recorded session extreme aggressor pressure ({current.mlofi_5l:+.2f}).",
                    supporting_values=supporting,
                    provenance_hash=ProvenanceGuard.compute_sha256(supporting),
                )
                events.append(evt)

        # 6. Strike-wise Numerical Closed OI & Structure Evolution
        current_strikes_map = {s["strike"]: s for s in current.strike_ladder if isinstance(s, dict) and s.get("strike") is not None}
        last_strikes_map = {s["strike"]: s for s in last.strike_ladder if isinstance(s, dict) and s.get("strike") is not None}

        for strike, c_s in current_strikes_map.items():
            l_s = last_strikes_map.get(strike)
            if not l_s:
                continue

            for opt_type, sec_key, struct_key, oi_5m_key, oi_15m_key in (
                ("CE", "ce_security_id", "ce_structure", "ce_closed_5m_oi", "ce_closed_15m_oi"),
                ("PE", "pe_security_id", "pe_structure", "pe_closed_5m_oi", "pe_closed_15m_oi"),
            ):
                c_oi5 = c_s.get(oi_5m_key)
                l_oi5 = l_s.get(oi_5m_key)
                c_oi15 = c_s.get(oi_15m_key)
                l_oi15 = l_s.get(oi_15m_key)
                c_struct = c_s.get(struct_key)
                l_struct = l_s.get(struct_key)

                # Numerical Closed 5M / 15M OI Delta (regardless of structure)
                if (c_oi5 is not None and l_oi5 is not None and c_oi5 != l_oi5) or (c_oi15 is not None and l_oi15 is not None and c_oi15 != l_oi15):
                    oi5_diff = (c_oi5 - l_oi5) if (c_oi5 is not None and l_oi5 is not None) else 0
                    supporting = {
                        "strike": strike,
                        "option_type": opt_type,
                        "before_5m_oi": l_oi5,
                        "after_5m_oi": c_oi5,
                        "5m_oi_delta": oi5_diff,
                        "before_15m_oi": l_oi15,
                        "after_15m_oi": c_oi15,
                        "structure": c_struct,
                        "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
                    }
                    evt_id = self._make_deterministic_event_id(
                        current.snapshot_id, "CLOSED_OI_DELTA", f"NIFTY_{strike:.0f}_{opt_type}", supporting
                    )
                    evt = MarketEvent(
                        event_id=evt_id,
                        session_date=session_date,
                        timestamp_utc=current.timestamp_utc,
                        timestamp_ist=current.timestamp_ist,
                        event_type="CLOSED_OI_DELTA",
                        instrument=f"NIFTY_{strike:.0f}_{opt_type}",
                        security_id=c_s.get(sec_key),
                        strike=strike,
                        summary=f"{strike:.0f} {opt_type} closed 5M OI changed by {oi5_diff:+} to {c_oi5} (structure: {c_struct}).",
                        supporting_values=supporting,
                        provenance_hash=ProvenanceGuard.compute_sha256(supporting),
                    )
                    events.append(evt)

                # Separate Structure Classification Transition
                if c_struct and l_struct and c_struct != l_struct:
                    supporting = {
                        "strike": strike,
                        "option_type": opt_type,
                        "before_structure": l_struct,
                        "after_structure": c_struct,
                        "closed_5m_oi": c_oi5,
                        "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
                    }
                    evt_id = self._make_deterministic_event_id(
                        current.snapshot_id, "CLOSED_OI_BUILDUP", f"NIFTY_{strike:.0f}_{opt_type}", supporting
                    )
                    evt = MarketEvent(
                        event_id=evt_id,
                        session_date=session_date,
                        timestamp_utc=current.timestamp_utc,
                        timestamp_ist=current.timestamp_ist,
                        event_type=MarketEventType.CLOSED_OI_BUILDUP.value,
                        instrument=f"NIFTY_{strike:.0f}_{opt_type}",
                        security_id=c_s.get(sec_key),
                        strike=strike,
                        summary=f"{strike:.0f} {opt_type} structure transitioned from {l_struct} to {c_struct}.",
                        supporting_values=supporting,
                        provenance_hash=ProvenanceGuard.compute_sha256(supporting),
                    )
                    events.append(evt)

        # 7. Volatility Surface & Straddle Cost
        if current.atm_straddle_price is not None and last.atm_straddle_price is not None and current.atm_straddle_price != last.atm_straddle_price:
            straddle_delta = current.atm_straddle_price - last.atm_straddle_price
            supporting = {
                "before_straddle": last.atm_straddle_price,
                "after_straddle": current.atm_straddle_price,
                "straddle_delta": straddle_delta,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "STRADDLE_CHANGE", "NIFTY_STRADDLE", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type="STRADDLE_CHANGE",
                instrument="NIFTY_STRADDLE",
                summary=f"ATM Straddle cost shifted {straddle_delta:+.2f} pts from {last.atm_straddle_price:.2f} to {current.atm_straddle_price:.2f} pts.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        if (
            (current.atm_iv is not None and last.atm_iv is not None and current.atm_iv != last.atm_iv)
            or (current.skew_25d is not None and last.skew_25d is not None and current.skew_25d != last.skew_25d)
            or (current.skew_10d is not None and last.skew_10d is not None and current.skew_10d != last.skew_10d)
            or (current.expected_move_pts is not None and last.expected_move_pts is not None and current.expected_move_pts != last.expected_move_pts)
        ):
            supporting = {
                "before_iv": last.atm_iv,
                "after_iv": current.atm_iv,
                "iv_delta": (current.atm_iv - last.atm_iv) if (current.atm_iv is not None and last.atm_iv is not None) else None,
                "skew_25d": current.skew_25d,
                "skew_10d": current.skew_10d,
                "expected_move_pts": current.expected_move_pts,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "VOLATILITY_SURFACE_SHIFT", "NIFTY_VOL_SURFACE", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type="VOLATILITY_SURFACE_SHIFT",
                instrument="NIFTY_VOL_SURFACE",
                summary=f"Volatility surface updated: ATM IV={current.atm_iv}, Skew25d={current.skew_25d}, ExpMove={current.expected_move_pts} pts.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        # 8. Dealer Gamma Exposure Shift
        if current.net_gex_inr is not None and last.net_gex_inr is not None and current.net_gex_inr != last.net_gex_inr:
            gex_delta = current.net_gex_inr - last.net_gex_inr
            supporting = {
                "before_gex": last.net_gex_inr,
                "after_gex": current.net_gex_inr,
                "gex_delta": gex_delta,
                "highest_gex_strike": current.highest_gex_strike,
                "zero_gamma_level": current.zero_gamma_level,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "GEX_SHIFT", "NIFTY_DEALER_GAMMA", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type=MarketEventType.GEX_SHIFT.value,
                instrument="NIFTY_DEALER_GAMMA",
                summary=f"Dealer Net GEX changed by {gex_delta:+,.0f} INR to {current.net_gex_inr:+,.0f} INR.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        # 9. Comprehensive Factual Sensorium Delta (Captures non-specialized changed fields)
        sensorium_diffs: Dict[str, Any] = {}
        for fld in (
            "ce_pricing",
            "pe_pricing",
            "current_flow_x",
        ):
            c_val = getattr(current, fld, None)
            l_val = getattr(last, fld, None)
            if c_val is not None and l_val is not None and c_val != l_val:
                sensorium_diffs[fld] = {"before": l_val, "after": c_val}

        if sensorium_diffs:
            supporting = {
                "diffs": sensorium_diffs,
                "canonical_snapshot_id": current.canonical_snapshot_id,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(current.snapshot_id, "SENSORIUM_DELTA", "NIFTY_SENSORIUM", supporting)
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type="SENSORIUM_DELTA",
                instrument="NIFTY_SENSORIUM",
                summary=f"Factual sensorium state delta in {len(sensorium_diffs)} fields: {', '.join(sensorium_diffs.keys())}.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        # 10. System Status Shift
        if current.system_status != last.system_status:
            supporting = {
                "before_status": last.system_status.value,
                "after_status": current.system_status.value,
                "chronology_mode": "ORDER_SAME_SNAPSHOT_WINDOW",
            }
            evt_id = self._make_deterministic_event_id(
                current.snapshot_id, "DATA_QUALITY_SHIFT", "FEED_HEALTH", supporting
            )
            evt = MarketEvent(
                event_id=evt_id,
                session_date=session_date,
                timestamp_utc=current.timestamp_utc,
                timestamp_ist=current.timestamp_ist,
                event_type=MarketEventType.DATA_QUALITY_SHIFT.value,
                instrument="FEED_HEALTH",
                summary=f"System data status shifted from {last.system_status.value} to {current.system_status.value}.",
                supporting_values=supporting,
                provenance_hash=ProvenanceGuard.compute_sha256(supporting),
            )
            events.append(evt)

        return events

    def build_events(self, current: SolEvidenceSnapshot) -> List[MarketEvent]:
        """Convenience method that compiles events and immediately commits baseline."""
        events = self.compile_events(current)
        self.commit_baseline(current)
        return events
