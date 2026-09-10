"""Qualification contract. No scheduling, state selection or durable writes.

Model assessments are interpretations, never canonical feature values. Runtime
adoption requires the external qualification gate; importing this module does
not select a model or change the existing coordinator.
"""
from copy import deepcopy
from src.oracle_sol.temporal_analysis_contract import SCHEMA as BASE_SCHEMA
from src.oracle_sol.temporal_analysis_contract import INSTRUCTIONS as BASE_INSTRUCTIONS
from src.oracle_sol.cognitive_output_validation import cognitive_output_error

SCHEMA = deepcopy(BASE_SCHEMA)
ASSESSMENT = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'plausibility': {'type': 'string', 'enum': ['PLAUSIBLE', 'WEAKENED', 'UNRESOLVED']},
        'discrimination': {'type': 'string'},
        'evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['plausibility', 'discrimination', 'evidence_ids'],
}
SCHEMA['properties']['hypotheses'] = {
    'type': 'object', 'additionalProperties': False,
    'properties': {name: deepcopy(ASSESSMENT) for name in ['CALL', 'PUT', 'NOISE', 'REVERSAL']},
    'required': ['CALL', 'PUT', 'NOISE', 'REVERSAL'],
}
SCHEMA['properties']['promotion_reason'] = {'type': 'string'}
SCHEMA['required'] += ['hypotheses', 'promotion_reason']

INSTRUCTIONS = BASE_INSTRUCTIONS + """
The question is NOT which directional story can be told. Compare simultaneous
CALL, PUT, NOISE/TRANSITION and REVERSAL interpretations. For each give one short
discrimination statement: which observed change distinguishes it from the
strongest alternative, or why the evidence cannot distinguish them. UNRESOLVED
is allowed, especially reversal without prior history. Do not invent persistence.
Possibility is not promotion: WAIT can coexist with a plausible CALL or PUT.
Explain promotion or non-promotion in promotion_reason using the cited conclusions.
This is your interpretation, not a numeric gate. A small amount of meaningful
partial evidence may earn DEVELOPING even while channels are missing. Neither
universal agreement nor a minimum price move nor a count of confirmations is needed.
Evaluate what changed, persisted or failed to follow through only where recorded.
Repeated labels/related transformations are not independent new evidence. Maintain
the strongest alternative, including noise; do not demand certainty to reject it.
Do not use OI source classifications as inferred participant actions: SHORT BUILDUP
etc. are producer labels only, not proof of writing/covering, resistance or demand.
In this source volatility-surface 25d means 25-delta, not days. Basis sign/change
is not pressure or confirmation of direction. Premium response is not aggressor
identity. Missing confirmation is not contradiction and does not automatically
force WAIT. Thesis strength is separate from entry maturity, which can be UNKNOWN.
Conclusions need only cover decision-changing rationale, counter-case, option
response, known missing/contradiction and next observation where supported. Do
not repeat the hypothesis prose in every conclusion. Cite exact supplied event IDs.
No future outcomes, certainty, invented levels or execution instructions.
Current facts retain individual source times/ages; availability is not proof of
recency. Do not call an old observation a fresh change. previous_model_view and
specialist_context are prior model assertions, not facts or votes. Compare them
with supplied temporal evidence; absent specialist findings must not block a read.
"""


def validate_structure(output, packet):
    """Schema/provenance only. This is NOT semantic or model qualification."""
    error = cognitive_output_error(output, SCHEMA, packet)
    if error:
        return error
    if len(output['conclusions']) > 10:
        return 'EXCESSIVE_CONCLUSIONS'
    if output['state'] != 'UNAVAILABLE' and not any(
        item['purpose'] == 'why_now' for item in output['conclusions']
    ):
        return 'STATE_WITHOUT_GROUNDED_REASON'
    if not output['promotion_reason'].strip():
        return 'MISSING_PROMOTION_EXPLANATION'
    for hypothesis in output['hypotheses'].values():
        if not hypothesis['discrimination'].strip():
            return 'MISSING_ALTERNATIVE_EXPLANATION'
    for conclusion in output['conclusions']:
        if not conclusion['claim'].strip() or not conclusion['evidence_ids']:
            return 'CLAIM_WITHOUT_EVIDENCE'
    return None
