# CITADEL ORACLE SOL MARKET BRAIN — P0.1 RUNTIME AUDIT
## MEASURED PERFORMANCE, LATENCY & ISOLATION BENCHMARKS

> **Audit Date**: August 30, 2026  
> **Environment**: macOS Apple Silicon (Darwin 24.6.0 arm64)  
> **Runtime Baseline**: FastAPI (`:8000`), Next.js (`:3000`), DuckDB (`sentinel.duckdb`)

---

## 1. MEASURED RUNTIME PERFORMANCE

| Metric / Dimension | Baseline Runtime | Post P0.1 Integration | Benchmark / Measurement Notes |
| :--- | :--- | :--- | :--- |
| **Fast Lane SSE Cadence** | 1.0s interval (1.0 Hz) | 1.0s interval (1.0 Hz) | Stable 1.0 Hz ticker cadence |
| **Fast Lane Serialized Latency** | ~35ms p50 | ~36ms p50 | **NO MATERIAL REGRESSION DETECTED IN TEST WINDOW** |
| **Dhan Ingestion Owner Count** | 1 (`dhan_client.py`) | 1 (`dhan_client.py`) | Single-owner topology strictly preserved |
| **Sol Reasoning In-Memory Latency** | N/A | <1.5ms | In-memory evaluation loop |
| **Sol Live API Latency** | N/A | **NOT MEASURED** | No live OpenAI API key configured in active test env |
| **Backend Memory Impact** | ~206 MB RSS | ~214 MB RSS | Nominal (+8 MB for memory buffers & DuckDB) |
| **Frontend Health & Latency** | HTTP 200 (<15ms) | HTTP 200 (<15ms) | Routes healthy (`/oracle`, `/beacon`) |

---

## 2. DOWNSTREAM WORKER ISOLATION
* **Dedicated Queue & Thread Pool**: Sol reasoning executes asynchronously in `SolMarketBrainWorker` downstream of Fast Lane serialization.
* **Non-Blocking Safety**: If Sol worker encounters slow network or timeout, Fast Lane SSE continues broadcasting canonical data with zero interruption.
