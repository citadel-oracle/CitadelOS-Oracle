from src.strategies.simple_pullback import SimplePullbackStrategy


class StrategyManager:

    def __init__(self):
        self.strategy = SimplePullbackStrategy()

    def strategy_name(self):
        return self.strategy.name()

    def strategy_config(self):
        return self.strategy.config()

    def generate(self, context):
        return self.strategy.generate(context)