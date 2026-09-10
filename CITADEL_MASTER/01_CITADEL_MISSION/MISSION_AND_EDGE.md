# 01 — CITADEL MISSION & EDGE PHILOSOPHY

## Overview
CITADEL is an institutional-grade algorithmic execution and real-time market intelligence operating system built for systematic options trading on Indian Index Derivatives (specifically NIFTY & BANKNIFTY).

---

## Status
**FROZEN & ACCEPTED (Core Philosophy)** / **ACTIVE IMPLEMENTATION & RESEARCH**

---

## Evidence & Theoretical Foundation
- **Payoff Convexity Structure**: Option buyer returns are non-linearly governed by positive Gamma ($\Gamma$) and negative Theta ($\Theta$). Profitability requires directional momentum and/or volatility expansion to exceed the cost of carry (theta decay) and execution friction (bid-ask spread).
- **Empirical Research Context**: Historical market observations indicate that buying high-IV overpriced options during range-bound consolidation or holding through extended theta decay are primary failure modes for retail option buyers. Ongoing statistical research in Sentinel is quantifying exact factor attributions across market regimes.
- **Architectural Verification**: Citadel's multi-tier architecture separates high-speed live feed ingestion, deterministic quant validation, and trader-facing 1-second cognition.

---

## Reason
Traditional retail trading approaches frequently underperform because participants:
1. Treat options like linear directional instruments without factoring in IV mispricing, volatility risk premia ($IV - RV$), and gamma/theta trade-offs.
2. Rely on lagging spot indicators while institutional market makers dynamically hedge portfolios based on aggregate dealer gamma (GEX) and wing skew.
3. Experience cognitive overload when interpreting raw quantitative Greeks during live market hours.

CITADEL addresses this through an integrated modular architecture:
- **Decision Synthesis (Oracle & Argus)**: Evaluates microstructure, order flow imbalance, and option surface dynamics in real time.
- **Option Buyer Intelligence (OBI)**: Filters for relative volatility discounts, favorable move response ratios, and supportive dealer positioning.
- **VOB Pullback Engine**: Provides clean price action anchors and structured volume order block reversals.
- **Execution Boundary & Aegis Risk Gate**: Fails closed, guarantees absolute capital protection, zero unhedged rogue orders, and strict paper-to-live graduation gates.

---

## Core Trading Objective & Edge Philosophy

### 1. Asymmetric Convexity Capture
- Minimize deployment during high-IV, mean-reverting absorption regimes.
- Prioritize option buyer capital deployment when:
  1. Implied Volatility (IV) is at a fair or discounted spread relative to Realized Volatility (RV).
  2. The Move Response / Gamma-to-Theta quality ratio is favorable ($\ge 1.5$), meaning small directional moves translate into rapid delta expansion before theta decay erodes capital.
  3. Aggregate dealer positioning (Net GEX) indicates an **Expansion Zone** or supportive momentum rather than a heavy dealer pinning/absorption barrier.

### 2. Absolute Risk Invariants
- **Live Trading Default**: `live_trading_enabled = false` (Hardcoded default fail-safe).
- **Position Limits**: Max 1 lot per strategy instance in paper validation mode, max 2 trades/day per symbol.
- **Hard Kill Switch**: Immediate shutdown on connectivity loss, stale market feed ($> 20\text{s}$ latency), or anomaly threshold breaches.
- **Capital Preservation**: Never average losing option buyer positions. Strict stop losses tied to technical VOB invalidation levels.

---

## Do Not Change
- The requirement that option buying requires **both** directional confirmation and volatility pricing justification.
- The fail-closed safety invariant (`live_trading_enabled = false` by default).
- The separation of quantitative analytical engines from broker execution firewalls.
