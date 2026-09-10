# CITADEL OS — Project Status

Last checkpoint: 2026-07-11 (Asia/Kolkata)

## Current production state

- Production repository: `/Users/ayushmudgal/Developer/CitadelOS`
- Backend: FastAPI, served locally from `app.main:app`
- Frontend: Next.js 16 + TypeScript in `citadel-dashboard`
- Dashboard: V1.1 premium state restored and visually frozen; no redesign is pending in this checkpoint
- Trading mode: paper
- Live trading: disabled in `config/settings.json`
- Broker access used by the dashboard: read-only Dhan market-data APIs
- Current production scope: local dashboard, read-only market intelligence, and paper-state reporting
- Separate research repository: `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer`; it is not part of CITADEL OS production work and must not be modified from production milestones

## Safety invariant

**Live order execution is not production-ready and must remain disabled.** Central authorization and a kill switch now exist, but authoritative execution counters, broker reconciliation, and an audited order lifecycle are still incomplete. Changing `live_trading_enabled` alone is never sufficient authorization for live trading.

The `.env` file contains local secrets and must never be printed, copied into documentation, or committed. This checkpoint did not read its contents.

## Completed milestones

### Broker Safety — complete and verified

- `src/broker/dhan_client.py` defines `BrokerMutationBlockedError`.
- Every non-GET request passes through a central mutation check before network I/O unless its exact endpoint is explicitly classified as read-only.
- The guard reloads `config/settings.json` immediately before a mutation decision.
- Missing or malformed settings fail closed because live trading does not resolve to enabled.
- Read-only Dhan POST exceptions are limited to market-data endpoints: `/optionchain`, `/optionchain/expirylist`, `/marketfeed/*`, and `/charts/*`.
- Generic POST and future PUT/PATCH/DELETE paths remain guarded.
- Safety tests verify that blocked mutations make zero broker network calls.
- Order and cancellation methods exist, but they must not be used while live trading is disabled.

### Risk Authorization + Kill Switch — complete and verified

- `src/risk/authorization.py` is the one authoritative ALLOW/DENY service for Dhan broker mutations.
- Every non-read-only mutation crossing `DhanClient._request` must receive an explicit `ALLOWED` decision immediately before network dispatch.
- Missing/invalid configuration, missing/malformed persisted state, stale market data, active kill switch, disabled live trading, invalid request/risk values, exhausted limits, duplicates, and unexpected exceptions fail closed.
- One atomic local document, `logs/risk_control_state.json`, persists kill-switch and daily-risk state across restarts; missing or corrupt state is never silently reset.
- Kill-switch activation/deactivation requires a reason and actor. Deactivation is explicit.
- Daily state tracks trading date, realized/unrealized/total P&L, trades, consecutive losses, open positions, and accepted request IDs. It resets only when the verified IST trading date advances.
- Non-secret decisions are appended to `logs/risk_authorization_audit.jsonl`; audit persistence failure converts a prospective ALLOW to DENY.
- Existing read-only Dhan POST allowlists remain unchanged. No live flag or broker credential was changed.

### Single Authoritative Paper State — complete and verified

- `src/execution/paper_state.py` is the sole persisted owner of paper positions, closed trades, realized/unrealized/total daily P&L, trades taken, consecutive losses, accepted request IDs, and lifecycle event IDs.
- State is stored atomically in schema-versioned `logs/paper_state.json` and reloads across process restarts.
- Missing, malformed, internally inconsistent, or future-dated state fails explicitly and is never silently repaired.
- Paper open, mark, partial/full close, duplicate rejection, P&L, and date rollover are deterministic.
- Long paper P&L is `(mark or exit - entry) × raw quantity`; SELL/SHORT compatibility uses the inverse direction.
- Raw broker quantity is preserved. Lot size, lots, instrument ID, symbol, option type, strike, and expiry are stored when supplied; lot values are never invented.
- `PaperExecution` is now a compatibility facade over authoritative state. The legacy active-paper JSON path is no longer read or written; the CSV journal remains a derived audit/history output rather than state truth.
- `RiskAuthorizationService` reads every daily counter and accepted request ID directly from `PaperStateService`; `RiskControlStore` now owns only the independent emergency kill switch.
- The initial local migration preserved 60 historical closed journal records, found no legacy active position, and initialized current-day counters at zero without altering the legacy CSV.

### Safe Backend Checkpoint + Read-Only Frontend Wiring — complete and verified

