# 08 — DATA ARCHITECTURE, DHAN INTEGRATION & FAST LANE

## Overview
Citadel's data architecture is engineered around strict provenance tracking, thread-safe memory ring buffers, and sub-millisecond serialization between the market ingestion gateway and the frontend dashboard.

---

## Status
**FROZEN & ACCEPTED (R3 Production Baseline)**

---

## Evidence
- Class-level Dhan client rate limiter verified across 10,000+ queries.
- Zero mutation leaks between background compute workers and frontend read models.
- Fast Lane SSE delivery verified under high-throughput market load.

---

## Data Pipeline & Provenance Layers

```
                ┌─────────────────────────────────────────┐
                │          DHAN HQ BROKER FEED            │
                │  - WebSocket: Binary Ticks & 5-Depth    │
                │  - REST API: Option Chain & Security ID │
                └────────────────────┬────────────────────┘
                                     │
                                     ▼
                ┌─────────────────────────────────────────┐
                │        MARKET DATA GATEWAY (MDG)        │
                │  - Monotonic Timestamping               │
                │  - Class-Level Rate Limiter (≥ 3.0s)    │
                │  - Tick Normalization                   │
                └────────────────────┬────────────────────┘
                                     │
                                     ▼
                ┌─────────────────────────────────────────┐
                │        CANONICAL RUNTIME TRUTH          │
                │  - CURRENT vs LAST_GOOD Separation      │
                │  - Source Timestamp vs Ingestion Epoch  │
                │  - Freshness Heartbeat (< 20.0s)        │
                └────────────────────┬────────────────────┘
                                     │
                                     ▼
                ┌─────────────────────────────────────────┐
                │        FAST LANE PUBLISHER              │
                │  - Path: /v1/oracle/fast-lane           │
                │  - Stream: /v1/oracle/fast-lane/stream  │
                │  - Lean Payload (~480 KB hydrated)      │
                └────────────────────┬────────────────────┘
                                     │
                                     ▼
                ┌─────────────────────────────────────────┐
                │        CITADEL DASHBOARD STORE          │
                │  - Zustand / React Query Provider       │
                │  - 3.0s Auto-Polling + Live SSE Event   │
                └─────────────────────────────────────────┘
```

---

## Provenance Rules & Field Origin Contract

1. **`LIVE_OBSERVED` Fields** (Direct from Exchange Wire):
   - `LTP` / `LTT`: WebSocket Tick.
   - `Top 5 Bid/Ask Depth`: WebSocket Full Depth packet.
   - `Volume` / `OI`: Subscribed Quote packet.

2. **`CALCULATED` Fields** (Derived by Citadel Engines):
   - `ATM IV`: Inverted from mid-price using continuous Black-Scholes solver.
   - `Greeks` ($\Delta, \Gamma, \Theta, \mathcal{V}$): Standard analytical derivatives.
   - `HAR-RV`: Daily, weekly, and monthly autoregressive components.
   - `Net GEX`: Weighted open interest gamma aggregation.

3. **Freshness & Staleness Rules**:
   - `feed_age_seconds <= 20.0s`: Marked as `LIVE` (green indicator).
   - `feed_age_seconds > 20.0s`: Marked as `STALE` / `DEGRADED` (amber warning).
   - If stream is disconnected: Surfaces flip to `STANDBY` / `AWAITING FEED` (no synthetic simulation).

---

## Do Not Change
- The singleton gateway pattern for Dhan market data ingestion.
- The minimum 3.0s throttle interval on full REST option chain requests to avoid broker IP banning.
- The separation of raw exchange timestamps from system ingestion timestamps.
