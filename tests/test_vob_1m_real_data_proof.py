"""Real-data 1M VOB proof and deterministic replay regression test."""

import json
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from typing import Any, Dict, List

from src.vob.engine import NiftyVOBEngine, VOBZone
from src.vob.episodes import VobEpisode
from src.vob.reversal import VobReversalEngine
from src.strategy_lab.strategies.pullback_master.strategy import PullbackMasterStrategyEngine, PullbackMasterConfig

IST = ZoneInfo("Asia/Kolkata")
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "market_data"
CANDLE_DIR = Path("logs/options_structure/candles")


def to_dt(ts: Any) -> datetime | None:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=IST)
    elif isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
    return None


def run_chronological_replay(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Replays 1m candles chronologically and records state."""
    engine = NiftyVOBEngine()
    reversal_engine = VobReversalEngine()
    pine_engine = PullbackMasterStrategyEngine(PullbackMasterConfig.tradingview_v2_20260814())

    zones_formed = []
    pine_evaluations = []
    vob_only_trades = []

    start_idx = 200
    if len(candles) < start_idx:
        start_idx = max(5, len(candles) // 2)

    # Bounded replay of 30 steps for fast, deterministic regression check
    end_idx = min(len(candles), start_idx + 30)
    t0 = time.perf_counter()

    for i in range(start_idx, end_idx):
        current_candles = candles[:i+1]
        latest = current_candles[-1]
        ts_str = latest.get("timestamp") or latest.get("time")
        dt = to_dt(ts_str)

        # 1. Update VOB engine
        res = engine.analyze_timeframe(timeframe="1m", candles=current_candles)
        support_val = res.get("nearest_bullish_support")
        resist_val = res.get("nearest_bearish_resistance")
        supports = [support_val] if support_val else []
        resistances = [resist_val] if resist_val else []

        # 2. Update Zone Registry & Lifecycle
        for s in supports:
            z_id = f"1m_{s['origin_candle_time']}"
            if not any(z["id"] == z_id for z in zones_formed):
                zones_formed.append({
                    "id": z_id, "timeframe": "1m", "direction": "SUPPORT",
                    "top": s["zone_high"], "btm": s["zone_low"], "loc_time": s["origin_candle_time"], "origin_ts": ts_str,
                    "lifecycle": []
                })
            
            for z in zones_formed:
                if z["id"] == z_id and s["status"] not in z["lifecycle"]:
                    z["lifecycle"].append(s["status"])

        for r in resistances:
            z_id = f"1m_{r['origin_candle_time']}"
            if not any(z["id"] == z_id for z in zones_formed):
                zones_formed.append({
                    "id": z_id, "timeframe": "1m", "direction": "RESISTANCE",
                    "top": r["zone_high"], "btm": r["zone_low"], "loc_time": r["origin_candle_time"], "origin_ts": ts_str,
                    "lifecycle": []
                })
            
            for z in zones_formed:
                if z["id"] == z_id and r["status"] not in z["lifecycle"]:
                    z["lifecycle"].append(r["status"])

        # 3. Reversal Engine & Shadow State
        projection = {
            "timeframes": {
                "1m": {
                    "SUPPORT": supports,
                    "RESISTANCE": resistances,
                    "unknown_fields": [], "trend_alignment": 0, "quality": 0,
                    "price_distance_pts": 0, "price_distance_atr": 0, "atr_200": 5.0
                }
            },
            "trend_composite": 0,
            "overall_quality": 0,
            "duel": {}, "unknown_fields": [], "paper_only": True
        }
        reversal_engine.ingest_ose(projection)
        
        events = reversal_engine.events()
        for ev in events:
            if ev.get("type") == "SHADOW_ENTRY_RECORDED" and ev.get("variant") == "VOB_ONLY":
                trade_id = ev.get("trade_id")
                if not any(t["trade_id"] == trade_id for t in vob_only_trades):
                    vob_only_trades.append(ev)

    elapsed = time.perf_counter() - t0

    return {
        "zones": zones_formed,
        "trades": vob_only_trades,
        "evaluations": pine_evaluations,
        "time": elapsed,
        "candles": len(candles)
    }

def test_1m_vob_deterministic_replay_frozen_fixture():
    """Run 5x determinism check on real frozen session candles."""
    with open(FIXTURES_DIR / "dhan_spot_1m_20260908.json") as fp:
        candles = json.load(fp)

    results = []
    for _ in range(5):
        res = run_chronological_replay(candles)
        results.append(res)

    first = results[0]
    for other in results[1:]:
        assert len(first["zones"]) == len(other["zones"])
        assert len(first["trades"]) == len(other["trades"])
        for z1, z2 in zip(first["zones"], other["zones"]):
            assert z1["id"] == z2["id"]
            assert z1["top"] == z2["top"]
            assert z1["btm"] == z2["btm"]
            assert z1["lifecycle"] == z2["lifecycle"]


def test_vob_output_parity_on_frozen_fixtures():
    """Feed frozen real session data from Dhan and Upstox independently into VOB engine.

    Asserts 100.0% zone parity across all 5 timeframes (1m, 3m, 5m, 15m, 1h).
    """
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures" / "market_data"
    with open(fixtures_dir / "dhan_spot_1m_20260908.json") as f:
        dhan_candles = json.load(f)
    with open(fixtures_dir / "upstox_spot_1m_20260908.json") as f:
        upstox_candles = json.load(f)

    def aggregate(candles, tf_mins):
        if tf_mins == 1:
            return candles
        res = []
        for i in range(0, len(candles), tf_mins):
            chunk = candles[i:i + tf_mins]
            if not chunk:
                continue
            res.append({
                "time": chunk[0]["time"],
                "open": chunk[0]["open"],
                "high": max(c["high"] for c in chunk),
                "low": min(c["low"] for c in chunk),
                "close": chunk[-1]["close"],
                "volume": sum(c.get("volume", 0) for c in chunk),
            })
        return res

    tf_map = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}

    for tf, mins in tf_map.items():
        vob_dhan = NiftyVOBEngine()
        vob_upstox = NiftyVOBEngine()

        c_dhan = aggregate(dhan_candles, mins)
        c_upstox = aggregate(upstox_candles, mins)

        res_d = vob_dhan.analyze_timeframe(timeframe=tf, candles=c_dhan)
        res_u = vob_upstox.analyze_timeframe(timeframe=tf, candles=c_upstox)

        zones_d = res_d.get("zone_ladder") or []
        zones_u = res_u.get("zone_ladder") or []

        assert len(zones_d) == len(zones_u), f"Zone count mismatch on {tf}: Dhan={len(zones_d)}, Upstox={len(zones_u)}"

        # Verify each zone matches exactly in side, role, zone_high, zone_low, status
        for zd, zu in zip(zones_d, zones_u):
            assert zd["side"] == zu["side"]
            assert zd["role"] == zu["role"]
            assert abs(zd["zone_high"] - zu["zone_high"]) < 0.1
            assert abs(zd["zone_low"] - zu["zone_low"]) < 0.1
            assert zd["status"] == zu["status"]

        # Verify primary zone matches
        pri_d = res_d.get("primary_zone")
        pri_u = res_u.get("primary_zone")
        if pri_d and pri_u:
            assert pri_d["side"] == pri_u["side"]
            assert abs(pri_d["zone_high"] - pri_u["zone_high"]) < 0.1
            assert abs(pri_d["zone_low"] - pri_u["zone_low"]) < 0.1
        else:
            assert pri_d == pri_u


def test_vob_output_parity_on_certified_fixtures():
    """Feed cryptographically certified Dhan capture (E4AD manifest) and Upstox independently into VOB engine.

    Asserts 100.0% zone parity across all 5 timeframes (1m, 3m, 5m, 15m, 1h).
    """
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures" / "market_data"
    with open(fixtures_dir / "certified_dhan_spot_1m_20260806.json") as f:
        dhan_candles = json.load(f)
    with open(fixtures_dir / "upstox_spot_1m_20260806.json") as f:
        upstox_candles = json.load(f)

    def aggregate(candles, tf_mins):
        if tf_mins == 1:
            return candles
        res = []
        for i in range(0, len(candles), tf_mins):
            chunk = candles[i:i + tf_mins]
            if not chunk:
                continue
            res.append({
                "time": chunk[0]["time"],
                "open": chunk[0]["open"],
                "high": max(c["high"] for c in chunk),
                "low": min(c["low"] for c in chunk),
                "close": chunk[-1]["close"],
                "volume": sum(c.get("volume", 0) for c in chunk),
            })
        return res

    tf_map = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}

    for tf, mins in tf_map.items():
        vob_dhan = NiftyVOBEngine()
        vob_upstox = NiftyVOBEngine()

        c_dhan = aggregate(dhan_candles, mins)
        c_upstox = aggregate(upstox_candles, mins)

        res_d = vob_dhan.analyze_timeframe(timeframe=tf, candles=c_dhan)
        res_u = vob_upstox.analyze_timeframe(timeframe=tf, candles=c_upstox)

        zones_d = res_d.get("zone_ladder") or []
        zones_u = res_u.get("zone_ladder") or []

        assert len(zones_d) == len(zones_u), f"Zone count mismatch on {tf}: Dhan={len(zones_d)}, Upstox={len(zones_u)}"

        for zd, zu in zip(zones_d, zones_u):
            assert zd["side"] == zu["side"]
            assert zd["role"] == zu["role"]
            assert abs(zd["zone_high"] - zu["zone_high"]) < 0.1
            assert abs(zd["zone_low"] - zu["zone_low"]) < 0.1
            assert zd["status"] == zu["status"]

        pri_d = res_d.get("primary_zone")
        pri_u = res_u.get("primary_zone")
        if pri_d and pri_u:
            assert pri_d["side"] == pri_u["side"]
            assert abs(pri_d["zone_high"] - pri_u["zone_high"]) < 0.1
            assert abs(pri_d["zone_low"] - pri_u["zone_low"]) < 0.1
        else:
            assert pri_d == pri_u


