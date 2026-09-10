"""Complete Price Action analyzer and FVG family engine for the Oracle Development segment."""

import math
from typing import Any, Dict, List, Optional, Tuple


class OracleDevPriceActionAnalyzer:
    """Computes all 15 locked Price Action modules and the FVG sub-family lifecycle."""

    def __init__(self, atr_period: int = 14):
        self.atr_period = atr_period

    @staticmethod
    def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> List[float]:
        """Calculate Average True Range (ATR) for a series of candles."""
        if len(candles) < 2:
            return [0.0] * len(candles)
        
        tr_list = []
        for i in range(len(candles)):
            if i == 0:
                tr_list.append(float(candles[i]["high"] - candles[i]["low"]))
            else:
                h = float(candles[i]["high"])
                l = float(candles[i]["low"])
                prev_c = float(candles[i-1]["close"])
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                tr_list.append(tr)

        atr = []
        if len(tr_list) >= period:
            # First ATR is simple average
            current_atr = sum(tr_list[:period]) / period
            for _ in range(period - 1):
                atr.append(0.0)
            atr.append(current_atr)

            for i in range(period, len(tr_list)):
                current_atr = (current_atr * (period - 1) + tr_list[i]) / period
                atr.append(current_atr)
        else:
            # Fallback
            atr = tr_list
        return atr

    @staticmethod
    def calculate_ema(candles: List[Dict[str, Any]], period: int) -> List[float]:
        """Calculate Exponential Moving Average (EMA)."""
        if not candles:
            return []
        closes = [float(c["close"]) for c in candles]
        ema = []
        k = 2.0 / (period + 1.0)
        
        for i, val in enumerate(closes):
            if i == 0:
                ema.append(val)
            else:
                ema.append(val * k + ema[-1] * (1.0 - k))
        return ema

    def analyze(
        self,
        spot_candles: List[Dict[str, Any]],
        futures_candles: List[Dict[str, Any]],
        underlying: str = "NIFTY"
    ) -> Dict[str, Any]:
        """Runs the 15 price action checks on Spot & Futures resampled candles."""
        if len(spot_candles) < 5:
            return {
                "score": 0,
                "regime": "WAITING_FOR_DATA",
                "swings": [],
                "fvg_family": [],
                "why": "Insufficient candle history",
                "no_chase": False,
                "factors": {}
            }

        # Calculate Spot technicals
        spot_atr = self.calculate_atr(spot_candles, self.atr_period)
        spot_ema20 = self.calculate_ema(spot_candles, 20)
        spot_ema50 = self.calculate_ema(spot_candles, 50)
        
        current_atr = spot_atr[-1] if spot_atr else 10.0
        last_spot = spot_candles[-1]
        prev_spot = spot_candles[-2]
        
        # 1. Swings & Swings history
        swings = self._detect_swings(spot_candles)
        
        # 2. Regime & Session State
        regime = self._determine_regime(spot_candles, spot_ema20, spot_ema50, spot_atr)
        
        # 3. Swing Structure: HH/HL, LL/LH
        structure_trend = self._analyze_swing_structure(swings)
        
        # 4. FVG Family lifecycle
        fvgs = self._detect_fvgs(spot_candles, spot_atr)
        
        # 5. Approach quality (exhaustion wicks vs breakout acceleration)
        approach = self._evaluate_approach(spot_candles, current_atr)
        
        # 6. Compression Squeezes
        compression = self._detect_compression(spot_candles, spot_atr)
        
        # 7. Expansion / Displacement
        displacement = self._detect_displacement(spot_candles, spot_atr)
        
        # 8. Breakout Anatomy
        breakout = self._analyze_breakout(spot_candles, swings)
        
        # 9. Acceptance vs Rejection
        acceptance = self._analyze_acceptance(spot_candles, swings)
        
        # 10. Liquidity Sweeps
        sweep = self._detect_sweeps(spot_candles, swings)
        
        # 11. Failed Breakout / Traps
        traps = self._detect_traps(spot_candles, swings)
        
        # 12. Range Engine
        range_state = self._evaluate_range(spot_candles, swings)
        
        # 13. Pullback Quality
        pullback = self._evaluate_pullback(spot_candles, spot_atr)
        
        # 14. Reversal / Exhaustion
        reversal = self._evaluate_reversal(spot_candles, spot_atr)
        
        # 15. Opening Structures
        opening = self._evaluate_opening(spot_candles)

        # 16. Spot-Futures relationship
        spot_fut_alignment = self._evaluate_spot_futures(spot_candles, futures_candles)

        # 17. Space & No-Chase Check
        no_chase, rr_ratio = self._evaluate_space_no_chase(spot_candles, swings, current_atr)

        # Calculate FVG Score Component (Max 8)
        fvg_score = 0
        fvg_types = set()
        for f in fvgs:
            if f["state"] in ("CREATED", "UNTOUCHED", "PARTIALLY_MITIGATED", "REACTION", "HELD", "CONTINUATION"):
                fvg_types.add(f["fvg_type"])
        
        # Assign points based on types found:
        # Breakaway (3), Retest/Continuation (3), Inversion (2)
        if "breakaway" in fvg_types:
            fvg_score += 3
        if "retest" in fvg_types or "continuation" in fvg_types:
            fvg_score += 3
        if "inversion" in fvg_types:
            fvg_score += 2
        fvg_score = min(8, fvg_score)

        # Calculate Price Action Score (out of 30)
        # Factor distribution:
        # - Regime & Swing Structure: HH/HL/BOS/CHOCH (8 pts)
        # - Breakout, Acceptance, Retest (6 pts)
        # - FVG Family (Max 8 pts)
        # - Sweeps & Traps (6 pts)
        # - EMA/RSI Minor Context (2 pts)
        pa_score = 0
        factors = {}
        
        # Swing/Structure points
        struct_pts = 0
        if structure_trend in ("BULLISH", "BEARISH"):
            struct_pts += 4
        if displacement.get("is_displacement"):
            struct_pts += 4
        pa_score += struct_pts
        factors["swing_structure"] = {"score": struct_pts, "status": "green" if struct_pts >= 6 else "amber", "val": structure_trend}

        # Breakout points
        bo_pts = 0
        if breakout.get("is_breakout"):
            bo_pts += 3
        if acceptance.get("is_accepted"):
            bo_pts += 3
        pa_score += bo_pts
        factors["breakout_anatomy"] = {"score": bo_pts, "status": "green" if bo_pts >= 4 else "grey", "val": "Accepted" if acceptance.get("is_accepted") else "None"}

        # FVG points
        pa_score += fvg_score
        factors["fvg_family"] = {"score": fvg_score, "status": "green" if fvg_score >= 5 else "grey", "val": list(fvg_types)}

        # Sweeps & Traps points
        sweep_pts = 0
        if sweep.get("is_sweep"):
            sweep_pts += 3
        if traps.get("is_trap"):
            sweep_pts += 3
        pa_score += sweep_pts
        factors["sweeps_traps"] = {"score": sweep_pts, "status": "green" if sweep_pts >= 3 else "grey", "val": "Trap" if traps.get("is_trap") else "None"}

        # Minor EMA alignment points
        ema_pts = 0
        close_last = float(last_spot["close"])
        if close_last > spot_ema20[-1] > spot_ema50[-1]:
            ema_pts = 2
        elif close_last < spot_ema20[-1] < spot_ema50[-1]:
            ema_pts = 2
        pa_score += ema_pts
        factors["minor_ema_context"] = {"score": ema_pts, "status": "green" if ema_pts == 2 else "grey", "val": "Aligned" if ema_pts == 2 else "Neutral"}

        # Veto checks
        why = f"Regime: {regime}. Structure: {structure_trend}."
        if no_chase:
            why += " WARNING: Missed / No-Chase threshold violated."
        if not spot_fut_alignment:
            why += " WARNING: Spot-Futures structural divergence."

        # 18. Historical Structural Events (BOS, CHoCH, sweep, breakout, acceptance, retest, trap)
        structure_events = self._detect_structure_events(spot_candles, swings, spot_atr)

        return {
            "score": min(30, pa_score),
            "regime": regime,
            "swings": swings,
            "fvg_family": fvgs,
            "why": why,
            "no_chase": no_chase,
            "factors": factors,
            "spot_futures_aligned": spot_fut_alignment,
            "compression_state": compression,
            "reversal_state": reversal,
            "range_state": range_state,
            "pullback_state": pullback,
            "opening_state": opening,
            "approach_state": approach,
            "structure_events": structure_events
        }

    def _detect_swings(self, candles: List[Dict[str, Any]], lookback: int = 2) -> List[Dict[str, Any]]:
        """Identify Swing Highs and Lows in a candle series."""
        swings = []
        for i in range(lookback, len(candles) - lookback):
            h = float(candles[i]["high"])
            l = float(candles[i]["low"])
            t = candles[i].get("time") or candles[i].get("timestamp")
            
            is_high = True
            is_low = True
            for j in range(1, lookback + 1):
                if float(candles[i-j]["high"]) >= h or float(candles[i+j]["high"]) >= h:
                    is_high = False
                if float(candles[i-j]["low"]) <= l or float(candles[i+j]["low"]) <= l:
                    is_low = False
            
            if is_high:
                swings.append({"type": "HIGH", "val": h, "index": i, "time": t})
            if is_low:
                swings.append({"type": "LOW", "val": l, "index": i, "time": t})
        return swings

    def _determine_regime(
        self,
        candles: List[Dict[str, Any]],
        ema20: List[float],
        ema50: List[float],
        atr: List[float]
    ) -> str:
        """Determines the market session regime."""
        last_close = float(candles[-1]["close"])
        last_ema20 = ema20[-1]
        last_ema50 = ema50[-1]
        
        # Check ATR to see expansion vs compression
        recent_atr = atr[-5:]
        is_compression = len(recent_atr) == 5 and recent_atr[-1] < sum(recent_atr) / 5.0
        
        if last_close > last_ema20 > last_ema50:
            return "strong_bull_trend" if not is_compression else "weak_bull_trend"
        elif last_close < last_ema20 < last_ema50:
            return "strong_bear_trend" if not is_compression else "weak_bear_trend"
        
        # Check BB width or close range bounds
        closes = [float(c["close"]) for c in candles[-10:]]
        max_c, min_c = max(closes), min(closes)
        if (max_c - min_c) < 1.5 * atr[-1]:
            return "tight_range"
        return "trading_range"

    def _analyze_swing_structure(self, swings: List[Dict[str, Any]]) -> str:
        """Determines structural trend from Swing Highs/Lows."""
        highs = [s for s in swings if s["type"] == "HIGH"]
        lows = [s for s in swings if s["type"] == "LOW"]
        
        if len(highs) >= 2 and len(lows) >= 2:
            h_trend = highs[-1]["val"] > highs[-2]["val"]
            l_trend = lows[-1]["val"] > lows[-2]["val"]
            if h_trend and l_trend:
                return "BULLISH"
            elif not h_trend and not l_trend:
                return "BEARISH"
        return "SIDEWAYS"

    def _detect_fvgs(self, candles: List[Dict[str, Any]], atr: List[float]) -> List[Dict[str, Any]]:
        """Scans for Fair Value Gaps and tracks their lifecycle including inversion (iFVG)."""
        fvgs = []
        
        for i in range(2, len(candles)):
            c_prev2 = candles[i-2]
            c_curr = candles[i]
            
            # 1. Detect Bullish FVG formation
            if float(c_curr["low"]) > float(c_prev2["high"]):
                fvg_zone = [float(c_prev2["high"]), float(c_curr["low"])]
                fvg_type = "bullish"
                is_breakaway = float(candles[i-1]["close"]) - float(candles[i-1]["open"]) > 1.5 * atr[i-1]
                if is_breakaway:
                    fvg_type = "breakaway"
                
                state = "CREATED"
                direction = "CALL"
                
                # Trace this FVG lifecycle on subsequent candles
                for j in range(i + 1, len(candles)):
                    low_j = float(candles[j]["low"])
                    high_j = float(candles[j]["high"])
                    close_j = float(candles[j]["close"])
                    
                    if fvg_type != "inversion":
                        if low_j < fvg_zone[1]:
                            # Entered the gap
                            if close_j < fvg_zone[0]:
                                # Inversion triggered (closed below)
                                state = "CREATED"
                                fvg_type = "inversion"
                                direction = "PUT"
                            elif low_j <= fvg_zone[0]:
                                # Touched bottom but close is not below: filled
                                state = "FULLY_FILLED"
                                break
                            else:
                                state = "PARTIALLY_MITIGATED"
                    else: # inversion active
                        if high_j > fvg_zone[0]:
                            # Entered gap from below
                            if close_j > fvg_zone[1]:
                                # Inverted FVG invalidated
                                state = "INVALIDATED"
                                break
                            elif high_j >= fvg_zone[1]:
                                # Fully filled from below
                                state = "FULLY_FILLED"
                                break
                            else:
                                state = "PARTIALLY_MITIGATED"
                                
                fvgs.append({
                    "fvg_type": fvg_type,
                    "direction": direction,
                    "zone": fvg_zone,
                    "state": state,
                    "index": i,
                    "time": c_curr.get("time") or c_curr.get("timestamp")
                })
                
            # 2. Detect Bearish FVG formation
            elif float(c_curr["high"]) < float(c_prev2["low"]):
                fvg_zone = [float(c_curr["high"]), float(c_prev2["low"])]
                fvg_type = "bearish"
                is_breakaway = float(candles[i-1]["open"]) - float(candles[i-1]["close"]) > 1.5 * atr[i-1]
                if is_breakaway:
                    fvg_type = "breakaway"
                
                state = "CREATED"
                direction = "PUT"
                
                for j in range(i + 1, len(candles)):
                    low_j = float(candles[j]["low"])
                    high_j = float(candles[j]["high"])
                    close_j = float(candles[j]["close"])
                    
                    if fvg_type != "inversion":
                        if high_j > fvg_zone[0]:
                            # Entered gap
                            if close_j > fvg_zone[1]:
                                # Inversion triggered (closed above)
                                state = "CREATED"
                                fvg_type = "inversion"
                                direction = "CALL"
                            elif high_j >= fvg_zone[1]:
                                # Touched top but close is not above: filled
                                state = "FULLY_FILLED"
                                break
                            else:
                                state = "PARTIALLY_MITIGATED"
                    else: # inversion active
                        if low_j < fvg_zone[1]:
                            # Entered gap from above
                            if close_j < fvg_zone[0]:
                                # Inverted FVG invalidated
                                state = "INVALIDATED"
                                break
                            elif low_j <= fvg_zone[0]:
                                # Fully filled from above
                                state = "FULLY_FILLED"
                                break
                            else:
                                state = "PARTIALLY_MITIGATED"
                                
                fvgs.append({
                    "fvg_type": fvg_type,
                    "direction": direction,
                    "zone": fvg_zone,
                    "state": state,
                    "index": i,
                    "time": c_curr.get("time") or c_curr.get("timestamp")
                })
                
        return fvgs

    def _detect_structure_events(
        self,
        candles: List[Dict[str, Any]],
        swings: List[Dict[str, Any]],
        atr: List[float]
    ) -> List[Dict[str, Any]]:
        if len(candles) < 5 or not swings:
            return []

        events = []
        current_trend = None # "BULLISH" or "BEARISH"
        
        for i in range(2, len(candles)):
            c = candles[i]
            c_close = float(c["close"])
            c_high = float(c["high"])
            c_low = float(c["low"])
            c_time = c.get("time") or c.get("timestamp")
            
            prior_swings = [s for s in swings if s["index"] < i]
            if not prior_swings:
                continue
                
            prior_highs = [s for s in prior_swings if s["type"] == "HIGH"]
            prior_lows = [s for s in prior_swings if s["type"] == "LOW"]
            
            last_high = prior_highs[-1] if prior_highs else None
            last_low = prior_lows[-1] if prior_lows else None
            
            # CHoCH & BOS
            if current_trend is None:
                if last_high and c_close > last_high["val"]:
                    current_trend = "BULLISH"
                    events.append({
                        "time": c_time,
                        "event_type": "CHOCH",
                        "direction": "CALL",
                        "level": last_high["val"],
                        "provenance": "Swing structure shift"
                    })
                elif last_low and c_close < last_low["val"]:
                    current_trend = "BEARISH"
                    events.append({
                        "time": c_time,
                        "event_type": "CHOCH",
                        "direction": "PUT",
                        "level": last_low["val"],
                        "provenance": "Swing structure shift"
                    })
            elif current_trend == "BULLISH":
                if last_high and c_close > last_high["val"]:
                    events.append({
                        "time": c_time,
                        "event_type": "BOS",
                        "direction": "CALL",
                        "level": last_high["val"],
                        "provenance": "Swing high extension"
                    })
                elif last_low and c_close < last_low["val"]:
                    current_trend = "BEARISH"
                    events.append({
                        "time": c_time,
                        "event_type": "CHOCH",
                        "direction": "PUT",
                        "level": last_low["val"],
                        "provenance": "Swing low shift"
                    })
            elif current_trend == "BEARISH":
                if last_low and c_close < last_low["val"]:
                    events.append({
                        "time": c_time,
                        "event_type": "BOS",
                        "direction": "PUT",
                        "level": last_low["val"],
                        "provenance": "Swing low extension"
                    })
                elif last_high and c_close > last_high["val"]:
                    current_trend = "BULLISH"
                    events.append({
                        "time": c_time,
                        "event_type": "CHOCH",
                        "direction": "CALL",
                        "level": last_high["val"],
                        "provenance": "Swing high shift"
                    })

            # Liquidity Sweep
            if last_high and c_high > last_high["val"] and c_close < last_high["val"]:
                events.append({
                    "time": c_time,
                    "event_type": "SWEEP",
                    "direction": "PUT",
                    "level": last_high["val"],
                    "provenance": "High liquidity sweep"
                })
            if last_low and c_low < last_low["val"] and c_close > last_low["val"]:
                events.append({
                    "time": c_time,
                    "event_type": "SWEEP",
                    "direction": "CALL",
                    "level": last_low["val"],
                    "provenance": "Low liquidity sweep"
                })

            # Breakout & Acceptance
            if last_high and c_close > last_high["val"]:
                if i + 1 < len(candles) and float(candles[i+1]["close"]) > last_high["val"]:
                    events.append({
                        "time": c_time,
                        "event_type": "ACCEPTANCE",
                        "direction": "CALL",
                        "level": last_high["val"],
                        "provenance": "High breakout accepted"
                    })
                else:
                    events.append({
                        "time": c_time,
                        "event_type": "BREAKOUT",
                        "direction": "CALL",
                        "level": last_high["val"],
                        "provenance": "High breakout attempt"
                    })
            elif last_low and c_close < last_low["val"]:
                if i + 1 < len(candles) and float(candles[i+1]["close"]) < last_low["val"]:
                    events.append({
                        "time": c_time,
                        "event_type": "ACCEPTANCE",
                        "direction": "PUT",
                        "level": last_low["val"],
                        "provenance": "Low breakout accepted"
                    })
                else:
                    events.append({
                        "time": c_time,
                        "event_type": "BREAKOUT",
                        "direction": "PUT",
                        "level": last_low["val"],
                        "provenance": "Low breakout attempt"
                    })

            # Failed Breakout / Trap
            if last_high and c_close > last_high["val"]:
                if i + 1 < len(candles) and float(candles[i+1]["close"]) < last_high["val"]:
                    events.append({
                        "time": c_time,
                        "event_type": "TRAP",
                        "direction": "PUT",
                        "level": last_high["val"],
                        "provenance": "Bull trap"
                    })
            elif last_low and c_close < last_low["val"]:
                if i + 1 < len(candles) and float(candles[i+1]["close"]) > last_low["val"]:
                    events.append({
                        "time": c_time,
                        "event_type": "TRAP",
                        "direction": "CALL",
                        "level": last_low["val"],
                        "provenance": "Bear trap"
                    })

            # Retest
            if len(events) >= 2:
                for ev in reversed(events[:-1]):
                    if ev["event_type"] in ("BREAKOUT", "ACCEPTANCE") and ev["level"] == (last_high["val"] if ev["direction"] == "CALL" else last_low["val"]):
                        if ev["direction"] == "CALL":
                            if c_low <= last_high["val"] and c_close >= last_high["val"]:
                                events.append({
                                    "time": c_time,
                                    "event_type": "RETEST",
                                    "direction": "CALL",
                                    "level": last_high["val"],
                                    "provenance": "Breakout support retest"
                                })
                        else:
                            if c_high >= last_low["val"] and c_close <= last_low["val"]:
                                events.append({
                                    "time": c_time,
                                    "event_type": "RETEST",
                                    "direction": "PUT",
                                    "level": last_low["val"],
                                    "provenance": "Breakout resistance retest"
                                })
                        break

        seen = set()
        dedup_events = []
        for e in events:
            key = (e["time"], e["event_type"])
            if key not in seen:
                seen.add(key)
                dedup_events.append(e)
                
        return dedup_events

    def _evaluate_approach(self, candles: List[Dict[str, Any]], current_atr: float) -> Dict[str, Any]:
        """Evaluates approach quality (accelerating breakdown vs exhausting wicks)."""
        last_body = abs(float(candles[-1]["close"]) - float(candles[-1]["open"]))
        prev_body = abs(float(candles[-2]["close"]) - float(candles[-2]["open"]))
        
        is_accelerating = last_body > prev_body and last_body > 1.0 * current_atr
        
        last_candle = candles[-1]
        body_mid = (float(last_candle["close"]) + float(last_candle["open"])) / 2.0
        high = float(last_candle["high"])
        low = float(last_candle["low"])
        
        # Exhausting approach: large wicks relative to body
        is_exhausting = (high - low) > 2.0 * last_body
        return {
            "is_accelerating": is_accelerating,
            "is_exhausting": is_exhausting
        }

    def _detect_compression(self, candles: List[Dict[str, Any]], atr: List[float]) -> Dict[str, Any]:
        """Checks for shrinking ranges (coiling / BB squeezes)."""
        recent_ranges = [float(c["high"] - c["low"]) for c in candles[-5:]]
        is_squeezing = recent_ranges[-1] < recent_ranges[-2] < recent_ranges[-3]
        return {
            "is_squeezing": is_squeezing,
            "current_range": recent_ranges[-1]
        }

    def _detect_displacement(self, candles: List[Dict[str, Any]], atr: List[float]) -> Dict[str, Any]:
        """Detects high-momentum displacement expansion."""
        last = candles[-1]
        body = abs(float(last["close"]) - float(last["open"]))
        is_displacement = body > 1.8 * atr[-1]
        return {
            "is_displacement": is_displacement,
            "direction": "BULL" if float(last["close"]) > float(last["open"]) else "BEAR"
        }

    def _analyze_breakout(self, candles: List[Dict[str, Any]], swings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Tracks breakout attempts on prior swing highs/lows."""
        if not swings:
            return {"is_breakout": False}
        
        highs = [s["val"] for s in swings if s["type"] == "HIGH"]
        lows = [s["val"] for s in swings if s["type"] == "LOW"]
        
        last_close = float(candles[-1]["close"])
        
        if highs and last_close > highs[-1]:
            return {"is_breakout": True, "direction": "UP", "level": highs[-1]}
        elif lows and last_close < lows[-1]:
            return {"is_breakout": True, "direction": "DOWN", "level": lows[-1]}
        
        return {"is_breakout": False}

    def _analyze_acceptance(self, candles: List[Dict[str, Any]], swings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Verifies acceptance outside breakout levels (consecutive closes)."""
        bo = self._analyze_breakout(candles, swings)
        if not bo.get("is_breakout") or len(candles) < 2:
            return {"is_accepted": False}
        
        prev_close = float(candles[-2]["close"])
        level = bo["level"]
        
        if bo["direction"] == "UP" and prev_close > level:
            return {"is_accepted": True}
        elif bo["direction"] == "DOWN" and prev_close < level:
            return {"is_accepted": True}
            
        return {"is_accepted": False}

    def _detect_sweeps(self, candles: List[Dict[str, Any]], swings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detects liquidity sweep wicks on swing boundaries."""
        if not swings or len(candles) < 1:
            return {"is_sweep": False}

        highs = [s["val"] for s in swings if s["type"] == "HIGH"]
        lows = [s["val"] for s in swings if s["type"] == "LOW"]
        
        last = candles[-1]
        h_last = float(last["high"])
        l_last = float(last["low"])
        c_last = float(last["close"])
        
        if highs and h_last > highs[-1] and c_last < highs[-1]:
            return {"is_sweep": True, "direction": "PUT", "level": highs[-1]}
        elif lows and l_last < lows[-1] and c_last > lows[-1]:
            return {"is_sweep": True, "direction": "CALL", "level": lows[-1]}
            
        return {"is_sweep": False}

    def _detect_traps(self, candles: List[Dict[str, Any]], swings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detects bull/bear traps where breakouts immediately fail."""
        if len(candles) < 2:
            return {"is_trap": False}
        
        prev_bo = self._analyze_breakout(candles[:-1], swings)
        if not prev_bo.get("is_breakout"):
            return {"is_trap": False}
            
        last_close = float(candles[-1]["close"])
        level = prev_bo["level"]
        
        if prev_bo["direction"] == "UP" and last_close < level:
            return {"is_trap": True, "type": "BULL_TRAP"}
        elif prev_bo["direction"] == "DOWN" and last_close > level:
            return {"is_trap": True, "type": "BEAR_TRAP"}
            
        return {"is_trap": False}

    def _evaluate_range(self, candles: List[Dict[str, Any]], swings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Measures range high, low, midpoint, and edge rotation."""
        if not swings:
            return {"is_range": False}
        
        highs = [s["val"] for s in swings if s["type"] == "HIGH"]
        lows = [s["val"] for s in swings if s["type"] == "LOW"]
        
        if not highs or not lows:
            return {"is_range": False}
            
        r_high = max(highs[-3:]) if len(highs) >= 3 else highs[-1]
        r_low = min(lows[-3:]) if len(lows) >= 3 else lows[-1]
        
        midpoint = (r_high + r_low) / 2.0
        width = r_high - r_low
        
        last_close = float(candles[-1]["close"])
        dist_from_mid = abs(last_close - midpoint)
        
        # Range-middle avoidance
        in_middle = dist_from_mid < 0.25 * width
        
        return {
            "is_range": True,
            "range_high": r_high,
            "range_low": r_low,
            "midpoint": midpoint,
            "width": width,
            "in_middle": in_middle
        }

    def _evaluate_pullback(self, candles: List[Dict[str, Any]], atr: List[float]) -> Dict[str, Any]:
        """Measures pullback volume, depth, and leg quality."""
        closes = [float(c["close"]) for c in candles[-5:]]
        vols = [float(c["volume"]) for c in candles[-5:] if c.get("volume")]
        
        is_pullback = False
        descending_vol = False
        
        if len(closes) >= 3:
            # Price retracing (e.g. close decreasing in bull trend)
            is_pullback = closes[-1] < closes[-2] < closes[-3]
        if len(vols) >= 3:
            descending_vol = vols[-1] < vols[-2] < vols[-3]
            
        return {
            "is_pullback": is_pullback,
            "descending_vol": descending_vol
        }

    def _evaluate_reversal(self, candles: List[Dict[str, Any]], atr: List[float]) -> Dict[str, Any]:
        """Evaluates reversal clues (exhaustion pin bars, effort vs result)."""
        last = candles[-1]
        h = float(last["high"])
        l = float(last["low"])
        c = float(last["close"])
        o = float(last["open"])
        
        body = abs(c - o)
        rng = h - l
        
        is_exhaustion_candle = rng > 1.8 * atr[-1] and body < 0.3 * rng
        return {
            "is_exhaustion": is_exhaustion_candle,
            "pin_direction": "CALL" if c > (h + l)/2.0 else "PUT"
        }

    def _evaluate_opening(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detects opening drive / gaps relative to session boundary."""
        import datetime
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        
        if len(candles) < 2:
            return {"opening_type": "neutral", "is_gap_up": False, "is_gap_down": False}
            
        first_candle = candles[0]
        t_val = first_candle.get("time") or first_candle.get("timestamp")
        
        # Determine if the session is currently in the opening hour (09:15 - 10:15 IST)
        last_candle = candles[-1]
        last_t = last_candle.get("time") or last_candle.get("timestamp")
        
        try:
            if isinstance(t_val, (int, float)):
                dt = datetime.datetime.fromtimestamp(t_val, tz=IST)
            else:
                dt = datetime.datetime.fromisoformat(str(t_val).replace("Z", "+00:00")).astimezone(IST)
                
            if isinstance(last_t, (int, float)):
                last_dt = datetime.datetime.fromtimestamp(last_t, tz=IST)
            else:
                last_dt = datetime.datetime.fromisoformat(str(last_t).replace("Z", "+00:00")).astimezone(IST)
                
            is_opening_hour = (last_dt.hour == 9) or (last_dt.hour == 10 and last_dt.minute <= 15)
        except Exception:
            is_opening_hour = True
        
        if not is_opening_hour:
            return {"opening_type": "regular_session", "is_gap_up": False, "is_gap_down": False}
            
        open_price = float(first_candle["open"])
        current_price = float(last_candle["close"])
        
        # Calculate percent change since open
        pct_change = (current_price - open_price) / max(1.0, open_price)
        
        if pct_change > 0.005:
            opening_type = "opening_drive_bullish"
        elif pct_change < -0.005:
            opening_type = "opening_drive_bearish"
        else:
            opening_type = "opening_range_bound"
            
        return {
            "opening_type": opening_type,
            "is_gap_up": pct_change > 0.002,
            "is_gap_down": pct_change < -0.002,
            "pct_change_since_open": round(pct_change * 100, 2)
        }

    def _evaluate_spot_futures(self, spot: List[Dict[str, Any]], futures: List[Dict[str, Any]]) -> bool:
        """Verifies structural agreement between Spot Index and Futures Index."""
        if not spot or not futures:
            return True
        
        # Check alignment of recent direction
        spot_dir = float(spot[-1]["close"]) - float(spot[-1]["open"])
        fut_dir = float(futures[-1]["close"]) - float(futures[-1]["open"])
        
        # If directions are violently opposed, mark divergence
        if (spot_dir > 0 and fut_dir < -0.1 * spot_dir) or (spot_dir < 0 and fut_dir > -0.1 * spot_dir):
            return False
        return True

    def _evaluate_space_no_chase(
        self,
        candles: List[Dict[str, Any]],
        swings: List[Dict[str, Any]],
        current_atr: float
    ) -> Tuple[bool, float]:
        """Checks if current price is too far from structural invalidation (chase check)."""
        if not candles or not swings:
            return False, 2.0
            
        last_close = float(candles[-1]["close"])
        
        highs = [s["val"] for s in swings if s["type"] == "HIGH"]
        lows = [s["val"] for s in swings if s["type"] == "LOW"]
        
        # Resolve structural SL point
        struct_sl = last_close
        if last_close > float(candles[-1]["open"]):
            # Long entry candidate: invalidation is the nearest swing low
            if lows:
                struct_sl = lows[-1]
        else:
            # Short entry candidate: invalidation is the nearest swing high
            if highs:
                struct_sl = highs[-1]

        distance = abs(last_close - struct_sl)
        no_chase = distance > 1.8 * current_atr
        
        # Estimate target spacing
        target_space = 2.5 * current_atr
        rr = target_space / max(1.0, distance)
        
        return no_chase, rr
