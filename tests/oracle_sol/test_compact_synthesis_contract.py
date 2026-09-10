"""Offline contract controls over real records; no simulated provider acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts.arena_recorded_temporal import recorded_temporal_packet
from src.oracle_sol.compact_synthesis_contract import build_input, validate_output, SCHEMA, SECTIONS


def recorded():
    p, _ = recorded_temporal_packet()
    rows = {r['ordinal']: r for r in map(json.loads, Path('artifacts/brain_arena_master_override/calls.jsonl').read_text().splitlines()) if r['kind'] == 'RESULT'}
    desks = [(s, role, rows[n]['output']) for s, role, n in [('CALL','specialist',16), ('CALL','falsifier',19), ('PUT','specialist',21), ('PUT','falsifier',22)]]
    return p, rows[14]['output'], desks


def test_lossless_claims_and_evidence_and_no_input_mutation():
    p, observer, desks = recorded()
    before = deepcopy((observer, desks))
    new = build_input(p, observer, desks)
    assert (observer, desks) == before
    for eid, row in new['evidence_lookup'].items():
        decoded = {**new['evidence_metadata'][row['metadata_ref']], **{k:v for k,v in row.items() if k != 'metadata_ref'}}
        original = p.resolve_evidence(eid)
        assert all(decoded[k] == v for k,v in original.items())
    def decode(v):
        if isinstance(v, dict) and set(v) == {'claim_ref'}:
            claim = new['memo_claims'][v['claim_ref']]
            return {'claim': claim['claim'], 'evidence_ids': [new['citation_ids'][i] for i in claim['citation_codes']]}
        if isinstance(v, dict): return {k:decode(x) for k,x in v.items()}
        if isinstance(v, list): return [decode(x) for x in v]
        return v
    assert decode(new['observer']) == observer
    assert [decode(m['memo']) for m in new['desks']] == [m for _,_,m in desks]
    assert set(p.unseen_event_ids) <= set(new['evidence_lookup'])


def control(text):
    p, _, _ = recorded()
    ref = next(eid for eid in p.unseen_event_ids if 'ce_pricing' in str(p.resolve_evidence(eid)))
    raw = {'state':'WAIT', 'temporal_stage':'UNRESOLVED', 'claims':[{'claim':text+' ['+ref+']','evidence_ids':[ref]}], **{k:[] for k in SECTIONS}}
    raw['why_now']=[0]
    return p, raw


@pytest.mark.parametrize('text', ['No increase in call premium', 'Call premium fell', 'Put premium increased'])
def test_real_same_contract_factual_mismatch_rejected(text):
    p, raw = control(text)
    assert validate_output(raw,p) == 'CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE'


def test_truthful_change_and_claim_reference_integrity():
    p, raw = control('Call premium increased')
    assert validate_output(raw,p) is None
    raw['contradiction']=[0];raw['missing_confirmation']=[0]
    assert validate_output(raw,p) == 'MISSING_IS_NOT_CONTRADICTION'
    raw['missing_confirmation']=[];raw['contradiction']=[9]
    assert validate_output(raw,p) == 'ORPHAN_CLAIM_REFERENCE'
    raw['contradiction']=[];raw['claims'][0]['claim']='Call premium increased'
    assert validate_output(raw,p) == 'INLINE_EVIDENCE_MISMATCH'


def test_no_fake_observer_or_asymmetric_desks():
    p, obs, desks = recorded()
    with pytest.raises(ValueError,match='OBSERVER_MISSING'): build_input(p,None,desks)
    with pytest.raises(ValueError,match='ASYMMETRIC'): build_input(p,obs,desks[:-1])


def test_temporal_vocabulary_is_expressive_not_a_market_rule():
    assert {'EARLY_POSSIBILITY','DEVELOPING','READY','STRENGTHENING','WEAKENING','REVERSAL_WATCH'} <= set(SCHEMA['properties']['temporal_stage']['enum'])
    assert {'CALL_DEVELOPING','PUT_DEVELOPING'} <= set(SCHEMA['properties']['state']['enum'])