- `GET /v1/risk/status` exposes only sanitized live-mode, kill-switch, state-health, configured-limit, freshness, and optional latest-authorization fields.
- `GET /v1/paper/status` projects authoritative daily paper P&L, counters, open-position count, accepted-ID count, trading date, health, and last update.
- Missing/malformed configuration or state returns truthful `degraded`/`unavailable` responses with `null` metrics; no zeros are manufactured for unavailable values.
- The Dashboard V1.1 adds one compact `RISK & PAPER CONTROL` section using the existing visual system, polling loop, timeout, abort, retry, stale preservation, and responsive protections.
- The section is display-only: no kill-switch toggle, mutation control, order action, credential, runtime path, or direct JSON/log access is present.
- Frontend telemetry now polls 11 feeds through the same single three-second interval.
- Pre-change and final non-destructive reports are stored under `docs/checkpoints/`; no commit/tag was created because the working tree contains mixed user-owned, secret, runtime, staged, and unstaged changes.

### Market Candle Integrity — complete and verified

- Candle timestamps are normalized and bucketed in `Asia/Kolkata`.
- One candle is retained per symbol and timeframe bucket.
- Repeated quotes in the same bucket preserve open, update high/low/close/LTP, and do not create poll-count candles.
- New buckets append once; stale observations are ignored; symbols remain independent.
- Higher timeframes use timestamp buckets rather than row-count grouping.
- Dhan quote payloads do not currently provide a trusted exchange timestamp in this path, so receipt time is used.
- Live quote volume may be unavailable and represented as zero; it is not fabricated from poll count.

### ARGUS Phase 1 — complete and verified

- Fetches Dhan expiry lists and option chains through read-only broker endpoints.
- Parses strike, CE/PE LTP, previous close, OI, previous OI, change OI, volume, IV, security ID, and moneyness when supplied.
- Detects nearest ATM plus five ITM and five OTM strikes without hardcoded strikes.
- Calculates CE/PE totals, day-change totals, PCR, change PCR, and OI/change-OI walls.
- Produces a reusable `OptionChainSnapshot` with explicit missing-field reporting.
- Day change remains relative to Dhan's previous-day values; legacy day-delta aliases are retained for compatibility.

### ARGUS Phase 2 — complete and verified

- Separates day deltas from intraday deltas captured against a persisted session baseline.
- Baseline identity is date + symbol + expiry + strike + option side.
- The first valid weekday request during 09:15–15:30 IST creates a baseline; later requests do not overwrite it.
- Baselines are written atomically with temporary-file, `fsync`, and `os.replace` semantics.
- Corrupt or invalid baseline state fails explicitly; it is not silently reset.
- Outside-session states are reported as `PRE_MARKET`, `CLOSED`, or `WEEKEND`; new baselines are not created then.
- Price/OI classifications include long buildup, short buildup, short covering, long unwinding, and insufficient/neutral evidence.
- ATM-window dominance, evidence coverage, writer/buyer regime, directional verdict, confidence, breakout levels, and avoid flags are deterministic—not fabricated or ML-generated.
- API caching and locking limit repeat Dhan calls; cache is process-local.

### ARGUS Phase 3 — complete and verified

- Adds one compact, read-only option-buyer decision panel between Performance and the existing engine panels.
- Displays underlying LTP, expiry, ATM, session/baseline status, verdict, confidence, dominance, key walls/zones, ATM ±3 strikes, and up to three evidence items when available.
- Shows unavailable/missing values honestly.
- Provides no buy, sell, entry, stop-loss, target, or order-execution controls.

### ARGUS Phase 3.1 — complete and accepted

- Uses one visibility-aware 3-second polling loop with an in-flight guard.
- Adds request cancellation, a 5-second timeout, bounded retry, mounted-state protection, and last-successful-data preservation.
- Sanitizes market rows before React state updates and memoizes the compact ARGUS strike window.
- Removes the ARGUS full-width backdrop compositor load that reproduced Safari instability.
- Verified one ARGUS panel, seven compact strike rows, one ATM row, stable DOM size, and no page-level mobile horizontal overflow.
- Backend pause/resume testing preserved stale data, showed a timeout/disconnected state, and recovered automatically.
- A 10-minute Safari soak completed without a new crash; console verification found no errors, warnings, or hydration failures.

### Oracle Completion + Read-Only Frontend Exposure — complete and verified

