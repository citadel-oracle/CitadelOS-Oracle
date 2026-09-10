# CITADEL OS — Current Project State

Updated: 2026-07-13  
Release: Version 2 real-data paper-trading edition

## What exists today

- FastAPI backend with versioned GET-only dashboard and module projections.
- Next.js 16 strict TypeScript institutional dashboard using one three-second V2 aggregate poll.
- Real Dhan market-data ingestion and closed-candle cache.
- Frozen NIFTY five-minute Simple Pullback production strategy.
- Technical Intelligence, ARGUS, KRONOS CORE, KRONOS ALPHA, CHRONOS-2, ATHENA, HERMES, Personal ORACLE, AEGIS, Risk Authorization, Kill Switch, Order & Fill Ledger, Paper Execution, Paper State, readiness, and V2 integration.
- Genuine local KRONOS ALPHA and CHRONOS-2 model environments in shadow mode.
- Append-only candle decision evidence and read-only opportunity replay infrastructure.
- Two isolated paper modes: frozen Production Mode and weighted Development Mode.
- Development-only strategy clone, weighted decision service, Risk instance, Paper Execution engine, Paper State, order/fill ledger, runtime, and forensic journal.
- Client-local Production/Development dashboard projection toggle with no backend mutation.
- Dependency manifests, pytest configuration, deterministic safety tests, checkpoints, and runtime instructions.

## Production-ready for paper validation

- Broker mutation protection.
- `live_trading_enabled=false` safety boundary.
- Closed-candle-only evaluation and duplicate origin suppression.
- AEGIS advisory gate followed by absolute Risk Authorization.
- One-lot/one-position/two-trades-per-day paper limits.
- Simulated fills, immutable order/fill evidence, idempotent Paper State, paper positions, and P&L.
- GET-only frontend projection with isolated module failures.
- Evidence recorder failures isolated from production decisions.
- Hash-chain verification and read-only replay.
- Production/Development state-path isolation and GET-only development projection.

## Experimental or collecting evidence

- KRONOS ALPHA forecast usefulness and calibration.
- CHRONOS-2 forecast usefulness, calibration, and lead/lag.
- Personal ORACLE behavioral maturity.
- Multi-session decision accuracy and option-buying edge.
- Forensic envelope coverage under sustained open-market runtime.
- Development weighted-score selectivity, trade frequency, MFE/MAE evidence, and multi-session decision quality.

## Disabled

- Live trading and all broker order submission.
- Frontend execution controls.
- KRONOS ALPHA execution influence.
- CHRONOS-2 execution and AEGIS influence.
- Automatic use of unavailable HERMES evidence.
- Any automatic promotion of Development weights, decisions, or strategy relaxation into Production Mode.

## Incomplete or unavailable

- Authoritative timestamp-aligned option candle history for evaluated and rejected opportunities.
- Instrument-master resolution for non-selected ATM+1 and ITM candidates.
- Complete inference lifecycle timestamps in historical model publications.
- Authoritative ATHENA current cash/equity/exposure, maximum drawdown, and weekly/monthly usage.
- Configured HERMES news/event provider.
- Multi-session statistical evidence sufficient to claim trading edge.
- Historical immutable decision envelopes before this foundation.

## Known bugs and technical debt

- FastAPI uses deprecated `on_event` lifecycle hooks.
- `.env` is historically tracked by Git; secret rotation and history remediation remain a separate security task.
- AEGIS's bounded legacy ledger is unsuitable as the only permanent forensic record; new candle envelopes address future lifecycle evidence only.
- Existing model ledgers retain bounded history and do not expose every lifecycle timestamp.

## Verified strengths

- Safety gates fail closed and do not depend on the frontend.
- No paper execution path contains broker submission methods.
- Read projections do not append lifecycle AEGIS decisions.
- The dashboard does not invoke models or trading.
- Order/fill and Paper State mutations are idempotent and independently testable.
- Unavailable upstream data is exposed truthfully.
- Module responsibilities are frozen and documented.
- New forensic replay performs no production recalculation.

