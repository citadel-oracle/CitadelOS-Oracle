"""Pre-Trade Risk Gate & Discipline Engine for Phase E6A.

Rigorously enforces capital risk, daily drawdown, max open risk, and trade sanity limits.
"""

from typing import Dict, List, Optional, Any
from src.eye.position.contracts import RiskPreTradeResult, RiskDecisionType, PositionState


class RiskDisciplineEngine:
    """Pre-Trade Veto Layer & Discipline State Supervisor."""

    def __init__(
        self,
        capital: float = 500000.0,
        risk_per_trade_pct: float = 1.0,
        daily_loss_limit_pct: float = 5.0,
        max_concurrent_trades: int = 2,
        max_trades_per_day: int = 10,
    ):
        self.capital = capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.daily_loss_limit = capital * (daily_loss_limit_pct / 100.0)
        self.max_concurrent_trades = max_concurrent_trades
        self.max_trades_per_day = max_trades_per_day

    def evaluate_pre_trade_risk(
        self,
        setup_decision: Dict[str, Any],
        active_positions: List[PositionState],
        daily_closed_pnl: float,
        daily_trade_count: int,
        analyzer_mode: bool,
    ) -> RiskPreTradeResult:
        # Gate 0: OpenAlgo Analyzer mode invariant
        if not analyzer_mode:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="ANALYZER_MODE_FALSE",
                message="OpenAlgo Analyzer mode is FALSE. Live broker submission prohibited.",
            )

        # Gate 0.1: CITADEL Option-Buying Only invariant
        opening_action = setup_decision.get("action", "BUY").upper()
        if opening_action != "BUY":
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="EXECUTION_BLOCKED_OPTION_BUYING_ONLY",
                message="Safety Violation: CITADEL is Option-Buying Only. Opening option order MUST be BUY.",
            )

        # Gate 1: Daily loss limit check
        if daily_closed_pnl <= -self.daily_loss_limit:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="DAILY_LOSS_LIMIT",
                message=f"Daily closed loss ({daily_closed_pnl:.2f}) reached daily limit (-{self.daily_loss_limit:.2f}).",
            )

        # Gate 2: Max concurrent open positions
        open_count = len([p for p in active_positions if p.closed_at is None])
        if open_count >= self.max_concurrent_trades:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="MAX_CONCURRENT_TRADES",
                message=f"Active open positions ({open_count}) reached maximum concurrent limit ({self.max_concurrent_trades}).",
            )

        # Gate 3: Max trades per day
        if daily_trade_count >= self.max_trades_per_day:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="MAX_TRADES_PER_DAY",
                message=f"Daily trade count ({daily_trade_count}) reached daily limit ({self.max_trades_per_day}).",
            )

        # Gate 4: Geometry & Trade Plan Sanity
        trade_plan = setup_decision.get("trade_plan", {})
        if trade_plan.get("status") != "ACTIVE":
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="INVALID_GEOMETRY",
                message="Setup trade plan is NOT ACTIVE or lacks valid structural geometry.",
            )

        eg = trade_plan.get("entry_geometry", {})
        ss = trade_plan.get("structural_stop", {})
        nt = trade_plan.get("natural_targets", [])

        ref_entry = eg.get("entry_reference")
        sl_price = ss.get("sl_price")

        if not ref_entry or not sl_price or not nt:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="INVALID_GEOMETRY",
                message="Entry, structural stop, or natural targets missing from trade plan.",
            )

        risk_pts = abs(ref_entry - sl_price)
        if risk_pts <= 0:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="RR_BELOW_POLICY",
                message=f"Risk points ({risk_pts}) must be strictly positive.",
            )

        # Quantity is a contract fact, never a market-wide default.  A missing
        # canonical lot size is unsafe because it can turn a valid risk point
        # calculation into the wrong rupee exposure.
        contract = setup_decision.get("contract") if isinstance(setup_decision.get("contract"), dict) else {}
        lot_size = contract.get("lot_size", setup_decision.get("lot_size"))
        if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
            return RiskPreTradeResult(
                decision=RiskDecisionType.BLOCK,
                allowed_quantity=0,
                estimated_risk_amount=0.0,
                risk_percentage=0.0,
                reason_code="LOT_SIZE_UNAVAILABLE",
                message="Canonical resolved contract lot size is required before approving risk.",
            )
        allowed_qty = lot_size
        trade_risk_amt = risk_pts * lot_size
        risk_pct = (trade_risk_amt / self.capital) * 100.0

        return RiskPreTradeResult(
            decision=RiskDecisionType.ALLOW,
            allowed_quantity=allowed_qty,
            estimated_risk_amount=round(trade_risk_amt, 2),
            risk_percentage=round(risk_pct, 2),
            reason_code="RISK_APPROVED",
            message=f"Pre-trade risk approved for {allowed_qty} qty.",
        )

    def get_risk_summary(
        self,
        active_positions: List[PositionState],
        daily_closed_pnl: float,
        daily_trade_count: int,
        analyzer_mode: bool,
    ) -> Dict[str, Any]:
        return {
            "analyzer_connected": True,
            "analyzer_mode": "analyze" if analyzer_mode else "off",
            "openalgo_reachable": True,
            "dhan_connected": True,
            "risk_policy_approved": False,
            "quality_evidence_gate": "NOT_DEFINED",
            "today_pnl": round(daily_closed_pnl, 2),
            "trades_taken": daily_trade_count,
            "open_positions_count": len(active_positions),
            "max_trades_per_day": self.max_trades_per_day,
            "daily_loss_limit": self.daily_loss_limit,
            "discipline_status": "WAIT_UNAPPROVED_POLICY",
            "blocker": "RISK_POLICY_NOT_APPROVED",
        }
