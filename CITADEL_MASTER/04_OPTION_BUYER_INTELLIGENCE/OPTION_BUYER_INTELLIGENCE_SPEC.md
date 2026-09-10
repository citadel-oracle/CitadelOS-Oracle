# 04 — OPTION BUYER INTELLIGENCE (OBI) MASTER SPECIFICATION

## Overview
**Option Buyer Intelligence (OBI)** is Citadel's specialized quantitative option surface analyzer designed specifically for intraday options buyers. It answers the 4 most critical questions for any trade:
1. *What is happening right now?*
2. *Which side is favoured? (CALL / PUT / SIDEWAYS / NO EDGE)*
3. *Is option buying cheap/friendly or expensive/risky?*
4. *Why? (The core mechanical driver).*

---

## Status
**PERMANENTLY FROZEN & LOCKED**  
**Golden Checkpoint Tag**: `oracle-option-intelligence-golden-v1`  
**Git Commit**: `98ecad03441687a83d620d2896d522fecb093182`  
**Date**: 2026-08-22

---

## Evidence
- Mathematical verification:
  - Intraday IV-RV spread: $IV - RV_{1\text{M}}$ accurately tracks premium mispricing.
  - HAR-RV (Heterogeneous Autoregressive Realized Volatility) daily/weekly/monthly forecast.
  - Gamma-to-Theta Quality ratio: $\mathcal{Q} = \frac{\Gamma \times S}{|\Theta_{\text{daily}}| \times \text{spread}}$.
  - Net GEX (Gamma Exposure) across full 50-strike option chain.
  - $25\Delta$ and $10\Delta$ Skew Spreads ($IV_{\text{Put}} - IV_{\text{Call}}$).
- Production UI verification: Real browser screenshot rendered and audited at `/oracle` with 0 errors.

---

## The 6 Quantitative Pillars (Locked Specifications)

### 1. HERO 1-SECOND COGNITION & WHEEL VECTOR
The top layer provides an immediate, cognitive summary within 1 second of viewing:
- **Primary Hero State (Single Final State)**:
  - `CALL FRIENDLY`: Green tone (`var(--mint)`), Fast plasma orbit.
  - `PUT FRIENDLY`: Green tone (`var(--mint)`), Fast plasma orbit.
  - `SIDEWAYS / SELECTIVE`: Amber tone (`var(--amber)`), Slow calm orbit.
  - `NO OPTION EDGE`: Crimson tone (`var(--algory-red)`), Sharp warning pulse.
  - `AWAITING FEED`: Dim tone (`var(--text-lo)`), Standby breathing.
- **Secondary Context Subtitle**: `Premium Cheap / Buyer Friendly`, `Fair Premium / Selective`, `Premium Expensive / Theta Risk`.
- **Live Driver Chips**:
  - `[PUT PROTECTION DEMAND 8.07%]` / `[CALL UPSIDE DEMAND]` / `[BALANCED PREMIUM DEMAND]`
  - `[FEAR RISING ↑]` / `[FEAR SUBSIDING ↓]` / `[IV STABLE →]`
  - `[PREMIUM CHEAP]` / `[FAIR PREMIUM]` / `[PREMIUM EXPENSIVE]`
  - `[🟢 ABSORBING ZONE]` / `[🔴 EXPANSION ZONE]`
- **Plain Language Translation**:
  - *"Market balance me hai — dono taraf symmetrical demand hai."*
  - *"Downside protection ki demand badh rahi hai."*
  - *"Upside participation aur call demand active hai."*
- **Actionable Conclusion**:
  - `CONCLUSION: Sideways / selective — balanced premium demand and no clear directional edge.`
  - `CONCLUSION: PUT protection demand increasing but premium cost is high — selective entry only.`

