class KronosProbability:

    def calculate(self, scores):

        bull = scores.bull_score
        bear = scores.bear_score
        neutral = scores.neutral_score

        total = bull + bear + neutral

        if total <= 0:

            return {

                "bull_probability": 0,

                "bear_probability": 0,

                "neutral_probability": 100,

            }

        bull_probability = round((bull / total) * 100)

        bear_probability = round((bear / total) * 100)

        neutral_probability = max(
            0,
            100 - bull_probability - bear_probability,
        )

        return {

            "bull_probability": bull_probability,

            "bear_probability": bear_probability,

            "neutral_probability": neutral_probability,

        }