# 02 — ORACLE ARCHITECTURE & RUNTIME EVOLUTION

## Overview
The **CITADEL ORACLE** is the central real-time decision synthesis and market intelligence surface. It aggregates live order flow, volumetric price action (VOB), options structure (OSE), Argus tactical synthesis, and Option Buyer Intelligence (OBI) into a unified, high-frequency decision HUD.

---

## Status
**FROZEN & ACCEPTED (R3.1 Production Baseline)**

---

## Evidence
- Recorded R3 soak audits (`reports/oracle_r3_mission2_final_20260818_160942/`):
  - 10-minute SSE stream: 1,555 frames, 0 reconnects, 0 frame drops, 0 duplicates.
  - Fast Lane latency: p50 = $2.34\text{ ms}$, p95 = $20.14\text{ ms}$.
  - Worker death detection: $109.86\text{ ms}$, automatic rehydration recovery: $122.40\text{ ms}$.
- Live Next.js Turbopack production build verified across 11 routes with 0 errors.

---

## Architecture

### 1. Backend Ingestion & Processing Pipeline
```
[Dhan WebSocket / REST]
       │
       ▼
[Market Data Gateway (Singleton Ingestion)]
       │
       ├───► [Order Flow / Tape Engine]
       ├───► [VOB Engine (BigBeluga Volumetric Reversal)]
       ├───► [ARGUS Prime (Multi-timeframe Decision Mesh)]
       └───► [Option Buyer Intelligence Engine (GEX, Skew, IV/RV, Quality)]
                  │
                  ▼
       [Fast Lane Publisher (/v1/oracle/fast-lane & /stream)]
                  │
                  ▼ (SSE / REST 3.0s Polling)
       [Citadel Dashboard UI (Next.js 16 + React Server / Client Store)]
```

### 2. Frontend Surface Hierarchy (`/oracle`)
- **Top Command Deck**: Luxury HUD Hero Layer with Master Health, Active Regime, and Symbol Selector (`NIFTY`, `BANKNIFTY`).
- **ARGUS 3-Wheel Tri-Matrix**:
  - `WHEEL 1`: Macro Trend / Higher Timeframe Bias.
  - `WHEEL 2`: Micro Structure / Intraday Flow Momentum.
  - `WHEEL 3`: Tactical Execution / Pullback Trigger.
- **Master Option Intelligence Surface** (`PhotonicOptionIntelligence.tsx`):
  - Mounted directly below the 3-wheel row.
  - Full-width dark acrylic container with HUD brackets and breathing aura.
  - 4-Tier decision layout:
    1. Hero 1-Second Cognition + Argus Plasma Vector Wheel.
    2. IV Velocity & Hedge Demand Grid.
    3. Option Quality (Move Response & Time Decay).
    4. Structural Context Strip (Dealer Position Net GEX, Protection Gap, Zero-Gamma Level).

---

## Runtime Evolution Timeline

| Release | Codename | Milestone Achieved |
|---|---|---|
| **R1.0** | *Foundation Genesis* | Single-process FastAPI + initial Next.js dashboard; basic scanner and order ledger. |
| **R2.0** | *Multi-Model Shadow* | Integrated Kronos Alpha, Chronos-2, and Personal Oracle behavioral coaching in shadow mode. |
| **R2.1** | *Process Isolation* | Separated analytics boundaries; prevented slow analytics from blocking main FastAPI loop. |
| **R3.0** | *Codex Reliability Spine* | Isolated Execution Boundary, Dhan class-level guard, worker crash-loop supervision, lean Fast Lane split. |
| **R3.1** | *Photonic Master Suite* | Integration of Photonic VOB Pullback Command and Golden Option Buyer Intelligence Master Surface. |

---

## Accepted Decisions vs Rejected Approaches

### ✅ Accepted Decisions:
1. **Single Final State Hero**: Main hero and wheel center MUST show exactly one state (`CALL FRIENDLY`, `PUT FRIENDLY`, `SIDEWAYS / SELECTIVE`, `NO OPTION EDGE`, `AWAITING FEED`).
2. **Deterministic Translation Layer**: Translates quantitative Greeks into actionable trader terms (`FAST ⚡` move response, `TIME DECAY`, `ENTRY COST`, `DEALER EXPANSION`).
3. **Fail-Safe Standby**: Cold or disconnected feeds render clean `STANDBY` / `UNAVAILABLE` rather than synthetic data.

### ❌ Rejected Approaches:
1. **Frontend Recalculation**: Calculating Greeks or pricing models client-side in React (rejected: introduces latency, numerical divergence, and battery drain).
2. **Gaming UI**: Flashy neon animations, distracting charts, and cluttered pills (rejected: institutional dark terminal aesthetic strictly enforced).
3. **Direct Database Queries on SSE Loop**: Querying PostgreSQL/SQLite on every 100ms SSE frame (rejected: caused queue debt; Fast Lane uses in-memory ring buffers).

---

## Known Failure Modes & Recovery

1. **Dhan Rate Limit / Stale Option Chain**:
   - *Symptom*: OBI `status` flips to `STANDBY` or `feed_age_seconds > 20.0s`.
   - *Resolution*: Shared monotonic Dhan guard limits option chain calls to $\ge 3.0\text{s}$ interval. Automatic reconnection resumes without process crash.
2. **Worker Process Hang**:
   - *Symptom*: `CanonicalRuntimeTruth` flags worker unhealthy.
   - *Resolution*: `IsolatedExecutionBoundary` restarts worker within $125\text{ms}$ and serves `LAST_GOOD` snapshot during rehydration.

---

## Do Not Change
- The SSE and Fast Lane payload contract (`feeds.option_buyer_intelligence.data`).
- The 3.0s polling / SSE broadcast cadence.
- The fail-safe state isolation between live analytics and broker execution gates.
