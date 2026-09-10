import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure we can import from src
sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.broker.dhan_client import DhanClient
from src.premium_intelligence.capture import PremiumCaptureStore, SynchronizedPremiumRecord, OptionLegEvidence

class V3IngestionEngine:
    def __init__(self):
        self.dhan = DhanClient()
        self.store = PremiumCaptureStore(
            storage_dir="logs/premium_intelligence",
            filename="captures_v3.jsonl"
        )
    
    def fetch_and_persist(self) -> Optional[SynchronizedPremiumRecord]:
        try:
            # 1. Resolve Expiries
            expiries = self.dhan.get_option_expiries("IDX_I", "13")  # 13 is NIFTY
            if not isinstance(expiries, dict) or "data" not in expiries:
                print("Failed to fetch expiries:", expiries)
                return None
            
            data_list = expiries.get("data", [])
            if not isinstance(data_list, list) or not data_list:
                print("Failed to fetch expiries (auth/empty):", expiries)
                return None
                print("No expiries found.")
                return None
            
            # Dynamically resolve active expiry
            active_expiry = data_list[0]
            
            # 2. Fetch Option Chain
            chain = self.dhan.get_option_chain("IDX_I", "13", active_expiry)
            if not isinstance(chain, dict) or "data" not in chain:
                print("Failed to fetch option chain:", chain)
                return None
                
            chain_data = chain.get("data", {})
            oc = chain_data.get("oc") or list(chain_data.values())[0] if chain_data else None
            
            if not oc or not isinstance(oc, list):
                print("Option chain data is empty or invalid.")
                return None

            # 3. Find ATM and Build Ladder
            spot_price = None
            atm_strike = None
            
            for item in oc:
                if isinstance(item, dict):
                    if item.get("ce_moneyness") == "ATM" or item.get("pe_moneyness") == "ATM":
                        atm_strike = item.get("strikePrice") or item.get("strike")
                    if item.get("underlyingValue") and spot_price is None:
                        spot_price = float(item.get("underlyingValue"))
                        
            if atm_strike is None and spot_price is not None:
                atm_strike = round(spot_price / 50.0) * 50
                
            if atm_strike is None:
                print("Could not resolve ATM strike.")
                return None

            # Sort by strike and filter ATM +/- 5
            oc_sorted = sorted([item for item in oc if item.get("strikePrice") is not None], key=lambda x: float(x.get("strikePrice")))
            atm_index = next((i for i, item in enumerate(oc_sorted) if float(item.get("strikePrice")) == atm_strike), None)
            
            if atm_index is None:
                print("ATM strike not found in chain.")
                return None
                
            start_idx = max(0, atm_index - 5)
            end_idx = min(len(oc_sorted), atm_index + 6)
            ladder_items = oc_sorted[start_idx:end_idx]
            
            strike_ladder = {}
            source_timestamp = datetime.now(timezone.utc).isoformat()  # Fallback
            ce_atm = OptionLegEvidence()
            pe_atm = OptionLegEvidence()
            
            for item in ladder_items:
                strike = float(item.get("strikePrice"))
                ce_data = item.get("ce", {}) or {}
                pe_data = item.get("pe", {}) or {}
                
                # Never convert missing to zero explicitly - rely on None semantics
                ce_ev = OptionLegEvidence(
                    symbol=ce_data.get("tradingSymbol"),
                    ltp=float(ce_data.get("lastPrice")) if ce_data.get("lastPrice") is not None else None,
                    bid=float(ce_data.get("buyPrice1")) if ce_data.get("buyPrice1") is not None else None,
                    ask=float(ce_data.get("sellPrice1")) if ce_data.get("sellPrice1") is not None else None,
                    spread=float(ce_data.get("sellPrice1")) - float(ce_data.get("buyPrice1")) if ce_data.get("sellPrice1") and ce_data.get("buyPrice1") else None,
                    volume=int(ce_data.get("volume")) if ce_data.get("volume") is not None else None,
                    oi=int(ce_data.get("openInterest")) if ce_data.get("openInterest") is not None else None,
                    oi_change=int(ce_data.get("openInterestChange")) if ce_data.get("openInterestChange") is not None else None,
                    iv=float(ce_data.get("impliedVolatility")) if ce_data.get("impliedVolatility") is not None else None,
                    delta=float(ce_data.get("delta")) if ce_data.get("delta") is not None else None,
                    gamma=float(ce_data.get("gamma")) if ce_data.get("gamma") is not None else None,
                    theta=float(ce_data.get("theta")) if ce_data.get("theta") is not None else None,
                    vega=float(ce_data.get("vega")) if ce_data.get("vega") is not None else None,
                    source_timestamp=str(ce_data.get("lastUpdateTime") or source_timestamp)
                )
                
                pe_ev = OptionLegEvidence(
                    symbol=pe_data.get("tradingSymbol"),
                    ltp=float(pe_data.get("lastPrice")) if pe_data.get("lastPrice") is not None else None,
                    bid=float(pe_data.get("buyPrice1")) if pe_data.get("buyPrice1") is not None else None,
                    ask=float(pe_data.get("sellPrice1")) if pe_data.get("sellPrice1") is not None else None,
                    spread=float(pe_data.get("sellPrice1")) - float(pe_data.get("buyPrice1")) if pe_data.get("sellPrice1") and pe_data.get("buyPrice1") else None,
                    volume=int(pe_data.get("volume")) if pe_data.get("volume") is not None else None,
                    oi=int(pe_data.get("openInterest")) if pe_data.get("openInterest") is not None else None,
                    oi_change=int(pe_data.get("openInterestChange")) if pe_data.get("openInterestChange") is not None else None,
                    iv=float(pe_data.get("impliedVolatility")) if pe_data.get("impliedVolatility") is not None else None,
                    delta=float(pe_data.get("delta")) if pe_data.get("delta") is not None else None,
                    gamma=float(pe_data.get("gamma")) if pe_data.get("gamma") is not None else None,
                    theta=float(pe_data.get("theta")) if pe_data.get("theta") is not None else None,
                    vega=float(pe_data.get("vega")) if pe_data.get("vega") is not None else None,
                    source_timestamp=str(pe_data.get("lastUpdateTime") or source_timestamp)
                )
                
                if strike == atm_strike:
                    ce_atm = ce_ev
                    pe_atm = pe_ev
                    source_timestamp = ce_ev.source_timestamp or source_timestamp
                
                strike_ladder[str(strike)] = {
                    "strike": strike,
                    "ce": ce_ev.to_dict(),
                    "pe": pe_ev.to_dict(),
                    "spot": spot_price,
                    "expiry": active_expiry
                }
                
            atm_straddle = None
            if ce_atm.ltp is not None and pe_atm.ltp is not None:
                atm_straddle = ce_atm.ltp + pe_atm.ltp
                
            v3_key = f"v3:{source_timestamp}:{active_expiry}:{atm_strike}"
            rec = SynchronizedPremiumRecord(
                record_id=f"cap_v3_{uuid.uuid4().hex[:8]}",
                idempotency_key=v3_key,
                session_date=datetime.fromisoformat(source_timestamp.replace('Z', '+00:00')).strftime("%Y-%m-%d") if "Z" in source_timestamp or "+" in source_timestamp else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                source_timestamp=source_timestamp,
                authority_timeframe="5m",
                is_completed_bar=True,
                bar_open_time=source_timestamp,
                bar_close_time=source_timestamp,
                contributing_snapshot_count=1,
                natural_boundary="",
                completeness_pct=100.0,
                gap_status="NONE",
                nifty_spot=spot_price,
                expiry=active_expiry,
                dte=None, # Needs a date diff if we want it precise
                atm_strike=atm_strike,
                ce_leg=ce_atm,
                pe_leg=pe_atm,
                atm_straddle=atm_straddle,
                pre_snapshot_id=None,
                pre_state=None,
                pre_regime=None,
                pli_snapshot_id=None,
                pli_lead=None,
                blockers=[],
                strategy_evaluations_ref=[],
                strike_ladder=strike_ladder,
                schema_version="V3",
                timestamp_type="source_timestamp",
                execution_influence="ZERO"
            )
            
            if self.store.write_record(rec):
                print(f"Successfully persisted V3 record for {source_timestamp}")
                return rec
            else:
                print(f"Duplicate record ignored for {v3_key}")
                return None
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"V3 Ingestion Failed: {e}")
            return None

if __name__ == "__main__":
    engine = V3IngestionEngine()
    engine.fetch_and_persist()
