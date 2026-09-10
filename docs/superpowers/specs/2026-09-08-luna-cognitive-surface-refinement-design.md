# Design Spec: Citadel Luna Cognitive Surface Refinement & Bull/Bear State Mapping

## 1. Context & Motivation
The Citadel Oracle dashboard features an institutional-grade award-motion cognitive experience. However, traders and observers need the cognitive stage to be **self-explanatory at a single glance**:
1. **LEFT PANEL**: What Luna received (the deterministic evidence stream).
2. **CENTER PANEL**: What Luna is currently thinking/stating (the hero state & orbital centerpiece).
3. **RIGHT PANEL**: What Luna concluded (the interpreted decision surface, competing hypotheses, and counter-case).
4. **BULL / BEAR ANIMATIONS**: Clear, cinematic visual correspondence with the underlying market state so that force dominance is instantly recognizable.

All refinements must strictly preserve the existing award-motion visual identity (fonts, glows, palette, orbital globe, cinematic dark theme), preserve truth invariants (zero fake numbers or causality overclaims), and keep VOB execution boundaries completely untouched (`execution_influence = 0`, `ai_vob_influence = 0`).

---

## 2. Canonical Luna State Audit & Bull/Bear Animation Mapping

### 2.1 State Audit Matrix

| State Identifier | Semantic Meaning | Active/Historical | Primary Hero Display |
|---|---|---|---|
| `CALL_DEVELOPING` | Emerging call-side structure with expanding call premiums | Active / Developing | `CALL` / `DEVELOPING` |
| `PUT_DEVELOPING` | Emerging put-side structure with expanding put premiums | Active / Developing | `PUT` / `DEVELOPING` |
| `WAIT` (or `NO_TRADE`) | Balanced/chop conditions; no directional edge | Active / Monitoring | `WAIT` / `MONITORING` |
| `REVERSAL_WATCH` | Active price move conflicting with underlying order flow | Active / Alert | `REVERSAL` / `WATCH` |
| `ANALYZING` | Model inference in-flight; ingesting new revision | Transient / Processing | `ANALYZING` / `EVIDENCE` |
| `STALE` | Prior session or revision mismatch without fresh intake | Degraded / Non-Current | `LAST KNOWN` / `STALE` |
| `UNAVAILABLE` | Genuinely missing stream, provider error, or disconnected | System Degraded | `UNAVAILABLE` / `PENDING` |
| `SESSION_LAST` | Session closed; authoritative final accepted analysis retained | Frozen Historical Audit | `CALL` / `DEVELOPING` (`· SESSION LAST ·`) |

---

### 2.2 Bull / Bear Animation Mapping

The `LivingMarketForcesViewport` uses a 5-layer visual stack:
- **Layer 1**: Volumetric Light Rays Canvas (Bull cyan/teal rays vs Bear crimson rays).
- **Layer 2**: Multi-Layer Video Stack (`vidBalanced`, `vidBullPressure`, `vidBullDominant`, `vidBearPressure`, `vidBearDominant`).
- **Layer 3**: Atmospheric Micro-Motes Particle Canvas (directional velocities and emission alphas).
- **Layer 4**: Radial Obsidian Vignette & Filter Stage.
- **Layer 5**: Minimal Institutional HUD Header & Tags (`actorTagCall`, `actorTagPut`, `marketStateBadge`).

#### Detailed Behavior Specification by State:
1. **`CALL_DEVELOPING`**:
   - **Video**: `vidBullPressure` (Loop 26.50s -> 30.00s).
   - **Rays**: Bull ray target alpha `0.28` (cyan/green flare), Bear ray target `0.04`. Initial 1.3x pulse on transition.
   - **Particles**: Cyan motes accelerate rightward (vx > 0), alpha elevated to 0.75. Crimson motes subdued (alpha 0.20).
   - **HUD**: Bull tag highlighted (`actorTagDominant`, cyan border glow). Bear tag dimmed. Badge: `CALL DEVELOPING` / `BULL PRESSURE`.
