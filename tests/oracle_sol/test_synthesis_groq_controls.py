"""Mock wire proof only; no live capability or model-quality certification."""
import json
from unittest.mock import patch
import pytest
from src.oracle_sol.groq_adapter import GroqBrainAdapter
from src.oracle_sol.provider_client import ProviderNeutralClient
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
from src.oracle_sol.synthesis_decision_brief import SCHEMA


@pytest.mark.parametrize('effort',['low','medium'])
def test_strict_schema_and_effort_reach_wire_once(effort):
    captured=[]
    class Response:
        status=200;headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'model':'openai/gpt-oss-120b','usage':{'completion_tokens_details':{'reasoning_tokens':12}},'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}).encode()
    def wire(req,**kwargs): captured.append(json.loads(req.data));return Response()
    adapter=GroqBrainAdapter(model_name='openai/gpt-oss-120b',api_key='isolated-test-key')
    with patch('urllib.request.urlopen',side_effect=wire),patch('src.oracle_sol.provider_client.GroqBrainAdapter',return_value=adapter):
        result=ProviderNeutralClient(CognitiveQuotaGovernor()).invoke('groq','openai/gpt-oss-120b',[],quota_key='gpt_oss',schema=SCHEMA,strict_schema=True,reasoning={'effort':effort},max_output_tokens=3500)
    assert len(captured)==1
    assert captured[0]['response_format']['json_schema']=={'name':'citadel_synthesis','strict':True,'schema':SCHEMA}
    assert captured[0]['reasoning_effort']==effort
    assert captured[0]['max_completion_tokens']==3500
    assert 'max_tokens' not in captured[0]
    assert 'Required output JSON Schema' not in captured[0]['messages'][0]['content']
    assert result.usage['reasoning_tokens']==12
    assert not result.success  # Strict wire request does not bypass local validation.


def test_invalid_effort_never_silently_falls_back():
    adapter=GroqBrainAdapter(model_name='openai/gpt-oss-120b',api_key='isolated-test-key')
    with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
        with pytest.raises(ValueError,match='EFFORT_UNSUPPORTED'):
            adapter.invoke_reasoning(reasoning_effort='none')


def test_schema_failure_completion_is_explicit_audit_only():
    import io
    from urllib.error import HTTPError
    partial='{"state":"", "claim":"private rejected completion"}'
    failure=HTTPError('https://api.groq.com/openai/v1/chat/completions',400,
                      'Bad Request',{},io.BytesIO(json.dumps({'error':{
                          'code':'json_validate_failed','failed_generation':partial}}).encode()))
    audit=[]
    adapter=GroqBrainAdapter(model_name='openai/gpt-oss-120b',api_key='isolated-test-key')
    with patch('urllib.request.urlopen',side_effect=failure):
        result=adapter.invoke_reasoning(audit_sink=audit.append)
    assert len(audit)==1
    assert audit[0]['content']==partial
    assert audit[0]['audit_only'] is True
    assert audit[0]['accepted_synthesis'] is False
    assert partial not in json.dumps(result)
