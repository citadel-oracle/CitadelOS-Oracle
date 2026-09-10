"""Paper execution backed by the single authoritative paper-state service."""

from time import time_ns

from src.execution.paper_state import PaperStateError, PaperStateService
from src.execution.trade_journal import TradeJournal
from src.oracle.feature_logger import OracleFeatureLogger
from src.oracle_personal import PersonalOracleService
from src.risk.trade_manager import TradeManager


class PaperExecution:
    """Compatibility facade; persisted truth belongs only to PaperStateService."""

    def __init__(self, paper_state=None, journal=None, oracle=None, personal_oracle=None):
        self.paper_state = paper_state or PaperStateService()
        self.manager = TradeManager()
        self.journal = journal or TradeJournal("logs/paper_trades.csv")
        self.oracle = oracle or OracleFeatureLogger("logs/oracle_features.csv")
        self.personal_oracle = personal_oracle or PersonalOracleService(
            paper_state=self.paper_state
        )
        self.last_closed_trade_id = None
        self.trade_contexts = {}
        self.state_error = None
        self._restore_projection()

    def _restore_projection(self):
        try:
            state = self.paper_state.load()
        except PaperStateError as error:
            self.state_error = str(error)
            self.manager.active_trade = None
            return

        self.state_error = None
        if not state.open_positions:
            self.manager.active_trade = None
            return

        position = state.open_positions[0]
        trade = self._position_to_trade(position)
        self.manager.active_trade = trade
        try:
            self.manager.trade_id = max(
                int(self.manager.trade_id), int(position.position_id)
            )
        except (TypeError, ValueError):
            pass

    def process_signal(self, signal, symbol="NIFTY", context=None):
        try:
            state = self.paper_state.load()
        except PaperStateError as error:
            self.state_error = str(error)
            return {
                "executed": False,
                "reason": "Authoritative paper state unavailable",
                "trade": None,
            }

        if state.open_positions:
            trade = self._position_to_trade(state.open_positions[0])
            self.manager.active_trade = trade
            return {
                "executed": False,
                "reason": "Trade already active",
                "trade": trade,
            }
        if signal.get("signal") not in ["BUY", "SELL"]:
            return {
                "executed": False,
                "reason": "No executable signal",
                "trade": None,
            }

        result = self.manager.open_trade(signal, symbol=symbol)
        trade = result.get("trade")
        if not result.get("opened") or not trade:
            return {
                "executed": False,
                "reason": result.get("reason"),
                "trade": trade,
            }

        metadata = context if isinstance(context, dict) else {}
        position_id = str(trade["trade_id"])
        request_id = str(metadata.get("request_id") or f"paper-open-{position_id}")
        event_id = str(metadata.get("event_id") or request_id)
        raw_quantity = signal.get("quantity", 1)

        try:
            position = self.paper_state.open_position(
                position_id=position_id,
                request_id=request_id,
                event_id=event_id,
                symbol=symbol,
                side=trade["side"],
                raw_quantity=raw_quantity,
                entry_price=trade["entry"],
                instrument_id=metadata.get("instrument_id"),
                lot_size=metadata.get("lot_size"),
                option_type=metadata.get("option_type"),
                strike=metadata.get("strike"),
                expiry=metadata.get("expiry"),
                stop_price=trade.get("sl"),
                target_price=trade.get("target"),
                confidence=trade.get("confidence"),
                reason=trade.get("reason", ""),
            )
        except PaperStateError as error:
            self.manager.active_trade = None
            self.state_error = str(error)
            return {"executed": False, "reason": str(error), "trade": None}

        authoritative_trade = self._position_to_trade(position)
        self.manager.active_trade = authoritative_trade
        self.journal.log_trade("OPEN", authoritative_trade)
        if context is not None:
            self.trade_contexts[position_id] = context
        return {
            "executed": True,
            "reason": "Trade opened",
            "trade": authoritative_trade,
        }

    def update_trade(self, ltp):
        position = self._active_position()
        if position is None:
            return {"status": "NO_TRADE", "trade": None}

        self.manager.active_trade = self._position_to_trade(position)
        result = self.manager.update(ltp)
        trade = result.get("trade")
        if not trade:
            return result

        if trade.get("status") == "OPEN":
            try:
                updated = self.paper_state.update_mark(
                    position.position_id,
                    ltp,
                    self._event_id("mark", position.position_id),
                    stop_price=trade.get("sl"),
                    break_even_done=trade.get("break_even_done"),
                    trailing_active=trade.get("trailing_active"),
                )
            except PaperStateError as error:
                self.state_error = str(error)
                return {"status": "ERROR", "reason": str(error), "trade": None}
            authoritative = self._position_to_trade(updated)
            self.manager.active_trade = authoritative
            return {"status": "OPEN", "trade": authoritative}

        try:
            closed = self.paper_state.close_position(
                position.position_id,
                ltp,
                self._event_id("close", position.position_id),
                exit_reason=trade.get("exit_reason", ""),
            )
        except PaperStateError as error:
            self.state_error = str(error)
            return {"status": "ERROR", "reason": str(error), "trade": None}
        closed_trade = self._closed_to_trade(closed, trade)
        self._capture_personal_oracle(closed)
        self._finalize_closed_trade(closed_trade)
        self.manager.active_trade = None
        return {"status": "CLOSED", "trade": closed_trade}

    def close_active_trade(self, reason="MANUAL EXIT"):
        position = self._active_position()
        if position is None:
            return {"closed": False, "reason": "No active trade", "trade": None}
        try:
            closed = self.paper_state.close_position(
                position.position_id,
                position.mark_price,
                self._event_id("manual-close", position.position_id),
                exit_reason=reason,
            )
        except PaperStateError as error:
            self.state_error = str(error)
            return {"closed": False, "reason": str(error), "trade": None}
        trade = self._closed_to_trade(closed)
        self._capture_personal_oracle(closed)
        self._finalize_closed_trade(trade)
        self.manager.active_trade = None
        return {"closed": True, "reason": reason, "trade": trade}

    def _finalize_closed_trade(self, trade):
        trade_id = trade.get("trade_id")
        if trade_id != self.last_closed_trade_id:
            self.journal.log_trade("CLOSE", trade)
            context = self.trade_contexts.get(str(trade_id))
            if context is not None:
                self.oracle.log_trade(trade, context)
            self.last_closed_trade_id = trade_id

    def _capture_personal_oracle(self, closed):
        """A failed intelligence append must never affect paper execution."""
        try:
            context = self.trade_contexts.get(str(closed.position_id))
            self.personal_oracle.capture_closed_trade(
                closed.to_dict(), entry_context=context
            )
        except Exception:
            return

    def has_active_trade(self):
        return self._active_position() is not None

    def get_active_trade(self):
        position = self._active_position()
        return self._position_to_trade(position) if position else None

    def journal_summary(self):
        try:
            return self.paper_state.journal_summary()
        except PaperStateError:
            return {"total_closed": 0, "wins": 0, "losses": 0, "net_points": 0}

    def recent_trades(self, limit=5):
        try:
            return self.paper_state.recent_closed_trades(limit)
        except PaperStateError:
            return []

    def _active_position(self):
        try:
            state = self.paper_state.load()
        except PaperStateError as error:
            self.state_error = str(error)
            return None
        self.state_error = None
        return state.open_positions[0] if state.open_positions else None

    @staticmethod
    def _position_to_trade(position):
        risk = (
            abs(position.entry_price - position.initial_stop_price)
            if position.initial_stop_price is not None
            else 0
        )
        pnl_points = (
            position.mark_price - position.entry_price
            if position.side in {"BUY", "LONG"}
            else position.entry_price - position.mark_price
        )
        return {
            "trade_id": position.position_id,
            "symbol": position.symbol,
            "side": "BUY" if position.side in {"BUY", "LONG"} else "SELL",
            "entry": position.entry_price,
            "sl": position.stop_price,
            "initial_sl": position.initial_stop_price,
            "target": position.target_price,
            "confidence": position.confidence,
            "reason": position.reason,
            "status": "OPEN",
            "ltp": position.mark_price,
            "quantity": position.remaining_quantity,
            "raw_quantity": position.raw_quantity,
            "lot_size": position.lot_size,
            "number_of_lots": position.number_of_lots,
            "instrument_id": position.instrument_id,
            "option_type": position.option_type,
            "strike": position.strike,
            "expiry": position.expiry,
            "pnl_points": round(pnl_points, 2),
            "unrealized_pnl": position.unrealized_pnl,
            "r_multiple": round(pnl_points / risk, 2) if risk > 0 else 0.0,
            "break_even_done": position.break_even_done,
            "trailing_active": position.trailing_active,
            "exit_reason": None,
            "opened_at": position.opened_at,
            "closed_at": None,
        }

    @staticmethod
    def _closed_to_trade(closed, prior=None):
        prior = prior or {}
        return {
            "trade_id": closed.position_id,
            "symbol": closed.symbol,
            "side": "BUY" if closed.side in {"BUY", "LONG"} else "SELL",
            "entry": closed.entry_price,
            "ltp": closed.exit_price,
            "sl": prior.get("sl"),
            "target": prior.get("target"),
            "quantity": closed.closed_quantity,
            "pnl_points": closed.realized_pnl,
            "realized_pnl": closed.realized_pnl,
            "r_multiple": prior.get("r_multiple", 0.0),
            "status": "CLOSED",
            "exit_reason": closed.exit_reason,
            "confidence": prior.get("confidence"),
            "reason": prior.get("reason", ""),
            "opened_at": closed.opened_at,
            "closed_at": closed.closed_at,
        }

    @staticmethod
    def _event_id(kind, position_id):
        return f"paper-{kind}-{position_id}-{time_ns()}"
