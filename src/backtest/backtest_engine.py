from src.scanner.indicator_builder import IndicatorBuilder
from src.kronos.kronos_engine import KronosEngine
from src.brain.context_builder import ContextBuilder
from src.strategies.strategy_manager import StrategyManager
from src.risk.trade_manager import TradeManager

from src.structure.structure_engine import StructureEngine
from src.structure.structure_engine_v2 import StructureEngineV2
from src.liquidity.liquidity_engine import LiquidityEngine
from src.fvg.fvg_engine import FVGEngine
from src.orderblock.order_block_engine import OrderBlockEngine
from src.timeframe.timeframe_engine import TimeframeEngine


class BacktestEngine:

    def __init__(self):
        self.indicators = IndicatorBuilder()
        self.kronos = KronosEngine()
        self.brain = ContextBuilder()
        self.strategy = StrategyManager()
        self.trade_manager = TradeManager()

        self.structure_v1 = StructureEngine()
        self.structure_v2 = StructureEngineV2()
        self.liquidity = LiquidityEngine()
        self.fvg = FVGEngine()
        self.order_block = OrderBlockEngine()
        self.timeframe = TimeframeEngine()

    def run(self, symbol, candles, start_index=100):
        trades = []

        for i in range(start_index, len(candles)):
            window = candles[:i + 1]
            latest = candles[i]

            indicators = self.indicators.build(window)

            structure_v1 = self.structure_v1.analyze(window)
            structure_v2 = self.structure_v2.analyze(window)
            liquidity = self.liquidity.analyze(window)
            fvg = self.fvg.analyze(window)
            order_block = self.order_block.analyze(window)
            timeframe = self.timeframe.analyze(window)

            kronos = self.kronos.analyze(
                indicators=indicators,
                structure=structure_v1,
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
                structure_v1=structure_v1,
                structure_v2=structure_v2,
                liquidity=liquidity,
                fvg=fvg,
                order_block=order_block,
                timeframe=timeframe,
            )

            if self.trade_manager.has_active_trade():
                result = self.trade_manager.update(latest["close"])

                if result.get("trade") and result["trade"].get("status") == "CLOSED":
                    trades.append(result["trade"])

                continue

            signal = self.strategy.generate(context)

            if signal.get("signal") in ["BUY", "SELL"]:
                self.trade_manager.open_trade(signal, symbol=symbol)

        return self._summary(trades)

    def _summary(self, trades):
        total = len(trades)
        wins = len([t for t in trades if t.get("pnl_points", 0) > 0])
        losses = len([t for t in trades if t.get("pnl_points", 0) < 0])
        net_points = round(sum(t.get("pnl_points", 0) for t in trades), 2)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total) * 100, 2) if total else 0,
            "net_points": net_points,
            "trades": trades,
        }