- `src/oracle/oracle_service.py` is the verified current technical-market assessment service and is now permanently classified as the **Technical Market Engine**.
- Oracle reads only the latest process-local `DashboardAPI` scanner snapshot; it does not refresh market data, call a broker, authorize risk, or read/write paper state.
- The typed assessment contract reports symbol, timeframe, generation/source times, age, data/oracle health, directional bias, signal, confidence, regime, reasons, features, warnings, maturity, and source/fallback metadata.
- Deterministic evidence uses existing EMA structure, VWAP relationship, RSI momentum, multi-timeframe bias, scanner trade/bias, regime, liquidity classification, and existing Kronos confidence. Unsupported volume evidence remains explicitly unavailable.
- Actionable `LONG`/`SHORT` requires live, complete, trending, aligned evidence above the existing Kronos threshold. Cached data is non-actionable `WAIT`; stale data is blocked `NO_TRADE`; missing or malformed data is unavailable without fabricated confidence.
- `GET /v1/oracle/status` and `GET /v1/oracle/assessment/{symbol}` expose sanitized read-only state. The legacy `GET /v1/oracle/reasoning` remains a NIFTY compatibility alias to the same service.
- The existing technical dashboard area follows the selected symbol and shows health, freshness, signal, confidence, bias, regime, reasons, warnings, maturity, and last update through the existing single polling loop.

### Module Responsibility Freeze + Original Vision Restoration — complete and accepted

- `docs/CITADEL_MODULE_ARCHITECTURE.md` permanently defines roles, inputs, outputs, dependency boundaries, data ownership, compatibility aliases, flow, soft influences, hard vetoes, and migration order.
- ARGUS is frozen as Options Positioning Intelligence; KRONOS as Setup Quality & Timing Intelligence; ATHENA as Risk & Capital Intelligence; HERMES as News & Event Intelligence; canonical ORACLE as Personal AI Trading Coach; AEGIS as Final Decision Controller; and Risk Authorization as the absolute hard safety gate.
- The existing `OracleService` behavior is preserved and reclassified as the Technical Market Engine. Existing files, classes, `/v1/oracle/*` routes, internal frontend types/components, and historical Oracle analytics names remain compatibility aliases.
- The only runtime-facing change is a safe text-label update from Oracle to **TECHNICAL INTELLIGENCE** in the existing dashboard panel. Layout, styling, API calls, polling, data mapping, behavior, responsive design, and all other sections remain unchanged.
- Starting AEGIS influences are documented—not implemented—as Technical 25%, KRONOS 25%, ARGUS 20%, Personal ORACLE 15%, HERMES 10%, and ATHENA 5%. All hard safety vetoes remain absolute.
- Athena, Hermes, Personal Oracle, AEGIS, and further KRONOS integration were not implemented in this milestone.

### ATHENA Risk & Capital Intelligence — complete and verified

- `src/athena/athena_service.py` is the one deterministic, read-only ATHENA advisory service.
- ATHENA consumes only sanitized `ControlStatusAPI` risk and authoritative-paper projections. It creates no state store and has no broker, execution, order, strategy, kill-switch mutation, or paper-position mutation dependency.
- The typed assessment reports health, risk state, `CONTINUE`/`REDUCE`/`PAUSE`/`STOP`, a bounded 0.0–1.0 advisory multiplier, daily P&L/loss usage/headroom, trade/loss-streak/open-position utilization, position-capacity exposure, drawdown, capital fields, reasons, warnings, missing inputs, maturity, and source metadata.
- Risk Authorization remains the absolute veto: active kill switch, observed authorization `DENY`, reached daily-loss/trade/loss-streak/open-position limits, or unavailable required state produces `STOP` with zero advisory size.
- Utilization below 50% is `SAFE/CONTINUE`; 50–79.99% is `CAUTION/REDUCE`; 80–99.99% is `HIGH_RISK/PAUSE`; hard limits are `STOP`. The multiplier is advisory only and is never converted into quantity or allowed to override configured limits.
- Current drawdown is the negative portion of authoritative total daily P&L. Open-position capacity is the only calculable exposure proxy; it is explicitly not rupee exposure.
- Paper cash balance is exposed when present. Blocked capital, current equity, rupee exposure, weekly/monthly usage, and a dedicated maximum-drawdown limit remain `null` because no authoritative ledger/configuration exists.
- `GET /v1/athena/status` is the canonical sanitized route. `GET /v1/athena/wheel` remains a read-only compatibility projection backed by the same service.
- The existing dashboard panel now displays ATHENA health, risk state, recommendation, advisory size, utilization/headroom, positions, drawdown, optional capital fields, reasons, warnings, maturity, and update time through the existing polling/failure architecture.

### HERMES News & Event Intelligence Foundation — complete and verified

