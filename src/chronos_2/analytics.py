from __future__ import annotations

import math


QUALITY_WEIGHTS = {"direction": 25, "persistence": 20, "move": 15, "reversal": 10, "uncertainty": 10, "argus": 10, "liquidity": 10}


def derive_analytics(forecast, *, origin, recent_volatility, argus=None):
    rows = forecast.get("forecast_rows") if isinstance(forecast, dict) else None
    if not rows or recent_volatility is None or recent_volatility <= 0:
        return unavailable_analytics("MANDATORY_FORECAST_EVIDENCE_MISSING")
    p50 = [float(row["p50"]) for row in rows]
    terminal = p50[-1] - origin
    above = sum(value > origin for value in p50) / len(p50)
    below = sum(value < origin for value in p50) / len(p50)
    changes = [p50[index] - (origin if index == 0 else p50[index - 1]) for index in range(len(p50))]
    positive_steps = sum(value > 0 for value in changes) / len(changes)
    negative_steps = sum(value < 0 for value in changes) / len(changes)
    sign_changes = sum(changes[index] * changes[index - 1] < 0 for index in range(1, len(changes))) / max(1, len(changes) - 1)
    interval_width = max(row["p90"] for row in rows) - min(row["p10"] for row in rows)
    dispersion_ratio = interval_width / max(recent_volatility * math.sqrt(len(rows)), 1e-9)
    uncertainty_score = _bounded(25 * dispersion_ratio)
    uncertainty = "LOW" if uncertainty_score < 30 else "MEDIUM" if uncertainty_score < 55 else "HIGH" if uncertainty_score < 80 else "EXTREME"
    normalized_move = abs(terminal) / recent_volatility
    threshold = max(origin * 0.0005, recent_volatility * 0.25)
    dominant = max(above, below)
    bias = "SIDEWAYS" if abs(terminal) < threshold else "MIXED" if dominant < 0.58 else "BULLISH" if terminal > 0 else "BEARISH"
    direction_consistency = above if terminal > 0 else below
    step_consistency = positive_steps if terminal > 0 else negative_steps
    interval_agreement = sum((row["p25"] > origin if terminal > 0 else row["p75"] < origin) for row in rows) / len(rows)
    confidence_components = {
        "path_direction": 100 * direction_consistency,
        "step_direction": 100 * step_consistency,
        "normalized_terminal_move": min(100.0, normalized_move * 35),
        "quantile_agreement": 100 * interval_agreement,
        "path_persistence": 100 * (1 - sign_changes),
        "uncertainty_penalty": 100 - uncertainty_score,
    }
    confidence = _bounded(sum(confidence_components.values()) / len(confidence_components))
    upward = _bounded(45 * above + 35 * positive_steps + 20 * sum(row["p25"] >= origin for row in rows) / len(rows))
    downward = _bounded(45 * below + 35 * negative_steps + 20 * sum(row["p75"] <= origin for row in rows) / len(rows))
    early = sum(p50[: max(1, len(p50) // 3)]) / max(1, len(p50) // 3) - origin
    terminal_opposes_early = early * terminal < 0
    crossing = sum(row["p10"] <= origin <= row["p90"] for row in rows) / len(rows)
    reversal = _bounded(35 * sign_changes + 25 * crossing + 20 * min(1.0, dispersion_ratio / 4) + (20 if terminal_opposes_early else 0))
    forecast_quality = _bounded(35 * forecast.get("input_coverage", 0) / 100 + 25 * (1 - uncertainty_score / 100) + 20 + 10 + 10)
    common = {"confidence": confidence, "normalized_move": normalized_move, "upward": upward, "downward": downward,
              "reversal": reversal, "uncertainty_score": uncertainty_score, "bias": bias}
    ce = option_quality("CE", common, argus)
    pe = option_quality("PE", common, argus)
    return {
        "label": "CITADEL-DERIVED FROM CHRONOS-2 FORECAST", "directional_bias": bias,
        "directional_confidence": confidence, "directional_confidence_components": confidence_components,
        "median_expected_move_points": round(terminal, 4), "median_expected_move_percentage": round(100 * terminal / origin, 6),
        "forecast_range": {"lower": forecast["forecast_low"], "upper": forecast["forecast_high"], "meaning": "P10/P90 probabilistic prediction interval across horizon"},
        "uncertainty": uncertainty, "uncertainty_score": uncertainty_score, "upward_persistence": upward,
        "downward_persistence": downward, "trend_persistence": upward if bias == "BULLISH" else downward if bias == "BEARISH" else max(upward, downward),
        "reversal_risk": reversal, "forecast_quality": forecast_quality, "ce_quality": ce, "pe_quality": pe,
        "warnings": ["DIRECTIONAL_CONFIDENCE_IS_NOT_A_CALIBRATED_PROBABILITY", "OPTION_QUALITY_IS_A_STARTING_SHADOW_HEURISTIC"],
    }


def option_quality(side, evidence, argus):
    bullish = side == "CE"
    direction = evidence["confidence"] if (evidence["bias"] == "BULLISH") == bullish else max(0.0, 100 - evidence["confidence"])
    persistence = evidence["upward"] if bullish else evidence["downward"]
    move = min(100.0, evidence["normalized_move"] * 40) if (evidence["bias"] == "BULLISH") == bullish else 0.0
    values = {"direction": direction, "persistence": persistence, "move": move,
              "reversal": 100 - evidence["reversal"], "uncertainty": 100 - evidence["uncertainty_score"]}
    argus_status = str((argus or {}).get("status") or "UNAVAILABLE")
    features = (argus or {}).get("features") if isinstance((argus or {}).get("features"), dict) else {}
    preferred = features.get("preferred_option_side")
    argus_confidence = features.get("confidence")
    if preferred and isinstance(argus_confidence, (int, float)):
        alignment = float(argus_confidence) if preferred == side else max(0.0, 100 - float(argus_confidence))
        values["argus"] = alignment * (0.75 if argus_status == "STALE" else 1.0)
    # Current compact ARGUS projection has no authoritative bid/ask liquidity history.
    available_weight = sum(QUALITY_WEIGHTS[name] for name in values)
    coverage = 100 * available_weight / sum(QUALITY_WEIGHTS.values())
    if available_weight < 60:
        return unavailable_quality("MINIMUM_EVIDENCE_NOT_MET", coverage, values)
    score = sum(values[name] * QUALITY_WEIGHTS[name] for name in values) / available_weight
    if evidence["bias"] in {"SIDEWAYS", "MIXED"}:
        score *= 0.72
    if evidence["uncertainty_score"] >= 70:
        score *= 0.65
    if evidence["reversal"] >= 70:
        score = min(score, 45.0)
    score = _bounded(score)
    return {"score": score, "interpretation": interpretation(score), "evidence_coverage": round(coverage, 2),
            "components": values, "missing_components": [name for name in QUALITY_WEIGHTS if name not in values],
            "label": f"CITADEL-DERIVED {side} OPTION-BUYING QUALITY", "shadow": True, "recommendation": None}


def unavailable_quality(reason, coverage=0.0, components=None):
    return {"score": None, "interpretation": "UNAVAILABLE", "evidence_coverage": round(coverage, 2),
            "components": components or {}, "missing_components": list(QUALITY_WEIGHTS), "label": "CITADEL-DERIVED OPTION-BUYING QUALITY",
            "shadow": True, "recommendation": None, "reason": reason}


def unavailable_analytics(reason):
    return {"label": "CITADEL-DERIVED FROM CHRONOS-2 FORECAST", "directional_bias": "UNAVAILABLE",
            "directional_confidence": None, "median_expected_move_points": None, "median_expected_move_percentage": None,
            "forecast_range": None, "uncertainty": "UNAVAILABLE", "uncertainty_score": None,
            "upward_persistence": None, "downward_persistence": None, "trend_persistence": None,
            "reversal_risk": None, "forecast_quality": None, "ce_quality": unavailable_quality(reason),
            "pe_quality": unavailable_quality(reason), "warnings": [reason]}


def interpretation(score):
    return "VERY STRONG SHADOW QUALITY" if score >= 80 else "STRONG SHADOW QUALITY" if score >= 65 else "MIXED" if score >= 50 else "WEAK" if score >= 35 else "VERY WEAK"


def _bounded(value):
    return round(max(0.0, min(100.0, float(value))), 2)
