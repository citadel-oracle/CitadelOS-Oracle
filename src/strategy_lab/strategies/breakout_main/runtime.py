"""Non-scheduled BREAKOUT MAIN runtime interface."""

from .strategy import BreakoutMainStrategyEngine


class BreakoutMainRuntimeInterface:
    def __init__(self, engine=None):
        self.engine = engine or BreakoutMainStrategyEngine()

    @staticmethod
    def _status():
        return {"status": "NOT_IMPLEMENTED", "reason": "NOT_IMPLEMENTED"}

    def status(self):
        return self._status()

    def start(self):
        return self._status()

    def stop(self):
        return self._status()

    def tick(self, context):
        if not context:
            return self._status()
        return self.engine.evaluate(context)

    def serialize(self):
        return self.engine.serialize()

    @classmethod
    def deserialize(cls, payload):
        return cls(BreakoutMainStrategyEngine.deserialize(payload))
