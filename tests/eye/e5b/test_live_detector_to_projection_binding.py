"""E5B Test: Verifies live DetectorBar stream ingestion updates EyeRuntimeState and projection."""

from datetime import datetime, timezone, timedelta
import pytest
from src.eye.contracts import InstrumentIdentity, PriceAtom
from src.eye.detectors.input_model import DetectorBar
from src.eye.oracle_projection.runtime_state import EyeRuntimeState
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService


def make_price(val: float) -> PriceAtom:
    return PriceAtom(ticks=int(round(val * 100)))


def make_bar(open_f, high_f, low_f, close_f, t_open, t_close, bar_idx):
    return DetectorBar(
        instrument_key="NSE:NIFTY",
        timeframe="5m",
        open_time=t_open,
        expected_close_time=t_close,
        available_at=t_close,
        bar_key=f"BAR:{bar_idx}",
        open=make_price(open_f),
        high=make_price(high_f),
        low=make_price(low_f),
        close=make_price(close_f),
        is_closed=True,
        volume=1000,
    )


def test_ingesting_bar_updates_runtime_state_and_projection():
    runtime = EyeRuntimeState()
    service = EyeOracleProjectionService(runtime_state=runtime)

    inst = InstrumentIdentity(
        raw_symbol="NIFTY",
        normalized_symbol="NIFTY",
        exchange="NSE",
        instrument_type="UNDERLYING_INDEX",
        underlying="NIFTY",
        source="DHAN",
        market="NSE",
    )

    now_utc = datetime.now(timezone.utc)
    t3_c = now_utc.replace(microsecond=0)
    t3_o = t3_c - timedelta(minutes=5)
    t2_c = t3_o
    t2_o = t2_c - timedelta(minutes=5)
    t1_c = t2_o
    t1_o = t1_c - timedelta(minutes=5)

    b1 = make_bar(24500.0, 24550.0, 24490.0, 24540.0, t1_o, t1_c, 1)
    b2 = make_bar(24540.0, 24620.0, 24530.0, 24610.0, t2_o, t2_c, 2)
    b3 = make_bar(24610.0, 24660.0, 24600.0, 24650.0, t3_o, t3_c, 3)

    runtime.ingest_bar("NIFTY", "5m", b1, inst)
    runtime.ingest_bar("NIFTY", "5m", b2, inst)
    runtime.ingest_bar("NIFTY", "5m", b3, inst)

    proj = service.get_projection(symbol="NIFTY", timeframe="5m")

    assert proj.freshness.market_data_last_seen_utc == t3_c.isoformat()
    assert proj.freshness.freshness_status == "FRESH"
    assert proj.provenance["source_type"] == "EYE_DETECTOR_COMPOSER_PIPELINE"
    assert proj.structure.nearest_swing_high == 24660.0
    assert proj.structure.nearest_swing_low == 24600.0