- `src/hermes/` contains one provider-agnostic deterministic HERMES foundation with frozen normalized input/event/assessment contracts, centralized timing configuration, India/global taxonomy, source-confidence mapping, and offline providers.
- Supported inputs are scheduled economic events, market news, social-media catalysts, and official announcements. Core logic consumes typed `HermesInput` values rather than raw provider payloads.
- Normalized events preserve bounded safe provenance, timing/countdown, impact, unsupported sentiment as `UNKNOWN`, affected scope, reasons, warnings, duplicate group, conflict state, and multi-source traceability. URLs lose query/fragment/user credentials; no unbounded raw payload is retained.
- Deterministic deduplication uses taxonomy/date or normalized-headline/time identity. Official/high-confidence evidence wins representative timing; impact/timing/sentiment disagreements remain explicit conflicts rather than being silently discarded.
- Official source categories map to high confidence, approved newswire/provider to medium, secondary/unverified social to low, and missing metadata to unknown. Low/unknown-confidence evidence cannot alone retain `CRITICAL` impact.
- Central windows are imminent within 30 minutes, live through 15 minutes after a scheduled event, recent through 120 minutes, six-hour event relevance, and five-minute provider-snapshot freshness.
- HERMES returns `NORMAL`, `CAUTION`, `WAIT`, or `AVOID_NEW_TRADES` advisory output. Missing/unconfigured/malformed provider state returns `UNAVAILABLE/UNKNOWN/WAIT`; stale snapshots cannot default to normal.
- Provider ingestion is explicit through `refresh_from_provider()`. `GET /v1/hermes/status` and `GET /v1/hermes/events` read only the current bounded in-memory cache and never trigger refresh or external activity.
- The production instance has no provider configured and truthfully reports unavailable. Offline fixture/in-memory providers exist for tests and are always labeled non-live when displayed.
- A compact dedicated HERMES panel was added to the existing intelligence grid without changing the single polling loop, failure protections, existing sections, responsive design, or footer.

## Dashboard V1.1

The dashboard is restored to the accepted premium dark institutional layout. Its section order, visual language, data mapping, API calls, and polling behavior are frozen for the next backend-foundation milestone.

Visible panels/sections:

1. System status header and backend connection state
2. Mission Control
3. Market Matrix
4. Active Trade
5. Performance Nexus
6. ARGUS OI Positioning
7. Kronos
8. Technical Intelligence (implemented by the `OracleService` compatibility path)
9. Athena — Risk & Capital Intelligence
10. Hermes — News & Event Intelligence
11. AI Insights

