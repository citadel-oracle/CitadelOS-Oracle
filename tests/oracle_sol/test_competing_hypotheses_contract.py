from copy import deepcopy
from types import SimpleNamespace
import pytest
from src.oracle_sol.competing_hypotheses_contract import validate_structure
from src.oracle_sol.evidence_gate import EvidenceGate


def specimen(state='WAIT'):
    return dict(state=state, thesis_evolution='EARLY_POSSIBILITY',
                opportunity_maturity='UNKNOWN', promotion_reason='Interpretation remains unresolved.',
                hypotheses={name: dict(plausibility='UNRESOLVED', discrimination='Not distinguished.',
                                       evidence_ids=['event']) for name in ['CALL','PUT','NOISE','REVERSAL']},
                conclusions=[dict(purpose='why_now',claim='Recorded observation is available.',evidence_ids=['event'])])


PACKET=SimpleNamespace(valid_evidence_ids=['event'], resolve_evidence=lambda eid: {'value':1} if eid=='event' else None)


@pytest.mark.parametrize('state',['WAIT','CALL_DEVELOPING','PUT_DEVELOPING','CALL','PUT','NO_TRADE','REVERSAL'])
def test_structure_never_selects_direction(state):
    assert validate_structure(specimen(state),PACKET) is None


def test_all_competing_hypotheses_required():
    raw=specimen();del raw['hypotheses']['NOISE']
    assert validate_structure(raw,PACKET)


def test_orphan_citation_rejected():
    raw=specimen();raw['conclusions'][0]['evidence_ids']=['invented']
    assert validate_structure(raw,PACKET)


def test_plausibility_does_not_force_promotion():
    raw=specimen();raw['hypotheses']['CALL']['plausibility']='PLAUSIBLE'
    before=deepcopy(raw)
    assert validate_structure(raw,PACKET) is None
    assert raw==before and raw['state']=='WAIT'


@pytest.mark.parametrize('delta',[10,25])
def test_delta_slice_is_not_duration(delta):
    packet=SimpleNamespace(resolve_evidence=lambda eid: {'value':{'supporting_values':{f'skew_{delta}d':0.5}}})
    assert EvidenceGate.validate_factual_claim(f'{delta}-day skew rose.', ['event'],packet)=='DELTA_SLICE_IS_NOT_DAYS_TO_EXPIRY'
    assert EvidenceGate.validate_factual_claim(f'{delta}-delta skew is recorded.', ['event'],packet) is None


def test_wait_needs_grounded_rationale_too():
    raw=specimen();raw['conclusions'][0]['purpose']='what_changed'
    assert validate_structure(raw,PACKET)=='STATE_WITHOUT_GROUNDED_REASON'