2. **`PUT_DEVELOPING`**:
   - **Video**: `vidBearPressure` (Loop 18.50s -> 20.00s).
   - **Rays**: Bear ray target alpha `0.32` (crimson blaze), Bull ray target `0.03`. Initial 1.3x pulse on transition.
   - **Particles**: Crimson motes accelerate leftward (vx < 0, vy < 0), alpha elevated to 0.80. Cyan motes subdued (alpha 0.20).
   - **HUD**: Bear tag highlighted (`actorTagDominant`, crimson border glow). Bull tag dimmed. Badge: `PUT DEVELOPING` / `BEAR PRESSURE`.
3. **`WAIT` / `NO_TRADE`**:
   - **Video**: `vidBalanced` (Loop `dual-01-balanced-sideways.mp4`).
   - **Rays**: Equal balance: Bull target `0.10`, Bear target `0.10`.
   - **Particles**: Neutral symmetric float, base alpha `0.30`, no directional bias.
   - **HUD**: Both tags equal opacity, neutral grey border. Badge: `NO TRADE` / `BALANCED`.
4. **`REVERSAL_WATCH`**:
   - **Video**: `vidBalanced` with high-tension particle friction.
   - **Rays**: Both Bull and Bear rays raised to `0.22` with counter-phase oscillation, creating visual tension at the center convergence line.
   - **Particles**: Turbulent motes where cyan and red motes cross each other with increased random jitter (vx +/- 0.8).
   - **HUD**: Amber warning accent. Badge: `REVERSAL WATCH` / `HORIZON CONFLICT`.
5. **`ANALYZING`**:
   - **Video**: `vidBalanced` with subtle soft focus / scanning overlay.
   - **Rays**: Gentle scanning sweep across both sides (`0.08` alpha with sinusoidal sweep).
   - **Particles**: Cyan scanning pulses moving horizontally.
   - **HUD**: Badge: `ANALYZING` / `INFERENCE IN-FLIGHT` with pulsating amber/cyan pill.
6. **`STALE`**:
   - **Video**: `vidBalanced` (or last known video) with desaturation filter (`filter: saturate(0.4) brightness(0.7)`).
   - **Rays**: Muted target alpha `0.05`.
   - **Particles**: Reduced speed (0.3x) and low opacity (0.15).
   - **HUD**: Muted amber badge: `LAST KNOWN` / `NOT CURRENT`.
7. **`UNAVAILABLE`**:
   - **Video**: `vidBalanced` paused or ultra-low opacity (`0.25`), dormant background.
   - **Rays**: Dormant alpha `0.02`.
   - **Particles**: Near static / dormant.
   - **HUD**: Grey/red badge: `SYSTEM UNAVAILABLE` / `DATA PENDING`.
8. **`SESSION_LAST`**:
   - **Video**: Matches last accepted directional state (`vidBullPressure` for Cutoff 4), rendered with institutional archive grade styling (`filter: saturate(0.85) contrast(1.05)`).
   - **Rays**: Bull alpha `0.20`, Bear alpha `0.04` (stable, steady, non-blinking).
   - **Particles**: Calm ambient drift (retained state).
   - **HUD**: Clear historical audit badge: `CALL DEVELOPING` / `· SESSION LAST · MARKET CLOSED ·`. Never displays as `LIVE`.

---

## 3. 3-Panel Information Architecture inside `CognitiveDecisionCore`

### 3.1 Left Panel — What Luna Received (Input Evidence Bus)
Divided into 4 clean, high-contrast institutional telemetry blocks:
1. **Underlying & Futures Dynamics**:
   - `NIFTY SPOT`: 23657.70
   - `FUTURES LTP`: 23672.40
   - `BASIS`: +14.70 (with change indicator)
   - *Status badge*: `SESSION LAST` or `LIVE`
