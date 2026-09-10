"""
CitadelOS Score Engine V1
Creates opportunity score from trend and quote quality.
"""


class ScoreEngine:

    def score(self, quote, trend_result):
        score = 0

        ltp = float(quote.get("ltp", 0))
        updated = quote.get("updated")

        if updated == "LIVE" and ltp > 0:
            score += 30

        strength = int(trend_result.get("strength", 0))
        score += int(strength * 0.7)

        signal = trend_result.get("signal")

        if signal in ["BUY", "SELL"]:
            score += 10

        score = max(0, min(score, 100))

        return {
            "opportunity_score": score,
            "market_mode": "ACTIVE" if updated == "LIVE" and ltp > 0 else "WAIT",
        }