import json
from unittest.mock import patch
import pytest
from src.oracle_sol.groq_adapter import GroqBrainAdapter
from src.oracle_sol.provider_client import ProviderNeutralClient
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
from scripts.synthesis_calibration_once import retain


def test_partial_completion_retained_exactly_but_never_accepted(tmp_path):
    body='  {"state":"CALL", "claims":['
    class Response:
        status=200
        headers={'x-ratelimit-remaining-tokens':'4000'}
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps({'model':'openai/gpt-oss-120b','usage':{'completion_tokens':3500},'choices':[{'finish_reason':'length','message':{'content':body,'reasoning':'audit reasoning'}}]}).encode()
    adapter=GroqBrainAdapter(api_key='isolated-test-key',model_name='openai/gpt-oss-120b')
    audit=tmp_path/'audit.json'
    with patch('urllib.request.urlopen',return_value=Response()), patch('src.oracle_sol.provider_client.GroqBrainAdapter',return_value=adapter):
        result=ProviderNeutralClient(CognitiveQuotaGovernor()).invoke('groq','openai/gpt-oss-120b',[],quota_key='gpt_oss',audit_sink=lambda r:retain(audit,r))
    assert json.loads(audit.read_text())['content']==body
    assert not result.success and result.parsed_output is None and result.response_text==''
    assert result.error_class=='OUTPUT_TRUNCATED'
    assert 'audit reasoning' not in json.dumps(result.to_dict())
    assert audit.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError): retain(audit,{})


def test_secrets_redacted_before_persistence(tmp_path):
    path=tmp_path/'audit.json'
    retain(path,{'content':'Authorization: Bearer example-secret-value'})
    assert 'example-secret-value' not in path.read_text()
