from __future__ import annotations

from threading import Event
from time import sleep

from src.argus.contract_technicals import LatestContractTechnicalsProvider


def test_contract_technicals_are_latest_wins_and_action_locked_while_warming():
    release = Event()
    calls: list[str] = []

    def provider(contract, observed_at):
        calls.append(str(observed_at))
        if len(calls) == 1:
            release.wait(1)
        return {"status": "AVAILABLE", "source_timestamp": str(observed_at), "current_premium": contract["premium"]}

    adapter = LatestContractTechnicalsProvider(provider)
    contract = {"side": "CE", "security_id": "101", "premium": 100}
    warming = adapter(contract, "2026-08-10T09:30:01+00:00")
    assert warming["action_locked"] is True
    adapter({**contract, "premium": 101}, "2026-08-10T09:35:01+00:00")
    release.set()
    for _ in range(50):
        result = adapter({**contract, "premium": 102}, "2026-08-10T09:35:02+00:00")
        if result.get("status") == "AVAILABLE":
            break
        sleep(0.01)
    assert result["current_premium"] == 102
    assert result["source_timestamp"] in {
        "2026-08-10T09:35:01+00:00",
        "2026-08-10T09:35:02+00:00",
    }
    assert 1 <= len(calls) <= 2
    assert adapter.status()["coalesced_revision_count"] >= 1
