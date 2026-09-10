import json
from datetime import datetime, timezone
import pytest
from scripts import audit_v2_blinded_inputs as boundary

def test_nested_time_and_security_identity_are_not_silently_stitched():
    cutoff=datetime(2026,9,4,10,tzinfo=timezone.utc)
    before={'option_type':'CE','security_id':1,'strike':100,'expiry':'2026-09-08',
            'ltp':5,'source_timestamp':'2026-09-04T09:59:00+00:00'}
    after={**before,'security_id':2,'strike':150,'source_timestamp':'2026-09-04T10:00:01+00:00'}
    problems,rotations,count=boundary.nested_integrity(
        {'event_id':'synthetic-control-only','diff':{'before':before,'after':after}},cutoff,{})
    assert any(p.startswith('FUTURE_SOURCE_TIME:') for p in problems)
    assert rotations[0]['before']=='1' and rotations[0]['after']=='2'
    assert count==2
    after.update(security_id=1,source_timestamp=before['source_timestamp'])
    problems,_,_=boundary.nested_integrity(
        {'event_id':'synthetic-control-only','diff':{'before':before,'after':after}},cutoff,{})
    assert any(p.startswith('SECURITY_ID_IDENTITY_CONFLICT:') for p in problems)


@pytest.mark.parametrize('provider,model',[
    ('groq','openai/gpt-oss-120b'),('groq','openai/gpt-oss-20b'),
    ('groq','qwen/qwen3.8-27b'),('gemini_primary','gemini-3.8-flash'),
    ('gemini_secondary','gemini-3.8-flash'),('gemini_tertiary','gemini-3.8-flash')])
def test_proprietary_dispatch_blocked_before_packet_or_provider_access(monkeypatch,provider,model):
    from scripts import v2_blinded_screen as screen
    monkeypatch.setattr('sys.argv',['screen','--case','CASE_A','--provider',provider,'--model',model,'--live'])
    def forbidden(_):raise AssertionError('Proprietary case must not be loaded')
    monkeypatch.setattr(screen,'load_case',forbidden)
    with pytest.raises(ValueError,match='PROPRIETARY_V2_PRIVACY_NOT_APPROVED'):screen.main()


def test_reused_id_with_changed_payload_fails_closed(tmp_path, monkeypatch):
    data=tmp_path/'data';data.mkdir()
    cases=tmp_path/'cases';cases.mkdir()
    row={'event_id':'canonical-1','timestamp_utc':'2026-09-04T04:00:00+00:00','value':1}
    (data/'events.jsonl').write_text(json.dumps(row)+'\n'+json.dumps({**row,'value':2})+'\n')
    case={'session_date':'2026-09-04','decision_cutoff_ist':'10:00:00',
          'canonical_sources':['data/events.jsonl'],
          'timeline':[{'timestamp_utc':row['timestamp_utc'],'events':[row]}]}
    (cases/'CASE_A.json').write_text(json.dumps(case))
    monkeypatch.setattr(boundary,'REPO',tmp_path)
    monkeypatch.setattr(boundary,'PACK',tmp_path)
    assert boundary.audit()[0]['problems']==['AMBIGUOUS_CANONICAL_ID:canonical-1']


def test_model_payload_excludes_evaluator_metadata(monkeypatch):
    from scripts.v2_blinded_screen import load_case
    packet=load_case('CASE_A')
    assert set(packet)=={'session_date','decision_cutoff_ist','timeline','known_missing_inputs'}
    assert 'outcomes_private' not in json.dumps(packet)


def test_screen_restores_real_retry_after_without_resetting_clock(tmp_path, monkeypatch):
    from scripts import v2_blinded_screen as screen
    from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
    folder=tmp_path/'receipt';folder.mkdir()
    (folder/'result.json').write_text(json.dumps({'response':{
        'provider':'groq','model_id':'test-model',
        'timestamp':'2026-09-07T10:00:00+00:00','http_status':429,
        'rate_limits':{'retry_after_seconds':120}}}))
    monkeypatch.setattr(screen,'ROOT',tmp_path)
    governor=CognitiveQuotaGovernor();screen.restore_observations(governor)
    from datetime import datetime
    observed=datetime.fromisoformat('2026-09-07T10:00:00+00:00').timestamp()
    assert governor.model_states['groq:test-model'].retry_after_until==observed+120
    assert governor.provider_states['groq'].retry_after_until==observed+120
