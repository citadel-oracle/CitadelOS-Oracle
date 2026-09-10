# E4A Requirement & Verification Matrix

| Requirement ID | Claim Description | Invariant Property | Target Test File | Failure Mode Caught |
|---|---|---|---|---|
| **E4A-REQ-001** | Exact Option Contract Identity | Stable `contract_key` separate from `identity_record_id` | `test_contract_identity.py` | Contract key mutation or collision |
| **E4A-REQ-002** | Metadata-Driven Security ID | Instrument master maps security ID to exact strike/expiry/lot | `test_instrument_master.py` | Hardcoded lot sizes / expiries |
| **E4A-REQ-003** | Dual-Lane Architecture | Fast quote lane separated from slow option-chain lane | `test_chain_adapter.py` & `test_quote_adapter.py` | Overwriting fresh quote with old chain snapshot |
| **E4A-REQ-004** | Quote Quality Classifier | 12 explicit quote states (`TWO_SIDED_VALID`, `CROSSED`, `LOCKED`, etc.) | `test_quote_quality.py` | Treating crossed/locked quotes as valid |
| **E4A-REQ-005** | Price Reference Policy | `BEST_ASK` (buy), `BEST_BID` (sell), `MIDPOINT`, `LTP` separated | `test_mark_prices.py` | Treating LTP as automatically executable |
| **E4A-REQ-006** | Greeks Provenance | Vendor Greeks vs independent Black-Scholes model estimates | `test_greeks_provenance.py` | Silent averaging or conflation |
| **E4A-REQ-007** | IV Provenance & Solvers | Vendor IV vs independent BS solver with no-arbitrage bounds | `test_iv_provenance.py` | Returning zero or fabricated IV on failure |
| **E4A-REQ-008** | SEBI Regulatory Delta | Regulatory FutEq delta ($\Delta \times \text{Lot Size}$) separated from trading deltas | `test_greeks_provenance.py` | Conflating regulatory limits with broker trading deltas |
| **E4A-REQ-009** | Exact Time to Expiry | ACT/365 & TRADING/252 time to expiry conventions | `test_time_to_expiry.py` | Midnight expiry assumption or hardcoded weekdays |
| **E4A-REQ-010** | Moneyness Classifier | `ITM`, `ATM`, `OTM` with intrinsic & time value decomposition | `test_moneyness.py` | Defining ATM from display labels |
| **E4A-REQ-011** | Exact vs Rolling Boundary | Rolling ATM proxy series (`ROLLING:...`) strictly separated from exact key | `test_exact_vs_rolling_history.py` | Representing proxy data as exact contract history |
| **E4A-REQ-012** | Setup Option Evidence Binding | Evidence bound to setup candidate watermark $T_{watermark}$ | `test_setup_binding.py` | Post-setup future observation leakage |
| **E4A-REQ-013** | No-Look-Ahead Enforcement | Observation available_at $> T_{watermark}$ strictly rejected | `test_no_lookahead.py` | Using future quotes or chain snapshots |
| **E4A-REQ-014** | Contract Roll & Epochs | Expiry roll creates new contract key; identity epoch maintains key | `test_contract_roll.py` & `test_identity_epoch.py` | Cross-contract data leaking after roll |
| **E4A-REQ-015** | Replay & Determinism | Incremental vs full replay produces 100% identical outputs | `test_incremental_replay.py` & `test_fresh_process_determinism.py` | Non-deterministic dict ordering or clock drift |
| **E4A-REQ-016** | Authority Lock | `AUTHORITY_ONLY`, zero recommendation/probability/trade authority | `test_authority_lock.py` | Exposing trade entry / stop / target fields |
