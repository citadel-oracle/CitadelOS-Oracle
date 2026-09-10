# CITADEL ORACLE SOL MARKET BRAIN — DURABLE PERSISTENCE & RECOVERY (P0.3)
## DISK-BACKED SESSION EVENT STORE, ACTIVE STORY RECONSTRUCTION & RESTART INTEGRITY

> **Store Version**: `3.0.0-p0.3`  
> **Storage Path**: `data/sol_shadow/sol_session_events_{session_date}.jsonl`  
> **Module Path**: `src/oracle_sol/event_sourced_memory.py`

---

## 1. PERSISTENCE TOPOLOGY

```
FAST LANE CANONICAL SNAPSHOT
            │
            ▼
MARKET EVENT STORY BUILDER (Deterministic Replay-Stable Event IDs)
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ EVENT SOURCED MARKET MEMORY                                 │
│                                                             │
│  1. In-Memory Sliding Buffer (50 raw micro-events)          │
│                                                             │
│  2. Persistent Append-Only Session Store                    │
│     -> data/sol_shadow/sol_session_events_{session_date}.jsonl│
│                                                             │
│  3. Event-Sourced Active Compressed Market Story            │
│     -> Preserves complete lineage across session            │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
        RECOVERY ON BACKEND / WORKER RESTART:
        • Detects active session date
        • Hydrates 100% of stored events from disk
        • Reconstructs Active Market Story & story revision
        • Restores unresolved expectation records
        • Preserves complete market context without amnesia
```

---

## 2. RECOVERY VALIDATION
* **Service Restart Test**: Validated by `test_persisted_session_events_survive_restart` asserting `pre_restart_event_count == restored_event_count`.
* **Session Boundary Isolation**: When calendar date rotates, memory automatically resets cleanly for the new day (`test_previous_session_thesis_does_not_restore_into_new_session`).
