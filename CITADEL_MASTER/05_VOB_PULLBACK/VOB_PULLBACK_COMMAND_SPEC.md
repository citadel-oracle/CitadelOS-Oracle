# 05 — VOB PULLBACK COMMAND SPECIFICATION

## Overview
The **VOB Pullback Engine** implements BigBeluga Volumetric Order Block (VOB) detection and pullback reversal strategies on Indian index derivatives (NIFTY 5-minute and 1-minute execution).

---

## Status
**FROZEN & ACCEPTED (Track A Baseline / Track B Confirmed Reversal Active)**

---

## Evidence
- Mathematical verification of Pine Script parity (`tests/test_vob_chronological_replay_parity.py` and `tests/vob/test_multi_timeframe_trades.py`):
  - Deterministic $O(N)$ chronological replay.
  - Identification of True High Volume Nodes (HVN) and impulse order blocks.
  - Zero forward-look leakage: VOB blocks finalize strictly on candle close ($T_{\text{close}}$).

---

## Architecture & Dual-Track Execution

```
                       ┌────────────────────────────────┐
                       │     5M / 1M NIFTY CANDLES      │
                       └───────────────┬────────────────┘
                                       │
                                       ▼
                       ┌────────────────────────────────┐
                       │      VOB DETECTION ENGINE      │
                       │   - Volume Impulse Imbalance   │
                       │   - Order Block Boundary (High/Low)│
                       │   - Invalidation Detection     │
                       └───────────────┬────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │  TRACK A: VOB ONLY    │             │  TRACK B: CONFIRMED   │
        │  Pure Pine Parity     │             │  Argus Flow + OBI     │
        │  Direct Limit Pullback│             │  Confluence Reversal  │
        └───────────────────────┘             └───────────────────────┘
```

---

## Key Concepts & Pine Parity Rules

1. **Order Block Formation**:
   - Requires abnormal volume spike ($\ge 1.8\times$ 20-period volume SMA) combined with a displacement body candle ($\ge 60\%$ body-to-range ratio).
   - The origin candle's high and low form the upper and lower boundaries of the active VOB zone.

2. **Pullback Reversal Entry**:
   - **Bullish VOB**: Price moves higher, then retraces into the demand order block without closing below the block low.
   - **Bearish VOB**: Price drops lower, then retraces into the supply order block without closing above the block high.

3. **Risk Management & Invalidation**:
   - Invalidation occurs immediately on candle close beyond the opposite VOB boundary.
   - Fixed Stop Loss placed $2\text{ pts}$ outside the VOB structure.

---

## Frontend VOB Pullback Command Deck

- **Location**: Top section of `/oracle` (`VobPullbackCommand.tsx` and `NiftyPhotonicMaster.tsx`).
- **Visual Design**:
  - Tesla-inspired glass rails with animated refractive light sheens (`.vobRailTrack`, `@keyframes vobRefract`).
  - Real-time distance-to-block gauge.
  - Active VOB zone badges (`BULLISH DEMAND ZONE` / `BEARISH SUPPLY ZONE`).

---

## Do Not Change
- The BigBeluga volume-weighted order block formula in `src/vob/bigbeluga_engine.py`.
- The rule that VOBs cannot be updated intra-candle before the period close.
- The separation between Track A (pure price action) and Track B (tape-confirmed).
