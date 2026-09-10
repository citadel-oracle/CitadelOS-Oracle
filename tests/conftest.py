import socket

import pytest


@pytest.fixture(autouse=True)
def offline_test_environment(monkeypatch, tmp_path):
    """Keep the default suite credential-independent and network-free."""

    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "offline-test-token")
    monkeypatch.setenv("DHAN_CLIENT_ID", "offline-test-client")
    monkeypatch.setenv(
        "CITADEL_RISK_STATE_PATH", str(tmp_path / "risk_state.json")
    )
    monkeypatch.setenv(
        "CITADEL_RISK_AUDIT_PATH", str(tmp_path / "risk_audit.jsonl")
    )
    monkeypatch.setenv(
        "CITADEL_PAPER_STATE_PATH", str(tmp_path / "paper_state.json")
    )


    def block_network(*args, **kwargs):
        raise AssertionError("Offline pytest suite attempted network access")

    monkeypatch.setattr(socket.socket, "connect", block_network)
    monkeypatch.setattr(socket, "create_connection", block_network)
