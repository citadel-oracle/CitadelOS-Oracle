"""Real recorded input; mocked outputs test validation, not market judgment."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts.arena_recorded_temporal import recorded_temporal_packet
from src.oracle_sol.synthesis_decision_brief import build_brief, validate_brief_output, require_retest_eligible, SCHEMA, SECTIONS, digest
from src.oracle_sol.evidence_gate import EvidenceGate

AS_OF = '2026-09-04T04:19:51+00:00'


def source():
    packet,_=recorded_temporal_packet()
    rows={r['ordinal']:r for r in map(json.loads,Path('artifacts/brain_arena_master_override/calls.jsonl').read_text().splitlines()) if r['kind']=='RESULT'}
    receipts=[{**rows[n],'role':role,'side':side} for n,role,side in [(14,'observer',None),(16,'specialist','CALL'),(19,'falsifier','CALL'),(21,'specialist','PUT'),(22,'falsifier','PUT')]]
    return packet,receipts


def test_real_union_chronology_identity_and_all_counter_cases():
    p,receipts=source(); original=deepcopy(receipts)
    b,a=build_brief(p,receipts,as_of=AS_OF)
    assert receipts==original
    assert set(p.unseen_event_ids) <= {f['evidence_id'] for f in b['facts']}
    assert [f['at'] for f in b['facts']] == sorted(f['at'] for f in b['facts'])
    for f in b['facts']:
        raw=p.resolve_evidence(f['evidence_id'])['value']
        assert f['values']==raw['supporting_values']
        assert f['security_id']==raw['security_id']
    for assertion, receipt in zip(b['assertions'],receipts):
        assert assertion['type']=='MODEL_ASSERTION_NOT_FACT'
        for name in ('contradiction','missing_confirmation'):
            assert assertion[name]==receipt['output'][name]
    sensor=next(f for f in b['facts'] if f['kind']=='SENSORIUM_DELTA')
    pair=sensor['values']['diffs']['ce_pricing']
    assert pair['before']['security_id']==pair['after']['security_id']==42637
    assert pair['before']['ltp']==109.15 and pair['after']['ltp']==110.5
    assert a['brief_hash']==digest(b)


def test_metamorphic_order_identity_and_elaboration_are_not_model_context():
    p,receipts=source(); b,_=build_brief(p,receipts,as_of=AS_OF)
    changed=deepcopy(receipts[::-1])
    for r in changed:
        r['provider']='hidden';r['response_model']='hidden'
        if r['role']!='observer' and 0 < len(r['output']['support']) < 3:
            r['output']['support'].append(deepcopy(r['output']['support'][0]))
    again,_=build_brief(p,changed,as_of=AS_OF)
    assert again==b  # Transport invariance, NOT proof of model order neutrality.
    p=replace(p,unseen_event_ids=p.unseen_event_ids+p.unseen_event_ids)
    assert build_brief(p,receipts,as_of=AS_OF)[0]==b


@pytest.mark.parametrize('defect', ['session','future','vob','orphan','duplicate_role','time_order'])
def test_fail_closed_input_controls(defect):
    p,receipts=source()
    event=next(eid for eid in p.unseen_event_ids if 'SENSORIUM' in eid)
    if defect=='session': receipts[0]['session_id']='2026-09-03'
    if defect=='future': p.evidence_registry[event]['value']['timestamp_utc']='2026-09-05T00:00:00+00:00'
    if defect=='vob': p.evidence_registry[event]['value']['supporting_values']['vob_score']=1
    if defect=='orphan': p=replace(p,unseen_event_ids=p.unseen_event_ids+['missing-id'])
    if defect=='duplicate_role': receipts.append(receipts[0])
    if defect=='time_order': p.evidence_registry[event]['value']['supporting_values']['diffs']['ce_pricing']['before']['source_timestamp']='2026-09-05T00:00:00+00:00'
    with pytest.raises(ValueError): build_brief(p,receipts,as_of=AS_OF)


def output(p,text='Call premium increased from 109.15 to 110.50'):
    eid=next(e for e in p.unseen_event_ids if 'SENSORIUM' in e)
    return {'state':'CALL_DEVELOPING','thesis_evolution':'EARLY_POSSIBILITY','opportunity_maturity':'UNKNOWN',
            **{s:[] for s in SECTIONS}, 'why_now':[{'claim':text+' ['+eid+']','evidence_ids':[eid]}]}


@pytest.mark.parametrize('claim,error', [
    ('Call premium fell','CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE'),
    ('No increase in call premium','CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE'),
    ('Call premium increased from 109.15 to 111.50','CLAIM_NUMERIC_MISMATCH'),
    ('Call premium rose, showing stronger call demand','PRICE_RESPONSE_IS_NOT_DEMAND_ATTRIBUTION'),
])
def test_factual_rejections_do_not_pick_market_direction(claim,error):
    p,rs=source();b,_=build_brief(p,rs,as_of=AS_OF)
    with patch.object(EvidenceGate,'validate_and_commit',side_effect=AssertionError('commit forbidden')):
        assert validate_brief_output(output(p,claim),p,b)==error


def test_partial_evidence_can_express_developing_without_confirmation_count():
    p,rs=source();b,_=build_brief(p,rs,as_of=AS_OF);raw=output(p)
    assert validate_brief_output(raw,p,b) is None
    raw['opportunity_maturity']='MATURE'
    assert validate_brief_output(raw,p,b)=='MATURITY_WITHOUT_EVIDENCE'
    # This is a schema control, not a claim that the real move is mature.
    assert 'MATURE' in SCHEMA['properties']['opportunity_maturity']['enum']
    assert 'STRENGTHENING' in SCHEMA['properties']['thesis_evolution']['enum']


def test_missing_and_rotated_input_are_not_fake_confirmation():
    p,rs=source();b,_=build_brief(p,rs,as_of=AS_OF);raw=output(p)
    raw['contradiction']=[{'claim':'Flow unavailable [coverage:input]','evidence_ids':['coverage:input']}]
    assert validate_brief_output(raw,p,b)=='MISSING_IS_NOT_MARKET_EVIDENCE'
    eid=next(e for e in p.unseen_event_ids if 'SENSORIUM' in e)
    p.evidence_registry[eid]['value']['supporting_values']['diffs']['ce_pricing']['after']['security_id']=999
    assert EvidenceGate.validate_factual_claim('Call premium increased',{eid},p)=='PREMIUM_CONTINUITY_ERROR'


def test_context_reduction_measured_without_token_estimates():
    p,rs=source();b,_=build_brief(p,rs,as_of=AS_OF)
    previous=json.loads(Path('artifacts/synthesis_calibration_20260907/input.json').read_text())['payload']
    size=lambda x:len(json.dumps(x,sort_keys=True,separators=(',',':')).encode())
    assert size(b) < size(previous)
    assert not any(k in json.dumps(b) for k in ['claim_ref','citation_codes'])


def test_historical_input_rejections_are_not_sanitized_into_qualification():
    p,rs=source();b,a=build_brief(p,rs,as_of=AS_OF)
    assert len(a['receipt_validation_issues'])==5
    assert a['original_receipts']==rs
    with pytest.raises(ValueError,match='UPSTREAM_ASSERTIONS_UNQUALIFIED'):
        require_retest_eligible(b,a)
    b['revision']+=1
    with pytest.raises(ValueError,match='BRIEF_IDENTITY_MISMATCH'):
        require_retest_eligible(b,a)


def test_unverified_external_summary_is_not_promoted_to_fact():
    p,rs=source()
    eid=p.unseen_event_ids[0]
    p.evidence_registry[eid]['field']='external_event'
    with pytest.raises(ValueError,match='VERIFICATION_PROOF_REQUIRED'):
        build_brief(p,rs,as_of=AS_OF)


def test_coverage_change_is_visible_not_a_direction_rule():
    p,rs=source();b,_=build_brief(p,rs,as_of=AS_OF)
    # Control mutation of availability metadata only; no invented market values.
    p.evidence_registry['coverage:input']['value']['unavailable'].append('test_missing_input')
    newer,_=build_brief(p,rs,as_of=AS_OF)
    assert 'test_missing_input' in newer['coverage']['value']['unavailable']
    assert newer['facts']==b['facts'] and newer['assertions']==b['assertions']
    assert validate_brief_output(output(p),p,b)=='FROZEN_EVIDENCE_CHANGED'


def test_previous_session_cannot_be_used_as_accepted_thesis():
    p,rs=source()
    p=replace(p,previous_thesis={'session_id':'2026-09-03','state':'NO_TRADE','model':'NONE'})
    with pytest.raises(ValueError,match='PREVIOUS_THESIS_NOT_REVALIDATED'):
        build_brief(p,rs,as_of=AS_OF)


def test_recorded_analyst_iv_conflation_rejected():
    p,_=source()
    eid=next(e for e in p.unseen_event_ids if 'SENSORIUM' in e)
    assert EvidenceGate.validate_factual_claim('Both call and put IVs fell marginally',{eid},p)=='CLAIM_CONTRADICTS_CONTRACT_IV'
    assert EvidenceGate.validate_factual_claim('Call IV increased',{eid},p) is None
