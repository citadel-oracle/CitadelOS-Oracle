from datetime import datetime, time

from src.market.session_calendar import NSESessionCalendar


class SessionManager:
    def __init__(self, calendar=None):
        self.calendar = calendar or NSESessionCalendar()
        self.market_open = time(9, 15)
        self.first_entry = time(9, 20)
        self.default_last_entry = time(15, 15)
        self.default_square_off = time(15, 28)
        self.market_close = time(15, 30)

    def now(self):
        return datetime.now().time()

    def is_market_open(self):
        return self.calendar.status()["market_open"]

    def entry_allowed(self, strategy_config=None):
        if not self.is_market_open():
            return False

        cfg = strategy_config or {}
        mode = cfg.get("mode", "INTRADAY")

        if mode == "POSITIONAL":
            return True

        last_entry = cfg.get("last_entry_time", self.default_last_entry)
        t = self.now()

        return self.first_entry <= t <= last_entry

    def should_square_off(self, strategy_config=None):
        cfg = strategy_config or {}

        if cfg.get("allow_overnight", False):
            return False

        if not cfg.get("auto_square_off", True):
            return False

        square_off = cfg.get("square_off_time", self.default_square_off)

        return self.now() >= square_off

    def status(self, strategy_config=None):
        session = self.calendar.status()
        return {
            "market_open": session["market_open"],
            "entry_allowed": self.entry_allowed(strategy_config),
            "square_off": self.should_square_off(strategy_config),
            "state": session["session_state"],
            "reason": session["reason"],
            "next_valid_open": session["next_valid_open"],
            "calendar_version": session["calendar_version"],
        }
