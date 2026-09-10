# 03 — ARGUS FLOW, FUSION & DECISION LAYERS

## Overview
**ARGUS Prime** is the multi-layered order flow, tape analysis, and tactical confluence engine of Citadel. It observes real-time buyer/seller aggressiveness, volume delta absorption, and liquidity pools across multi-timeframe horizons.

---

## Status
**FROZEN & ACCEPTED**

---

## Evidence
- Benchmarked compute latencies in R3 Mission 2:
  - Tactical Edge compute: $3.24\text{ ms}$ (p50).
  - Full analytics pipeline: $4.54\text{ ms}$ (p50).
  - Stream publication: $1.25\text{ ms}$ (p50).
- Zero queue drops across 60-minute continuous market soak tests.

---

## ARGUS Architecture & Components

```
                ┌──────────────────────────────────────────────┐
                │          DHAN LIVE 5-LEVEL DEPTH             │
                └──────────────────────┬───────────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │         ARGUS FLOW ENGINE         │
                     │  - Volume Delta (CVD)             │
                     │  - Aggressive Buyer/Seller Ratio  │
                     │  - Microstructure Imbalance       │
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │        ARGUS FUSION MATRIX        │
                     │  - Timeframe 1: 1M Flow Anchor    │
                     │  - Timeframe 2: 5M Structure      │
                     │  - Timeframe 3: 15M Macro Trend   │
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │       TACTICAL STORE (CACHE)      │
                     │  - Memory Ring Buffer             │
                     │  - Copy-on-Read Firewall          │
                     └───────────────────────────────────┘
```

---

## The 3 Decision Layers

1. **Macro Flow Vector (Wheel 1)**:
   - Measures cumulative multi-session institutional order accumulation.
   - Evaluates whether higher-timeframe participants are net long or net short.

2. **Micro Structure Vector (Wheel 2)**:
   - Tracks 5-minute absorption vs breakout velocity.
   - Flags aggressive passive absorption at key VOB support/resistance bands.

3. **Tactical Execution Vector (Wheel 3)**:
   - The immediate 1-minute trigger for trade entries.
   - Confirms that the tape agrees with the price action breakout before signaling readiness.

---

## Data Dependencies & Protection Firewalls

- **Copy Boundaries**: Tactical Edge utilizes strict deep-copy boundaries on output dicts to ensure the background compute worker never mutates the cached Fast Lane object while a client is reading it.
- **Clock Synchronization**: Every flow tick records both `source_timestamp` (exchange timestamp) and `ingest_epoch_ms` to detect and filter out stale ticks ($> 300\text{ms}$ network lag).

---

## Do Not Change
- The multi-timeframe fusion weighting logic without running the standard 15-minute verification benchmark.
- The thread-safe copy-on-read mechanism in `src/argus/tactical_store.py`.
- The immutability of historical flow events once written to the ring buffer.
