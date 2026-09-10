"""
Layered Stop-Loss Engine for CITADEL.

GOVERNANCE:
  default_noise_floor     — UNVALIDATED_DEFAULT (5.0 pts)  → telemetry only, no hard veto
  default_atr_multiplier  — UNVALIDATED_DEFAULT (0.5)      → telemetry only, no hard veto
  default_max_risk_pct    — UNVALIDATED_DEFAULT (2%)       → telemetry only, no hard veto

LOCKED hard-veto conditions (always enforced):
  - non-positive entry price
  - missing/None/zero structural_price (LOCKED gate: trade has no defined invalidation)
  - invalid side

UNVALIDATED gates never set skip_reason. They record WOULD_SKIP_IF_ENFORCED in details.
"""

from __future__ import annotations
from typing import Optional, Tuple
from src.risk_engine.contracts import SkipReason


class LayeredStopEngine:
    def __init__(
        self,
        default_noise_floor: float = 5.0,      # UNVALIDATED_DEFAULT
        default_atr_multiplier: float = 0.5,   # UNVALIDATED_DEFAULT
        default_max_risk_pct: float = 0.02,    # UNVALIDATED_DEFAULT — 2% cap, telemetry only
    ):
        self.default_noise_floor = default_noise_floor
        self.default_atr_multiplier = default_atr_multiplier
        self.default_max_risk_pct = default_max_risk_pct

    def compute_layered_stop(
        self,
        entry_price: float,
        side: str,
        structural_price: Optional[float],
        atr: Optional[float] = None,
        spread: float = 0.0,
        noise_floor: Optional[float] = None,
        max_risk_cap: Optional[float] = None,
    ) -> Tuple[float, SkipReason, str]:
        """
        Calculates layered stop-loss price.

        LOCKED hard-veto: entry <= 0, missing structural price, invalid side.
        UNVALIDATED checks: noise floor, ATR buffer, risk cap — these append a
          WOULD_SKIP_IF_ENFORCED tag to `details` but never set a non-NONE skip_reason.

        Returns: (effective_stop, skip_reason, details)
        """
        # ── LOCKED: non-positive entry is structurally invalid ────────────────
        if entry_price <= 0:
            return 0.0, SkipReason.STOP_UNCALCULABLE, "Invalid non-positive entry price"

        # ── LOCKED: missing structural invalidation ───────────────────────────
        if structural_price is None or structural_price <= 0:
            return 0.0, SkipReason.MISSING_STRUCTURAL_INVALIDATION, (
                "Missing or invalid structural invalidation price"
            )

        # ── UNVALIDATED parameters (telemetry only) ───────────────────────────
        noise = noise_floor if noise_floor is not None else self.default_noise_floor
        # spread gate disabled: spread is always passed as 0.0 from service; noise alone used
        min_distance = noise
        max_cap = (
            max_risk_cap if max_risk_cap is not None
            else (entry_price * self.default_max_risk_pct)
        )

        # 1. Compute ATR volatility buffer (UNVALIDATED_DEFAULT — 0 when atr is None)
        vol_buffer = (atr * self.default_atr_multiplier) if (atr and atr > 0) else 0.0

        would_skip_tags = []

        if side.upper() == "LONG":
            raw_stop = structural_price - vol_buffer
            raw_distance = entry_price - raw_stop

            # Apply noise floor (UNVALIDATED_DEFAULT — adjust stop, no hard veto)
            if raw_distance < min_distance:
                effective_stop = entry_price - min_distance
                would_skip_tags.append(
                    f"NOISE_FLOOR_ADJUSTED(distance={raw_distance:.2f}<floor={min_distance:.2f})"
                )
            else:
                effective_stop = raw_stop

            effective_distance = entry_price - effective_stop

            # Risk cap check — UNVALIDATED_DEFAULT: record telemetry, do NOT hard-veto
            if effective_distance > max_cap:
                would_skip_tags.append(
                    f"WOULD_SKIP_IF_ENFORCED(STOP_EXCEEDS_RISK_CAP "
                    f"distance={effective_distance:.2f} cap={max_cap:.2f} "
                    f"governance=UNVALIDATED_DEFAULT)"
                )

            tags = " | ".join(would_skip_tags)
            detail = f"Valid structural stop calculated" + (f" | {tags}" if tags else "")
            return effective_stop, SkipReason.NONE, detail

        elif side.upper() == "SHORT":
            raw_stop = structural_price + vol_buffer
            raw_distance = raw_stop - entry_price

            if raw_distance < min_distance:
                effective_stop = entry_price + min_distance
                would_skip_tags.append(
                    f"NOISE_FLOOR_ADJUSTED(distance={raw_distance:.2f}<floor={min_distance:.2f})"
                )
            else:
                effective_stop = raw_stop

            effective_distance = effective_stop - entry_price

            if effective_distance > max_cap:
                would_skip_tags.append(
                    f"WOULD_SKIP_IF_ENFORCED(STOP_EXCEEDS_RISK_CAP "
                    f"distance={effective_distance:.2f} cap={max_cap:.2f} "
                    f"governance=UNVALIDATED_DEFAULT)"
                )

            tags = " | ".join(would_skip_tags)
            detail = f"Valid structural stop calculated" + (f" | {tags}" if tags else "")
            return effective_stop, SkipReason.NONE, detail

        else:
            return 0.0, SkipReason.STOP_UNCALCULABLE, f"Invalid trade side: {side}"
