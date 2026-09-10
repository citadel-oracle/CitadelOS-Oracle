from abc import ABC, abstractmethod


class BaseStrategy(ABC):

    @abstractmethod
    def name(self):
        pass

    def config(self):
        return {
            "mode": "INTRADAY",
            "allow_overnight": False,
            "auto_square_off": True,
            "last_entry_time": None,
            "square_off_time": None,
        }

    @abstractmethod
    def generate(self, context):
        pass