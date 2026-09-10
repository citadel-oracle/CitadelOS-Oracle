"""
CitadelOS Risk Engine
Risk validation for paper mode with Kronos filter.
"""


class RiskEngine:
    def __init__(self):
        self.min_confidence_required = 60

    def validate(self, signal, kronos=None):
        if signal.get("signal") == "NO TRADE":
            return {
                "approved": False,
                "reason": "No valid trade signal",
                "signal": signal,
                "kronos": kronos,
            }

        if signal.get("confidence", 0) < self.min_confidence_required:
            return {
                "approved": False,
                "reason": "Signal confidence below required threshold",
                "signal": signal,
                "kronos": kronos,
            }

        if kronos and kronos.get("allow_trade") is False:
            return {
                "approved": False,
                "reason": f"Kronos blocked trade: {kronos.get('reason')}",
                "signal": signal,
                "kronos": kronos,
            }

        return {
            "approved": True,
            "reason": "Risk + Kronos check passed",
            "signal": signal,
            "kronos": kronos,
        }


def print_risk(risk):
    print("\n🛡️ Risk Check")
    print(f"Approved : {risk.get('approved')}")
    print(f"Reason   : {risk.get('reason')}")