The frontend polls 12 data feeds every three seconds through one interval: the prior 11 feeds plus cached/current HERMES status. It includes initial loading states, bounded retry, stale-data preservation, disconnected/error states, last-updated time, and responsive layouts. HERMES polling never refreshes a provider. ARGUS supports `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, and `SENSEX`; the current V1.1 selector exposes those supported symbols.

## Backend capability truth

Only these maturity labels are used: **VERIFIED**, **PARTIAL**, **STUBBED**, and **NOT STARTED**.

| Capability | State | Repository truth |
|---|---|---|
| Broker mutation guard | VERIFIED | Central fail-closed protection is implemented and tested. |
| Risk authorization / kill switch | VERIFIED | All broker mutation methods cross one deterministic ALLOW/DENY gate with persistent control state. |
| Authoritative paper state | VERIFIED | One atomic state owns paper lifecycle, P&L, counters, positions, and accepted IDs. |
| Read-only risk/paper telemetry | VERIFIED | Sanitized GET projections feed a display-only dashboard section. |
| Dhan quotes / Market Matrix | VERIFIED | Read-only live quotes feed deterministic scanner and indicator logic. |
| Candle integrity | VERIFIED | Time-bucket deduplication and same-bucket OHLC updates are implemented and tested. |
| ARGUS option-chain engine | VERIFIED | Read-only Dhan chain parsing, baselines, deterministic classification, API, and compact panel are implemented. |
| Dashboard polling resilience | VERIFIED | Timeout, retry, stale preservation, visibility pause, and recovery were runtime-tested. |
| Mission Control | PARTIAL | Combines live scanner context, static/session settings, local paper state, and analytics. |
| Active Trade | PARTIAL | Reports local paper-trade state, not reconciled Dhan positions. |
| Performance statistics | PARTIAL | Derived from local Oracle/paper logs whose sources are not yet unified. |
| Performance equity | STUBBED | Uses a fixed preview time axis and synthetic intermediate points. |
| Performance heatmap | STUBBED | Fixed day/week structure with unavailable cells. |
| KRONOS setup quality/timing | PARTIAL | Deterministic trend/momentum/regime scoring exists; the complete structure/freshness/timing/cooldown/holding/DTE mandate is not integrated. |
| Technical Market Engine | VERIFIED | Implemented through the `OracleService` compatibility path as deterministic, explainable, read-only technical assessment; it is not Personal Oracle. |
| Personal ORACLE | NOT STARTED | Historical feature/performance tooling exists, but the evidence-backed personal AI trading coach does not. |
| ATHENA risk/capital intelligence | VERIFIED | Deterministic advisory utilization, headroom, risk state, recommendation, sizing multiplier, GET API, and compact frontend are implemented; unavailable capital-ledger values remain explicit. |
| HERMES foundation | VERIFIED | Typed normalization, taxonomy, source confidence, timing/freshness, deduplication/conflicts, deterministic assessment, cached GET API, offline providers, and compact frontend are tested. |
| HERMES live provider ingestion | NOT STARTED | No external news/calendar/social provider is configured or called; production status is truthfully unavailable. |
| AEGIS final decision controller | NOT STARTED | No final multi-engine controller exists; current scanner/strategy flags are not AEGIS. |
| AI Insights | PARTIAL | Deterministic optimizer suggestions exposed under a legacy route name; not generative AI. |
| Unified paper-state persistence | VERIFIED | Dashboard paper execution and risk authorization consume the same authoritative state. |
| Live execution authorization | PARTIAL | Central risk authorization and kill switch exist; broker reconciliation and authoritative execution state do not. |
| Live trading | NOT STARTED | Disabled; not safe to enable. |

## FastAPI route inventory

All current dashboard routes are read-only GET routes.

| Route | Current role |
|---|---|
| `GET /` | Basic service status. |
| `GET /citadel/snapshot` | Composite dashboard snapshot; route existence does not imply every nested capability is complete. |
| `GET /v1/mission-control` | Session, scanner, paper-journal, active-paper, analytics, and optimizer summary. |
| `GET /v1/market/matrix` | Read-only Dhan quotes plus deterministic matrix calculations. |
| `GET /v1/trade/active` | Local active paper-trade state. |
| `GET /v1/performance/stats` | Local Oracle-feature analytics. |
| `GET /v1/risk/status` | Sanitized risk limits, live flag, kill-switch health, and optional latest authorization. |
| `GET /v1/paper/status` | Sanitized authoritative daily paper-state summary. |
| `GET /v1/argus/oi` | Validated symbol/optional-expiry option-chain intelligence with cache and baseline status. |
| `GET /v1/kronos/gauge` | Deterministic technical gauge. |
| `GET /v1/oracle/status` | Technical Market Engine health and latest NIFTY assessment under a retained Oracle compatibility route. |
| `GET /v1/oracle/assessment/{symbol}` | Symbol-scoped deterministic technical assessment under a retained Oracle compatibility route. |
| `GET /v1/oracle/reasoning` | Legacy NIFTY technical-assessment compatibility alias. |
| `GET /v1/athena/status` | Canonical sanitized ATHENA Risk & Capital Intelligence assessment. |
| `GET /v1/athena/wheel` | Legacy read-only compatibility projection backed by the authoritative ATHENA service. |
| `GET /v1/hermes/status` | Cached/current sanitized HERMES assessment; never refreshes a provider. |
| `GET /v1/hermes/events` | Bounded deterministic normalized event list from the same in-memory cache. |
| `GET /v1/ai/insights` | Rule-based optimizer suggestions. |
| `GET /v1/performance/equity` | Preview equity series. |
| `GET /v1/performance/distribution` | Local journal win/loss distribution. |
| `GET /v1/performance/heatmap` | Stubbed heatmap structure. |

## Runtime commands

Backend, from the repository root:

```bash
uvicorn app.main:app --reload
```

Equivalent virtual-environment command when dependencies are installed there:

```bash
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend development, from `citadel-dashboard`:

```bash
npm run dev
```

Frontend production verification and start:

```bash
npm run build
npm run start
```

## Tests and verification state

Existing test modules:

- `tests/test_broker_safety.py`
- `tests/test_market_candle_integrity.py`
- `tests/test_argus_intraday_oi.py`
- `tests/test_argus_api.py`
- `src/api/test_dashboard_api.py`
- `app/test_server.py`

