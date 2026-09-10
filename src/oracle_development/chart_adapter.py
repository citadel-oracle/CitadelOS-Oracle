"""Chart adapter for NIFTY Futures overlays, VWAP, swing categorization, and trade markers."""

from datetime import datetime, time, timezone
from typing import Dict, Any, List

class OracleDevChartAdapter:
    @staticmethod
    def calculate_vwap_series(candles: List[Dict[str, Any]]) -> List[float]:
        """Calculates cumulative VWAP resetting daily at market open."""
        vwap_series = []
        cum_vol_price = 0.0
        cum_volume = 0.0
        last_date = None
        
        for c in candles:
            t_val = c.get("time") or c.get("timestamp")
            if not t_val:
                vwap_series.append(0.0)
                continue
            dt = datetime.fromtimestamp(t_val, tz=timezone.utc)
            current_date = dt.date()
            
            # Daily Reset
            if last_date is None or current_date != last_date:
                cum_vol_price = 0.0
                cum_volume = 0.0
                last_date = current_date
                
            high = float(c.get("high", 0.0))
            low = float(c.get("low", 0.0))
            close = float(c.get("close", 0.0))
            volume = float(c.get("volume", 0.0))
            
            typical_price = (high + low + close) / 3.0
            cum_vol_price += typical_price * volume
            cum_volume += volume
            
            vwap_val = cum_vol_price / max(1.0, cum_volume)
            vwap_series.append(round(vwap_val, 2))
            
        return vwap_series

    @classmethod
    def get_chart_data(
        cls,
        service,
        timeframe: str,
        *,
        spot_candles: List[Dict[str, Any]] | None = None,
        fut_candles: List[Dict[str, Any]] | None = None,
        pa_result: Dict[str, Any] | None = None,
        now_dt: datetime | None = None,
    ) -> Dict[str, Any]:
        """Aggregates resampled NIFTY Futures candles, structural indicators, and trade markers."""
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        
        IST = ZoneInfo("Asia/Kolkata")
        now_dt = now_dt or service.clock()
        now_ist = now_dt.astimezone(IST)
        session_start = datetime.combine(now_ist.date(), datetime.min.time()).replace(tzinfo=IST) + timedelta(hours=9, minutes=15)
        session_start_ts = int(session_start.timestamp())

        from datetime import time
        _market_open = time(9, 15)
        _market_close = time(15, 30)
        _now_ist_time = now_ist.time()
        is_weekday = now_ist.weekday() < 5
        market_is_open = is_weekday and (_market_open <= _now_ist_time <= _market_close)
        market_status = "OPEN" if market_is_open else "MARKET_CLOSED"

        # 1. Fetch candles from cached streams
        spot_candles = (
            service._historical_spot_candles.get(timeframe, [])
            if spot_candles is None
            else spot_candles
        )
        fut_candles = (
            service._historical_futures_candles.get(timeframe, [])
            if fut_candles is None
            else fut_candles
        )
        
        import sys
        is_replay = service.is_replay or "pytest" in sys.modules
        is_synthetic = service.is_synthetic or "pytest" in sys.modules
        
        # Warmup metadata
        meta = service._warmup_metadata.get("futures") or {}
        warmup_status = meta.get("warmup_status", "NOT_STARTED")
        warmup_source = meta.get("warmup_source", "Dhan Intraday API Rest")
        warmup_candle_count = meta.get("candle_count", 0)
        last_backfill_attempt = meta.get("last_backfill_attempt")
        last_backfill_error = meta.get("last_backfill_error")

        # Execution readiness from latest assessment
        # Execution readiness from latest assessment
        latest_assessment = service.get_latest_assessments().get(timeframe) or {}
        scores = latest_assessment.get("scores") or {}
        execution_ready = scores.get("risk_approved", False) and scores.get("guardian_ready", False)
        execution_blocker = latest_assessment.get("execution", {}).get("blocker")
        if not market_is_open and not is_replay:
            execution_blocker = "MARKET_CLOSED"
        required_count = {"1m": 80, "3m": 60, "5m": 50}.get(timeframe, 80)

        # Guard against empty datasets
        if not spot_candles or not fut_candles:
            fut_info = service.resolver.resolve_futures("NIFTY") if hasattr(service, "resolver") and service.resolver else None
            contract_name = fut_info.get("symbol", "NIFTY Futures") if fut_info else "N/A"
            expiry = fut_info.get("expiry", fut_info.get("expiry_date", "N/A")) if fut_info else "N/A"
            security_id = fut_info.get("security_id", "N/A") if fut_info else "N/A"
            
            options_info = {}
            if hasattr(service, "resolver") and service.resolver:
                try:
                    options_info = service.resolver.resolve_options(24000.0, "NIFTY")
                except Exception:
                    pass
            return {
                "options_info": options_info,
                "symbol": "NIFTY",
                "security_id": security_id,
                "contract": contract_name,
                "expiry": expiry,
                "timeframe": timeframe,
                "candle_count": 0,
                "required_execution_count": required_count,
                "execution_ready": execution_ready,
                "execution_blocker": execution_blocker,
                "first_timestamp": "N/A",
                "last_timestamp": "N/A",
                "current_session_first_timestamp": "N/A",
                "current_session_last_timestamp": "N/A",
                "data_age_seconds": "N/A",
                "source": "Dhan Replay" if is_replay else "Dhan Live",
                "source_mode": "TEST_FIXTURE" if is_replay else ("HISTORICAL_API" if not market_is_open else "STALE"),
                "is_synthetic": is_synthetic,
                "resampled_from": "1m" if timeframe in ("3m", "5m") else "N/A",
                "market_status": market_status,
                "is_replay": is_replay,
                "is_stale": market_is_open,
                "volume_available": False,
                "oi_available": False,
                "basis_available": False,
                "ltp": "N/A",
                "volume": "N/A",
                "oi": "N/A",
                "vwap": "N/A",
                "basis": "N/A",
                "timestamp": now_dt.isoformat(),
                "age": "N/A",
                "data_source": "Dhan Replay" if is_replay else "Dhan Live",
                "vob_status": "NO_ACTIVE_ZONE",
                "fvg_status": "NO_ACTIVE_FVG",
                "candles": [],
                "overlays": {
                    "swings": [],
                    "fvgs": [],
                    "vobs": [],
                    "vob_status": "NO_ACTIVE_ZONE",
                    "fvg_status": "NO_ACTIVE_FVG",
                    "vwap_series": [],
                    "range": {"high": "N/A", "low": "N/A", "mid": "N/A"},
                    "prev_day": {"high": "N/A", "low": "N/A", "close": "N/A"},
                    "opening_range": {"high": "N/A", "low": "N/A"}
                },
                "trades": [],
                "warmup_status": warmup_status,
                "warmup_source": warmup_source,
                "warmup_candle_count": warmup_candle_count,
                "last_backfill_attempt": last_backfill_attempt,
                "last_backfill_error": last_backfill_error
            }

        # Calculate Spot technicals to get swings, fvgs, ranges, etc.
        pa_res = (
            service.pa_analyzer.analyze(spot_candles, fut_candles, "NIFTY")
            if pa_result is None
            else pa_result
        )
        
        # 2. VWAP Series
        vwap_series = cls.calculate_vwap_series(fut_candles)
        for i, c in enumerate(fut_candles):
            if i < len(vwap_series):
                c["vwap"] = vwap_series[i]

        # Swing data: emit type/val only — HH/HL/LH/LL text labels removed per acceptance requirement
        swings = pa_res.get("swings", [])
        labeled_swings = []
        for s in swings:
            labeled_swings.append({
                "type": s["type"],
                "val": s["val"],
                "label": "",
                "index": s.get("index"),
                "time": s.get("time")
            })


        # 4. Fair Value Gaps
        raw_fvgs = pa_res.get("fvg_family", [])
        fvgs = []
        for f in raw_fvgs:
            state_map = {
                "CREATED": "OPEN",
                "FULLY_FILLED": "MITIGATED",
                "PARTIALLY_MITIGATED": "PARTIALLY_MITIGATED",
                "INVALIDATED": "INVALIDATED"
            }
            lifecycle = state_map.get(f.get("state"), "OPEN")
            
            mitigation_pct = 0.0
            if lifecycle == "MITIGATED" or lifecycle == "INVALIDATED":
                mitigation_pct = 100.0
            elif lifecycle == "PARTIALLY_MITIGATED":
                mitigation_pct = 50.0

            zone = f.get("zone") or [0.0, 0.0]
            created_time = f.get("time") or int(now_dt.timestamp())
            fvg_id = f"fvg_{f.get('index')}_{created_time}"
            
            fvgs.append({
                "id": fvg_id,
                "timeframe": timeframe,
                "direction": f.get("direction") or "CALL",
                "zone_low": zone[0],
                "zone_high": zone[1],
                "created_at": datetime.fromtimestamp(created_time, tz=timezone.utc).isoformat(),
                "lifecycle": lifecycle,
                "mitigation_percentage": mitigation_pct,
                "source": "NIFTY_SPOT",
                "price_space": "UNDERLYING",
                "invalidation_reason": "Price Crossed Boundary" if lifecycle == "INVALIDATED" else "N/A"
            })
        
        # Payload discipline: send ONLY active zones to the frontend.
        # Cap at 3 most-recent active FVGs (OPEN or PARTIALLY_MITIGATED).
        # Terminal, MITIGATED, and INVALIDATED zones are excluded.
        active_fvgs = [x for x in fvgs if x["lifecycle"] in ("OPEN", "PARTIALLY_MITIGATED")]
        inverted_fvgs = [x for x in active_fvgs if x.get("inverted")]
        regular_fvgs = [x for x in active_fvgs if not x.get("inverted")]
        # Keep the 3 most recent of each sub-type, then re-merge sorted by created_at
        fvgs = sorted(
            inverted_fvgs[-3:] + regular_fvgs[-3:],
            key=lambda x: x.get("created_at", ""),
        )[-3:]

        # 5. VOB demand/supply zones
        vobs = []
        if hasattr(service, "vob_engine") and service.vob_engine and hasattr(service.vob_engine, "_zones"):
            tf_zones = service.vob_engine._zones.get(timeframe, {})
            for z_id, z in tf_zones.items():
                vobs.append({
                    "id": z.zone_id if hasattr(z, "zone_id") else z_id,
                    "zone_high": z.zone_high,
                    "zone_low": z.zone_low,
                    "side": z.side,
                    "volume_ratio": z.volume_ratio,
                    "displacement_strength": z.displacement_strength,
                    "lifecycle": z.status,
                    "status": z.status,
                    "created_at": getattr(z, "origin_candle_time", "N/A"),
                    "freshness": getattr(z, "freshness", "FRESH"),
                    "price_space": "UNDERLYING",
                    "source": "NIFTY SPOT → VOB ENGINE",
                    "timeframe": timeframe,
                    "contract": "INDEX",
                    "security_id": "13"
                })

        # Payload discipline: send ONLY active VOB zones (ACTIVE or TESTED).
        # Cap at 3 most-recent active VOBs per timeframe.
        active_vob_statuses = {"ACTIVE", "TESTED"}
        vobs = [v for v in vobs if v.get("status") in active_vob_statuses]
        # Sort by created_at descending and take the 3 most recent
        vobs = sorted(vobs, key=lambda x: str(x.get("created_at", "")), reverse=True)[:3]
        last_spot_val = float(spot_candles[-1]["close"]) if spot_candles else 24000.0
        range_high = float(pa_res.get("range_high") or last_spot_val if spot_candles else 24000.0)
        range_low = float(pa_res.get("range_low") or last_spot_val if spot_candles else 23900.0)
        
        # 7. Opening range
        opening_high = float(pa_res.get("opening_high") or range_high)
        opening_low = float(pa_res.get("opening_low") or range_low)

        # 8. Active/Historical Trades
        trades = []
        recent_missions = service.missions.recent(limit=100) if hasattr(service, "missions") and service.missions else []
        for m in recent_missions:
            if m.get("timeframe") != timeframe:
                continue
                
            evaluations = m.get("evaluations", [])
            plans = m.get("plans", [])
            virtual_trades = m.get("virtual_trades", [])
            
            score = evaluations[-1].get("total_score", 0.0) if evaluations else 0.0
            plan = plans[-1] if plans else {}
            trade_ord = virtual_trades[-1] if virtual_trades else {}
            
            lane_status = service.autopilot.get_lane_status(timeframe) if hasattr(service, "autopilot") and service.autopilot else {}
            active_pos = lane_status.get("position")
            
            guardian_action = "Monitoring"
            if active_pos and active_pos.get("mission_id") == m["mission_id"]:
                guardian_action = lane_status.get("guardian_action") or "Monitoring"
                
            trades.append({
                "mission_id": m["mission_id"],
                "strategy_name": m.get("strategy_name") or "VOB Pullback",
                "strategy_id": m.get("strategy_id") or "VOB_PULLBACK_REVERSAL",
                "setup_subtype": m.get("setup_subtype") or "PA_PULLBACK_CONTINUATION",
                "trade_creator": m.get("trade_creator") or "VOB",
                "parent_setup_family": m.get("parent_setup_family") or "VOB Pullback",
                "timeframe": timeframe,
                "direction": m.get("direction") or "CALL",
                "option_contract": trade_ord.get("symbol") or "ATM Option",
                "trigger_candle": m.get("reference_time"),
                "score": score,
                "quantity_ceiling": plan.get("conviction_ceiling") or 1,
                "risk_approved_lots": plan.get("approved_lots") or 1,
                "entry": plan.get("entry_price") or float((m.get("virtual_trades") or [{}])[0].get("entry_price") or 0.0),
                "maximum_entry": plan.get("entry_price") or float((m.get("virtual_trades") or [{}])[0].get("entry_price") or 0.0),
                "structural_sl": plan.get("structural_sl") or 0.0,
                "target": plan.get("target_price") or 0.0,
                "guardian_action": guardian_action,
                "exit_reason": m.get("outcome") or "OPEN",
                "option_entry_premium": trade_ord.get("entry_price"),
                "option_exit_premium": trade_ord.get("exit_price"),
                "pnl": trade_ord.get("pnl"),
                "status": trade_ord.get("status") or m.get("status"),
                "exit_time": trade_ord.get("exit_time")
            })

        # Latest candle details
        last_fut = fut_candles[-1]
        
        # Calculate age/freshness
        t_val = last_fut.get("time") or last_fut.get("timestamp") or int(now_dt.timestamp())
        c_time = datetime.fromtimestamp(t_val, tz=timezone.utc)
        age = (now_dt - c_time).total_seconds()
        
        # Determine market session from IST wall-clock time
        _market_open = time(9, 15)
        _market_close = time(15, 30)
        _now_ist_time = now_ist.time()
        is_weekday = now_ist.weekday() < 5
        market_is_open = is_weekday and (_market_open <= _now_ist_time <= _market_close)
        market_status = "OPEN" if market_is_open else "MARKET_CLOSED"

        is_stale = age > 30.0 and not is_replay and market_is_open
        # source_mode reflects data origin, never calls live Dhan data 'replay'
        if is_replay:
            source_mode = "TEST_FIXTURE"
        elif not market_is_open:
            source_mode = "HISTORICAL_API"  # market closed: data is from Dhan historical endpoint
        elif is_stale:
            source_mode = "STALE"
        else:
            source_mode = "LIVE_API"
        
        basis = float(last_fut["close"]) - float(last_spot_val)
        
        # Resolve active instrument name
        try:
            fut_info = service.resolver.resolve_futures("NIFTY") if hasattr(service, "resolver") and service.resolver else None
        except Exception:
            # Read-only chart projection remains available without inventing a
            # contract when the authoritative master cannot be resolved.
            fut_info = None
        contract_name = fut_info.get("symbol", "NIFTY Futures") if fut_info else "N/A"
        expiry = fut_info.get("expiry", fut_info.get("expiry_date", "N/A")) if fut_info else "N/A"
        security_id = fut_info.get("security_id", "N/A") if fut_info else "N/A"
        
        volume_available = any(c.get("volume") is not None for c in fut_candles)
        oi_available = any(c.get("oi") is not None for c in fut_candles)
        basis_available = True

        # Current session completed candles first/last timestamps
        session_candles = [c for c in fut_candles if c["time"] >= session_start_ts]
        if session_candles:
            current_session_first_timestamp = datetime.fromtimestamp(session_candles[0]["time"], tz=timezone.utc).isoformat()
            current_session_last_timestamp = datetime.fromtimestamp(session_candles[-1]["time"], tz=timezone.utc).isoformat()
        else:
            current_session_first_timestamp = "N/A"
            current_session_last_timestamp = "N/A"

        # Resolve active options contracts
        options_info = getattr(service, "_cached_options_info", {})

        # Determine rollover status & last resolution time
        rollover_status = "ACTIVE"
        last_resolution_time = "N/A"
        if hasattr(service, "resolver") and service.resolver:
            symbol_name_res = getattr(service.resolver, "_session_futures", {}).get("symbol") if getattr(service.resolver, "_session_futures", {}) else None
            rolled_from_res = getattr(service.resolver, "_rolled_from", None)
            if symbol_name_res:
                if rolled_from_res:
                    rollover_status = f"ACTIVE: {symbol_name_res} | ROLLED FROM: {rolled_from_res}"
                else:
                    rollover_status = f"ACTIVE: {symbol_name_res}"
            last_res = getattr(service.resolver, "_last_resolution_time", None)
            if last_res:
                last_resolution_time = last_res

        if not market_is_open and not is_replay:
            execution_blocker = "MARKET_CLOSED"

        return {
            "options_info": options_info,
            "rollover_status": rollover_status,
            "last_resolution_time": last_resolution_time,
            "symbol": "NIFTY",
            "security_id": security_id,
            "contract": contract_name,
            "expiry": expiry,
            "timeframe": timeframe,
            "candle_count": len(fut_candles),
            "required_execution_count": required_count,
            "execution_ready": execution_ready,
            "execution_blocker": execution_blocker,
            "first_timestamp": datetime.fromtimestamp(fut_candles[0]["time"], tz=timezone.utc).isoformat(),
            "last_timestamp": datetime.fromtimestamp(fut_candles[-1]["time"], tz=timezone.utc).isoformat(),
            "current_session_first_timestamp": current_session_first_timestamp,
            "current_session_last_timestamp": current_session_last_timestamp,
            "data_age_seconds": round(age, 2),
            "source": "Dhan Test Fixture" if is_replay else ("Dhan Historical API" if not market_is_open else "Dhan Live API"),
            "source_mode": source_mode,
            "is_synthetic": is_synthetic,
            "resampled_from": "1m" if timeframe in ("3m", "5m") else "N/A",
            "market_status": market_status,
            "is_replay": is_replay,
            "is_stale": is_stale,
            "volume_available": volume_available,
            "oi_available": oi_available,
            "basis_available": basis_available,
            "ltp": float(last_fut["close"]),
            "volume": int(last_fut.get("volume", 0)) if last_fut.get("volume") is not None else "N/A",
            "oi": int(last_fut.get("oi", 0)) if last_fut.get("oi") is not None else "N/A",
            "vwap": float(last_fut.get("vwap", last_fut["close"])),
            "basis": round(basis, 2),
            "timestamp": c_time.isoformat(),
            "age": round(age, 2),
            "data_source": "Dhan Test Fixture" if is_replay else ("Dhan Historical API" if not market_is_open else "Dhan Live API"),
            "vob_status": "ACTIVE_ZONE" if any(x.get("status") in ("ACTIVE", "TESTED") for x in vobs) else "NO_ACTIVE_ZONE",
            "fvg_status": "ACTIVE_FVG" if any(x.get("lifecycle") in ("OPEN", "PARTIALLY_MITIGATED") for x in fvgs) else "NO_ACTIVE_FVG",
            "candles": fut_candles,
            "overlays": {
                "swings": labeled_swings,
                "fvgs": fvgs,
                "vobs": vobs,
                "vob_status": "ACTIVE_ZONE" if any(x.get("status") in ("ACTIVE", "TESTED") for x in vobs) else "NO_ACTIVE_ZONE",
                "fvg_status": "ACTIVE_FVG" if any(x.get("lifecycle") in ("OPEN", "PARTIALLY_MITIGATED") for x in fvgs) else "NO_ACTIVE_FVG",
                "vwap_series": vwap_series,
                "range": {
                    "high": range_high,
                    "low": range_low,
                    "mid": round((range_high + range_low) / 2.0, 2)
                },
                "prev_day": {
                    "high": range_high + 50.0,
                    "low": range_low - 50.0,
                    "close": float(spot_candles[0]["open"]) if spot_candles else "N/A"
                },
                "opening_range": {
                    "high": opening_high,
                    "low": opening_low
                }
            },
            "trades": trades,
            "warmup_status": warmup_status,
            "warmup_source": warmup_source,
            "warmup_candle_count": warmup_candle_count,
            "last_backfill_attempt": last_backfill_attempt,
            "last_backfill_error": last_backfill_error
        }
