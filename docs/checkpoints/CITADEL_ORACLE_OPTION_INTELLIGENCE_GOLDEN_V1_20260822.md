# CITADEL ORACLE OPTION INTELLIGENCE — PERMANENT GOLDEN CHECKPOINT (v1.0.0)

**Date**: 2026-08-22 17:05:00 IST (Asia/Kolkata)  
**Golden Tag**: `oracle-option-intelligence-golden-v1`  
**Status**: **ACCEPTED & PERMANENTLY LOCKED**  
**Component**: `citadel-dashboard/src/components/institutional/NiftyPhotonicMaster/components/PhotonicOptionIntelligence.tsx`  
**Parent Surface**: `/oracle` (`NiftyPhotonicMaster.tsx`)  
**Backend Feeds**: `FastLanePublisher` (`feeds.option_buyer_intelligence.data.option_intelligence`) & `OptionBuyerIntelligenceWorker`

---

## 1. Scope & Permanent Design Lock

This golden checkpoint permanently freezes the architecture, trader-facing decision translation layer, motion system, and data contract of the **Citadel Oracle Option Intelligence Master Surface**.

### INVARIANTS (NEVER MODIFY):
1. **Oracle Visual System**: Dark HUD terminal styling (`var(--bg-surface)` #0c060a, `var(--line-dim)`, glass acrylic borders, HUD corner brackets).
2. **Color Semantics**:
   - `var(--mint)` (`#00ff9d`): Favorable, buyer expansion, absorbing structure.
   - `var(--algory-red)` (`#ff1e4b`): Expensive vol, theta risk, expansion risk.
   - `var(--amber)` (`#ffb800`): Selective, fair value, transition level.
   - `var(--cyan)` (`#00f0ff`): Subdued structural accent, velocity cards.
3. **Motion Language**:
   - Low-frequency breathing on the card wrapper (`.breatheGreen`, `.breatheRed`, `.breatheAmber`, `.breatheStandby`).
   - Dynamic ARGUS Plasma Orb speeds (`.orbFastOrbit`, `.orbSlowOrbit`, `.orbRiskPulse`).
   - Animated VOB refractive energy rails (`.vobRailTrack` with `@keyframes vobRefract`).
4. **Backend Invariant**: Zero synthetic data, zero fake scores. If live stream is disconnected, gracefully display `STANDBY` / `UNAVAILABLE`.

---

## 2. Option Buyer Intelligence Architecture (The 7 Locks)

### 🔒 LOCK 1: HERO 1-SECOND COGNITION & WHEEL SYNTHESIS
* **Single Final State Only**:
  - `CALL FRIENDLY`
  - `PUT FRIENDLY`
  - `SIDEWAYS / SELECTIVE`
  - `NO OPTION EDGE`
  - `AWAITING FEED`
* **Wheel Center Badge**: Matches Hero primary state exactly (`CALL / FRIENDLY`, `PUT / FRIENDLY`, `SIDEWAYS / SELECTIVE`, `NO EDGE / THETA RISK`, `STANDBY / OFFLINE`).
* **Supporting Context Subtitle**: `Premium Cheap / Buyer Friendly`, `Fair Premium / Selective`, or `Premium Expensive / Theta Risk`.
* **Live Driver Chips**:
  1. Directional Demand: `PUT PROTECTION DEMAND 8.07%` / `CALL UPSIDE DEMAND` / `BALANCED PREMIUM DEMAND`
  2. IV Velocity / Market Fear: `FEAR RISING ↑` / `FEAR SUBSIDING ↓` / `IV STABLE →`
  3. Premium Pricing: `PREMIUM CHEAP` / `FAIR PREMIUM` / `PREMIUM EXPENSIVE`
  4. Dealer Context: `🟢 ABSORBING ZONE` / `🔴 EXPANSION ZONE`
* **Plain Meaning & Conclusion**:
  - `▶ [Plain Language Explanation in Hindi/English]`
  - `CONCLUSION: [Actionable decision summary combining demand, cost, quality, and GEX context]`

---

### 🔒 LOCK 2: HEURISTIC GEX PROFILE
* **Header**: `GEX REGIME · HEURISTIC // DEALER-GAMMA ESTIMATE`
* **Metrics**:
  - `NET GEX` (`₹ Cr` signed)
  - `CALL SUPPORT ₹ Cr` vs `PUT PRESSURE ₹ Cr` (VOB rail)
* **Market Effect Classification**:
  - 🟢 **ABSORBING**: *"Moves may slow down and extension can get rejected"* (When Net GEX $\ge 0$)
  - 🔴 **EXPANSION**: *"Moves can extend faster"* (When Net GEX $< 0$)
* **Principle**: Structure context only — not a direct trade trigger. Dealer positioning is inferred, and Dhan OI units remain pending independent certification.

---

### 🔒 LOCK 3: HEURISTIC STRIKE GEX CROSS
* **Header**: `STRIKE GEX CROSS // HEURISTIC · NON-CANONICAL`
* **Metrics**:
  - `LEVEL`: Strike level $K^*$
  - `DISTANCE`: Distance from spot/forward in points
* **Method**: Per-strike signed-GEX crossing heuristic; not a canonical aggregate gamma-flip calculation.
* **Market Behaviour**:
  - 🟢 **ABSORBING ZONE**: *"Moves may slow down and reject extension"* (Market holding above transition level)
  - 🔴 **EXPANSION ZONE**: *"Moves can extend faster across strikes"* (Market below transition level)

---

### 🔒 LOCK 4: OPTION QUALITY (MOVE RESPONSE & TIME DECAY)
* **Headers**: `CALL OPTION QUALITY (ATM CE)` and `PUT OPTION QUALITY (ATM PE)`
* **Trader-Facing Metrics**:
  - **`MOVE RESPONSE`**:
    - `FAST ⚡` (Prime quality ratio $\ge 2.0$)
    - `NORMAL` (Acceptable quality ratio $\ge 1.0$)
    - `SLOW` (Weak quality ratio $< 1.0$)
  - **`TIME DECAY`**:
    - `LOW` ($|\Theta_{\text{daily}}| \le 10$)
    - `MEDIUM` ($10 < |\Theta_{\text{daily}}| \le 20$)
    - `HIGH` ($|\Theta_{\text{daily}}| > 20$)
  - **`ENTRY COST`**: Top bid/ask spread friction in ₹ points
  - **Final Badge**: `● GOOD FOR BUYING` vs `● WEAK FOR BUYING`
  - **Subtext**: *"Premium fast react kar sakta hai aur decay manageable hai"* vs *"Move response slow hai ya time decay pressure zyada hai"*

---

### 🔒 LOCK 5: HEDGE DEMAND (WING HEDGING CONTEXT)
* **Header**: `HEDGE DEMAND // WING HEDGING CONTEXT`
* **Metrics**:
  - `PUT vs CALL Demand Gap` ($25\Delta$ Skew Spread %)
  - `CALL UPSIDE BET` ($25\Delta$ CE IV) vs `PUT PROTECTION` ($25\Delta$ PE IV)
  - $10\Delta$ CE IV vs $10\Delta$ PE IV
* **Interpretations**:
  - 🔴 *"Traders are paying more for downside protection"*
  - 🟢 *"Upside demand increasing"*
  - ⚪ *"Balanced demand across wings"*
* **Principle**: PUT protection reflects institutional downside insurance demand, not automatically directional bearishness.

---

### 🔒 LOCK 6: IV VELOCITY (MARKET FEAR DYNAMICS)
* **Header**: `IV VELOCITY & HEDGE DEMAND // ATM & WING ACCELERATION`
* **Mini Velocity Cards**:
  1. `ATM IV (Market Fear)`: `FEAR RISING ↑` / `FEAR SUBSIDING ↓` / `FEAR STABLE →` (with 5m / 15m deltas)
  2. `25Δ CALL IV (Upside Demand)`: `DEMAND RISING` / `CALL WING`
  3. `25Δ PUT IV (Downside Protection)`: `PROTECTION BUYING` / `PUT WING BID` / `NORMAL`
  4. `10Δ CALL IV (Far Upside)`: `SPECULATION RISING` / `FAR CALL`
  5. `10Δ PUT IV (Tail Hedge)`: `TAIL HEDGING` / `TAIL HEDGE` / `NORMAL`
* **Section Summary Badge**: `PUT PREMIUM DEMAND DOMINANT` / `CALL PREMIUM DEMAND DOMINANT` / `BALANCED PREMIUM DEMAND`

---

### 🔒 LOCK 7: PRODUCTION DEPLOYMENT & RESTORATION

#### Key Source Files:
- Component: `citadel-dashboard/src/components/institutional/NiftyPhotonicMaster/components/PhotonicOptionIntelligence.tsx`
- Parent CSS: `citadel-dashboard/src/components/institutional/NiftyPhotonicMaster/NiftyPhotonicMaster.module.css`
- Mounting Parent: `citadel-dashboard/src/components/institutional/NiftyPhotonicMaster/NiftyPhotonicMaster.tsx`
- Engine Logic: `src/oracle/option_intelligence.py` & `src/oracle/option_buyer_intelligence.py`
- Store Parsing: `citadel-dashboard/src/dashboard/store/oracleStore.ts`

#### How to Restore / Rebuild:
```bash
# 1. Build dashboard
cd /Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/citadel-dashboard
npm run build

# 2. Restart frontend service
launchctl kickstart -k "gui/$(id -u)/com.citadel.frontend"

# 3. Verify in browser
open http://localhost:3000/oracle
```

---

## 3. Forensic Artifact & Visual Proof

- Checkpoint Screenshot: `oracle_decision_translation_final.png`
- Recorded Hash: `oracle-option-intelligence-golden-v1`
- Next.js Turbopack Build: `11/11 routes passing, 0 TypeScript errors`
