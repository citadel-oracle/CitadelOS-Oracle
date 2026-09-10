import pytest
from scripts.free_candidate_comparison import assert_zero_catalog, MODELS

def test_catalog_proof_never_accepts_paid_or_wildcard():
    model=MODELS[0]
    assert_zero_catalog(model,{'id':model,'pricing':{'prompt':'0','completion':'0'}})
    for candidate, row in [
        ('openrouter/free',{'id':'openrouter/free','pricing':{'prompt':'0','completion':'0'}}),
        (model,{'id':model,'pricing':{'prompt':'0','completion':'0.01'}}),
        (model,{'id':model,'pricing':{'prompt':'0','completion':'0','request':'1'}}),
        (model,{'id':model,'pricing':{}}),
    ]:
        with pytest.raises(ValueError):assert_zero_catalog(candidate,row)

def test_openrouter_partial_is_retained_before_json_parsing(monkeypatch):
    import json
    from src.oracle_sol.openrouter_adapter import OpenRouterAdapter
    class Response:
        status=200;headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'model':MODELS[0], 'usage':{'completion_tokens':3500},
            'choices':[{'finish_reason':'length','message':{'content':'{"state":','reasoning':'audit-only'}}]}).encode()
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:Response())
    retained=[]
    parsed,telemetry=OpenRouterAdapter(model_name=MODELS[0],api_key='isolated-test-secret').invoke_reasoning(
        'offline-test','Return JSON','Isolated test',audit_sink=retained.append)
    assert parsed is None
    assert telemetry['finish_reason']=='length'
    assert retained[0]['content']=='{"state":'
    assert retained[0]['accepted_synthesis'] is False
    assert retained[0]['usage']['completion_tokens']==3500
