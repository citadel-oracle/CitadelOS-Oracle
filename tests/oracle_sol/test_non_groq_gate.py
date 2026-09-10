from types import SimpleNamespace
import pytest
from scripts import non_groq_analyst_gate as gate


@pytest.mark.parametrize('statuses,profiles',[
 ([503,503,503],['gemini_primary','gemini_primary','gemini_secondary']),
 ([429],['gemini_primary']),([200],['gemini_primary']),
])
def test_explicit_transport_budget(tmp_path,monkeypatch,statuses,profiles):
 seen=[]
 monkeypatch.setattr(gate,'ROOT',tmp_path)
 monkeypatch.setattr(gate,'resolve_secret',lambda p:('synthetic-test-key','TEST'))
 monkeypatch.setattr(gate,'CognitiveQuotaGovernor',lambda:SimpleNamespace(
  register_model_binding=lambda *a:None,can_invoke=lambda *a:True))
 def invoke(*args,**kwargs):
  seen.append(kwargs['profile']);status=statuses[len(seen)-1]
  return SimpleNamespace(http_status=status,parsed_output=None,finish_reason=None,
   latency_ms=0,usage={},error_class=None,to_dict=lambda:{'http_status':status})
 monkeypatch.setattr(gate,'ProviderNeutralClient',lambda g:SimpleNamespace(_invoke_gemini=invoke))
 gate.main()
 assert seen==profiles
 assert len(list((tmp_path/'non_groq_gate').glob('attempt_*.json')))==len(profiles)
