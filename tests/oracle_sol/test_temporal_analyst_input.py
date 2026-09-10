from scripts.arena_recorded_temporal import recorded_temporal_packet
from src.oracle_sol.synthesis_decision_brief import build_temporal_analyst_input, require_retest_eligible, SCHEMA


def test_single_analyst_does_not_launder_failed_memos():
    packet,_=recorded_temporal_packet()
    brief,audit=build_temporal_analyst_input(packet,as_of='2026-09-04T04:19:51+00:00')
    assert brief['assertions']==[] and audit['original_receipts']==[]
    assert len(brief['facts'])==8
    assert set(packet.unseen_event_ids)=={f['evidence_id'] for f in brief['facts']}
    assert SCHEMA['properties']['call_case']==SCHEMA['properties']['put_case']
    assert require_retest_eligible(brief,audit)
    assert brief['previous_accepted_thesis'] is None
