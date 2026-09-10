from copy import deepcopy
import pytest
from scripts.analyst_factual_regression import FACTS, QUESTIONS, validate_response


def test_all_regression_dimensions_and_no_real_identifiers():
 assert len(QUESTIONS)==10
 assert FACTS['F1']['current']-FACTS['F1']['previous']==600
 assert FACTS['F4']['ltp']-FACTS['F3']['ltp']==1
 assert FACTS['F3']['security_id']==FACTS['F4']['security_id']!=FACTS['F5']['security_id']
 assert FACTS['F6']['days_to_expiry'] is None
 assert FACTS['F7']['observed_opposing_response'] is None


def test_citations_are_mandatory_and_resolved():
 answer={q:{'answer':'Fixture text, not model quality proof.','evidence_ids':['F1']} for q in QUESTIONS}
 validate_response(answer)
 bad=deepcopy(answer);bad['Q1']['evidence_ids']=['made_up']
 with pytest.raises(ValueError):validate_response(bad)
 del answer['Q10']
 with pytest.raises(Exception):validate_response(answer)