The repository has minimal runtime/development dependency manifests, root pytest discovery, strict markers, credential-independent offline fixtures, and a socket-level network block. The safe suite currently collects 193 tests and passes all 193: the prior 159 plus 30 HERMES model/service/API/safety cases and four frontend contract cases. The Next.js production build and ESLint validation both pass.

## Environment, secrets, and runtime files

- `.gitignore` covers `.env`, `.env.*` (except `.env.example`), Python caches, `.venv`, `node_modules`, `.next`, `out`, `logs`, and `*.log`.
- `.env` is already tracked in the current repository history despite ignore rules and is locally modified. This is a credential-hygiene risk; its contents were not inspected or reproduced here. Removing it from tracking or rotating credentials requires a separately authorized secret-remediation task.
- Runtime files already tracked include `logs/live_candles.csv`, `logs/paper_trades.csv`, and `logs/test_paper_trades.csv`. They were not modified by this checkpoint.
- `logs/argus_oi_baselines.json` is runtime state covered by the `logs/` ignore rule.
- `logs/risk_control_state.json` and `logs/risk_authorization_audit.jsonl` are local runtime state covered by the `logs/` ignore rule.
- `logs/paper_state.json` is authoritative runtime paper state and is covered by the `logs/` ignore rule.
- Documentation must never contain Dhan credentials, tokens, or `.env` values.

## Known limitations and approximations

- Market candles use quote receipt time rather than a trusted exchange timestamp in the current quote path.
- Polling is three-second HTTP polling, not WebSockets or tick-perfect streaming.
- Dashboard and ARGUS caches are process-local and unsuitable for multi-worker consistency without shared state.
- ARGUS session logic is weekday/time aware but not exchange-holiday aware.
- ARGUS baseline begins on the first valid in-session request, which may be later than 09:15 IST.
- OI classifications and confidence are deterministic threshold formulas, not predictive guarantees.
- The active strategy path uses `SimplePullbackStrategy`; `config/settings.json` naming and the separate unfinished pullback-v3 module do not make Pullback V3 the active implementation.
- Mission Control, analytics, paper journal, and active-paper state are not yet backed by one authoritative persistence model.
- ATHENA is authoritative advisory risk-limit intelligence but cannot report or size from absent capital/equity/margin/rupee-exposure ledgers; Personal ORACLE, HERMES, and AEGIS are not started; KRONOS covers only part of its frozen setup/timing mandate; AI Insights remains heuristic optimizer output.
- ATHENA's exposure percentage is open-position-capacity utilization, not rupee exposure or broker margin. The advisory multiplier is relative guidance only and never a broker quantity.
- ATHENA's current drawdown is derived from negative total daily paper P&L. A separate configured maximum drawdown, weekly/monthly risk usage, blocked capital, and current equity are unavailable.
- The latest Risk Authorization summary has no request-applicability/freshness contract; ATHENA conservatively treats any exposed latest `DENY` as a hard stop.
- HERMES has no live external provider, durable/shared cache, exchange-holiday calendar, or market-session context. Production reports unavailable until an explicitly approved provider is integrated and refreshed out of band.
- Fixture/in-memory HERMES inputs prove deterministic behavior but are not current news. Sentiment is accepted only from normalized provider evidence and is never inferred from headlines or taxonomy.
- HERMES duplicate grouping is deterministic taxonomy/date or normalized-headline/time matching, not semantic NLP entity resolution. Its source-confidence categories are policy mappings, not independent fact verification.
- HERMES is advisory only; `AVOID_NEW_TRADES` does not directly block execution and no AEGIS consumer exists yet.
- Oracle consumes only the most recent process-local DashboardAPI scanner snapshot and never triggers a refresh. Before the first snapshot it returns unavailable; its fallback cache is not shared across workers.
- Oracle's market timestamp means backend scan completion, not an exchange tick. Trusted volume is absent from this snapshot contract, so volume evidence is unavailable and does not influence the decision.
- Cached Oracle evidence is deliberately non-actionable and stale evidence is blocked. Oracle does not produce entries, stops, targets, orders, or execution authorization.
- Live broker position/order reconciliation is absent.
- Risk per trade currently uses absolute entry-to-stop distance multiplied by raw broker quantity; instrument lot-size/value normalization is not yet available.
- Persistent risk writes are atomic and process-local locked, but no cross-process file lock or shared multi-worker store exists.
- Paper-state writes are atomic and protected by an in-process lock, not a cross-process file lock or shared multi-worker database.
- Brokerage and slippage are not included in paper P&L. Legacy closed trades have raw quantity `1` because the previous journal recorded points rather than explicit quantity; lot metadata remains unavailable for those imports.
- Cash balance remains unavailable because the existing paper path did not maintain one. There is no separate order-book/fill ledger beyond authoritative open and close lifecycle events.
- Legacy paper-trader modules remain for manual historical scripts but are not authoritative production state paths.
- The kill-switch runtime file is currently absent locally, so the read-only risk projection truthfully reports degraded/unknown kill-switch state until explicitly initialized by an authorized operational workflow.
- Per-tab browser memory could not be isolated from unrelated browser-process memory during Safari verification.

