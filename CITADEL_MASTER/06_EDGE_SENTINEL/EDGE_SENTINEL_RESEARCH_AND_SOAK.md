# 06 — EDGE SENTINEL RESEARCH & SOAK AUDITS

## Overview
**Edge Sentinel** is Citadel's automated forensic auditing, statistical verification, and live-runtime soak test guardian. It continuously tests hypotheses, detects data leakage, measures clock drift, and verifies whether claimed trading edges are statistically robust.

---

## Status
**ACCEPTED & ACTIVE AUDIT AUTHORITY**

---

## Evidence & Forensic Audit Results

### 1. Data Provenance & Leakage Audit
- Verified live fields across recorded datasets (`reports/R3_FREEZE_TEST_PROVENANCE.json` and session logs):
  - `ATM IV`: Inverted via continuous Black-Scholes solver from Dhan top-of-book bid/ask midpoint.
  - `Realized Volatility`: Computed via high-frequency log-return standard deviation across 1-minute closed bars.
  - `Look-Ahead Invariant`: Confirmed strictly zero forward-look leakage ($T_{\text{eval}} \le T_{\text{event}}$).

### 2. Multi-Horizon Soak Test Metrics (Observed on macOS M-Series Host, 2026-08-18)
- **10-Minute SSE Stream**: 1,555 frames delivered with 0 reconnects, 0 frame drops, and 0 duplicates recorded.
- **1-Hour Continuous Live Soak**:
  - Main Fast Lane latency: p50 = $2.34\text{ ms}$, p95 = $74.01\text{ ms}$.
  - Zero fatal unhandled exceptions during steady-state evaluation.
  - Memory footprint: Observed non-monotonic plateau between $680\text{ MB}$ and $880\text{ MB}$ without unbounded linear accumulation.

---

## Research Hypotheses & Observed Empirical Tendencies

### 🔬 Observed Empirical Tendencies (Active Research Sampling):
1. **IV-RV Premium Spread Impact**: In observed historical test datasets, entering long option positions during elevated IV-RV spreads ($> +3.5\%$) frequently coincides with volatility crush and reduced trade profitability during consolidation. Formal multi-regime sample significance testing is ongoing.
2. **Dealer Gamma (GEX) Regime Dynamics**: In observed negative aggregate GEX regimes ($\text{Net GEX} < -₹100\text{ Cr}$), directional price movement tends to exhibit faster strike-to-strike extension compared to positive GEX regimes where dealer hedging absorbs volatility. Exact acceleration rates vary across market regimes and liquidity conditions.
3. **Move Response ($\mathcal{Q}$) Thresholds**: Initial backtest observations show higher MFE/MAE efficiency when filtering for $\mathcal{Q} \ge 1.5$ compared to unfiltered entries.

### ❓ Hypotheses Under Investigation:
1. **Isolated Wing Skew Predictive Power**: Extreme $10\Delta$ wing spikes alone without underlying volume delta confirmation show low standalone directional correlation ($< 50\%$).
2. **Intraday Flow to Overnight Gap Correlation**: High-frequency intraday order flow exhibits low predictive power for next-session market open gaps.

---

## Do Not Change
- The requirement that all new strategy ideas must undergo Sentinel backtest falsification before paper trading deployment.
- The forensic timestamping standards (ISO 8601 UTC + Epoch ms).
