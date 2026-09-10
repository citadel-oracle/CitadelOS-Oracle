# 🛰️ CURRENT CITADEL STATE & SYSTEM INVARIANTS

**Last Updated**: 2026-08-22 17:06:00 IST (+05:30)  
**Active Baseline Tag**: `oracle-option-intelligence-golden-v1`  
**Primary Git Commit**: `98ecad03441687a83d620d2896d522fecb093182`  
**Platform**: macOS Darwin / Apple Silicon  
**Engine**: Python 3.11+ / FastAPI / Uvicorn  
**Frontend**: Next.js 16.2.10 (Turbopack) / React 19 / TypeScript 5.8  

---

## 1. What is Working? (Operational & Live-Verified)

1. **Live Data Ingestion**:
   - Dhan HQ WebSocket binary tick & full 5-level depth feed.
   - Singleton Market Data Gateway with class-level monotonic rate limiting ($\ge 3.0\text{s}$).
2. **Real-time Analytical Engines**:
   - **Argus Prime**: Multi-timeframe order flow & CVD calculations ($< 4.5\text{ms}$ latency).
   - **Option Buyer Intelligence (OBI)**: Live continuous IV-RV calculation, 50-strike GEX profiles, Zero-Gamma transition strike solver, and Move Response/Time Decay quality scoring.
   - **VOB Engine**: BigBeluga Volumetric Order Block detection and pullback tracking.
3. **High-Speed Serialization**:
   - Fast Lane Publisher streaming unified snapshots over SSE and REST (`/v1/oracle/fast-lane`).
4. **Institutional HUD Dashboard (`/oracle`)**:
   - Multi-wheel decision vector matrix.
   - Photonic VOB Pullback Command deck.
   - Master Option Intelligence 4-Tier decision surface (`PhotonicOptionIntelligence.tsx`).
   - Real-time client-side IV history ring buffer computing rolling 5m/15m velocity deltas.

---

## 2. What is Frozen? (Locked Specifications)

1. **Option Buyer Intelligence Master Surface**:
   - Locked under tag `oracle-option-intelligence-golden-v1`.
   - Single final hero state (`CALL FRIENDLY`, `PUT FRIENDLY`, `SIDEWAYS / SELECTIVE`, `NO OPTION EDGE`, `AWAITING FEED`).
   - Plain-language trader translation layer.
   - Card structure, breathing glow loops, plasma orb motion, and VOB rail styles.
2. **Oracle R3 Infrastructure Spine**:
   - Process-isolated execution boundaries (`IsolatedExecutionBoundary`).
   - `CURRENT` vs `LAST_GOOD` state separation.
   - Worker crash supervision ($< 125\text{ms}$ recovery).
3. **Broker Safety Boundary**:
   - `live_trading_enabled = false` by default.
   - Zero broker mutation methods accessible from dashboard projections.

---

## 3. What is Experimental? (Under Continuous Research)

1. **Kronos Alpha & Chronos-2 Forecasting**:
   - Running in read-only shadow evaluation mode. No automated execution influence.
2. **Deep Tail Skew Alpha Correlation**:
   - Evaluating multi-session predictive accuracy of $10\Delta$ wing spikes during volatile news events.
3. **Automated Dynamic Sizing**:
   - Testing Kelly Criterion volatility sizing in paper simulation before graduating to risk-engine approval.

---

## 4. What Should NEVER Be Changed? (System Invariants)

1. **Never Fabricate Data**: Cold or disconnected streams MUST display `STANDBY` or `UNAVAILABLE`. Never synthesize fake demo values.
2. **Never Change UI Design Language**: Keep the dark HUD terminal aesthetic (`#0c060a`, cyan, mint, amber, crimson). No gaming UI or decorative clutter.
3. **Never Remove the Dhan Rate Limiter**: Full REST option chain requests must strictly adhere to the $\ge 3.0\text{s}$ throttle to prevent IP bans.
4. **Never Run Recalculations on the Frontend**: All quantitative Greek math, GEX aggregates, and SMILE fits belong in backend Python engines; frontend only consumes and displays.
5. **Never Bypass the Aegis Risk Gate**: All trade opportunities must pass closed-candle validation, position limits, and risk authorization.

---

## 5. How to Restore the Complete System (Disaster Recovery)

If any future change introduces regressions or breaking behavior, execute this exact sequence to restore the complete golden state:

```bash
# Step 1: Navigate to repository root
cd /Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9

# Step 2: Checkout the golden checkpoint tag
git checkout oracle-option-intelligence-golden-v1

# Step 3: Rebuild the Next.js frontend
cd citadel-dashboard
npm run build

# Step 4: Restart backend and frontend launchd daemons
launchctl kickstart -k "gui/$(id -u)/com.citadel.backend"
launchctl kickstart -k "gui/$(id -u)/com.citadel.frontend"

# Step 5: Verify live operation in browser
open http://localhost:3000/oracle
```
