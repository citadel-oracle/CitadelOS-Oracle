# ⚡ CITADEL FINAL STATE & MANDATORY AGENT DIRECTIVE

**Document Purpose**: **MANDATORY FIRST READ**. Every future AI agent, developer, or quantitative engineer MUST read this file in full before proposing or executing changes in CITADEL.  
**Date**: 2026-08-22 17:15:00 IST (+05:30)  
**System Authority**: CITADEL OS Master Architecture  

---

## 🏷️ Active Golden Baseline Lineage

| Baseline Layer | Git Commit Hash | Authoritative Git Tag | Purpose & Scope |
|---|---|---|---|
| **Layer 1: Component Golden** | `98ecad03441687a83d620d2896d522fecb093182` | `oracle-option-intelligence-golden-v1` | Option Buyer Intelligence master surface permanently frozen (UI, GEX, Skew, Quality, 1-sec Hero). |
| **Layer 2: Master Knowledge** | `250000333200e00557e6d7206ef90affb98717b0` | `citadel-master-knowledge-v1` | Full 10-module Obsidian architecture specification. |
| **Layer 3: Evidence Governance**| `cbad51014a2005b912d26ba50d74fe6f01ced556` | `citadel-master-evidence-audit-v1` | Strict evidence integrity audit & removal of false certainty. |
| **Layer 4: Final Baseline**     | *[Current Commit]* | `citadel-final-master-baseline-v1` | Permanent unified baseline registration & vault hardening. |

---

## SECTION 1: WHAT CITADEL IS

**CITADEL** is an institutional-grade systematic algorithmic options trading and market intelligence operating system built for Indian Index Derivatives (specifically **NIFTY 50** & **BANKNIFTY**). 

It combines 6 modular layers:
1. **Oracle Decision Surface**: Real-time multi-wheel HUD synthesizing macro flow, micro structure, and execution triggers.
2. **ARGUS Prime**: Microstructure order flow engine computing live volume delta (CVD) and tape absorption.
3. **Option Buyer Intelligence (OBI)**: Quantitative option surface analyzer evaluating real-time IV-RV mispricing, aggregate dealer gamma (Net GEX), Zero-Gamma transition strike, and Gamma/Theta move quality.
4. **VOB Pullback Engine**: BigBeluga Volumetric Order Block reversal detector tracking institutional supply/demand zones.
5. **Edge Sentinel**: Continuous automated forensic auditing, soak testing, clock drift verification, and hypothesis testing.
6. **Fast Backtest Laboratory**: Vectorized DuckDB OLAP engine for multi-year strategy simulation and slippage analysis.

---

## SECTION 2: CURRENT VERIFIED SYSTEM

### 🖥️ Frontend (Next.js 16.2.10 Turbopack / TypeScript 5.8)
- **Route**: `/oracle` (Active, verified, 0 build errors).
- **Master UI Component**: `PhotonicOptionIntelligence.tsx` (mounted directly below the 3-wheel section in `NiftyPhotonicMaster.tsx`).
- **Command Deck**: `VobPullbackCommand.tsx` with refractive VOB energy rails.
- **Client Cache**: Rolling 20-minute client-side ring buffer for live 5m/15m IV velocity deltas.

### ⚙️ Backend (Python 3.11+ / FastAPI / Uvicorn)
- **Fast Lane Publisher**: Unified `/v1/oracle/fast-lane` and `/stream` endpoints with hydrated OBI payloads.
- **Market Data Gateway**: Singleton Dhan WebSocket and REST ingestion with class-level rate limiter ($\ge 3.0\text{s}$).
- **Worker Engine**: `OptionBuyerIntelligenceWorker` + `OptionIntelligenceEngine` evaluating live 50-strike option chains.
- **Process Supervision**: `IsolatedExecutionBoundary` providing crash protection and rehydration in $< 125\text{ms}$.

