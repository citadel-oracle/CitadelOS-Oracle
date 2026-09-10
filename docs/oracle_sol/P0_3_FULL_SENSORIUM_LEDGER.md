# CITADEL ORACLE SOL MARKET BRAIN — FULL SENSORIUM COVERAGE LEDGER (P0.3A)
## FORENSIC AUDIT OF CITADEL CANONICAL MARKET FEATURES, TRANSPORT PATH & VOB ISOLATION

> **Ledger Version**: `3.1.0-p0.3a`  
> **Date**: August 30, 2026  
> **Workspace**: `/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9` (HEAD: `3fa6c89`)  
> **Rule**: Producer Algorithm Owner is distinct from Transport Carrier (Fast Lane / Argus / Oracle Feed).

---

## 1. COMPREHENSIVE SENSORIUM FEATURE REGISTRY & LINEAGE

| Domain | Field Path | Producer / Algorithm Owner | Transport Carrier / Module | Live Available? | Raw/Derived | Security ID Req? | Expiry Req? | VOB Dep? | Included in Sol? | Inclusion / Exclusion Rationale | Availability Semantics |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Underlying** | `spot_ltp` | DhanMarketDataGateway | `oracle.data.spot_ltp` (`src/broker/dhan_client.py`) | YES | RAW | NO | NO | **NO** | **YES** | Core cash index price | `None` / `UNAVAILABLE` |
| **Underlying** | `futures_ltp` | DhanMarketDataGateway | `oracle.data.futures_ltp` (`src/broker/dhan_client.py`) | YES | RAW | YES | YES | **NO** | **YES** | Active near-month futures LTP | `None` / `UNAVAILABLE` |
| **Underlying** | `futures_basis` | OracleDevService | `oracle.data.futures_basis` (`src/oracle_development/oracle_dev_service.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Authoritative spot-futures basis | `None` / `UNAVAILABLE` |
| **Underlying** | `session_vwap` | StrategyLabVWAP | `oracle.data.session_vwap` (`src/strategy_lab/core/vwap.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Intraday cumulative VWAP | `None` / `UNAVAILABLE` |
| **Underlying** | `spot_to_vwap_pts` | OracleDevService | `oracle.data.spot_to_vwap` (`src/oracle_development/oracle_dev_service.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Distance to session VWAP | `None` / `UNAVAILABLE` |
| **Contract** | `active_expiry` | OptionChainEngine | `argus.data.expiry` (`src/argus/option_chain_engine.py`) | YES | RAW | NO | YES | **NO** | **YES** | Active weekly expiry string | `None` / `UNAVAILABLE` |
| **Contract** | `atm_strike` | OptionChainEngine | `argus.data.atm_strike` (`src/argus/option_chain_engine.py`) | YES | RAW | NO | NO | **NO** | **YES** | Authoritative ATM strike | `None` / `UNAVAILABLE` |
| **Contract** | `futures_security_id`| DhanMarketDataGateway | `oracle.data.futures_sid` (`src/broker/dhan_client.py`) | YES | RAW | YES | YES | **NO** | **YES** | Futures security ID | `None` / `UNAVAILABLE` |
| **OI** | `sudden_oi_call` | OptionBuyerIntelligence | `argus.data.sudden_oi.CALL` (`src/oracle/option_buyer_intelligence.py`) | YES | DERIVED | YES | YES | **NO** | **YES** | Call side closed OI surge | `None` / `UNAVAILABLE` |
| **OI** | `sudden_oi_put` | OptionBuyerIntelligence | `argus.data.sudden_oi.PUT` (`src/oracle/option_buyer_intelligence.py`) | YES | DERIVED | YES | YES | **NO** | **YES** | Put side closed OI surge | `None` / `UNAVAILABLE` |
| **OI** | `closed_5m_oi` | OptionBuyerIntelligence | `argus.data.chain_strikes[].ce/pe_closed_5m_oi` | YES | DERIVED | YES | YES | **NO** | **YES** | 5M closed window ΔOI | `None` / `UNAVAILABLE` |
| **OI** | `closed_15m_oi` | OptionBuyerIntelligence | `argus.data.chain_strikes[].ce/pe_closed_15m_oi` | YES | DERIVED | YES | YES | **NO** | **YES** | 15M closed window ΔOI | `None` / `UNAVAILABLE` |
| **OI** | `oi_structure` | OptionBuyerIntelligence | `argus.data.chain_strikes[].ce/pe_structure` | YES | DERIVED | YES | YES | **NO** | **YES** | Buildup/Unwinding state | `None` / `UNAVAILABLE` |
| **Order Flow** | `mlofi_5l` | OrderFlowService | `order_flow.data.mlofi` (`src/order_flow/service.py`) | YES | RAW | NO | NO | **NO** | **YES** | 5-Level depth flow imbalance | `None` / `UNAVAILABLE` |
| **Order Flow** | `current_flow_x` | ResolverEngine | `order_flow.data.flow_x` (`src/oracle/resolver_engine.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Multiplier of session flow avg | `None` / `UNAVAILABLE` |
| **Order Flow** | `mlofi_session_extreme`| OrderFlowService | `order_flow.data.is_extreme` (`src/order_flow/service.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Aggressor pressure extreme flag | `None` / `UNAVAILABLE` |
| **Options** | `ce_ltp` | OptionBuyerIntelligence | `argus.data.chain_strikes[].ce_ltp` | YES | RAW | YES | YES | **NO** | **YES** | Call market LTP | `None` / `UNAVAILABLE` |
| **Options** | `pe_ltp` | OptionBuyerIntelligence | `argus.data.chain_strikes[].pe_ltp` | YES | RAW | YES | YES | **NO** | **YES** | Put market LTP | `None` / `UNAVAILABLE` |
| **Options** | `bid_ask_spread` | OptionBuyerIntelligence | `argus.data.ce/pe_pricing.spread` | YES | RAW | YES | YES | **NO** | **YES** | Bid-ask spread per strike | `None` / `UNAVAILABLE` |
| **Options** | `depth_5_levels` | OptionBuyerIntelligence | `argus.data.ce/pe_pricing.depth_levels` | YES | RAW | YES | YES | **NO** | **YES** | 5-level bid/ask market depth | `None` / `UNAVAILABLE` |
| **Pricing** | `fair_iv` | OptionBuyerIntelligence | `argus.data.ce/pe_pricing.fair_iv` | YES | DERIVED | YES | YES | **NO** | **YES** | Black-76 inverted IV | `None` / `UNAVAILABLE` |
| **Pricing** | `fair_price` | OptionBuyerIntelligence | `argus.data.ce/pe_pricing.fair_price` | YES | DERIVED | YES | YES | **NO** | **YES** | Black-76 theoretical price | `None` / `UNAVAILABLE` |
| **Pricing** | `fair_gap_pct` | OptionBuyerIntelligence | `argus.data.ce/pe_pricing.fair_gap_pct` | YES | DERIVED | YES | YES | **NO** | **YES** | Premium inflation gap % | `None` / `UNAVAILABLE` |
| **Pricing** | `time_value_decay`| OptionBuyerIntelligence | `argus.data.ce/pe_pricing.holding_decay_per_min` | YES | DERIVED | YES | YES | **NO** | **YES** | Holding decay per minute | `None` / `UNAVAILABLE` |
| **Volatility** | `atm_straddle_price`| OptionBuyerIntelligence | `oracle.data.atm_straddle_price` | YES | DERIVED | NO | YES | **NO** | **YES** | ATM Call + Put straddle cost | `None` / `UNAVAILABLE` |
| **Volatility** | `straddle_change_5m`| OptionBuyerIntelligence | `argus.data.straddle_change_5m` | YES | DERIVED | NO | YES | **NO** | **YES** | 5M straddle premium change | `None` / `UNAVAILABLE` |
| **Volatility** | `atm_iv` | OptionIntelligenceEngine | `oracle.data.atm_iv` (`src/oracle/option_intelligence.py`) | YES | DERIVED | NO | YES | **NO** | **YES** | ATM implied volatility | `None` / `UNAVAILABLE` |
| **Volatility** | `skew_25d` | OptionIntelligenceEngine | `oracle.data.skew_25d` (`src/oracle/option_intelligence.py`) | YES | DERIVED | NO | YES | **NO** | **YES** | 25-Delta Put-Call IV skew | `None` / `UNAVAILABLE` |
| **Volatility** | `skew_10d` | OptionIntelligenceEngine | `oracle.data.skew_10d` (`src/oracle/option_intelligence.py`) | YES | DERIVED | NO | YES | **NO** | **YES** | 10-Delta wing IV skew | `None` / `UNAVAILABLE` |
| **Volatility** | `expected_move_pts`| OptionIntelligenceEngine | `oracle.data.expected_move` (`src/oracle/option_intelligence.py`) | YES | DERIVED | NO | YES | **NO** | **YES** | 1-Day expected move points | `None` / `UNAVAILABLE` |
| **Positioning** | `net_gex_inr` | OptionIntelligenceEngine | `oracle.data.net_gex_inr` (`src/oracle/option_intelligence.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Aggregate dealer GEX (INR) | `None` / `UNAVAILABLE` |
| **Positioning** | `highest_gex_strike`| OptionIntelligenceEngine | `oracle.data.highest_gex_strike` | YES | DERIVED | NO | NO | **NO** | **YES** | Major dealer gamma strike | `None` / `UNAVAILABLE` |
| **Positioning** | `zero_gamma_level` | OptionIntelligenceEngine | `oracle.data.zero_gamma` (`src/oracle/option_intelligence.py`) | YES | DERIVED | NO | NO | **NO** | **YES** | Gamma flip pivot point | `None` / `UNAVAILABLE` |
| **Excluded** | `vob_score` | VobEngine | `vob.data.vob_score` (`src/vob/engine.py`) | YES | DERIVED | NO | NO | **YES** | **NO** | Direct VOB metric (prohibited) | Prohibited |
| **Excluded** | `horsepower_speed` | VobEngine | `vob.data.horsepower` (`src/vob/horsepower.py`) | YES | DERIVED | NO | NO | **YES** | **NO** | VOB execution speed (prohibited)| Prohibited |
| **Excluded** | `resolver_composite`| ResolverEngine | `resolver.data.composite` (`src/oracle/resolver_engine.py`) | YES | DERIVED | NO | NO | **YES** | **NO** | Blends VOB with flow | Prohibited |
| **Excluded** | `photonic_wheel` | NiftyPhotonicMaster | `citadel-dashboard` UI composite | NO | UI | NO | NO | **YES** | **NO** | Frontend visual state | Prohibited |

---

## 2. SUMMARY
* **Discovered Features Audited**: 37 candidate features/states.
* **Included in Sol VOB-Free Sensorium**: 33 verified canonical VOB-free fields across 7 typed domains.
* **Excluded**: 4 composite/VOB-dependent metrics strictly quarantined at the projection boundary.
