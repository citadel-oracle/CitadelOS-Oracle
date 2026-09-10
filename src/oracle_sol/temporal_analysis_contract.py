"""Flat typed conclusions for a single symmetric analyst; offline candidate.

Canonical citations live next to their exact claim. UI/gate rendering may append
them, but cannot invent citations or rewrite the claim. No output is committed here.
"""
from copy import deepcopy
from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.synthesis_decision_brief import SCHEMA as BRIEF_SCHEMA, SECTIONS, validate_brief_output

SCHEMA={"type":"object","additionalProperties":False,"properties":{
    **{k:deepcopy(BRIEF_SCHEMA['properties'][k]) for k in ('state','thesis_evolution','opportunity_maturity')},
    'conclusions':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{
        'purpose':{'type':'string','enum':list(SECTIONS)},
        'claim':{'type':'string'},
        'evidence_ids':{'type':'array','items':{'type':'string'}},
    },'required':['purpose','claim','evidence_ids']}},
},'required':['state','thesis_evolution','opportunity_maturity','conclusions']}

INSTRUCTIONS="""Analyze the temporal Oracle facts, not a checklist. Compare CALL and PUT fairly.
Return only a small set of decision-changing conclusions, each with a purpose and exact canonical evidence_ids.
Use direct evidence_ids beside each claim; do not repeat IDs inside prose. Never cite model opinions.
Do not fill every purpose. Keep at most ten conclusions. Empty/unresolved is legitimate, but explain a WAIT view with current facts, not missing inputs alone.
Distinguish known missing confirmation from observed contradiction. Partial evidence can justify DEVELOPING without universal agreement.
Separate thesis strengthening from opportunity maturity. Unknown maturity stays UNKNOWN.
Quotes and IV do not identify buyer demand or buying/selling pressure. Basis is a spread, not bearish/bullish pressure.
OI/PCR/GEX do not establish direction. Missing OI/PCR/GEX is not itself contradiction.
Individual CE and PE IV must not be confused with aggregate ATM IV. Preserve exact security_id continuity.
No invented thresholds, confidence, entry levels or institutional attribution.
Do not recite the whole input. Explain relationships and their limitations; do not infer a sustained trend from one pair of observations."""


def validate_analysis(raw,packet,brief):
    error=cognitive_output_error(raw,SCHEMA,packet)
    if error:return error
    if len(raw['conclusions'])>10:return 'EXCESSIVE_CONCLUSIONS'
    # WAIT is a market conclusion too, not an escape from grounded explanation.
    # This checks explanation presence, never the number of confirming signals.
    if raw['state']!='UNAVAILABLE' and not any(c['purpose']=='why_now' for c in raw['conclusions']):
        return 'STATE_WITHOUT_GROUNDED_REASON'
    projected={k:raw[k] for k in ('state','thesis_evolution','opportunity_maturity')}
    projected.update({s:[] for s in SECTIONS})
    for item in raw['conclusions']:
        if not item['claim'].strip() or not item['evidence_ids']:return 'CLAIM_WITHOUT_EVIDENCE'
        # Deterministic citation rendering only. Original provider output retained.
        projected[item['purpose']].append({'claim':item['claim']+' ['+', '.join(item['evidence_ids'])+']',
                                           'evidence_ids':item['evidence_ids']})
    return validate_brief_output(projected,packet,brief)