## Current scores

- Engineering readiness: **90/100**, retained from the verified production-stabilization checkpoint. This score applies only to continued paper validation.
- Trading intelligence score: **NOT DETERMINABLE**. Current evidence is insufficient for an institutional alpha or edge score.
- Live-trading readiness: **0/100 by design**. Live trading is disabled and outside this release.

## Immediate next milestones

1. Validate the new forensic evidence chain across multiple open-market paper sessions.
2. Design a secret-safe, read-only timestamp-aligned option candle archive without changing strategy or provider polling semantics.
3. Establish predeclared opportunity/outcome definitions before computing recall, false-WAIT rate, or option edge.
4. Accumulate multi-session forecast evidence before proposing any model or policy change.
5. Address `.env` tracking through a separately authorized rotation/history-remediation procedure.
6. Run several open-market Development sessions and verify that every weighted decision and completed trade has an intact replay-linked evidence record.

## Development Mode truth

- Status: implemented, isolated, and ready for paper evidence collection; not production validated.
- Strategy: `Simple Pullback (Development)` with only EMA ordering relaxed.
- Weighted threshold: 60/100.
- Optional missing evidence: reduces score and coverage; does not create a hard veto.
- Hard vetoes: live-trading state, Kill Switch, market session, closed candle, data freshness, isolated Paper State health, and Development Risk.
- Evidence ceiling: 20 entered development trades per day; this is a safety ceiling, not a quota.
- Expected frequency: approximately 5–20 in an active session is a target hypothesis, not a verified outcome or guarantee.
- Production influence: none.

The authoritative engineering rules and roadmap are in `docs/CITADEL_ENGINEERING_BIBLE.md`.

## Strategy Lab state

- Status: isolated architecture plus institutional paper execution implemented; manager and GET-only projections ready.
- Deployment state: PULLBACK MASTER is registered and hash-pinned but scheduler-gated pending TradingView parity validation; no research strategy is actively trading.
- Isolation: per-strategy scheduler, strategy state, Paper State, Risk instance, order/fill ledgers, journal, replay, evidence, statistics, and logs.
- Failure boundary: one adapter failure is contained and cannot stop another runtime.
- Dashboard: Strategy Lab summary, runtime cards, completed-trade-only leaderboard, deployment capability view, and per-strategy research page.
- Input architecture: Pine, Python, manual rules, JSON, Git, ZIP, and AI-generated packages are represented by stable interfaces.
- Implemented deployment path: reviewed adapter injection plus the gated authoritative-Pine-event bridge for PULLBACK MASTER.
- Paper engine: one isolated account/OMS/fill/position/statistics aggregate per strategy, durable state recovery, immutable lifecycle events, and a paper-only provider boundary.
- Execution providers: abstract `ExecutionProvider`; only `PaperExecutionProvider` exists. No broker providers exist.
- OMS: pending, partial, filled, rejected, cancelled, and expired states; immutable order/fill IDs and full lineage.
- Capital/risk: fixed lots, fixed rupee risk, fixed percent, maximum daily loss, concurrent-position cap, and daily-trade cap. Missing policy fails closed.
- Portfolio: one default Strategy Lab portfolio projection; multi-portfolio architecture is prepared but behavior is disabled.
- APIs: GET-only portfolio, capital, positions, orders, fills, statistics, open trades, and closed trades in addition to existing Lab routes.
- Not implemented: native Pine parser/compiler, broker execution provider, multi-portfolio behavior, external deployment endpoints, automatic strategy generation, or Trading Workspace UI.
- Tournament: same-context fanout architecture ready; rankings remain unavailable without completed paper trades.
- Safety: paper only, live trading false, broker submission false, frontend execution absent, Production and Development state mutation false.

Strategy Lab readiness means the research architecture is ready, not that any strategy is validated, running, profitable, or production eligible.

The institutional paper engine is ready for strategies with an explicitly reviewed capital/risk policy and parity-valid adapter. PULLBACK MASTER remains ineligible for live paper activation until its parity requirements are satisfied.
