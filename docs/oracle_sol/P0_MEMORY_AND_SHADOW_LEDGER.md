# CITADEL ORACLE SOL MARKET BRAIN — P0.1 MEMORY & PREDICTION LEDGER
## EVENT-SOURCED SESSION STORE, IMMUTABLE PREDICTIONS & REPLAY

> **Ledger Path**: `data/sol_shadow/sol_shadow_cycles.jsonl` & `data/sol_shadow/sol_shadow.duckdb`  
> **Module Path**: `src/oracle_sol/event_sourced_memory.py` & `src/oracle_sol/thesis_memory.py`

---

## 1. EVENT-SOURCED MEMORY TOPOLOGY (REPLACING PRIMARY FIFO)

```
SESSION EVENT STREAM
│
├── A. RECENT RAW BUFFER (Bounded at 50 events for micro-comparisons)
│
├── B. ACTIVE MARKET STORY (Event-sourced compressed session narrative)
│    • Session Open Baseline
│    • Structural Evolution Summary
│    • Order Flow Regime Summary
│    • Strike Positioning Summary
│    • Lineage & Event IDs Retained across Session
│
└── C. PROVENANCE LINEAGE
     • Event #61 arriving does NOT erase earlier structural lineage!
```

---

## 2. IMMUTABLE PREDICTION LEDGER & SEPARATE EVALUATIONS

1. **`ExpectationRecord`**:
   * Pre-registered forward expectation created *before* subsequent ticks arrive.
   * Frozen dataclass. **NEVER MUTATED** after creation.
2. **`ExpectationEvaluationRecord`**:
   * Separate, append-only evaluation record (`SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONTRADICTED`, `UNRESOLVED`).
   * References actual event IDs, evidence hashes, and evaluation notes.
   * Enforces: **PREDICTION $\rightarrow$ OBSERVATION $\rightarrow$ EVALUATION** (no retrospective rewriting).
