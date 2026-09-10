# 09 — CITADEL ORACLE UI DESIGN SYSTEM & PERMANENT VISUAL RULES

## Overview
The **Citadel Oracle UI System** is an institutional-grade dark HUD terminal interface engineered for maximum visual hierarchy, 1-second cognitive parsing, low visual fatigue, and zero gaming distractions.

---

## Status
**PERMANENTLY FROZEN & LOCKED**

---

## Evidence
- Production user testing across live market sessions.
- Tested and verified across desktop and widescreen displays (1600x1200+ viewport).
- Zero layout jitter, smooth CSS GPU-accelerated transforms.

---

## Permanent Design Tokens & Rules

### 1. Color Palette (Semantic Meaning)
- **Background Surface**: `var(--bg-surface)` (`#0c060a`) — Ultra-dark obsidian background.
- **Card Background**: `rgba(0, 0, 0, 0.35)` with `1px solid var(--line-dim)`.
- **`var(--mint)` (`#00ff9d`)**: Favorable buyer expansion, call strength, cheap vol, absorbing dealer zone.
- **`var(--algory-red)` (`#ff1e4b`)**: Warning, expensive vol, theta bleed, put pressure, expansion risk.
- **`var(--amber)` (`#ffb800`)**: Selective, fair value premium, zero gamma pivot level.
- **`var(--cyan)` (`#00f0ff`)**: Structural accent, IV velocity cards, technical labels.
- **`var(--text-white)` (`#ffffff`)** / **`var(--text-mid)` (`#a0a0a0`)** / **`var(--text-lo)` (`#555555`)**.

### 2. Motion Language (Restrained & Institutional)
- **Low-Frequency Breathing Glow**:
  - Green (`.breatheGreen`): $3.0\text{s}$ soft expansion pulse.
  - Red (`.breatheRed`): $2.0\text{s}$ controlled warning pulse.
  - Amber (`.breatheAmber`): $4.0\text{s}$ calm neutral pulse.
  - Standby (`.breatheStandby`): $4.5\text{s}$ low-frequency calm breathing.
- **ARGUS Plasma Orb**:
  - Continuous smooth rotation (`.orbFastOrbit`, `.orbSlowOrbit`) with liquid core glow.
- **VOB Energy Rails**:
  - Subtle refractive sheen sweep (`@keyframes vobRefract`) simulating high-speed fiber optics across active meters.

### 3. Typography Hierarchy
- **Display Headings**: `var(--font-display)` (JetBrains Mono / Inter Display bold), uppercase, letter-spacing `-0.01em` to `0.02em`.
- **Technical Metrics / Values**: `var(--font-mono)` (Tabular figures, monospace, bold `13.5px`–`15px`).
- **HUD Subtext & Labels**: Monospace, `7.5px`–`8.5px`, uppercase with `letter-spacing: 0.1em`.

### 4. Component Structure & Framing
- **HUD Corner Brackets**: Acrylic cyan/amber corner brackets (`.hudTl`, `.hudTr`, `.hudBl`, `.hudBr`) on all master cards.
- **Pills**: Compact status pills (`.pillMint`, `.pillRed`, `.pillAmber`) with small pulsing dot.

---

## 🚫 NEVER CHANGE LIST
1. **NO Gaming UI**: Never introduce flashy particle effects, neon rainbows, or cartoon gamification.
2. **NO Layout Resizing**: Never compress Option Intelligence into small cramped sidebars; it must remain a full-width master section below the 3-wheel row.
3. **NO Font Inconsistencies**: Never use serif or casual non-institutional fonts.
4. **NO Metric Clutter**: Keep 1-second cognition paramount: State first, then live drivers, then plain Hindi/English translation, then core metrics.
