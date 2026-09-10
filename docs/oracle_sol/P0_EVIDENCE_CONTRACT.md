# CITADEL ORACLE SOL MARKET BRAIN — P0.1 EVIDENCE CONTRACT
## CANONICAL VOB-FREE INPUT FACTS, ALLOWLIST & MISSING DATA SCHEMAS

> **Contract Version**: `2.0.0-sol-p0.1`  
> **Module Path**: `src/oracle_sol/contracts.py`

---

## 1. CANONICAL FIELDS, LINEAGE & ALLOWLIST

| Field | Source Owner | Type | Missing Representation | VOB Lineage Status |
| :--- | :--- | :--- | :--- | :--- |
| `spot_ltp` | `src/broker/dhan_client.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `futures_ltp` | `src/broker/dhan_client.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `futures_basis` | Derived (`fut - spot`) | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `session_vwap` | `src/strategy_lab/core/vwap.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `mlofi_5l` | `src/order_flow/service.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `net_gex_inr` | `src/oracle/option_intelligence.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `atm_strike` | `src/argus/option_chain_engine.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `atm_straddle_price` | `option_buyer_intelligence.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `atm_iv` | `option_buyer_intelligence.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `skew_25d` | `src/oracle/option_intelligence.py` | `Optional[float]` | `None` (`UNAVAILABLE`) | **ALLOWLIST CONFIRMED** |
| `strike_ladder` | `src/argus/option_chain_engine.py` | `List[Dict]` | Missing entries `None` | **ALLOWLIST CONFIRMED** |

---

## 2. STRICT MISSING-DATA RULES (MISSING != 0.0)
* **Zero is NOT Missing**: An observed zero (e.g. `futures_basis = 0.0` or `mlofi = 0.0`) is tagged as `OBSERVED_ZERO`.
* **Missing is NOT Zero**: If a feed or field is missing, it is strictly serialized as `None` / `null` with `UNAVAILABLE` in `availability_matrix`.
* **Zero Invented Latency Cutoffs**: Data health is derived directly from upstream authoritative connectivity (`dhan_connected`, `market_open`, `oracle_feed_ok`). No arbitrary 3.0s threshold exists.
