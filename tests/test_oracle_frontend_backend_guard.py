import json
from contextlib import contextmanager

from scripts.oracle_frontend_backend_guard import inspect_contract
import scripts.oracle_frontend_backend_guard as guard


def test_stale_8102_bundle_prevents_ready(tmp_path, monkeypatch):
    (tmp_path / "bundle.js").write_text("http://127.0.0.1:8102/v1/oracle/fast-lane")
    evidence = tmp_path / "browser.json"
    evidence.write_text(json.dumps({"browser_events": []}))
    result = inspect_contract(build=tmp_path, expected_base="http://127.0.0.1:8000", browser_evidence=evidence)
    assert result["oracle_ready"] is False
    assert result["stale_compiled_ports"] == ["8102"]


def test_exact_browser_resolved_urls_and_reachable_backend_allow_ready(tmp_path, monkeypatch):
    (tmp_path / "bundle.js").write_text("oracle-fast-lane")
    base = "http://127.0.0.1:8000"
    evidence = tmp_path / "browser.json"
    evidence.write_text(json.dumps({"browser_events": [
        {"event_type": "BACKEND_CONTRACT", "backend_base_url": base,
         "fast_lane_url": f"{base}/v1/oracle/fast-lane",
         "eventsource_url": f"{base}/v1/oracle/fast-lane/stream"},
        {"event_type": "FETCH_OK", "url": f"{base}/v1/oracle/fast-lane"},
        {"event_type": "EVENTSOURCE_CONNECTED", "url": f"{base}/v1/oracle/fast-lane/stream"},
    ]}))
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(guard, "urlopen", lambda *args, **kwargs: Response())
    assert inspect_contract(build=tmp_path, expected_base=base, browser_evidence=evidence)["oracle_ready"] is True
