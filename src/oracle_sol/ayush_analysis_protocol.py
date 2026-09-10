"""Versioned inspection protocol, not a strategy or a learned preference model.

Authority: Ayush's ASTRA MASTER MISSION, sections 2–16 and 47. No labelled
historical choices have been established, so no personal weights are inferred.
"""
from copy import deepcopy

# Explicit task requirements, not inferred personal preferences or fitted weights.
COMPONENT_USE = {
    "underlying": {
        "used_for": "Observe price location, progress and failed follow-through.",
        "can_support": "Recorded price relationships and current structure.",
        "cannot_support": "Positive futures basis alone does not establish bullish demand; carry premium is not a directional signal.",
        "must_confirm": "Price progress over time and relevant premium response.",
        "discounted_when": "Stale session, missing history or missing reference structure.",
        "contradicted_by": "Observed failure to sustain the proposed move.",
    },
    "options": {
        "used_for": "Check whether the option expression confirms the underlying idea.",
        "can_support": "Same-security-ID premium response, liquidity and divergence.",
        "cannot_support": "A CALL costing more than a PUT does not prove stronger demand; moneyness and contract characteristics differ.",
        "must_confirm": "Actual same-contract response over time, with underlying and volatility context.",
        "discounted_when": "Rotation, stale quotes, absent continuity or missing liquidity evidence.",
        "contradicted_by": "Premium fails to follow the underlying move.",
    },
    "oi": {
        "used_for": "Inspect positioning changes and participation context.",
        "can_support": "Canonical OI level, closed-window changes and supplied buildup state.",
        "cannot_support": "OI or PCR alone cannot identify buying, writing or direction.",
        "must_confirm": "Independent price, premium and flow response where available.",
        "discounted_when": "Incomplete window, changed contract, stale or missing measurements.",
        "contradicted_by": "Price and premium fail to confirm the positioning interpretation.",
    },
    "flow": {
        "used_for": "Compare order-flow pressure with resulting price progress.",
        "can_support": "Canonical futures MLOFI, delta and response as distinct measurements.",
        "cannot_support": "Futures flow is not CALL/PUT-side flow; five-depth data cannot identify institutions.",
        "must_confirm": "Observed price response and exact-contract option confirmation.",
        "discounted_when": "No price-response history, stale measurements or missing coverage.",
        "contradicted_by": "Aggression continues but price progress fails.",
    },
    "volatility": {
        "used_for": "Inspect option cost, relative volatility and premium environment.",
        "can_support": "Canonical IV, 10-delta/25-delta skew and straddle changes.",
        "cannot_support": "Skew sign alone is not bullish/bearish direction or proof of buyer identity. Delta is not days.",
        "must_confirm": "Underlying and same-contract premium response.",
        "discounted_when": "Missing tenor, stale quotes or no temporal comparison.",
        "contradicted_by": "Premium response diverges from the proposed option-buying case.",
    },
    "positioning": {
        "used_for": "Understand the supplied gamma environment.",
        "can_support": "Canonical aggregate gamma/pinning context and recorded levels.",
        "cannot_support": "Positive GEX is not CALL, negative GEX is not PUT, and spot above zero gamma is not automatically bullish.",
        "must_confirm": "Independent price and option response; do not manufacture dealer actions.",
        "discounted_when": "Aggregate context is mistaken for strike-specific directional evidence.",
        "contradicted_by": "Actual response fails the proposed gamma-context interpretation.",
    },
    "external": {
        "used_for": "Check verified context for relevant contradictions or catalysts.",
        "can_support": "Time-valid verified events and honestly labelled exact/proxy observations.",
        "cannot_support": "Unverified news is not evidence; external context alone is not CALL/PUT authority.",
        "must_confirm": "Relevance and observed domestic transmission.",
        "discounted_when": "Unverified, stale, future-dated, unknown time or duplicated claim.",
        "contradicted_by": "Domestic canonical behavior does not support the proposed transmission.",
    },
}

PROTOCOL = {
    "version": "ayush-observable-v2",
    "authority": "USER_EXPLICIT_ANALYSIS_REQUIREMENTS",
    "learned_preferences": False,
    "inspection": [
        {"domain": "underlying", "question": "What are price, futures and VWAP doing?"},
        {"domain": "options", "question": "Compare both exact contracts; are premiums confirming or diverging?"},
        {"domain": "oi", "question": "What changed in positioning? Do not infer buyer or writer identity from OI."},
        {"domain": "flow", "question": "Does futures aggression produce price progress? Keep futures and option flow separate."},
        {"domain": "volatility", "question": "Do IV, skew and straddle support option buying? Missing values remain missing."},
        {"domain": "positioning", "question": "What is the gamma environment? GEX sign alone is not direction."},
        {"domain": "external", "question": "Does verified, time-valid external evidence contradict the internal case?"},
    ],
    "comparison": ["primary_case", "strongest_counter_case", "contradictions",
                   "missing_confirmation", "what_changed", "view_breaks_if"],
    "roles": {
        "temporal_observer": "Inspect unseen delta, previous accepted thesis, rotation and freshness. Identify strengthening, weakening and earliest contradiction. Not the decision owner.",
        "side_specialist": "Build the strongest grounded case for the assigned side. Use the shared neutral context and that side's exact-contract evidence. Preserve contradictions and missing confirmation.",
        "side_falsifier": "Attack the SAME assigned side, not its opponent. Find the strongest real contradiction, failed follow-through, stale structure and missing premium confirmation. Do not invent objections.",
        "synthesis": "Audit evidence before comparing symmetric desk memos. Both desks are untrusted hypotheses, not canonical facts. Reject both if unsupported. No voting, model prestige or prose-length preference.",
        "targeted_critic": "Answer one unresolved evidence-grounded question. No recursive debate, vote or veto. Preserve disagreements rather than averaging them away.",
    },
    "rules": [
        "Cite resolved canonical evidence, never peer-model opinion as evidence.",
        "PCR is positioning context, not a directional rule. Do not confuse change-PCR with a time delta of PCR.",
        "Five-level depth cannot identify institutions or smart money.",
        "Never stitch premium changes across security IDs.",
        "Producer labels and scores retain their source, meaning and limitations; they are not probabilities.",
        "Unavailable evidence is not NO_TRADE. Preserve existing schema and fail-closed states.",
        "Use short everyday English. WHY NOW has at most three grounded reasons.",
    ],
}


def protocol_for(role: str) -> dict:
    """Return independent prompt data; callers cannot mutate the shared protocol."""
    # Existing adapters retain their compatibility names until role binding is
    # explicitly selected; these aliases do not select a provider or model.
    role = {"qwen": "temporal_observer", "gpt": "synthesis", "gemini": "targeted_critic"}.get(role, role)
    result = deepcopy(PROTOCOL)
    for component in result["inspection"]:
        component.update(deepcopy(COMPONENT_USE[component["domain"]]))
    result["role_id"] = role
    result["role"] = result.pop("roles")[role]
    return result