### 🔒 Safety Invariants
- **Live Trading Default**: `live_trading_enabled = false` (Fail-closed).
- **Zero Frontend Execution**: Dashboard projections are strictly GET-only and cannot place broker orders.
- **Position Limits**: Max 1 lot per strategy instance in paper mode, max 2 trades/day per symbol.

---

## SECTION 3: LOCKED INVARIANTS (PERMANENT RULES)

Every future agent MUST strictly follow these 6 permanent rules:

1. **NEVER change Oracle visual language without explicit user approval**:
   - Preserve dark HUD terminal styling (`#0c060a`), HUD corner brackets, cyan/mint/amber/red color semantics, breathing aura loops, and VOB rail sheen animations.
2. **NEVER introduce fake or synthetic demo data**:
   - When market is closed or feeds disconnect, surfaces MUST display `STANDBY` or `UNAVAILABLE`. Never synthesize fake random numbers to make UI look active.
3. **NEVER move quantitative calculations into the frontend**:
   - All Greeks, Black-Scholes solvers, GEX aggregates, and SMILE fits belong in Python backend engines. Frontend is strictly a presentation and translation layer.
4. **NEVER bypass Sentinel forensic validation**:
   - All new strategy ideas and analytical claims must be verified against historical tick data with zero look-ahead bias ($T_{\text{eval}} \le T_{\text{event}}$).
5. **NEVER modify formulas or quantitative thresholds without an evidence review**:
   - Core math in `option_intelligence.py` and `option_buyer_intelligence.py` is frozen and protected by regression tests.
6. **NEVER claim alpha or win rates before rigorous statistical validation**:
   - Distinguish observed single-session backtest samples from statistically proven institutional edge.

---

## SECTION 4: PRODUCTION VS RESEARCH PIPELINE

| Environment | Included Modules & Features | Operational Policy |
|---|---|---|
| **PRODUCTION PIPELINE** (Frozen & Certified) | • Real Dhan Live Market Gateway<br>• Oracle Fast Lane SSE Stream<br>• Master Option Intelligence Surface<br>• BigBeluga VOB Pullback Track A/B<br>• Argus Tactical Edge & CVD<br>• Aegis Risk Authorization Gate | **STRICTLY FROZEN**: Zero code modifications without complete regression test suite execution. |
| **RESEARCH PIPELINE** (Active Investigation) | • Dealer GEX momentum extension dynamics<br>• Multi-regime IV-RV entry spread optimization<br>• Far-wing $10\Delta$ skew predictive models<br>• Kronos Alpha & Chronos-2 shadow models<br>• Dynamic Kelly Criterion volatility sizing | **EXPERIMENTAL**: Isolated in Strategy Lab and Sentinel test harnesses; no automated execution authority. |

---

## SECTION 5: RESTORATION ORDER & DISASTER RECOVERY

If any regression or breakage occurs, execute recovery in this exact priority hierarchy:

```
┌────────────────────────────────────────────────────────────────────────┐
│  PRIORITY 1: Restore Component Golden Baseline                         │
│  git checkout oracle-option-intelligence-golden-v1                     │
│  (Restores verified PhotonicOptionIntelligence.tsx & Python engines)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  PRIORITY 2: Restore Master Knowledge System                           │
│  git checkout citadel-master-knowledge-v1                              │
│  (Restores complete 10-module Obsidian documentation architecture)     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  PRIORITY 3: Restore Evidence Governance Baseline                      │
│  git checkout citadel-master-evidence-audit-v1                         │
│  (Restores audited claim matrix & scientific integrity standards)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  PRIORITY 4: Rebuild & Restart Production Stack                        │
│  cd citadel-dashboard && npm run build                                 │
│  launchctl kickstart -k "gui/$(id -u)/com.citadel.backend"             │
│  launchctl kickstart -k "gui/$(id -u)/com.citadel.frontend"            │
└────────────────────────────────────────────────────────────────────────┘
```
