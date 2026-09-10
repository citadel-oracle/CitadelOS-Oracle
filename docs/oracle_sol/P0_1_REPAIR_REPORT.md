# CITADEL ORACLE SOL MARKET BRAIN — P0.1 DELTA REPAIR REPORT
## ARCHITECTURE HARDENING & CONTRACT INTEGRITY CORRECTIONS

> **Mission**: P0.1 Architecture Hardening (Delta Repair Only)  
> **Date**: August 30, 2026

---

## 1. SUMMARY OF SPECIFIC REPAIRS IMPLEMENTED

1. **REPAIR 1 (Invented 3.0s Threshold Removed)**:
   * Removed arbitrary 3.0s/5.0s cutoff in `snapshot_extractor.py`.
   * Replaced with authoritative upstream connectivity status (`dhan_connected`, `market_open`, `oracle_feed_ok`).
2. **REPAIR 2 (Missing Numeric Data Never Becomes 0.0)**:
   * Replaced `0.0` default with `None` / `UNAVAILABLE` across all quantitative fields in `contracts.py` and `snapshot_extractor.py`.
   * Explicitly distinguish `OBSERVED_ZERO` (calculated zero) from `UNAVAILABLE` (missing).
   * Fixed Python truthiness bug in dictionary key retrieval via `_get_first_present`.
3. **REPAIR 3 (Event-Sourced Session Memory & Active Story)**:
   * Replaced primary FIFO with `EventSourcedMarketMemory` in `event_sourced_memory.py`.
   * Combines a bounded raw buffer (50 events) with a deterministic Active Market Story that preserves structural session lineage past event #61.
4. **REPAIR 4 (Immutable Prediction Ledger & Separate Evaluations)**:
   * Split expectations into frozen `ExpectationRecord` (never mutated once written) and separate append-only `ExpectationEvaluationRecord` (`SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONTRADICTED`, `UNRESOLVED`).
5. **REPAIR 5 (System Status Separated from Market Thesis)**:
   * Separated `system_status` (`HEALTHY`, `DATA_DEGRADED`, `STALE`, `UNAVAILABLE`, `OFF_MARKET`) and `reasoning_status` from `market_verdict` (`CALL`, `PUT`, `NO_TRADE`, or `None`).
   * Uninitialized or disconnected systems output `system_status = UNAVAILABLE` with `market_verdict = null`. Never fake `NO_TRADE`.
6. **REPAIR 6 (Honest Model Identity Reporting)**:
   * Distinguish `configured_model` (e.g. `gpt-5.6-sol`) from `actually_invoked_model` (`NONE` when uninvoked).
7. **REPAIR 7 (Unmeasured API Latency Removed)**:
   * Replaced unmeasured latency claim with `NOT MEASURED`.
8. **REPAIR 8 (Honest Fast Lane Benchmarking)**:
   * Replaced false 0.0% claim with: `NO MATERIAL REGRESSION DETECTED IN TEST WINDOW`.
9. **REPAIR 9 (GIL Claim Corrected)**:
   * Replaced "Zero GIL Blocking" with factual description of downstream worker queue and thread pool isolation.
10. **REPAIR 10 (Event Compiler Market Priors Removed)**:
    * Replaced `(flow -> price -> OI)` assumption with timestamp-derived factual sequencing.
11. **REPAIR 11 (No Forced Contradictions)**:
    * Allowed `strongest_contradiction = "NONE_OBSERVED"`.
12. **REPAIR 12 (Allowlist & Deep Lineage Defense)**:
    * Added `CANONICAL_AUTHORIZED_ROOT_KEYS` allowlist in `provenance_guard.py`. Quarantines unknown or indirect aliases.
13. **REPAIR 13 (Honest Test Inventory)**:
    * Executed and reported exact relevant test counts.
14. **REPAIR 14 (Active Story Separated from LLM Thesis)**:
    * Active Market Story is deterministically generated from canonical event history, completely un-editable by the LLM.
15. **REPAIR 15 (No Historical Episodic Retrieval)**:
    * Verified zero vector database or cross-session episodic retrieval in P0.1.
