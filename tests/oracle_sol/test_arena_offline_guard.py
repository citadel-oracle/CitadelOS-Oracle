import io
import json

import pytest

from scripts.brain_arena_desk_probe import recorded_input, reserve, failure_blocks_comparison


def test_repeated_build_of_real_frame_has_stable_comparison_input():
    first, text, source_hash = recorded_input("CALL", "side_specialist")
    second, again, same_hash = recorded_input("CALL", "side_specialist")
    assert text == again
    assert source_hash == same_hash
    assert first.canonical_state == second.canonical_state
    assert "ose_ssi_score" not in text


def test_reservations_include_interrupted_calls_and_never_retry_same_comparison():
    stream = io.StringIO(json.dumps({"kind": "RESERVATION", "comparison_id": "one"}) + "\n")
    assert reserve(stream, "two") == 2
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        reserve(stream, "one")
    stream = io.StringIO("\n".join(json.dumps({"kind": "RESERVATION", "comparison_id": str(i)}) for i in range(24)))
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        reserve(stream, "extra")


def test_request_size_failure_is_model_scoped_but_transport_failures_remain_shared():
    row = {"kind": "RESULT", "provider": "groq", "requested_model": "qwen", "http_status": 413}
    assert failure_blocks_comparison(row, "groq", "qwen")
    assert not failure_blocks_comparison(row, "groq", "gpt")
    for status in (None, 429, 503):
        assert failure_blocks_comparison({**row, "http_status": status}, "groq", "gpt")


def test_two_call_extension_is_synthesis_only_and_hard_bounded():
    def ledger(n):
        return io.StringIO("\n".join(json.dumps({"kind": "RESERVATION", "comparison_id": str(i)}) for i in range(n)))
    allowed = dict(provider="groq", model="openai/gpt-oss-120b", role="synthesis")
    assert reserve(ledger(24), "new", **allowed) == 25
    assert reserve(ledger(25), "new", **allowed) == 26
    for args in (allowed, {**allowed, "role": "side_specialist"}, {**allowed, "model": "new-model"}):
        with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
            reserve(ledger(26 if args == allowed else 24), "new", **args)
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        reserve(ledger(24), "0", **allowed)
    row = dict(kind="RESULT", provider="groq", requested_model=allowed["model"], http_status=413)
    assert not failure_blocks_comparison(row, **{k: v for k, v in allowed.items()}, approved_extension=True)
    assert failure_blocks_comparison({**row, "http_status": 429}, **allowed, approved_extension=True)
