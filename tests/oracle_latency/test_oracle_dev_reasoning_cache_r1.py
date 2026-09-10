"""R1 regression: presentation polling must never execute development logic."""

from app import main


def test_oracle_development_reasoning_route_is_cache_only(monkeypatch):
    expected = {"3m": {"status": "CACHED"}, "is_replay": False}
    monkeypatch.setattr(main.oracle_dev_service, "get_latest_assessments", lambda: expected)

    def must_not_run():
        raise AssertionError("HTTP presentation route invoked assess_and_execute")

    monkeypatch.setattr(main.oracle_dev_service, "assess_and_execute", must_not_run)

    assert main.oracle_dev_reasoning() == expected
