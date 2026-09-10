# CITADEL OS — Real-Market Paper Trading Ready

Completed: 2026-07-12 IST

## Recovery and baseline

- Secret-safe pre-change checkpoint: `/Users/ayushmudgal/Developer/CitadelOS_backups/20260712T130820Z_pre_real_market_paper_trading`.
- Sanitized bundle, tracked/staged patches, dirty-state metadata, 268-file allowlisted source archive, checksums, and zero prohibited paths verified.
- Frozen baseline: 427 backend tests passed with one intentional isolated-CHRONOS skip; genuine KRONOS and CHRONOS-2 2/2 each; frontend build/lint and desktop/390 verification passed.

## Delivered runtime

- `REAL_DATA_PAPER_ONLY` lifecycle-owned scheduler, every-three-second position marking, and once-per-unique-closed-NIFTY-5m strategy evaluation.
- One unchanged activated strategy: `SimplePullbackStrategy`; registry cap is two.
- Real Dhan option-chain security/ask/bid/LTP fields plus filtered detailed instrument-master lot resolution; no hardcoded strike, security ID, or lot quantity.
- NIFTY long CE/PE only, one dynamic lot, one open position, maximum two entered/traded positions per day, no averaging, pyramiding, overnight permission, or entry after 15:15; square-off attempt begins 15:20.
- AEGIS consumes typed Technical Intelligence and KRONOS CORE evidence derived from the same closed candle, plus existing ARGUS/module projections; it no longer depends on frontend-created scanner state for this paper path. AEGIS APPROVE plus independent fail-closed paper Risk Authorization are required. APPROVE_REDUCED is denied when a one-lot minimum cannot be reduced.
- Conservative long-option maximum loss uses observed ask/LTP multiplied by dynamic lot quantity and may veto a trade under the unchanged configured per-trade limit.
- Quote-backed simulated fills use top ask/top bid and fall back to explicitly labeled LTP. No synthetic price/spread is created.
- Partial fills remain ledger-only, resume before any new strategy evaluation, and apply the quantity-weighted completed lot once to authoritative Paper State.
- Entry/exit intents, fills, and Paper application evidence are restart-safe and idempotent in the Order & Fill Ledger.
- Option P&L uses real quote-backed paper fill/mark prices and raw exchange quantity. Existing strategy stop/target remain NIFTY underlying closed-candle triggers.
- Corrupt scheduler state, missing Paper/contract/lot/quote, stale data, closed session, kill-switch uncertainty, AEGIS non-approval, or Risk denial blocks entry.
- Seven GET-only paper-trading projections and a read-only dashboard section with engine, strategy, gates, position, P&L, and timeline.

## Verification

- New deterministic paper/orchestrator tests: 15 passed; new and ledger combined target: 40 passed.
- Impacted strategy/ARGUS/Paper/Risk/AEGIS/ledger suite: 140 passed before final additions.
- Final backend suite: 442 passed, 0 failed, 1 intentional isolated-CHRONOS module skip, 4 existing FastAPI lifecycle warnings.
- Genuine KRONOS ALPHA: 2 passed. Genuine CHRONOS-2: 2 passed.
- Next.js production build and ESLint: passed.
- Runtime lifecycle on closed Sunday: scheduler running, `WAITING / MARKET_CLOSED`, 0 orders, 0 fills, 0 positions, 0 P&L, and no provider/model/execution action by the new orchestrator.
- All seven paper-trading GET routes: HTTP 200.
- Desktop 1280px: connected, no horizontal overflow, AEGIS → Order & Fill → Real Market Paper Trading order correct, no controls.
- 390px: 362px section, two-column metrics, single-column detail/timeline, no overflow/clipping, no controls.
- Browser console: zero errors.

## Safety

No Dhan order, broker order/tradebook/position, live execution, automatic frontend execution, configuration toggle, strategy rewrite, Risk/kill-switch mutation, forced model inference, or secret exposure occurred. Broker submission remains absent. `live_trading_enabled=false`. KRONOS ALPHA and CHRONOS-2 remain SHADOW with execution influence 0%. The research repository was untouched.

## Known limitations

The new end-to-end path has not yet been observed during an open NSE session. No trade is guaranteed: existing strategy, all unchanged AEGIS hard gates (including HERMES/ATHENA evidence), dynamic metadata, freshness, and Risk must all pass naturally. Current ₹500 per-trade risk may deny most one-lot option premiums under conservative premium-at-risk accounting. Top-of-book absence uses LTP rather than invented liquidity. A process outage near square-off can produce an overnight-position breach requiring explicit reconciliation. Simulated fills are not broker execution evidence, and no broker margin/order/tradebook reconciliation exists.

## Exact next milestone

**OPEN-MARKET PAPER FORWARD VALIDATION** — not started.
