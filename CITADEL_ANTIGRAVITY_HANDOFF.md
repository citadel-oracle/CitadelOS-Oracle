# CITADEL OS — ANTIGRAVITY HANDOFF

## 1. Repository & Git State
* **Repository Path**: `/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend`
* **Branch**: `stabilization/stale-chain-safe`
* **HEAD**: `541669cab3284fc41e37c114d4290fffedcab8a5`
* **Checkpoint Branch**: `checkpoint/runtime-stale-chain-pass-20260721`
* **Annotated Tag**: `citadel-runtime-stale-chain-pass-20260721`
* **Rollback Bundle**: `~/Desktop/citadel-runtime-stale-chain-pass-20260721.bundle`
* **Git Clean Status**: YES (working tree clean)

## 2. Canonical State Root
* **Canonical Root**: `/Users/ayushmudgal/Developer/CitadelOS/logs` (ACTIVE)
* **Strategy Lab Root**: `/Users/ayushmudgal/Developer/CitadelOS/logs/strategy_lab`
* **Paper State**: `/Users/ayushmudgal/Developer/CitadelOS/logs/paper_state.json`
* **Personal Oracle Ledger**: `/Users/ayushmudgal/Developer/CitadelOS/logs/personal_oracle.json`
* **KRONOS Candles**: `/Users/ayushmudgal/Developer/CitadelOS/logs/kronos_alpha_candles.json`
* **Chronos2 Forecast**: `/Users/ayushmudgal/Developer/CitadelOS/logs/chronos_2_forecast.json`

## 3. Commit History (this session)
| Commit | Description |
|--------|-------------|
| `541669c` | Wire exact held-contract provider into production |
| `98c2f7c` | Preserve safe evaluation during stale option-chain state |
| `dd8e89a` | Update handoff: runtime-logic-pass-20260721 checkpoint |
| `fe0a9f8` | Use candle-close time for model freshness |
| `ec494b7` | Bind intelligence runners to canonical virtualenvs |
| `96850d3` | Bind CITADEL runtime to canonical production state |
| `5a7bdbe` | (Base) Drain strategy candle backlogs in bounded batches |

Do NOT include or merge commit `25ff2ae`.

## 4. Start Methods
### Backend (via launchd supervisor — preferred)
```bash
launchctl kickstart -k gui/501/com.citadelos.backend
```
### Backend (direct)
```bash
/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/scripts/run-citadel-backend.sh
```
### Frontend (Next.js Dashboard)
```bash
cd citadel-dashboard && npm run dev
```

## 5. KRONOS & Chronos2 Intelligence Status
* **KRONOS Alpha (Nifty 5m)**: FRESH — HEALTHY — advisory_only=true (execution influence ZERO)
* **Chronos2 (Nifty 5m)**: FRESH — HEALTHY — advisory_only=true (execution influence ZERO)

## 6. Stale Option-Chain Safety & Deployment Providers
* **10/10 Deployment Providers Active**: Deployment-scoped `held_security_id_provider` passed to all 10 `CompletedCandleContextProvider` instances.
* **Stale Chain Rules**:
  - New entries and contract rotations BLOCKED when option chain is stale.
  - Exact held-contract exits REMAIN ENABLED using latest completed candle fallback.
  - Index price and current ATM substitution REJECTED.

## 7. Ledger & Deployment Status (verified 2026-07-21)
| Metric | Count |
|--------|-------|
| Strategy Lab Orders | 81 |
| Strategy Lab Fills | 78 |
| Open Positions | 0 |
| Closed Trades | 39 |
| Duplicate Orders/Fills | 0 |

| Deployment Metric | Status |
|-------------------|--------|
| Lag | <= 1 (all 10 deployments) |
| Backlog | 0 / CLEAR |
| Interruption | None |
| Strategy Logic Parity | PASS |

## 8. Safety Rules (unchanged)
* `paper_only = true`
* `live_trading_enabled = false`
* `broker_submission = false`
* `AEGIS execution_influence = ZERO`
* `KRONOS advisory_only = true`
* `Chronos2 advisory_only = true`

## 9. Remaining Blockers
1. **Dashboard status contradictions** — Edge cases in V2 dashboard status thresholds for non-model feeds.
2. **Complete intervention-free session certification** — Full session certification from market open to close.

## 10. Rollback Commands
```bash
# Rollback using local tag
git switch stabilization/stale-chain-safe
git reset --hard citadel-runtime-stale-chain-pass-20260721

# Rollback using bundle file
git bundle unbundle ~/Desktop/citadel-runtime-stale-chain-pass-20260721.bundle
git checkout -B stabilization/stale-chain-safe checkpoint/runtime-stale-chain-pass-20260721
```
