from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json


PATH = Path(__file__).resolve().parents[2] / "scripts" / "collect_hud_live_certification.py"
SPEC = spec_from_file_location("collect_hud_live_certification", PATH)
MODULE = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_packet_to_dom_latency_matches_latest_same_strike_packet():
    raw = [
        {"payload": {"strike": 24600, "receive_wall_utc": "2026-08-12T03:45:00.100000+00:00"}},
        {"payload": {"strike": 24600, "receive_wall_utc": "2026-08-12T03:45:00.250000+00:00"}},
        {"payload": {"strike": 24650, "receive_wall_utc": "2026-08-12T03:45:00.290000+00:00"}},
    ]
    dom = [{"focus_strike": 24600, "commit_epoch_ms": 1786506300300.0}]
    assert MODULE.packet_dom_latency(raw, dom) == [50.0]


def test_collector_latency_summary_is_explicit_when_no_live_samples():
    assert MODULE.stats([]) == {
        "count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None, "max_ms": None,
    }


def test_browser_event_instrumentation_persists_transport_and_dom_evidence():
    MODULE.BROWSER_EVENTS.clear()
    payload = {
        "event_type": "DOM_SEMANTIC_COMMIT", "surface": "FLOW_PULSE",
        "headline": "NO TRADE", "market": "ACCEPTING LOWER",
        "pressure": "SELLERS STRONG", "result": "PRICE FALLING WITH SELLERS",
        "speed": "FAST", "futures_ltp": 24500.0, "revision": "oracle-fast-1",
    }
    MODULE.record_browser_event(json.loads(json.dumps(payload)))
    assert MODULE.BROWSER_EVENTS[-1]["surface"] == "FLOW_PULSE"
    assert MODULE.BROWSER_EVENTS[-1]["collector_receive_epoch_ms"] > 0
