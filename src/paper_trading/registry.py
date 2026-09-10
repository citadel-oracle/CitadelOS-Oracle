"""Bounded registry over existing, unchanged production strategies."""

from src.strategies.simple_pullback import SimplePullbackStrategy


class StrategyRegistry:
    MAX_ACTIVE = 2

    def __init__(self, strategies=None):
        values = list(strategies or [SimplePullbackStrategy()])
        if not values or len(values) > self.MAX_ACTIVE:
            raise ValueError("strategy registry must contain one or two strategies")
        names = [item.name() for item in values]
        if len(set(names)) != len(names): raise ValueError("duplicate strategy")
        self._strategies = tuple(values)

    def evaluate(self, context):
        results=[]
        for strategy in self._strategies:
            result=dict(strategy.generate(context)); result["strategy_config"] = strategy.config(); results.append(result)
        actionable=[item for item in results if item.get("signal") in {"BUY","SELL"}]
        return actionable[0] if len(actionable) == 1 else {"signal":"WAIT","confidence":0,"entry":None,"sl":None,"target":None,"reason":"No single eligible strategy signal","strategy":"REGISTRY"}

    def projection(self):
        return {"status":"READY","maximum_strategies":self.MAX_ACTIVE,"active_count":len(self._strategies),"strategies":[{"name":item.name(),"config":item.config(),"source":f"{item.__class__.__module__}.{item.__class__.__name__}","logic_modified":False} for item in self._strategies]}
