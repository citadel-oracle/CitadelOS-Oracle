import time as time_module
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.broker.dhan_client import DhanClient
from src.data.data_engine import DataEngine, MarketHistoryUnavailable
from src.market.session_calendar import NSESessionCalendar
from src.scanner.watchlist import WATCHLIST
from src.scanner.indicator_builder import IndicatorBuilder

from src.kronos.kronos_engine import KronosEngine
from src.brain.context_builder import ContextBuilder
from src.strategies.strategy_manager import StrategyManager

from src.structure.structure_engine import StructureEngine
from src.structure.structure_engine_v2 import StructureEngineV2
from src.liquidity.liquidity_engine import LiquidityEngine
from src.fvg.fvg_engine import FVGEngine
from src.orderblock.order_block_engine import OrderBlockEngine
from src.timeframe.timeframe_engine import TimeframeEngine


class MarketScanner:
    HISTORY_BUFFER_CANDLES = 500
    EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        *,
        dhan=None,
        calendar=None,
        clock=None,
        sleeper=None,
    ):
        self.dhan = dhan or DhanClient()
        self.calendar = calendar or NSESessionCalendar()
        self.clock = clock or (lambda: datetime.now(self.EXCHANGE_TIMEZONE))
        self.sleeper = sleeper or time_module.sleep
        self.data_engine = DataEngine(dhan=self.dhan, max_candles=1000)

        self.indicator_builder = IndicatorBuilder()
        self.kronos = KronosEngine()
        self.brain = ContextBuilder()
        self.strategy_manager = StrategyManager()

        self.structure_engine = StructureEngine()
        self.structure_v2_engine = StructureEngineV2()
        self.liquidity_engine = LiquidityEngine()
        self.fvg_engine = FVGEngine()
        self.order_block_engine = OrderBlockEngine()
        self.timeframe_engine = TimeframeEngine()

        self.candles = self.data_engine.cache
        for symbol in WATCHLIST:
            self.candles[symbol] = []
        self.history_loaded = False
        self.history_bootstrapped = False
        self._history_sync_target = None
        self.history_reason = "INSUFFICIENT_FEATURES"
        self.history_metadata = {
            "source": "DHAN_V2_INTRADAY",
            "requested_candles": self.HISTORY_BUFFER_CANDLES,
            "loaded_candles": 0,
            "earliest_candle": None,
            "latest_candle": None,
        }

    def load_history_once(self):
        observed_at = self._aware(self.clock())
        expected_bucket = self.data_engine.bucket_start(
            observed_at, 1
        ) - timedelta(minutes=1)
        expected_epoch = int(expected_bucket.timestamp())
        if (
            self.history_bootstrapped
            and self._history_sync_target == expected_epoch
        ):
            return

        info = WATCHLIST["NIFTY"]
        try:
            from_date = (
                observed_at.date()
                if self.history_bootstrapped
                else self._history_start_date(observed_at.date())
            )
            loaded = self.data_engine.load_completed_history(
                symbol="NIFTY",
                segment=info["segment"],
                security_id=info["security_id"],
                interval="1",
                from_date=from_date.isoformat(),
                to_date=observed_at.date().isoformat(),
                limit=self.HISTORY_BUFFER_CANDLES,
                now=observed_at,
                calendar=self.calendar,
                # Startup/reconnect keeps the required bounded three-attempt
                # bootstrap.  Once warm, a missed minute retries on the next
                # background projection cycle rather than blocking that
                # atomic projection for up to three network timeouts.
                attempts=1 if self.history_bootstrapped else 3,
                sleeper=self.sleeper,
            )
        except MarketHistoryUnavailable:
            self.history_loaded = False
            self.history_reason = "DHAN_HISTORY_UNAVAILABLE"
            return

        completed = self.data_engine.completed_candles(
            "NIFTY", now=observed_at, interval_minutes=1
        )
        completed_ids = {int(item["time"]) for item in completed}
        session = self.calendar.session_for_date(observed_at.date())
        should_have_current_bucket = (
            session.get("session_state") in {"OPEN", "SPECIAL_SESSION"}
            and expected_bucket
            >= self._aware(session["scheduled_open"])
        )
        if should_have_current_bucket and expected_epoch not in completed_ids:
            self.history_loaded = False
            self.history_reason = "DHAN_HISTORY_UNAVAILABLE"
            return

        self.history_bootstrapped = True
        self._history_sync_target = expected_epoch
        self.history_reason = "INSUFFICIENT_FEATURES"
        authoritative = completed[-self.HISTORY_BUFFER_CANDLES:]
        self.history_metadata = {
            "source": "DHAN_V2_INTRADAY",
            "requested_candles": self.HISTORY_BUFFER_CANDLES,
            "loaded_candles": len(authoritative),
            "earliest_candle": (
                self._aware(authoritative[0]["time"]).isoformat()
                if authoritative else None
            ),
            "latest_candle": (
                self._aware(authoritative[-1]["time"]).isoformat()
                if authoritative else None
            ),
        }

    def scan(self):
        self.load_history_once()

        quotes = self.dhan.get_multiple_quotes(WATCHLIST)
        observed_at = self._aware(self.clock())
        rows = []

        for symbol, quote in quotes.items():
            quote_ltp = quote.get("ltp")
            ltp = float(quote_ltp) if quote_ltp is not None else None

            if ltp is not None and ltp > 0:
                self.data_engine.update_live_price(
                    symbol=symbol,
                    price=ltp,
                    timestamp=observed_at,
                    interval_minutes=1,
                )

            candles = self.data_engine.completed_candles(
                symbol,
                now=observed_at,
                interval_minutes=1,
            )

            indicators = self.indicator_builder.build(
                candles,
                session_date=observed_at.date(),
            )
            if symbol == "NIFTY":
                missing = [
                    key
                    for key in (
                        "ema_21",
                        "ema_38",
                        "vwap",
                        "rsi_14",
                        "adx_14",
                        "atr_14",
                    )
                    if indicators.get(key) is None
                ]
                self.history_loaded = (
                    self.history_bootstrapped
                    and len(candles) >= self.HISTORY_BUFFER_CANDLES
                    and not missing
                )
                if self.history_reason != "DHAN_HISTORY_UNAVAILABLE":
                    if (
                        indicators.get("vwap") is None
                        and all(
                            indicators.get(key) is not None
                            for key in (
                                "ema_21",
                                "ema_38",
                                "rsi_14",
                                "adx_14",
                                "atr_14",
                            )
                        )
                    ):
                        self.history_reason = "VOLUME_UNAVAILABLE"
                    else:
                        self.history_reason = (
                            "READY"
                            if self.history_loaded
                            else "INSUFFICIENT_FEATURES"
                        )

            structure = self.structure_engine.analyze(candles)
            structure_v2 = self.structure_v2_engine.analyze(candles)
            liquidity = self.liquidity_engine.analyze(candles)
            fvg = self.fvg_engine.analyze(candles)
            order_block = self.order_block_engine.analyze(candles)
            timeframe = self.timeframe_engine.analyze(candles)

            kronos = self.kronos.analyze(
                indicators=indicators,
                structure=structure,
                liquidity=liquidity,
                fvg=fvg,
                order_block=order_block,
                structure_v2=structure_v2,
                timeframe=timeframe,
            )

            context = self.brain.build(
                symbol=symbol,
                indicators=indicators,
                kronos=kronos,
                structure_v1=structure,
                structure_v2=structure_v2,
                liquidity=liquidity,
                fvg=fvg,
                order_block=order_block,
                timeframe=timeframe,
            )

            signal = self.strategy_manager.generate(context)

            if signal.get("signal") == "BUY":
                direction = "▲"
            elif signal.get("signal") == "SELL":
                direction = "▼"
            else:
                direction = "→"

            rows.append({
                "symbol": symbol,
                "ltp": ltp,
                "previous_close": quote.get("previous_close"),
                "change_percent": quote.get("change_percent"),
                "quote_status": quote.get("updated", "NA"),
                "direction": direction,

                "regime": kronos.regime,
                "bias": kronos.bias,
                "mode": kronos.trade_mode,
                "bull": kronos.bull_probability,
                "bear": kronos.bear_probability,
                "neutral": kronos.neutral_probability,
                "confidence": kronos.confidence,
                "trade": "YES" if kronos.allow_trade else "NO",

                "smart_score": context.smart_score,
                "strategy": self.strategy_manager.strategy_name(),

                "structure": structure_v2.get("structure"),
                "bos": structure_v2.get("bos"),
                "choch": structure_v2.get("choch"),
                "liquidity": liquidity.get("type"),
                "fvg": fvg.get("type"),
                "order_block": order_block.get("type"),
                "mtf_bias": timeframe.get("bias"),

                "pullback_signal": signal.get("signal"),
                "entry": signal.get("entry"),
                "sl": signal.get("sl"),
                "target": signal.get("target"),
                "reason": signal.get("reason"),
                "technical_readiness": {
                    **self.history_metadata,
                    "status": "READY" if self.history_loaded else "NOT_READY",
                    "reason": self.history_reason,
                    "timeframe": "1m",
                    "completed_candle_count": len(candles),
                    "required_candle_count": self.indicator_builder.required_candle_count,
                    "vwap_session_date": (
                        observed_at.astimezone(self.EXCHANGE_TIMEZONE).date().isoformat()
                        if indicators.get("vwap") is not None
                        else None
                    ),
                } if symbol == "NIFTY" else None,
                "context": context,
            })

        return rows

    def _previous_trading_session(self, current_date):
        for offset in range(1, 15):
            candidate = current_date - timedelta(days=offset)
            session = self.calendar.session_for_date(candidate)
            if session.get("session_state") in {"OPEN", "SPECIAL_SESSION"}:
                return candidate
        # Calendar unavailability fails closed instead of guessing a session.
        raise MarketHistoryUnavailable(
            "DHAN_HISTORY_UNAVAILABLE: previous NSE session unavailable"
        )

    def _history_start_date(self, current_date):
        """Return enough real NSE sessions to provide the 500-row audit buffer."""

        sessions = []
        for offset in range(1, 31):
            candidate = current_date - timedelta(days=offset)
            session = self.calendar.session_for_date(candidate)
            if session.get("session_state") in {"OPEN", "SPECIAL_SESSION"}:
                sessions.append(candidate)
                if len(sessions) == 2:
                    return sessions[-1]
        raise MarketHistoryUnavailable(
            "DHAN_HISTORY_UNAVAILABLE: warm-up NSE sessions unavailable"
        )

    @classmethod
    def _aware(cls, value):
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=cls.EXCHANGE_TIMEZONE)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            parsed = value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=cls.EXCHANGE_TIMEZONE)
        return parsed.astimezone(cls.EXCHANGE_TIMEZONE)
