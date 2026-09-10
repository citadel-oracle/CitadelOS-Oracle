"""CITADEL EYE — Isolated Deterministic Replay Harness for 07-Aug-2026 Golden Replay."""

import sys, os, json, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from copy import deepcopy

from src.eye.oracle_projection.runtime_state import EyeRuntimeState
from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
from src.eye.detectors.input_model import DetectorBar
from src.eye.contracts import InstrumentIdentity, PriceAtom
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector
from src.eye.composer.matcher import SetupComposer
from src.eye.composer.setup_registry import get_e3_setup_definitions

IST = ZoneInfo("Asia/Kolkata")
NIFTY_FILE = Path("/Users/ayushmudgal/Developer/CitadelOS/reports/eye_golden_replay/20260807/nifty_1m_20260807.json")
OPTION_FILE = Path("/Users/ayushmudgal/Developer/CitadelOS/reports/eye_golden_replay/20260807/option_24700pe_20260807.json")


def clean_wallclock_metadata(obj):
    """Recursively strip wall-clock execution timestamps to ensure 100% semantic hash determinism."""
    if isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            if k in {"resolved_at_utc", "projection_computed_at_utc", "source_age_ms", "semantic_event_age_seconds", "calculated_at", "generated_at"}:
                continue
            res[k] = clean_wallclock_metadata(v)
        return res
    elif isinstance(obj, list):
        return [clean_wallclock_metadata(x) for x in obj]
    return obj


def run_golden_replay(speed_factor=1, watermark_ts=None):
    with open(NIFTY_FILE) as f:
        nifty_candles = json.load(f)
    with open(OPTION_FILE) as f:
        pe_candles = json.load(f)

    pe_by_time = {}
    for c in pe_candles:
        ts_val = c.get("time") or c.get("timestamp") if isinstance(c, dict) else c[0]
        pe_by_time[int(ts_val)] = c

    runtime = object.__new__(EyeRuntimeState)
    runtime.__init__()
    # Isolate symbol state cleanly
    runtime._bars["NIFTY"] = []
    runtime._detectors["NIFTY"] = {
        "swing": SwingStateDetector(),
        "structure": StructureBreakDetector(),
        "liquidity": LiquidityDetector(),
        "displacement": DisplacementDetector(),
        "fvg": FVGClusterDetector(),
    }
    runtime._composers["NIFTY"] = SetupComposer(get_e3_setup_definitions())
    runtime._latest_structure["NIFTY"] = {}
    runtime._latest_active_setup["NIFTY"] = {}

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

    raw_setup_journal = []
    normal_tradable_journal = []
    pe_alignment_journal = []

    for i, c in enumerate(nifty_candles):
        ts_val = c.get("time") or c.get("timestamp") if isinstance(c, dict) else c[0]
        t_close = datetime.fromtimestamp(ts_val, tz=timezone.utc)
        t_open = t_close - timedelta(seconds=60)
        dt_ist = t_close.astimezone(IST)

        if watermark_ts and t_close > watermark_ts:
            break

        bar = DetectorBar(
            instrument_key="NSE:NIFTY",
            timeframe="1m",
            open_time=t_open,
            expected_close_time=t_close,
            available_at=t_close,
            bar_key=f"BAR:GOLDEN:{i+1}",
            open=PriceAtom(ticks=int(round(c["open"] * 100))),
            high=PriceAtom(ticks=int(round(c["high"] * 100))),
            low=PriceAtom(ticks=int(round(c["low"] * 100))),
            close=PriceAtom(ticks=int(round(c["close"] * 100))),
            is_closed=True,
            volume=int(c.get("volume", 0)),
        )

        prev_setup_key = runtime._latest_active_setup.get("NIFTY", {}).get("setup_key")
        runtime.ingest_bar("NIFTY", "1m", bar, inst)

        curr_setup = runtime._latest_active_setup.get("NIFTY", {})
        curr_setup_key = curr_setup.get("setup_key")

        if curr_setup_key and curr_setup_key != prev_setup_key and curr_setup.get("family") != "NO_ACTIVE_SETUP":
            proj = service.get_projection(symbol="NIFTY", timeframe="5m")
            proj_dict = proj.to_dict()

            pe_bar = pe_by_time.get(int(ts_val), {})
            pe_close = pe_bar.get("close") if isinstance(pe_bar, dict) else (pe_bar[4] if len(pe_bar) > 4 else None)

            is_cas = (dt_ist.hour == 15 and dt_ist.minute >= 15 and dt_ist.minute <= 35)

            rec = {
                "timestamp": dt_ist.strftime("%Y-%m-%d %H:%M:%S"),
                "family": curr_setup.get("family"),
                "direction": curr_setup.get("direction"),
                "lifecycle": curr_setup.get("lifecycle"),
                "entry": curr_setup.get("entry_reference"),
                "pe_close": pe_close,
                "is_cas": is_cas,
                "projection": proj_dict,
            }
            raw_setup_journal.append(rec)

            if is_cas:
                rec["tradability_classification"] = "CAS_EXCLUDED_FROM_NORMAL_SETUP"
            else:
                rec["tradability_classification"] = "NORMAL_CTS_EVENT"
                normal_tradable_journal.append(rec)

            # PE Alignment logic
            underlying_dir = curr_setup.get("direction", "UNKNOWN")
            alignment = "PREFERRED" if underlying_dir == "BEARISH" else "CONTRARY"
            action = "WATCH_PE_PREMIUM" if alignment == "PREFERRED" else "NO_ACTION"

            pe_alignment_journal.append({
                "timestamp": dt_ist.strftime("%Y-%m-%d %H:%M:%S"),
                "underlying_direction": underlying_dir,
                "premium": pe_close,
                "oi": pe_bar.get("oi") if isinstance(pe_bar, dict) else None,
                "contract_alignment": alignment,
                "Oracle_action": action,
            })

    cleaned_raw = clean_wallclock_metadata(raw_setup_journal)
    serialized = json.dumps(cleaned_raw, sort_keys=True, default=str)
    semantic_sha256 = hashlib.sha256(serialized.encode()).hexdigest()

    return {
        "semantic_sha256": semantic_sha256,
        "raw_setup_count": len(raw_setup_journal),
        "normal_tradable_count": len(normal_tradable_journal),
        "cas_excluded_count": len(raw_setup_journal) - len(normal_tradable_journal),
        "raw_journal": raw_setup_journal,
        "normal_journal": normal_tradable_journal,
        "pe_journal": pe_alignment_journal,
    }


if __name__ == "__main__":
    res = run_golden_replay()
    print("REPLAY_HARNESS_SEMANTIC_SHA256:", res["semantic_sha256"])
    print("RAW_SETUP_COUNT:", res["raw_setup_count"])
    print("NORMAL_TRADABLE_SETUP_COUNT:", res["normal_tradable_count"])
    print("CAS_EXCLUDED_COUNT:", res["cas_excluded_count"])
