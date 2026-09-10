def _state(score):
    if score is None:
        return "UNAVAILABLE"
    return "STRONG_ALIGNMENT" if score >= 75 else "MODERATE_ALIGNMENT" if score >= 60 else "WEAK_ALIGNMENT" if score >= 45 else "AVOID"


def forecast_quality(metrics, expected_paths, input_fresh=True, model_ready=True, inference_complete=True):
    if not metrics or not metrics.get("valid_path_count"):
        return None
    agreement = max(metrics["bullish_probability"], metrics["bearish_probability"], metrics["sideways_probability"])
    coverage = min(100, metrics["valid_path_count"] * 100 / max(1, expected_paths))
    inverse_uncertainty = max(0, 100 - metrics["forecast_uncertainty"])
    return round(0.35 * agreement + 0.25 * inverse_uncertainty + 0.20 * coverage + 0.10 * (100 if input_fresh else 0) + 0.05 * (100 if model_ready else 0) + 0.05 * (100 if inference_complete else 0), 2)


def option_outlooks(metrics, quality, input_fresh=True):
    required = ("bullish_probability", "bearish_probability", "sideways_probability", "forecast_volatility", "forecast_uncertainty")
    if not metrics or quality is None or any(metrics.get(key) is None for key in required):
        return {"ce": _unavailable("CE"), "pe": _unavailable("PE"), "forecast_quality_score": None}
    volatility = metrics["forecast_volatility"]
    volatility_suitability = max(0, min(100, volatility / 0.60 * 100))
    uncertainty_inverse = max(0, 100 - metrics["forecast_uncertainty"])

    def build(side):
        bullish = side == "CE"
        probability = metrics["bullish_probability" if bullish else "bearish_probability"]
        persistence = metrics["bullish_persistence_probability" if bullish else "bearish_persistence_probability"]
        reversal = metrics["bullish_reversal_probability" if bullish else "bearish_reversal_probability"]
        if persistence is None or reversal is None:
            return _unavailable(side)
        input_model_quality = 100 if input_fresh and quality is not None else 0
        score = round(0.35 * probability + 0.25 * persistence + 0.15 * volatility_suitability + 0.10 * (100 - reversal) + 0.10 * uncertainty_inverse + 0.05 * input_model_quality, 2)
        if not input_fresh:
            return {**_unavailable(side), "warnings": ["INPUT_NOT_FRESH"]}
        return {
            "side": side,
            "option_buying_quality_score": max(0, min(100, score)),
            "recommendation_state": _state(score),
            "directional_probability": probability,
            "persistence_probability": persistence,
            "reversal_risk": reversal,
            "sideways_probability": metrics["sideways_probability"],
            "opposite_probability": metrics["bearish_probability" if bullish else "bullish_probability"],
            "volatility_suitability": volatility_suitability,
            "forecast_volatility": volatility,
            "uncertainty": metrics["forecast_uncertainty"],
            "expected_favorable_move": max(0, metrics["upside_quantile"] if bullish else -metrics["downside_quantile"]),
            "expected_adverse_move": max(0, -metrics["downside_quantile"] if bullish else metrics["upside_quantile"]),
            "label": "OPTION_BUYING_QUALITY",
            "warnings": [],
        }

    return {"ce": build("CE"), "pe": build("PE"), "forecast_quality_score": quality}


def _unavailable(side):
    return {
        "side": side,
        "option_buying_quality_score": None,
        "recommendation_state": "UNAVAILABLE",
        "directional_probability": None,
        "persistence_probability": None,
        "reversal_risk": None,
        "sideways_probability": None,
        "opposite_probability": None,
        "volatility_suitability": None,
        "forecast_volatility": None,
        "uncertainty": None,
        "expected_favorable_move": None,
        "expected_adverse_move": None,
        "label": "OPTION_BUYING_QUALITY",
        "warnings": ["FORECAST_UNAVAILABLE"],
    }
