# CITADEL ORACLE SOL MARKET BRAIN — P0.1 ARCHITECTURE (HARDENED)
## REASONING SENSORIUM, EVENT-SOURCED MEMORY & BEACON HUD INTEGRATION

> **Status**: P0.1 ARCHITECTURE HARDENING COMPLETE  
> **Date**: August 30, 2026  
> **Workspace**: `/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9` (HEAD: `3fa6c89`)  
> **Core Mandate**: 100% VOB-Free Allowlist $\mid$ CITADEL Calculates, Sol Interprets $\mid$ Zero Invented Rules/Thresholds $\mid$ Explicit Missing Data

---

## 1. COMPONENT TOPOLOGY

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. CANONICAL SENSORIUM (CITADEL CORE)                                       │
│    • Dhan Ingestion & L1/L2 Market Data Gateway                             │
│    • 5-Level MLOFI / L1-OFI Order Flow (`src/order_flow/service.py`)        │
│    • Option Greeks, 10D/25D Skew, Net GEX (`src/oracle/option_intelligence`)│
│    • Black-76 Fair IV Inversion & Closed 5M OI (`option_buyer_intelligence`)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (Canonical Feeds Dict)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. VOB-FREE ALLOWLIST & SNAPSHOT EXTRACTOR (`src/oracle_sol/`)              │
│    • ProvenanceGuard: Strict Allowlist validation & deep alias defense      │
│    • SolEvidenceSnapshot: Explicit missing handling (None != 0.0)           │
│    • System Health: Authoritative upstream feed status (no invented cutoffs)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (VOB-Free Canonical Snapshot)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. EVENT COMPILER & EVENT-SOURCED SESSION MEMORY                            │
│    • MarketEventStoryBuilder: Timestamp-derived chronological state deltas  │
│    • EventSourcedMarketMemory: Raw buffer + Factual Active Market Story     │
│    • Lineage Preservation: Event #61 never erases active structural lineage │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (Chronological Context & Active Story)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. GPT-5.6 SOL REASONING ORCHESTRATOR                                       │
│    • 9-Pass Reasoning Protocol (Observe -> Sequence -> Adversarial Cases)   │
│    • Immutable Prediction Records (`ExpectationRecord`, never mutated)      │
│    • Separate Evaluation Records (`ExpectationEvaluationRecord`)            │
│    • SolModelAdapter: Configured Model vs Actually Invoked Model separation │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (Machine-Readable Contract)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. MINIMAL BEACON HUD (`citadel-dashboard/src/app/beacon/page.tsx`)         │
│    • Ultra-compact 340px floating HUD beside trading chart                  │
│    • Separates System Health (UNAVAILABLE / DEGRADED) from Market Thesis    │
│    • Uninitialized system NEVER displays fake NO_TRADE                     │
│    • Real-time SSE stream on `/v1/oracle/sol/stream`                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │ (Parallel Out-of-Band Logging)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. IMMUTABLE SHADOW LEDGER & REPLAY (`data/sol_shadow/`)                    │
│    • SolShadowLedger: Appends every cycle to JSONL & DuckDB                 │
│    • SolCycleReplayEngine: Bit-exact input payload reconstruction           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. STRICT ISOLATION & PROVENANCE CONTROLS
1. **Single Dhan Gateway**: Exclusively owned by `src/broker/dhan_client.py`.
2. **Explicit Allowlist Lineage**: `ProvenanceGuard.verify_allowlist_lineage()` enforces root keys and rejects unknown aliases.
3. **Downstream Worker Isolation**: Sol reasoning runs downstream in `SolMarketBrainWorker` on a dedicated thread, completely isolated from Fast Lane request handling.
