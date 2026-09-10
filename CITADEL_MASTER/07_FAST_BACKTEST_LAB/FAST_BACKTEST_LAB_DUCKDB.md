# 07 — FAST BACKTEST LAB & DUCKDB ARCHITECTURE

## Overview
The **Fast Backtest Lab** provides high-throughput vectorized backtesting, parameter sweeps, and strategy optimization across multi-year tick and 1-minute historical datasets using DuckDB and columnar Apache Parquet storage.

---

## Status
**ACCEPTED & OPERATIONAL**

---

## Evidence & Benchmarks
- **Vectorized OLAP Performance**: Benchmark tests on Apple Silicon local storage demonstrate DuckDB SQL kernels evaluating over 1,000,000 candle rows in approximately $1.2\text{ seconds}$ across multi-parameter grid searches.
- **Chronological Execution Integrity**: Verification tests confirm strict chronological trade sequencing with realistic slippage modeling ($0.5\text{ pts}$ on NIFTY) and exchange transaction fees.

---

## Architecture & Data Flow

```
[Parquet Historical Lake (1M Candles / Full Depth Ticks)]
                        │
                        ▼
           [DuckDB In-Memory OLAP Engine]
                        │
         ┌──────────────┴──────────────┐
         ▼                             ▼
[Vectorized Feature Engine]   [Strategy Lab Execution Service]
 - VOB Matrix                  - Trailing Stop Simulation
 - Volatility Surface          - MFE / MAE Distribution
 - Order Flow Delta            - Drawdown Profile
         │                             │
         └──────────────┬──────────────┘
                        │
                        ▼
       [Strategy Lab Dashboard UI (/strategy-lab)]
```

---

## Data Model & Schema

- **`candles_1m`**: `timestamp`, `symbol`, `open`, `high`, `low`, `close`, `volume`, `oi`.
- **`option_chain_ticks`**: `timestamp`, `strike`, `expiry`, `ce_ltp`, `pe_ltp`, `ce_iv`, `pe_iv`, `ce_oi`, `pe_oi`.
- **`vob_events`**: `timestamp`, `symbol`, `direction`, `block_high`, `block_low`, `volume_ratio`, `status`.

---

## Optimization & Research Roadmap

1. **GPU-Accelerated Greeks Batching**: Offloading batch Black-Scholes and SABR volatility surface fits to Apple Silicon Metal / CUDA.
2. **Walk-Forward Validation Grid**: Enforcing out-of-sample testing across rolling 3-month walk-forward windows to combat overfitting.

---

## Do Not Change
- The strict chronological ordering constraint during trade replay (no forward look-ahead allowed in SQL joins).
- The transaction cost and slippage inclusion in all P&L reporting.
