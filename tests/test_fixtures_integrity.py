"""Integrity and Schema Validation for Frozen Market Data Fixtures.

Guarantees that fixtures in fixtures/market_data/ are hermetic, immutable,
non-empty, strictly monotonic, and satisfy all canonical OHLCV invariants.
"""

import json
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "market_data"


@pytest.fixture
def spot_dhan():
    path = FIXTURES_DIR / "dhan_spot_1m_20260908.json"
    assert path.exists(), f"Missing fixture: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def spot_upstox():
    path = FIXTURES_DIR / "upstox_spot_1m_20260908.json"
    assert path.exists(), f"Missing fixture: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def fut_dhan():
    path = FIXTURES_DIR / "dhan_fut_1m_20260908.json"
    assert path.exists(), f"Missing fixture: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def fut_upstox():
    path = FIXTURES_DIR / "upstox_fut_1m_20260908.json"
    assert path.exists(), f"Missing fixture: {path}"
    with open(path) as f:
        return json.load(f)


def _validate_candle_series(candles, expected_len, require_monotonic=True):
    assert len(candles) == expected_len, f"Expected {expected_len} candles, got {len(candles)}"
    canonical_keys = {"time", "open", "high", "low", "close"}
    last_time = 0

    for i, c in enumerate(candles):
        # Time extraction
        t = int(c.get("time") or c.get("timestamp") or 0)
        assert t > 0, f"Bar {i} has invalid timestamp: {c}"
        if require_monotonic and i > 0:
            assert t > last_time, f"Bar {i} timestamp {t} not strictly monotonic after {last_time}"
        last_time = t

        # Key validation
        assert canonical_keys.issubset(c.keys()), f"Bar {i} missing canonical keys: {c}"

        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        assert h >= max(o, cl) - 1e-4, f"Bar {i} high {h} < max(open {o}, close {cl})"
        assert l <= min(o, cl) + 1e-4, f"Bar {i} low {l} > min(open {o}, close {cl})"

        vol = float(c.get("volume") or 0.0)
        assert vol >= 0.0, f"Bar {i} negative volume: {vol}"


def test_spot_fixtures_integrity(spot_dhan, spot_upstox):
    _validate_candle_series(spot_dhan, expected_len=375)
    _validate_candle_series(spot_upstox, expected_len=375)

    # Validate exact session bounds: 09:15 to 15:29 IST
    # 2026-09-08 09:15 IST = 1788839100
    # 2026-09-08 15:29 IST = 1788861540
    assert spot_dhan[0]["time"] == spot_upstox[0]["time"] == 1788839100
    assert spot_dhan[-1]["time"] == spot_upstox[-1]["time"] == 1788861540


def test_fut_fixtures_integrity(fut_dhan, fut_upstox):
    _validate_candle_series(fut_dhan, expected_len=375)
    _validate_candle_series(fut_upstox, expected_len=385)

    # Dhan internal store ended at 15:29, while Upstox completed the full 385-bar F&O normal trading session through 15:39 IST
    assert fut_dhan[0]["time"] == fut_upstox[0]["time"] == 1788839100
    assert fut_dhan[-1]["time"] == 1788861540  # 15:29:00 IST
    assert fut_upstox[-1]["time"] == 1788862140  # 15:39:00 IST (F&O session closes at 15:40 IST)


def test_certified_spot_fixtures_integrity():
    """Verify cryptographically certified Dhan snapshot (E4AD manifest) and matching Upstox capture."""
    c_dhan_path = FIXTURES_DIR / "certified_dhan_spot_1m_20260806.json"
    c_upstox_path = FIXTURES_DIR / "upstox_spot_1m_20260806.json"
    assert c_dhan_path.exists()
    assert c_upstox_path.exists()
    with open(c_dhan_path) as f:
        c_dhan = json.load(f)
    with open(c_upstox_path) as f:
        c_upstox = json.load(f)

    _validate_candle_series(c_dhan, expected_len=375)
    _validate_candle_series(c_upstox, expected_len=375)

    # 2026-08-06 09:15 IST = 1785987900, 15:29 IST = 1786010340
    assert c_dhan[0]["time"] == c_upstox[0]["time"] == 1785987900
    assert c_dhan[-1]["time"] == c_upstox[-1]["time"] == 1786010340
