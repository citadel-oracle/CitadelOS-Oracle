"""Upstox Market Information and Global Intelligence Service.

Periodically queries factual market information endpoints from Upstox:
- PCR (Put-Call Ratio)
- Max Pain
- Open Interest & Change in OI
- FII / DII Institutional Flows
- Real-time India VIX and GIFT Nifty quotes

Exposes cached, immutable snapshots with strict field-level provenance.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.broker.upstox_client import UpstoxClient

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")


class MarketInfoService:
    """Manages periodic factual polling of Upstox Market Info and global quotes."""

    def __init__(
        self,
        client: Optional[UpstoxClient] = None,
        poll_interval_seconds: float = 60.0,
    ) -> None:
        self.client = client or UpstoxClient()
        self.poll_interval_seconds = max(15.0, float(poll_interval_seconds))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_snapshot: Dict[str, Any] = {
            "status": "UNAVAILABLE",
            "provider": "UPSTOX",
            "as_of": None,
            "source_timestamp": None,
            "pcr": None,
            "pcr_shift": None,
            "max_pain": None,
            "max_pain_shift": None,
            "total_call_oi": None,
            "total_put_oi": None,
            "oi_shift": None,
            "fii": None,
            "dii": None,
            "fii_dii_summary": None,
            "nifty_spot": None,
            "nifty_spot_change": None,
            "nifty_spot_change_pct": None,
            "india_vix": None,
            "india_vix_change": None,
            "india_vix_change_pct": None,
            "india_vix_low": None,
            "india_vix_high": None,
            "india_vix_direction": None,
            "gift_nifty": None,
            "gift_nifty_change": None,
            "gift_nifty_change_pct": None,
            "gift_nifty_freshness": "DELAYED_PROVIDER",
            "bank_nifty": None,
            "bank_nifty_change": None,
            "bank_nifty_change_pct": None,
            "midcap_select": None,
            "midcap_select_change": None,
            "midcap_select_change_pct": None,
            "sensex": None,
            "sensex_change": None,
            "nifty_spot_low": None,
            "nifty_spot_high": None,
            "bank_nifty_low": None,
            "bank_nifty_high": None,
            "midcap_select_low": None,
            "midcap_select_high": None,
            "sensex_low": None,
            "sensex_high": None,
            "india_vix_context": None,
            "nifty_futures_oi": None,
            "nifty_futures_oi_day_high": None,
            "nifty_futures_oi_day_low": None,
            "nifty_futures_oi_range_text": None,
            "pcr_provenance": "DIRECT_UPSTOX_MARKET_INFO",
            "max_pain_provenance": "DIRECT_UPSTOX_MARKET_INFO",
            "global_quotes": {},
            "poll_count": 0,
            "last_error": None,
        }

    def start(self) -> None:
        """Starts background polling thread if client has a valid token."""
        if not self.client.has_token:
            logger.info("MarketInfoService: No Upstox token available, service idle.")
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="citadel-upstox-market-info",
                daemon=True,
            )
            self._thread.start()
            logger.info("MarketInfoService started (poll interval %.1fs)", self.poll_interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def refresh_once(self) -> Dict[str, Any]:
        """Performs a single synchronous factual refresh."""
        if not self.client.has_token:
            return self.latest_snapshot()

        now_utc = datetime.now(timezone.utc)
        now_ist = datetime.now(_IST)
        today_str = now_ist.strftime("%Y-%m-%d")

        # 1. Resolve current active weekly expiry for NIFTY
        expiry_str = None
        try:
            contracts = self.client.get_option_contracts("NSE_INDEX|Nifty 50")
            expiries = sorted(set(c.get("expiry") for c in contracts if c.get("expiry")))
            if expiries:
                expiry_str = expiries[0]
        except Exception as exc:
            logger.warning("MarketInfoService: failed to resolve option expiry: %s", exc)

        pcr_val = None
        pcr_shift = None
        max_pain_val = None
        max_pain_shift = None
        total_call_oi = None
        total_put_oi = None
        oi_shift = None
        fii_val = None
        dii_val = None

        # 2. PCR & Max Pain & OI
        if expiry_str:
            try:
                pcr_data = self.client.get_pcr("NSE_INDEX|Nifty 50", expiry_str, today_str, 15)
                if isinstance(pcr_data, dict):
                    pcr_val = pcr_data.get("pcr")
                    insights = pcr_data.get("insights") or []
                    if pcr_val is None and insights:
                        pcr_val = insights[-1].get("pcr")
                    if len(insights) >= 2:
                        prev_b = insights[-2]
                        curr_b = insights[-1]
                        p_prev = prev_b.get("pcr")
                        p_curr = curr_b.get("pcr")
                        if p_prev is not None and p_curr is not None:
                            pcr_shift = {
                                "prev": round(float(p_prev), 4),
                                "curr": round(float(p_curr), 4),
                                "delta": round(float(p_curr - p_prev), 4),
                                "interval": "15m",
                                "prev_time": prev_b.get("time"),
                                "curr_time": curr_b.get("time"),
                            }
            except Exception as exc:
                logger.debug("MarketInfoService PCR query error: %s", exc)

            try:
                mp_data = self.client.get_max_pain("NSE_INDEX|Nifty 50", expiry_str, today_str, 15)
                if isinstance(mp_data, dict):
                    max_pain_val = mp_data.get("max_pain")
                    insights = mp_data.get("insights") or []
                    if len(insights) >= 2:
                        prev_b = insights[-2]
                        curr_b = insights[-1]
                        mp_prev = prev_b.get("max_pain")
                        mp_curr = curr_b.get("max_pain")
                        if mp_prev is not None and mp_curr is not None:
                            max_pain_shift = {
                                "prev": float(mp_prev),
                                "curr": float(mp_curr),
                                "delta": float(mp_curr - mp_prev),
                                "interval": "15m",
                                "prev_time": prev_b.get("time"),
                                "curr_time": curr_b.get("time"),
                            }
            except Exception as exc:
                logger.debug("MarketInfoService Max Pain query error: %s", exc)

            try:
                oi_data = self.client.get_open_interest("NSE_INDEX|Nifty 50", expiry_str, today_str)
                if isinstance(oi_data, dict):
                    total_call_oi = oi_data.get("total_calls")
                    total_put_oi = oi_data.get("total_puts")
            except Exception as exc:
                logger.debug("MarketInfoService OI query error: %s", exc)

            # Query official Upstox Change in OI endpoint first
            official_change_oi_success = False
            total_call_delta_official = None
            total_put_delta_official = None
            strike_change_map: Dict[float, Dict[str, float]] = {}
            try:
                chg_oi_resp = self.client.get_change_oi("NSE_INDEX|Nifty 50", expiry_str, today_str, interval=1)
                if isinstance(chg_oi_resp, dict) and chg_oi_resp.get("total_call_change_oi") is not None:
                    total_call_delta_official = int(chg_oi_resp.get("total_call_change_oi"))
                    total_put_delta_official = int(chg_oi_resp.get("total_put_change_oi"))
                    for row in chg_oi_resp.get("call_put_oi_data_list") or []:
                        st = row.get("strike_price")
                        if st is not None:
                            strike_change_map[float(st)] = {
                                "call_change_oi": float(row.get("call_change_oi") or 0.0),
                                "put_change_oi": float(row.get("put_change_oi") or 0.0),
                            }
                    if total_call_delta_official is not None and strike_change_map:
                        official_change_oi_success = True
            except Exception as exc:
                logger.debug("MarketInfoService official change-oi query error: %s", exc)

            try:
                chain = self.client.get_option_chain("NSE_INDEX|Nifty 50", expiry_str)
                if chain:
                    tot_c_oi = 0.0
                    tot_c_prev = 0.0
                    tot_p_oi = 0.0
                    tot_p_prev = 0.0
                    call_shifts = []
                    put_shifts = []
                    for item in chain:
                        strike = item.get("strike_price")
                        c_md = (item.get("call_options") or {}).get("market_data") or {}
                        p_md = (item.get("put_options") or {}).get("market_data") or {}
                        c_oi = float(c_md.get("oi") or 0.0)
                        c_prev = float(c_md.get("prev_oi") or 0.0)
                        p_oi = float(p_md.get("oi") or 0.0)
                        p_prev = float(p_md.get("prev_oi") or 0.0)

                        c_ltp = float(c_md.get("ltp") or 0.0)
                        c_cp = float(c_md.get("close_price") or 0.0)
                        p_ltp = float(p_md.get("ltp") or 0.0)
                        p_cp = float(p_md.get("close_price") or 0.0)

                        tot_c_oi += c_oi
                        tot_c_prev += c_prev
                        tot_p_oi += p_oi
                        tot_p_prev += p_prev

                        if official_change_oi_success and strike is not None and float(strike) in strike_change_map:
                            c_d_oi = strike_change_map[float(strike)]["call_change_oi"]
                            p_d_oi = strike_change_map[float(strike)]["put_change_oi"]
                        else:
                            c_d_oi = c_oi - c_prev
                            p_d_oi = p_oi - p_prev

                        c_d_p = round(c_ltp - c_cp, 2) if (c_ltp and c_cp) else 0.0
                        p_d_p = round(p_ltp - p_cp, 2) if (p_ltp and p_cp) else 0.0
                        c_d_pct = round((c_d_p / c_cp) * 100.0, 2) if c_cp else 0.0
                        p_d_pct = round((p_d_p / p_cp) * 100.0, 2) if p_cp else 0.0

                        def _heur(dp: float, doi: float) -> str:
                            if dp >= 0 and doi >= 0:
                                return "LONG-BUILD STYLE · HEURISTIC"
                            if dp < 0 and doi >= 0:
                                return "SHORT-BUILD STYLE · HEURISTIC"
                            if dp >= 0 and doi < 0:
                                return "SHORT-COVERING STYLE · HEURISTIC"
                            return "LONG-UNWIND STYLE · HEURISTIC"

                        if strike is not None:
                            call_shifts.append({
                                "strike": strike,
                                "delta_oi": c_d_oi,
                                "oi": c_oi,
                                "ltp": c_ltp,
                                "close_price": c_cp,
                                "change": c_d_p,
                                "change_pct": c_d_pct,
                                "heuristic": _heur(c_d_p, c_d_oi),
                            })
                            put_shifts.append({
                                "strike": strike,
                                "delta_oi": p_d_oi,
                                "oi": p_oi,
                                "ltp": p_ltp,
                                "close_price": p_cp,
                                "change": p_d_p,
                                "change_pct": p_d_pct,
                                "heuristic": _heur(p_d_p, p_d_oi),
                            })

                    call_shifts.sort(key=lambda x: x["delta_oi"], reverse=True)
                    put_shifts.sort(key=lambda x: x["delta_oi"], reverse=True)

                    top_call_inc = call_shifts[0] if call_shifts else None
                    top_call_unwind = sorted(call_shifts, key=lambda x: x["delta_oi"])[0] if call_shifts else None
                    top_put_inc = put_shifts[0] if put_shifts else None
                    top_put_unwind = sorted(put_shifts, key=lambda x: x["delta_oi"])[0] if put_shifts else None

                    if total_call_oi is None:
                        total_call_oi = int(tot_c_oi)
                    if total_put_oi is None:
                        total_put_oi = int(tot_p_oi)

                    total_call_delta = total_call_delta_official if (official_change_oi_success and total_call_delta_official is not None) else int(tot_c_oi - tot_c_prev)
                    total_put_delta = total_put_delta_official if (official_change_oi_success and total_put_delta_official is not None) else int(tot_p_oi - tot_p_prev)

                    oi_shift = {
                        "status": "AVAILABLE",
                        "expiry": expiry_str,
                        "provenance": "OFFICIAL_UPSTOX_CHANGE_OI" if official_change_oi_success else "DERIVED_UPSTOX_OPTION_CHAIN",
                        "source_type": "OFFICIAL_ENDPOINT" if official_change_oi_success else "FALLBACK_RECONSTRUCTED_OPTION_CHAIN",
                        "horizon": "TODAY ΔOI vs PREVIOUS SESSION (1D)" if official_change_oi_success else "TODAY ΔOI vs PREV CLOSE (FALLBACK)",
                        "total_call_oi": int(tot_c_oi),
                        "total_put_oi": int(tot_p_oi),
                        "total_call_delta_oi": total_call_delta,
                        "total_put_delta_oi": total_put_delta,
                        "largest_call_increase": top_call_inc,
                        "largest_call_unwind": top_call_unwind,
                        "largest_put_increase": top_put_inc,
                        "largest_put_unwind": top_put_unwind,
                        "bias_rule": "FACTUAL_OI_DELTAS_NO_BIAS_INFERRED",
                        "heuristic_explainer": "Derived from premium direction + OI change. Not direct buyer/writer proof.",
                    }
            except Exception as exc:
                logger.debug("MarketInfoService Option chain OI shift error: %s", exc)

        # 3. Institutional FII / DII
        try:
            fii_val = self.client.get_fii_data(today_str)
        except Exception as exc:
            logger.debug("MarketInfoService FII query error: %s", exc)

        try:
            dii_val = self.client.get_dii_data(today_str)
        except Exception as exc:
            logger.debug("MarketInfoService DII query error: %s", exc)

        # 4. Global Quotes, India VIX & Broad Indices
        india_vix = None
        gift_nifty = None
        nifty_spot = None
        bank_nifty = None
        midcap_select = None
        sensex = None
        nifty_spot_entry = None
        india_vix_entry = None
        gift_nifty_entry = None
        bank_nifty_entry = None
        midcap_select_entry = None
        sensex_entry = None
        futures_oi = None
        futures_oi_day_high = None
        futures_oi_day_low = None
        global_quotes: Dict[str, Any] = {}
        try:
            symbols = [
                "NSE_INDEX|Nifty 50",
                "NSE_INDEX|Nifty Bank",
                "NSE_INDEX|NIFTY MID SELECT",
                "BSE_INDEX|SENSEX",
                "NSE_INDEX|India VIX",
                "GLOBAL_INDEX|SGX NIFTY",
                "NSE_FO|68407",
                "GLOBAL_INDEX|^GSPC",
                "GLOBAL_INDEX|^DJI",
                "GLOBAL_INDEX|IXIX",
                "GLOBAL_INDEX|^N225",
            ]
            quotes = self.client.get_quotes(symbols) or {}
            for k, q in quotes.items():
                token = q.get("instrument_token") or k
                ltp = q.get("last_price")
                net_change = q.get("net_change")
                ohlc = q.get("ohlc") or {}
                cp = q.get("previous_close_price") or ohlc.get("close") or q.get("close_price")
                if net_change is not None and ltp is not None:
                    chg = float(net_change)
                    if cp is None:
                        cp = ltp - chg
                else:
                    chg = float(ltp - cp) if ltp is not None and cp is not None else None
                chg_pct = round((chg / cp) * 100.0, 2) if chg is not None and cp and cp > 0 else None
                entry = {
                    "token": token,
                    "symbol": k,
                    "ltp": ltp,
                    "close": cp,
                    "change": round(chg, 2) if chg is not None else None,
                    "change_pct": chg_pct,
                    "low": ohlc.get("low"),
                    "high": ohlc.get("high"),
                    "open": ohlc.get("open"),
                    "provider": "UPSTOX",
                    "exact_or_proxy": "EXACT",
                }
                global_quotes[token] = entry
                if "Nifty 50" in token:
                    nifty_spot = ltp
                    nifty_spot_entry = entry
                elif "India VIX" in token:
                    india_vix = ltp
                    india_vix_entry = entry
                elif "SGX NIFTY" in token:
                    entry["freshness"] = "DELAYED_PROVIDER"
                    gift_nifty = ltp
                    gift_nifty_entry = entry
                elif "Nifty Bank" in token:
                    bank_nifty = ltp
                    bank_nifty_entry = entry
                elif "MID SELECT" in token:
                    midcap_select = ltp
                    midcap_select_entry = entry
                elif "SENSEX" in token:
                    sensex = ltp
                    sensex_entry = entry
                elif "68407" in token or "NIFTY" in str(q.get("symbol", "")):
                    futures_oi = q.get("oi")
                    futures_oi_day_high = q.get("oi_day_high")
                    futures_oi_day_low = q.get("oi_day_low")
        except Exception as exc:
            logger.warning("MarketInfoService global quotes query error: %s", exc)

        # 5. Official Institutional Participant Summary (FII / DII)
        fii_dii_summary = None
        fii_fut_dict = None
        fii_opt_dict = None
        fii_cash_dict = None
        dii_cash_dict = None
        fii_date_str = None

        if fii_val or dii_val:
            # FII Futures
            if fii_val and isinstance(fii_val.get("NSE_FO|INDEX_FUTURES"), list) and fii_val["NSE_FO|INDEX_FUTURES"]:
                fut_list = fii_val["NSE_FO|INDEX_FUTURES"]
                first_rec = fut_list[0]
                prev_rec = fut_list[1] if len(fut_list) > 1 else None
                b = float(first_rec.get("buy_amount") or 0.0)
                s = float(first_rec.get("sell_amount") or 0.0)
                net_cr = round(b - s, 2)
                prev_net_cr = round(float(prev_rec.get("buy_amount") or 0.0) - float(prev_rec.get("sell_amount") or 0.0), 2) if prev_rec else None
                chg_cr = round(net_cr - prev_net_cr, 2) if prev_net_cr is not None else None
                l_cnt = int(first_rec.get("total_long_contracts") or 0)
                s_cnt = int(first_rec.get("total_short_contracts") or 0)
                tot_cnt = l_cnt + s_cnt
                long_pct = round((l_cnt / tot_cnt) * 100, 1) if tot_cnt > 0 else 0.0
                fii_fut_dict = {
                    "buy_amount_cr": round(b, 2),
                    "sell_amount_cr": round(s, 2),
                    "net_amount_cr": net_cr,
                    "change_amount_cr": chg_cr,
                    "view": "BEARISH" if long_pct < 40.0 else "BULLISH",
                    "buy_contracts": int(first_rec.get("buy_contracts") or 0),
                    "sell_contracts": int(first_rec.get("sell_contracts") or 0),
                    "long_contracts": l_cnt,
                    "short_contracts": s_cnt,
                    "long_pct": long_pct,
                    "oi_contracts": int(first_rec.get("oi_contracts") or 0),
                    "oi_amount_cr": round(float(first_rec.get("oi_amount") or 0.0), 2),
                }
                ts = first_rec.get("time_stamp")
                if ts:
                    fii_date_str = datetime.fromtimestamp(ts / 1000, tz=_IST).strftime("%d %b").upper()

            # FII Options
            if fii_val and isinstance(fii_val.get("NSE_FO|INDEX_OPTIONS"), list) and fii_val["NSE_FO|INDEX_OPTIONS"]:
                opt_list = fii_val["NSE_FO|INDEX_OPTIONS"]
                first_opt = opt_list[0]
                prev_opt = opt_list[1] if len(opt_list) > 1 else None
                b = float(first_opt.get("buy_amount") or 0.0)
                s = float(first_opt.get("sell_amount") or 0.0)
                net_cr = round(b - s, 2)
                prev_net_cr = round(float(prev_opt.get("buy_amount") or 0.0) - float(prev_opt.get("sell_amount") or 0.0), 2) if prev_opt else None
                chg_cr = round(net_cr - prev_net_cr, 2) if prev_net_cr is not None else None
                c_l = int(first_opt.get("total_call_long_contracts") or 0)
                c_s = int(first_opt.get("total_call_short_contracts") or 0)
                p_l = int(first_opt.get("total_put_long_contracts") or 0)
                p_s = int(first_opt.get("total_put_short_contracts") or 0)
                c_net = c_l - c_s
                p_net = p_l - p_s
                prev_c_net = (int(prev_opt.get("total_call_long_contracts") or 0) - int(prev_opt.get("total_call_short_contracts") or 0)) if prev_opt else 0
                prev_p_net = (int(prev_opt.get("total_put_long_contracts") or 0) - int(prev_opt.get("total_put_short_contracts") or 0)) if prev_opt else 0
                c_chg = c_net - prev_c_net
                p_chg = p_net - prev_p_net
                bearish_bias = (c_s + p_l) > (c_l + p_s)
                fii_opt_dict = {
                    "buy_amount_cr": round(b, 2),
                    "sell_amount_cr": round(s, 2),
                    "net_amount_cr": net_cr,
                    "change_amount_cr": chg_cr,
                    "view": "BEARISH" if bearish_bias else "BULLISH",
                    "buy_contracts": int(first_opt.get("buy_contracts") or 0),
                    "sell_contracts": int(first_opt.get("sell_contracts") or 0),
                    "call_long_contracts": c_l,
                    "call_short_contracts": c_s,
                    "call_net_contracts": c_net,
                    "call_change_contracts": c_chg,
                    "call_view": "SHORT CALL" if c_net < 0 else "LONG CALL",
                    "put_long_contracts": p_l,
                    "put_short_contracts": p_s,
                    "put_net_contracts": p_net,
                    "put_change_contracts": p_chg,
                    "put_view": "LONG PUT" if p_net > 0 else "SHORT PUT",
                    "oi_contracts": int(first_opt.get("oi_contracts") or 0),
                    "oi_amount_cr": round(float(first_opt.get("oi_amount") or 0.0), 2),
                }

            # FII Cash
            if fii_val and isinstance(fii_val.get("NSE_EQ|CASH"), list) and fii_val["NSE_EQ|CASH"]:
                cash_list = fii_val["NSE_EQ|CASH"]
                first_fii_cash = cash_list[0]
                prev_fii_cash = cash_list[1] if len(cash_list) > 1 else None
                b = float(first_fii_cash.get("buy_amount") or 0.0)
                s = float(first_fii_cash.get("sell_amount") or 0.0)
                net_cr = round(b - s, 2)
                prev_net = round(float(prev_fii_cash.get("buy_amount") or 0.0) - float(prev_fii_cash.get("sell_amount") or 0.0), 2) if prev_fii_cash else None
                fii_cash_dict = {
                    "buy_amount_cr": round(b, 2),
                    "sell_amount_cr": round(s, 2),
                    "net_amount_cr": net_cr,
                    "change_amount_cr": round(net_cr - prev_net, 2) if prev_net is not None else None,
                }

            # DII Cash
            if dii_val and isinstance(dii_val.get("NSE_EQ|CASH"), list) and dii_val["NSE_EQ|CASH"]:
                dii_list = dii_val["NSE_EQ|CASH"]
                first_dii = dii_list[0]
                prev_dii = dii_list[1] if len(dii_list) > 1 else None
                b = float(first_dii.get("buy_amount") or 0.0)
                s = float(first_dii.get("sell_amount") or 0.0)
                net_cr = round(b - s, 2)
                prev_net = round(float(prev_dii.get("buy_amount") or 0.0) - float(prev_dii.get("sell_amount") or 0.0), 2) if prev_dii else None
                dii_cash_dict = {
                    "buy_amount_cr": round(b, 2),
                    "sell_amount_cr": round(s, 2),
                    "net_amount_cr": net_cr,
                    "change_amount_cr": round(net_cr - prev_net, 2) if prev_net is not None else None,
                    "view": "BULLISH" if net_cr > 0 else "BEARISH",
                    "derivatives": "N/A",
                }

            fii_fut_net = fii_fut_dict.get("net_amount_cr") if fii_fut_dict else None
            dii_cash_net = dii_cash_dict.get("net_amount_cr") if dii_cash_dict else None
            fii_dii_summary = {
                "status": "DAILY_OFFICIAL",
                "date": fii_date_str or "04 SEP",
                "fii_fut_net": fii_fut_net,
                "fii_fut_chg": fii_fut_dict.get("change_amount_cr") if fii_fut_dict else None,
                "fii_fut_view": fii_fut_dict.get("view") if fii_fut_dict else None,
                "fii_opt_net": fii_opt_dict.get("net_amount_cr") if fii_opt_dict else None,
                "fii_opt_chg": fii_opt_dict.get("change_amount_cr") if fii_opt_dict else None,
                "fii_opt_view": fii_opt_dict.get("view") if fii_opt_dict else None,
                "fii_call_options": {
                    "net_contracts": fii_opt_dict.get("call_net_contracts"),
                    "change_contracts": fii_opt_dict.get("call_change_contracts"),
                    "view": fii_opt_dict.get("call_view"),
                } if fii_opt_dict else None,
                "fii_put_options": {
                    "net_contracts": fii_opt_dict.get("put_net_contracts"),
                    "change_contracts": fii_opt_dict.get("put_change_contracts"),
                    "view": fii_opt_dict.get("put_view"),
                } if fii_opt_dict else None,
                "dii_cash_net": dii_cash_net,
                "dii_cash_chg": dii_cash_dict.get("change_amount_cr") if dii_cash_dict else None,
                "dii_cash_view": dii_cash_dict.get("view") if dii_cash_dict else None,
                "dii_derivatives": "N/A (official source unavailable)",
                "view_rule_explanation": "View = dashboard interpretation of official net + change fields",
                "fii_fut_net_cr": fii_fut_net,
                "dii_cash_net_cr": dii_cash_net,
                "fii_futures": fii_fut_dict,
                "fii_options": fii_opt_dict,
                "dii_cash": dii_cash_dict,
                "fii_cash": fii_cash_dict,
            }

        def _vix_ctx(v: Optional[float], chg: Optional[float]) -> str:
            if v is None:
                return "NORMAL REGIME"
            if v < 11.5:
                return "RISING VOL" if (chg or 0) > 0 else "COMPLACENT"
            elif v < 15.0:
                return "RISING VOL" if (chg or 0) > 0 else "NORMAL REGIME"
            elif v < 20.0:
                return "ELEVATED VOL"
            return "HIGHER HEDGE DEMAND"

        vix_ctx = _vix_ctx(float(india_vix) if india_vix is not None else None, india_vix_entry.get("change") if india_vix_entry else None)

        with self._lock:
            self._latest_snapshot.update({
                "status": "AVAILABLE",
                "provider": "UPSTOX",
                "as_of": now_utc.isoformat(),
                "source_timestamp": now_utc.isoformat(),
                "expiry": expiry_str,
                "pcr": round(float(pcr_val), 4) if pcr_val is not None else None,
                "pcr_shift": pcr_shift,
                "pcr_provenance": "DIRECT_UPSTOX_MARKET_INFO" if pcr_val is not None else None,
                "max_pain": float(max_pain_val) if max_pain_val is not None else None,
                "max_pain_shift": max_pain_shift,
                "max_pain_provenance": "DIRECT_UPSTOX_MARKET_INFO" if max_pain_val is not None else None,
                "total_call_oi": int(total_call_oi) if total_call_oi is not None else None,
                "total_put_oi": int(total_put_oi) if total_put_oi is not None else None,
                "oi_shift": oi_shift,
                "oi_shift_source": oi_shift.get("source_type") if oi_shift else None,
                "oi_shift_horizon": oi_shift.get("horizon") if oi_shift else None,
                "fii": fii_val,
                "dii": dii_val,
                "fii_dii_summary": fii_dii_summary,
                "nifty_spot": float(nifty_spot) if nifty_spot is not None else None,
                "nifty_spot_change": nifty_spot_entry.get("change") if nifty_spot_entry else None,
                "nifty_spot_change_pct": nifty_spot_entry.get("change_pct") if nifty_spot_entry else None,
                "nifty_spot_low": float(nifty_spot_entry["low"]) if (nifty_spot_entry and nifty_spot_entry.get("low") is not None) else None,
                "nifty_spot_high": float(nifty_spot_entry["high"]) if (nifty_spot_entry and nifty_spot_entry.get("high") is not None) else None,
                "india_vix": float(india_vix) if india_vix is not None else None,
                "india_vix_change": india_vix_entry.get("change") if india_vix_entry else None,
                "india_vix_change_pct": india_vix_entry.get("change_pct") if india_vix_entry else None,
                "india_vix_low": float(india_vix_entry["low"]) if (india_vix_entry and india_vix_entry.get("low") is not None) else None,
                "india_vix_high": float(india_vix_entry["high"]) if (india_vix_entry and india_vix_entry.get("high") is not None) else None,
                "india_vix_direction": "RISING" if (india_vix_entry and (india_vix_entry.get("change") or 0) > 0) else ("FALLING" if (india_vix_entry and (india_vix_entry.get("change") or 0) < 0) else "FLAT"),
                "india_vix_context": vix_ctx,
                "gift_nifty": float(gift_nifty) if gift_nifty is not None else None,
                "gift_nifty_change": gift_nifty_entry.get("change") if gift_nifty_entry else None,
                "gift_nifty_change_pct": gift_nifty_entry.get("change_pct") if gift_nifty_entry else None,
                "gift_nifty_freshness": "DELAYED_PROVIDER",
                "bank_nifty": float(bank_nifty) if bank_nifty is not None else None,
                "bank_nifty_change": bank_nifty_entry.get("change") if bank_nifty_entry else None,
                "bank_nifty_change_pct": bank_nifty_entry.get("change_pct") if bank_nifty_entry else None,
                "bank_nifty_low": float(bank_nifty_entry["low"]) if (bank_nifty_entry and bank_nifty_entry.get("low") is not None) else None,
                "bank_nifty_high": float(bank_nifty_entry["high"]) if (bank_nifty_entry and bank_nifty_entry.get("high") is not None) else None,
                "midcap_select": float(midcap_select) if midcap_select is not None else None,
                "midcap_select_change": midcap_select_entry.get("change") if midcap_select_entry else None,
                "midcap_select_change_pct": midcap_select_entry.get("change_pct") if midcap_select_entry else None,
                "midcap_select_low": float(midcap_select_entry["low"]) if (midcap_select_entry and midcap_select_entry.get("low") is not None) else None,
                "midcap_select_high": float(midcap_select_entry["high"]) if (midcap_select_entry and midcap_select_entry.get("high") is not None) else None,
                "sensex": float(sensex) if sensex is not None else None,
                "sensex_change": sensex_entry.get("change") if sensex_entry else None,
                "sensex_change_pct": sensex_entry.get("change_pct") if sensex_entry else None,
                "sensex_low": float(sensex_entry["low"]) if (sensex_entry and sensex_entry.get("low") is not None) else None,
                "sensex_high": float(sensex_entry["high"]) if (sensex_entry and sensex_entry.get("high") is not None) else None,
                "nifty_futures_oi": float(futures_oi) if futures_oi is not None else None,
                "nifty_futures_oi_day_high": float(futures_oi_day_high) if futures_oi_day_high is not None else None,
                "nifty_futures_oi_day_low": float(futures_oi_day_low) if futures_oi_day_low is not None else None,
                "nifty_futures_oi_range_text": f"LOW {futures_oi_day_low/1e7:.2f}Cr → CURRENT {futures_oi/1e7:.2f}Cr → HIGH {futures_oi_day_high/1e7:.2f}Cr" if (futures_oi and futures_oi_day_high and futures_oi_day_low) else None,
                "global_quotes": global_quotes,
                "poll_count": self._latest_snapshot.get("poll_count", 0) + 1,
                "last_error": None,
            })
            snapshot_copy = dict(self._latest_snapshot)

        # Forward latest market info snapshot to Live Island Hub
        try:
            from src.oracle.live_island.hub import LiveIslandIntelligenceHub
            LiveIslandIntelligenceHub.get_instance().ingest_market_info(snapshot_copy)
        except Exception:
            pass

        return snapshot_copy

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.refresh_once()
            except Exception as exc:
                with self._lock:
                    self._latest_snapshot["last_error"] = str(exc)
                logger.error("MarketInfoService poll failed: %s", exc)
            self._stop_event.wait(self.poll_interval_seconds)

    def latest_snapshot(self) -> Dict[str, Any]:
        """Thread-safe copy of latest factual snapshot."""
        with self._lock:
            return dict(self._latest_snapshot)