2. **Option Premium Response**:
   - `ATM STRIKE`: 23650
   - `ATM CE LTP & Δ`: ₹48.85 (expanded from 40.95)
   - `ATM PE LTP & Δ`: ₹28.20 (declined from 31.95)
   - `ATM STRADDLE`: ₹77.05 (net change near-flat)
   - `BID/ASK SPREAD`: ₹0.20 / ₹0.25
3. **OI Distribution & Kinematics**:
   - `SESSION ΔOI (C/P)`: +1.42M / -0.84M
   - `SUDDEN 5m OI`: Call pulse detected
   - `OI VELOCITY`: +12.4k contracts/min
   - `OI ACCELERATION`: +1.8k contracts/min²
   - `OI CONCENTRATION`: 0.38 (top strike ratio)
   - `BUILDUP CLASSIFICATION`: `LONG BUILDUP (HEURISTIC)*` with disclaimer tooltip: *"Heuristic label based on price & OI change. Does not claim participant identity or writer causality."*
4. **Structure & Volatility Metrics**:
   - `PCR (OI)`: 1.14 (canonical open-interest put-call ratio)
   - `TOTAL NET GEX`: +₹412 Cr (Dealer Regime: `LONG_GAMMA`)
   - `ZERO GAMMA LEVEL`: 23550
   - `ATM IV & SKEW`: IV 13.82%, 25d skew +1.20%
   - `INDIA VIX`: `UNAVAILABLE` (truthfully labeled; never faked)

### 3.2 Center Panel — Existing Luna Hero Globe & Cognitive Stage
Preserved in its full cinematic glory:
- Dominant 56px typography (`CALL DEVELOPING`, `PUT DEVELOPING`, `WAIT`, `REVERSAL WATCH`, `ANALYZING`, `UNAVAILABLE`)
- Concentric 360px gyroscopic gimbal rings with SVG consensus arcs
- Breathing optical iris core
- 2.5D holographic globe canvas with orbital particle nodes
- Readiness kicker badge (`· SESSION LAST · MARKET CLOSED ·`)
- Flow agreement tag (`SESSION LAST · NOT CURRENT` or `FLOW CONFIRMED`)
- Visual connector cues (`◀ INCOMING EVIDENCE BUS` and `CONCLUDED DECISION ▶`) to anchor the 3-panel architecture
- Timestamp and revision chip (`08 Sept, 14:35 IST · r4`)

### 3.3 Right Panel — What Luna Concluded (Decision Surface)
Concise, structured, and institutional:
1. **Primary Synthesis Thesis**:
   - Active thesis narrative with cited canonical event brackets (`[evt_...]`)
   - Institutional "Why Luna is favoring this view" readout
2. **Falsification Counter-Case**:
   - Explicit invalidation condition: what facts break or weaken this thesis
3. **4-Way Competing Hypotheses Cluster**:
   - `CALL CONTINUATION`: `PLAUSIBLE`
   - `PUT EXPANSION`: `WEAKENED`
   - `CHOP / NOISE`: `PLAUSIBLE`
   - `REVERSAL THESIS`: `UNRESOLVED`
4. **Temporal Horizon & Readiness**:
   - `THESIS EVOLUTION`: `STRENGTHENING`
   - `OPPORTUNITY MATURITY`: `EMERGING`
   - `REVERSAL POSTURE`: `QUIET`
   - `ENTRY WINDOW`: `SESSION LAST` / `WAIT`

---

## 4. Truth Invariants & Non-Negotiables
1. **No Fake Numbers or Extrapolations**: If a sensor is unavailable or disconnected, display `UNAVAILABLE` or `NOT REPORTED`.
2. **Heuristic Disclaimers**: Buildup classifications are strictly labeled as heuristic context.
3. **No Writer Causality Claims**: OI changes are never framed as "smart money writing calls".
4. **Strict Isolation**: `execution_influence = 0`, `ai_vob_influence = 0`. No broker logic or trading routes modified.