### 2. IV VELOCITY & HEDGE DEMAND
Tracks live Implied Volatility acceleration across the ATM strike and both wings:
- **5 Mini Cards**:
  1. `ATM IV (Market Fear)`: `FEAR RISING ↑` / `FEAR STABLE →` / `FEAR SUBSIDING ↓`
  2. `25Δ CALL IV (Upside Demand)`: `DEMAND RISING` / `CALL WING`
  3. `25Δ PUT IV (Downside Protection)`: `PROTECTION BUYING` / `PUT WING BID` / `NORMAL`
  4. `10Δ CALL IV (Far Upside)`: `SPECULATION RISING` / `FAR CALL`
  5. `10Δ PUT IV (Tail Hedge)`: `TAIL HEDGING` / `TAIL HEDGE` / `NORMAL`
- **Section Summary**: `PUT PREMIUM DEMAND DOMINANT` / `CALL PREMIUM DEMAND DOMINANT` / `BALANCED PREMIUM DEMAND`.

### 3. OPTION QUALITY (MOVE RESPONSE & TIME DECAY)
Evaluates whether contracts provide efficient move capture vs decay drag:
- **Move Response**:
  - `FAST ⚡` ($\mathcal{Q} \ge 2.0$ or Prime rating): Delta accelerates quickly on small moves.
  - `NORMAL` ($1.0 \le \mathcal{Q} < 2.0$): Standard responsiveness.
  - `SLOW` ($\mathcal{Q} < 1.0$): High premium inertia, slow delta expansion.
- **Time Decay**:
  - `LOW` ($|\Theta_{\text{daily}}| \le 10\text{ pts}$): Manageable holding risk.
  - `MEDIUM` ($10 < |\Theta_{\text{daily}}| \le 20\text{ pts}$): Moderate decay pressure.
  - `HIGH` ($|\Theta_{\text{daily}}| > 20\text{ pts}$): Heavy intraday bleed.
- **Entry Cost**: Top bid-ask spread in ₹ points.
- **Decision Badge**: `● GOOD FOR BUYING` vs `● WEAK FOR BUYING`.

### 4. DEALER POSITION (NET GEX CONTEXT)
Calculates institutional dealer gamma positioning to detect market pinning vs extension risk:
- **Metrics**: `NET GEX` in ₹ Cr, `CALL SUPPORT ₹ Cr` vs `PUT PRESSURE ₹ Cr`.
- **Market Effect**:
  - 🟢 **ABSORBING** ($\text{Net GEX} \ge 0$): Dealers are long gamma; they buy dips and sell rips, dampening volatility.
  - 🔴 **EXPANSION** ($\text{Net GEX} < 0$): Dealers are short gamma; dynamic delta hedging accelerates directional expansion.
- **Note**: Structural context only — not a direct trade trigger.

### 5. ZERO GAMMA TRANSITION LEVEL
Identifies the exact strike $K^*$ where aggregate dealer gamma flips from positive to negative:
- **Metrics**: `LEVEL` (e.g. $24,259.8$) and `DISTANCE` (e.g. $25.35\text{ pts}$).
- **Market Behaviour**:
  - 🟢 **ABSORBING ZONE** (Spot above $K^*$): Market holding above pivot; moves slow down and reject extension.
  - 🔴 **EXPANSION ZONE** (Spot below $K^*$): Market below pivot; moves can accelerate across strikes.

### 6. HEDGE DEMAND (WING CONTEXT)
Measures the $25\Delta$ and $10\Delta$ volatility smile skew:
- **Metric**: `PUT vs CALL Demand Gap` ($IV_{25\Delta\text{ PE}} - IV_{25\Delta\text{ CE}}$).
- **Interpretation**:
  - 🔴 *"Traders are paying more for downside protection"* (Put wing rich).
  - 🟢 *"Upside demand increasing"* (Call wing rich).
  - ⚪ *"Balanced demand"* (Symmetrical smile).
- **Core Principle**: High Put protection means institutional downside insurance is in demand, not automatically that market is dumping.

---

## Do Not Change
- The 4-tier visual hierarchy in `PhotonicOptionIntelligence.tsx`.
- The quantitative formulas in `src/oracle/option_intelligence.py` and `src/oracle/option_buyer_intelligence.py`.
- The plain-language trader translation layer.
