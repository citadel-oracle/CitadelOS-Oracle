class PositionManager:

    def __init__(self):

        self.position = None

    def open_position(
        self,
        side,
        entry,
        sl,
        target,
    ):

        if self.position is not None:
            return False

        self.position = {

            "side": side,

            "entry": entry,

            "sl": sl,

            "target": target,

            "status": "OPEN",

            "trail": False,

            "breakeven": False,

        }

        return True

    def get_position(self):
        return self.position

    def close(self):

        self.position = None

    def has_position(self):

        return self.position is not None