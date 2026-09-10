from copy import deepcopy
from scripts.arena_recorded_temporal import recorded_temporal_packet
from src.oracle_sol.synthesis_decision_brief import build_temporal_analyst_input
from src.oracle_sol.temporal_analysis_contract import validate_analysis


def test_typed_citations_preserve_exact_claim_and_do_not_relax_factual_gate():
    p,_=recorded_temporal_packet();b,_=build_temporal_analyst_input(p,as_of='2026-09-04T04:19:51+00:00')
    eid=next(e for e in p.unseen_event_ids if 'SENSORIUM' in e)
    out={'state':'CALL_DEVELOPING','thesis_evolution':'EARLY_POSSIBILITY','opportunity_maturity':'UNKNOWN',
         'conclusions':[{'purpose':'why_now','claim':'Call premium increased','evidence_ids':[eid]}]}
    original=deepcopy(out)
    assert validate_analysis(out,p,b) is None
    assert out==original
    out['conclusions'][0]['claim']='Call premium fell'
    assert validate_analysis(out,p,b)=='CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE'
    out['conclusions'][0]['evidence_ids']=['model:fake']
    assert validate_analysis(out,p,b)=='MODEL_CLAIM_UNSUPPORTED'


def test_wait_is_not_a_default_without_an_evidence_backed_explanation():
    p,_=recorded_temporal_packet();b,_=build_temporal_analyst_input(p,as_of='2026-09-04T04:19:51+00:00')
    out={'state':'WAIT','thesis_evolution':'UNRESOLVED','opportunity_maturity':'UNKNOWN','conclusions':[]}
    assert validate_analysis(out,p,b)=='STATE_WITHOUT_GROUNDED_REASON'
    out['state']='UNAVAILABLE'
    assert validate_analysis(out,p,b) is None
