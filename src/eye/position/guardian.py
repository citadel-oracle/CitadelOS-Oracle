"""Guardian Engine for Phase E6A.

Continuously monitors active OpenAlgo Analyzer sandbox positions against real canonical underlying
and option market data feeds, triggering deterministic SL, Target, Invalidation, and Session Exits.
"""

from typing import Dict, List, Optional, Any
from src.eye.position.contracts import PositionState, GuardianState
from src.eye.position.supervisor import PositionSupervisor


class GuardianEngine:
    """Active Position Guardian and Trade Management Engine."""

    def __init__(self, supervisor: PositionSupervisor):
        self.supervisor = supervisor

    def evaluate_active_positions(
        self,
        current_underlying_bar: Dict[str, Any],
        current_option_bar: Optional[Dict[str, Any]],
        timestamp_str: str,
    ) -> List[PositionState]:
        closed_positions = []
        u_low = float(current_underlying_bar.get("low", 0.0))
        u_high = float(current_underlying_bar.get("high", 0.0))
        u_close = float(current_underlying_bar.get("close", 0.0))

        opt_close = float(current_option_bar.get("close")) if (current_option_bar and isinstance(current_option_bar, dict) and current_option_bar.get("close") is not None) else (current_option_bar[4] if (current_option_bar and isinstance(current_option_bar, (list, tuple)) and len(current_option_bar) > 4) else u_close)

        for pos in self.supervisor.get_active_positions():
            pos.current_underlying = u_close
            pos.current_premium = opt_close

            # Update MFE and MAE for option buying (always BUY to open)
            pnl_pts = opt_close - pos.actual_fill

            pos.unrealized_pnl = round(pnl_pts * pos.quantity, 2)
            pos.current_r = round(pnl_pts / pos.initial_risk_points, 2) if pos.initial_risk_points > 0 else 0.0
            pos.mfe = max(pos.mfe, pos.current_r)
            pos.mae = min(pos.mae, pos.current_r)

            # 1. Session End Exit (15:15 IST)
            if "15:15" <= timestamp_str[-8:-3] <= "15:30":
                pos.guardian_state = GuardianState.EXIT_PENDING
                closed = self.supervisor.close_analyzer_position(
                    position_id=pos.position_id,
                    close_price=opt_close,
                    timestamp_str=timestamp_str,
                    exit_reason="SESSION_EXIT",
                )
                if closed: closed_positions.append(closed)
                continue

            # 2. Check Target 1 Hit (CE: underlying rises to T1; PE: underlying falls to T1)
            hit_target = False
            if pos.option_type == "CE" and u_high >= pos.t1:
                hit_target = True
            elif pos.option_type == "PE" and u_low <= pos.t1:
                hit_target = True

            # 3. Check Structural SL Hit (CE: underlying falls to SL; PE: underlying rises to SL)
            hit_sl = False
            if pos.option_type == "CE" and u_low <= pos.structural_sl:
                hit_sl = True
            elif pos.option_type == "PE" and u_high >= pos.structural_sl:
                hit_sl = True

            if hit_target and hit_sl:
                # Intrabar ambiguity exit
                pos.guardian_state = GuardianState.EXIT_PENDING
                closed = self.supervisor.close_analyzer_position(
                    position_id=pos.position_id,
                    close_price=opt_close,
                    timestamp_str=timestamp_str,
                    exit_reason="STRUCTURAL_INVALIDATION",
                )
                if closed: closed_positions.append(closed)
            elif hit_target:
                pos.guardian_state = GuardianState.TARGET_PROGRESS
                closed = self.supervisor.close_analyzer_position(
                    position_id=pos.position_id,
                    close_price=opt_close,
                    timestamp_str=timestamp_str,
                    exit_reason="TARGET_T1",
                )
                if closed: closed_positions.append(closed)
            elif hit_sl:
                pos.guardian_state = GuardianState.EXIT_PENDING
                closed = self.supervisor.close_analyzer_position(
                    position_id=pos.position_id,
                    close_price=opt_close,
                    timestamp_str=timestamp_str,
                    exit_reason="STRUCTURAL_SL",
                )
                if closed: closed_positions.append(closed)
            else:
                pos.guardian_state = GuardianState.PROTECTING

        return closed_positions