## Order & Fill Ledger Foundation — complete

The production backend now has one schema-v1, atomic, append-only, corruption-aware audit ledger for immutable order intents, explicit lifecycle events, and observed fills. It enforces integer/lot quantity consistency, runtime authorization provenance, idempotent replay, terminal-state safety, Decimal weighted fill/cost/slippage projections, and reconciliation-required overfill handling. Ten bounded GET-only routes and an always-visible read-only dashboard panel expose truthful empty/unavailable state. No broker submission, execution method, automatic Paper State application, seeded order, or live-trading path was added.

## Exact next production milestone

**OPEN-MARKET VERSION 2 PAPER VALIDATION**

## Version 2 paper-trading integration — complete

The frontend now consumes one authoritative, fault-isolated `GET /v2/dashboard` projection every three seconds instead of 21 independent requests. All 21 feeds expose version, health, readiness, latency, projection/source timestamps, fail-closed state, and trace/evidence metadata. Fabricated insight, equity, and heatmap fallbacks were removed. Safe verification is 446 passed with one isolated-runtime CHRONOS-2 skip; genuine KRONOS ALPHA and CHRONOS-2 suites each pass 2 tests; build, lint, desktop, and 390px checks pass. Weekend verification truthfully leaves ARGUS limited, ATHENA limited, KRONOS ALPHA not ready, and HERMES unconfigured.

## Real-Market Paper Trading Activation — complete at readiness scope

The lifecycle-owned paper orchestrator, one-strategy registry, dynamic Dhan NIFTY option/lot resolver, separate fail-closed paper risk gate, quote-backed simulated fill model, partial-fill continuation, Order & Fill Ledger application audit, authoritative Paper State/P&L integration, closed-candle exit engine, GET-only APIs, and read-only dashboard monitor are implemented. No open-session trade has yet been observed through the new path. Broker submission remains absent and live trading remains false.

## AEGIS decision foundation

AEGIS is feature-complete at deterministic advisory scope: typed versioned inputs, absolute hard gates, frozen weighted scoring, conflict resolution, CE/PE logic, fail-closed strategy eligibility, bounded atomic decision audit, six GET-only APIs, and a complete read-only frontend console. Risk Authorization remains the absolute veto; execution permission is always false; KRONOS ALPHA direct weight remains 0%. Current production truth is BLOCK because critical kill-switch state is unavailable, with MARKET CLOSED also visible.

Verification: 352 safe backend tests passed, 2 genuine KRONOS ALPHA model tests passed, frontend build/lint passed, and desktop/390px browser checks passed with zero console errors.

## Personal ORACLE data foundation

Personal ORACLE now has schema-v1 completed-trade evidence, a separate bounded atomic append-only ledger, idempotent Paper State close capture/backfill, entry-time no-look-ahead validation, deterministic threshold-gated analytics, six GET-only routes, and a read-only dashboard section. Sixty historical closes were backfilled; missing intelligence, option, R, cost, strategy, and behavioral fields remain unavailable. The safe suite passes 266 tests; model tests, frontend build/lint, and browser checks pass. Live trading remains disabled.

## Personal ORACLE behavioral and coaching layer

Typed observations, immutable structured enrichments, explicit behavior policies, deterministic comparisons, evidence-gated findings, maximum-three advisory coaching, category-only scorecards, sample-gated trends, five additional GET-only APIs, and the compact coaching dashboard are complete. Historical context remains unavailable; only timestamp/sequence-derived behavior is classified. No psychology, execution, risk, strategy, KRONOS, or AEGIS authority was introduced.

## KRONOS ALPHA installation checkpoint

The official `shiyu-coder/Kronos` upstream, `NeoQuasar/Kronos-small`, and `NeoQuasar/Kronos-Tokenizer-base` identities and revisions were verified. Local installation is **blocked/not complete**: the host data volume reports 100% capacity with about 1.4 GiB free, only Python 3.14 was discovered, and PyTorch is absent. No environment, weights, backend adapter, API, frontend panel, or production behavior was added. KRONOS CORE remains intact. The deferred zero-influence shadow contract is documented in `docs/KRONOS_ALPHA.md`; this does not displace the exact next milestone below.

