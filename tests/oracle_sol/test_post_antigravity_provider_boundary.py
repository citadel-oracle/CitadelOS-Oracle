import io
from urllib.error import HTTPError
from unittest.mock import Mock
from src.oracle_sol.provider_client import ProviderNeutralClient

def test_gemini_503_is_one_request_without_profile_substitution(monkeypatch):
    client=ProviderNeutralClient()
    secret=Mock(return_value=('isolated-test-secret','TEST'))
    monkeypatch.setattr('src.oracle_sol.provider_client.resolve_secret',secret)
    wire=Mock(side_effect=HTTPError('https://generativelanguage.googleapis.com',503,'capacity',{},io.BytesIO(b'{}')))
    monkeypatch.setattr('urllib.request.urlopen',wire)
    result=client._invoke_gemini('gemini_primary','gemini-3.8-flash','test','Return JSON','{}',
        {'type':'object'},1,100,{'effort':'low'},'2026-09-07T00:00:00Z')
    assert wire.call_count==1
    assert secret.call_count==1
    assert result.actual_profile=='gemini_primary'
    assert not result.success
    assert result.fallback_path is None
