# CITADEL ORACLE SOL MARKET BRAIN — SENSORIUM COVERAGE LEDGER
## COMPLETE AUDIT OF CANONICAL CITADEL FEATURES & VOB-FREE STATUS

> **Ledger Version**: `2.0.0-p0.2`  
> **Date**: August 30, 2026

---

## 1. FEATURE AUDIT & COVERAGE MATRIX

| Feature / State | Canonical Owner | Live Available? | VOB-Free? | Included in Sol? | Reason / Lineage Justification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `spot_ltp` | `src/broker/dhan_client.py` | YES | **YES** | **INCLUDED** | Direct index cash LTP from Dhan Gateway. |
| `futures_ltp` | `src/broker/dhan_client.py` | YES | **YES** | **INCLUDED** | Direct active near-month NIFTY futures LTP from Dhan. |
| `futures_basis` | Derived (`fut - spot`) | YES | **YES** | **INCLUDED** | Spot-futures basis spread; purely numerical delta. |
| `session_vwap` | `src/strategy_lab/core/vwap.py` | YES | **YES** | **INCLUDED** | Cumulative volume-weighted average price. |
| `spot_to_vwap_pts` | Derived (`spot - vwap`) | YES | **YES** | **INCLUDED** | Distance to session VWAP in index points. |
| `mlofi_5l` | `src/order_flow/service.py` | YES | **YES** | **INCLUDED** | 5-Level multi-level order flow imbalance from L2 book. |
| `mlofi_session_extreme`| `src/order_flow/service.py` | YES | **YES** | **INCLUDED** | Factual flag indicating whether MLOFI is at session extreme. |
| `net_gex_inr` | `src/oracle/option_intelligence.py` | YES | **YES** | **INCLUDED** | Black-76 aggregate dealer gamma exposure across strikes. |
| `atm_strike` | `src/argus/option_chain_engine.py` | YES | **YES** | **INCLUDED** | Canonical ATM strike resolved by contract resolver. |
| `atm_straddle_price`| `option_buyer_intelligence.py` | YES | **YES** | **INCLUDED** | Combined ATM Call + Put market price. |
| `atm_iv` | `option_buyer_intelligence.py` | YES | **YES** | **INCLUDED** | Black-76 inverted implied volatility via bisection. |
| `skew_25d` | `src/oracle/option_intelligence.py` | YES | **YES** | **INCLUDED** | 25-Delta Put-Call IV skew spread. |
| `strike_ladder` | `src/argus/option_chain_engine.py` | YES | **YES** | **INCLUDED** | Multi-strike ladder with 5M closed OI deltas and fair gaps. |
| `vob_score` | `src/vob/engine.py` | YES | **NO** | **EXCLUDED** | Direct Volume Order Block score (prohibited by mandate). |
| `horsepower_speed` | `src/vob/horsepower.py` | YES | **NO** | **EXCLUDED** | Derived VOB execution speed metric. |
| `composite_resolver`| `src/oracle/resolver_engine.py` | YES | **MIXED** | **EXCLUDED** | Resolver blends VOB with market flow; excluded in favor of raw flow. |

---

## 2. STRICT COMPOSITE EXCLUSION POLICY
Any upstream composite metric that mixes VOB with raw flow or OI (such as legacy resolver composite scores) is strictly excluded at the Sol ingestion boundary. Sol consumes only the independently verified, unblended canonical components.
