# CITADEL ORACLE SOL MARKET BRAIN — P0.2 DELTA REPAIR REPORT
## TRUTH, LINEAGE, REPLAY & FULL-SENSORIUM INTEGRATION REPAIRS

> **Mission**: P0.2 Truth, Lineage, Replay & Full-Sensorium Integration  
> **Date**: August 30, 2026

---

## 1. SUMMARY OF P0.2 REPAIRS IMPLEMENTED

1. **REPAIR 1 (Removed Hidden 5-Point Spot Threshold)**:
   * Removed `if abs(spot_delta) >= 5.0:` in `MarketEventStoryBuilder`. Emits factual state deltas on any actual price change without invented thresholds.
2. **REPAIR 2 (No Synthetic ATM or Strike Ladder)**:
   * Removed `round(spot / 50) * 50` and synthetic ATM-50 / ATM+50 ladders from `snapshot_extractor.py`. Missing contract identities remain `None` / `UNAVAILABLE`.
3. **REPAIR 3 (Removed Non-Canonical GEX Interpretation)**:
   * Removed dealer gamma regime interpretation from Sol extraction layer. Exposes factual `net_gex_inr` only.
4. **REPAIR 4 (Missing Booleans/Enums Remain None)**:
   * Missing `dhan_connected`, `market_open`, and `is_extreme` are strictly typed as `Optional[bool] = None` (never default to True/False).
5. **REPAIR 5 & 6 (Field-Level Lineage Registry & Fail-Closed Quarantine)**:
   * Built `SOL_VOB_FREE_FIELD_REGISTRY` in `src/oracle_sol/field_registry.py`.
   * Enforced fail-closed behavior in `ProvenanceGuard`: Any payload containing VOB or unverified lineage triggers an immediate exception.
6. **REPAIR 7 & 8 (Canonical Cycle ID & Distinct Thesis Transition Lineage)**:
   * Single `canonical_cycle_id` established before model call and passed across model envelope, ExpectationRecord, Shadow Ledger, and Replay.
   * `previous_thesis_id` and `new_thesis_id` strictly refer to distinct before/after states.
7. **REPAIR 9 (Exact Model Input Replay Proven by Hash)**:
   * Replay engine persists and verifies `SolModelRequestEnvelope` asserting `original_input_hash == replayed_input_hash`.
8. **REPAIR 10, 11, 12 (Fail-Closed Evidence Reference Validation)**:
   * Created `EvidenceReferenceValidator` in `provenance_guard.py`.
   * Model-evaluated expectation IDs must exist in `prev_thesis.active_expectations`.
   * Model-cited event references must exist in `known_event_ids`.
9. **REPAIR 13 (Invalid Model Output Cannot Become NO_TRADE)**:
   * Unparseable or schema-invalid model output produces `reasoning_status = OUTPUT_INVALID` and `market_verdict = None` (never fake NO_TRADE).
10. **REPAIR 14, 15, 16 (OpenAI Structured Outputs & Explicit Telemetry)**:
    * Implemented `SOL_STRUCTURED_OUTPUT_JSON_SCHEMA` with strict schema validation.
    * Telemetry explicitly records `configured_model`, `requested_model`, `provider_response_model`, `successful_reasoning_model`, `reasoning_effort="low"` (labeled `UNVALIDATED_CONFIGURATION`), and `api_latency`.
11. **REPAIR 17 (Neutral Quantitative Prompt Framing)**:
    * Neutralized prompt language; removed prestige and loss-prevention framing.
12. **REPAIR 18 & 19 (Sensorium Coverage Ledger & Composite Exclusion)**:
    * Built `P0_SENSORIUM_COVERAGE_LEDGER.md` auditing all 16 canonical features.
    * Excluded composite metrics blending VOB in favor of raw unblended components.
13. **REPAIR 20 (Fast Lane to Sol Live Wiring)**:
    * Wired `_oracle_fast_base_projection()` in `app/main.py` directly into `SolMarketBrainService.ingest_feeds()` non-blockingly.
14. **REPAIR 21, 22, 23 (Auto Session Boundary, Timestamps & Replay-Stable Event IDs)**:
    * Service auto-rotates session memory on calendar date change.
    * Emits `ORDER_SAME_SNAPSHOT_WINDOW` when concurrent.
    * Stable deterministic event IDs: `f"evt_{snap[:8]}_{type}_{inst}_{seq:04d}"`.
15. **REPAIR 24 (Durable Session Event Store)**:
    * Implemented durable session store in `event_sourced_memory.py` retaining 100% of factual events across the session.
16. **REPAIR 25 (Visible Persistence Health Telemetry)**:
    * Exposes JSONL health, DuckDB health with 250ms lock timeout, last successful write timestamp, and last error.
17. **REPAIR 26 & 27 (Beacon UI Label & Status Separation)**:
    * Changed label to `VOB EXCLUDED`.
    * Separated `STREAM: CONNECTED / OFFLINE` from `MARKET SENSORIUM STATUS` and `REASONING STATUS`.
18. **REPAIR 28 (Validation Horizons Reclassified)**:
    * Reclassified validation requirements as prospective statistical samples without arbitrary 12-expiry or fixed 2-factor baseline claims.
19. **REPAIR 29 (Accurate Test Inventory)**:
    * Accurately reported test suites: Sol tests (14), Core Oracle (110), Frontend vitest (51). Full repo suite marked NOT RUN.
