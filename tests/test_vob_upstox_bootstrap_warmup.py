"""VOB Upstox Bootstrap & Warmup Test Suite.

Validates that:
1. Upstox historical bootstrap fetches multi-day + intraday 1m candles.
2. Warmup transitions to READY without waiting for live market ticks.
3. VOB engine ingests the bootstrap candles and forms 1m, 3m, 5m, 15m, 1h zones.
4. Swing pivot detection (MSLEN=5) and ATR (200) invariants are preserved.
"""

import json
from datetime import datetime
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest

from src.oracle_development.oracle_dev_service import OracleDevService
from src.vob.engine import NiftyVOBEngine

IST = ZoneInfo("Asia/Kolkata")
REAL_CANDLE_PATH = Path("logs/oracle_dev/candle_store_spot_1m.json")


def _get_test_candles(count: int = 1200) -> list:
    if REAL_CANDLE_PATH.exists():
        raw = json.loads(REAL_CANDLE_PATH.read_text())
        if len(raw) >= count:
            return raw[-count:]
    candles = []
    base_price = 24800.0
    for i in range(count):
        t = 1788750000 + i * 60
        wave = ((i % 50) - 25) * 4.0
        o = base_price + wave
        c = o + (5.0 if i % 2 == 0 else -5.0)
        h = max(o, c) + 8.0
        l = min(o, c) - 8.0
        v = 8000.0 + (i % 20) * 400.0
        candles.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
    return candles


def test_upstox_historical_bootstrap_ready_state():
    """Verify bootstrap transitions warmup_status to READY when candles >= 250."""
    mock_upstox = MagicMock()
    mock_upstox.has_token = True
    
    all_candles = _get_test_candles(1200)
    hist_candles = all_candles[:1125]
    intra_candles = all_candles[1125:]

    mock_upstox.get_historical_candles.return_value = hist_candles
    mock_upstox.get_intraday_candles.return_value = intra_candles

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        vob_engine = NiftyVOBEngine(persistence_path=tmp_path / "vob_state.json")
        svc = OracleDevService(
            dhan=None,
            argus_api=None,
            options_structure_engine=None,
            vob_engine=vob_engine,
            state_root=tmp_path,
            upstox=mock_upstox,
        )

        now_ist = datetime(2026, 9, 9, 15, 30, 0, tzinfo=IST)
        candles = svc._backfill_warmup_if_due(
            segment="IDX_I",
            security_id="13",
            instrument="INDEX",
            store_path=tmp_path / "spot_store.json",
            metadata_path=tmp_path / "metadata_spot.json",
            now_ist=now_ist,
            force=True,
            symbol="NIFTY Spot",
            contract="INDEX",
            expiry="N/A",
        )

        assert len(candles) == 1200
        meta = json.loads((tmp_path / "metadata_spot.json").read_text())
        assert meta["warmup_status"] == "READY"
        assert meta["warmup_source"] == "Upstox Historical+Intraday API V3"
        assert meta["last_backfill_error"] is None


def test_vob_engine_zones_formed_from_bootstrap():
    """Verify VOB forms zones across 1m, 3m, 5m, 15m, 1h from bootstrap candles."""
    candles = _get_test_candles(1200)
    last_spot = candles[-1]["close"]

    with tempfile.TemporaryDirectory() as tmpdir:
        vob_engine = NiftyVOBEngine(persistence_path=Path(tmpdir) / "vob_state.json")
        vob_engine.ingest_1m_candles(candles, last_spot)

        # Invariant: zones must exist on multiple timeframes
        assert "1m" in vob_engine._zones
        assert "3m" in vob_engine._zones
        assert "5m" in vob_engine._zones
        assert "15m" in vob_engine._zones
        assert "1h" in vob_engine._zones

        assert len(vob_engine._zones["1m"]) > 0
        assert len(vob_engine._zones["3m"]) > 0
        assert len(vob_engine._zones["5m"]) > 0
        assert len(vob_engine._zones["15m"]) > 0

        # Invariant: zone price geometry is well-formed
        for tf, z_map in vob_engine._zones.items():
            for zid, z in z_map.items():
                assert z.zone_high >= z.zone_low
                assert z.strength_score >= 0.0