The historical blocked record above is preserved. The resumed V2 milestone is now **complete at shadow-integration scope**: official Kronos-small/tokenizer artifacts are pinned outside Git; Python 3.11/PyTorch are isolated in `.venv-kronos-alpha`; real MPS model inference and offline cached reload passed; CPU tensor fallback passed; `src/kronos_alpha/`, cached GET routes, deterministic metrics/cache coverage, and an additive dashboard panel exist. KRONOS CORE remains intact and all execution/AEGIS/Risk Authorization influence is 0%. Production forecast output remains truthfully `UNAVAILABLE` until authoritative closed NIFTY/5m history is wired through a separately controlled candle-close trigger.

Full real-data activation is now complete at closed-market readiness scope. A canonical versioned NSE 2026 calendar correctly reports 2026-07-11 as WEEKEND/CLOSED. The read-only Dhan Data API mapping `IDX_I / 13 / INDEX / 5m` persisted 256 genuine closed candles, the 20-path MPS configuration passed benchmark/integration tests, and the lifecycle scheduler is ready for the first confirmed Monday candle close at approximately 09:20:10 IST. No weekend forecast was fabricated; status is `READY_FOR_NEXT_OPEN / INPUT_CACHED_MARKET_CLOSED`. CE/PE quality wheels, bounded forecast history, realization evaluation, and cached GET APIs are active. Actual Monday open-session observation remains pending.

## Kill-Switch Restoration + AEGIS Market Readiness — complete

- The sole authoritative `RiskControlStore` was genuinely absent and was initialized once as persisted `INACTIVE`, reason `INITIALIZED_SAFE_DEFAULT`; restart re-read is healthy and exact.
- ACTIVE, UNKNOWN, and CORRUPT remain hard Risk Authorization DENY and AEGIS BLOCK states. INACTIVE removes only the false kill-switch block.
- Current closed-market AEGIS result is `WAIT` with exact gate `MARKET_CLOSED`; execution permission remains false.
- GET-only `/v1/risk/kill-switch`, `/v1/system/open-market-readiness`, and `/v1/system/next-session-plan` are integrated into the existing three-second frontend polling loop.
- Readiness uses cached/read-only projections only and publishes explicit no-refresh/no-inference/no-broker flags. The canonical next session is planned for 2026-07-13 09:15 IST, first eligible 5-minute close 09:20, grace completion 09:20:10; these are planned, not observed.
- Current readiness is `WAITING_FOR_MARKET`. ARGUS closed-market stale cache is disclosed, HERMES remains unconfigured, Personal ORACLE context remains limited, and KRONOS ALPHA awaits eligible closed-candle context/inference.
- That checkpoint's next milestone and the subsequent real-market paper activation are complete; the current next milestone is **OPEN-MARKET VERSION 2 PAPER VALIDATION**.

That milestone is specified in `docs/NEXT_TASK.md`. Do not begin it as part of this milestone.

## CHRONOS-2 Multivariate Challenger — complete

- Genuine official `amazon/chronos-2` revision `29ec3766d36d6f73f0696f85560a422f50e8498c` runs through `chronos-forecasting==2.3.1` in isolated `.venv-chronos-2`; model weights remain outside Git.
- Online acquisition, local official-class load, CPU inference, genuine Apple MPS inference, and fresh-process offline inference passed.
- Production uses the shared canonical closed NIFTY 5-minute cache without increasing Dhan provider rate. It supports truthful UNIVARIATE fallback and genuine OHLCV/realized-volatility/ATR MULTIVARIATE mode.
- Quantile forecasts, CITADEL-derived Directional Confidence/persistence/reversal/uncertainty/Forecast Quality, independent CE/PE shadow-quality wheels, atomic history, complete-horizon evaluator, KRONOS comparison, GET-only APIs, and compact frontend are implemented.
- Current genuine historical result: MULTIVARIATE, 256 closed candles, seven model columns, 12-step P10/P90 range 24,138.9805–24,253.9023, SIDEWAYS, Directional Confidence 37.34, CE Quality 15.37, PE Quality 16.62.
- CHRONOS-2 remains SHADOW, advisory-only, execution influence 0, and direct AEGIS influence 0. The current next milestone is **OPEN-MARKET VERSION 2 PAPER VALIDATION**.
