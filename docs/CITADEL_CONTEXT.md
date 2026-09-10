# CITADEL OS — Complete Context

This is the durable narrative memory for the production repository at `/Users/ayushmudgal/Developer/CitadelOS`. Repository code is authoritative when older roadmap or product documents conflict with this checkpoint.

The separate research repository `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` is outside production scope. Production tasks must not edit it, import experimental work from it implicitly, or mix its research conclusions into CITADEL OS without a separate, explicit promotion decision.

## Product intent

CITADEL OS is a local, dark institutional trading command center for Indian indices. Its current safe role is read-only market intelligence plus local paper-state visibility. It is not an autonomous live-trading system.

The dashboard is dedicated subtly to Vihaann. The accepted V1.1 visual state includes the `Legacy Build • Vihaann` footer; future backend tasks must preserve it and must not reopen visual design without an explicit UI milestone.

## Chronological implementation history

### Foundation and direct-edit workflow

The project began as a modular Python trading stack and later gained a Next.js dashboard. Earlier manual patch handoffs created drift, circular-import risk, and inconsistent local states. The working preference became direct, minimal repository edits, small milestones, explicit file scope, and verification after each milestone.

### Dashboard MVP and integration hardening

The Next.js 16 TypeScript dashboard was connected to FastAPI routes for Mission Control, Market Matrix, Active Trade, and Performance. Later milestones integrated Kronos, the technical service historically named Oracle, Athena preview, AI Insights, and ARGUS. The frontend retained three-second polling and gained loading, retry, stale-cache preservation, disconnected states, and last-updated reporting.

The dark premium CITADEL theme was refined without changing section order. Duplicate CSS tokens and selectors were removed in focused cleanup passes. Dashboard V1.1 has since been restored to the correct accepted premium state and is frozen for the next backend-foundation milestone.

### Backend truth audit

A source audit separated implemented behavior from aspirational naming. Market Matrix and Dhan quote ingestion are real read-only integrations. Kronos is partial deterministic setup-quality scoring, the current `OracleService` is the Technical Market Engine, Athena is a preview rather than complete Risk & Capital Intelligence, and AI Insights is deterministic optimizer output. Personal Oracle, Hermes, and AEGIS are not implemented. Performance endpoints mix local sources, and some visualizations remain previews/stubs. These distinctions must remain visible in documentation and UI wording.

### Broker Safety milestone

The Dhan client received a low-level, fail-closed mutation barrier. Non-GET broker requests are checked immediately before network I/O. Settings are reloaded for each mutation decision. Missing/malformed settings do not enable trading. Only explicitly recognized read-only market-data POST endpoints bypass mutation blocking. Tests assert that blocked requests make zero network calls.

The original broker guard was necessary but not sufficient for live trading. It has now been strengthened by the centralized authorization milestone below; broker reconciliation and an audited execution lifecycle remain absent, so live trading remains disabled.

### Dependency Manifest + Real Pytest Foundation milestone

The repository gained minimal runtime/development manifests and root pytest discovery. Tests no longer need a manual `PYTHONPATH`. Strict unit, safety, integration, and external-data markers are registered. The default suite substitutes non-secret test credentials, suppresses dotenv loading, and blocks network sockets. Manual server and live-data scripts are excluded from pytest discovery.

### Risk Authorization + Kill Switch milestone

The broker transport boundary now delegates every non-read-only mutation to one deterministic `RiskAuthorizationService`. A mutation proceeds only after explicit ALLOW. The service validates typed configuration and request structure, preserves the disabled-live gate, requires fresh market data, loads persistent kill-switch/daily state, rejects duplicate request IDs, and enforces loss, trade-count, consecutive-loss, open-position, position-size, per-trade-risk, and optional volatility limits. Unexpected conditions return DENY.

One atomic JSON document under `logs/` owns kill-switch and daily risk-control state. Kill activation/deactivation carries reason, timestamp, and actor. Missing or malformed state blocks authorization and is never silently reset. A verified later IST date creates a new zeroed daily state, while process restart alone does not. ALLOW reserves an available request ID before broker dispatch. Authorization audits contain only whitelisted non-secret metadata, decisions, calculated values, limits, and kill-switch state.

The centralized gate is still not sufficient to enable live trading. Paper counters are now authoritative, but instrument lot-value normalization and broker reconciliation remain absent.

### Single Authoritative Paper State milestone

`PaperStateService` now owns the only persisted paper-trading truth: positions, closed trades, raw quantity and optional lot metadata, daily realized/unrealized P&L, trades taken, consecutive losses, accepted request IDs, and lifecycle event IDs. It writes one schema-versioned JSON document atomically and rejects missing, malformed, inconsistent, or future-dated state without repair.

`PaperExecution` remains the dashboard/scanner compatibility interface but projects its active trade from authoritative state. It no longer reads or writes `active_paper_trade.json`. The existing CSV journal and Oracle feature log remain derived historical/audit outputs, not counter or active-position sources. The initial local migration retained 60 closed legacy journal events and no open position; current-day counters were initialized at zero because the journal had no current-date events.

Long paper P&L uses `(mark price - entry price) × remaining raw quantity` for unrealized value and `(exit price - entry price) × closed raw quantity` for realized value. SELL/SHORT compatibility reverses the price direction. Brokerage and slippage are excluded. Lot size and number of lots are available only when actual lot size is supplied; legacy records retain raw quantity without invented lot metadata.

Risk authorization now reads all P&L, trade-count, loss-streak, open-position, and accepted-ID values from `PaperStateService`. The separate risk-control document owns only the kill switch, preserving its independent emergency authority.

### Safe Backend Checkpoint + Read-Only Frontend Wiring milestone

Two sanitized GET-only projections were added: `/v1/risk/status` and `/v1/paper/status`. They whitelist operational fields rather than returning configuration documents, persistence paths, raw audit records, or credentials. Missing and malformed sources return explicit degraded/unavailable health with null metrics.

Dashboard V1.1 gained one compact `RISK & PAPER CONTROL` section immediately after Mission Control. It shows system safety, daily authoritative paper metrics, active non-live limits, and an optional non-secret authorization summary. It uses the existing one-loop three-second polling system, abort/timeouts, last-successful-data preservation, responsive grid, semantic tones, and footer. It exposes no action or toggle.

### Technical Market Engine Completion + Read-Only Frontend Exposure milestone

`src/oracle/oracle_service.py` is the verified service for current technical-market assessments. It consumes an injected read-only provider for the latest already-built `DashboardAPI` scanner snapshot. A read never initiates a scanner refresh, broker call, risk decision, paper-state read/write, or execution action. Its Oracle-named classes, files, and `/v1/oracle/*` routes remain compatibility aliases; they do not implement the canonical Personal Oracle role.

The result contract contains symbol, timeframe, generated and source timestamps, data age/status, Oracle health, directional bias, signal, bounded confidence and label, regime, reason codes, concise reasoning, a typed input-feature summary, warnings, maturity, and source/fallback metadata. Supported symbols match the production market set: `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, and `SENSEX`.

Decision evidence is deterministic and explainable. It uses existing EMA 21/38 structure, price-to-VWAP relationship, RSI momentum, multi-timeframe bias, scanner trade/bias, regime/liquidity classification, and existing Kronos confidence. Directional evidence is weighted with existing accepted configuration weights; Oracle does not optimize them. Its confidence is 75% normalized directional-feature alignment plus 25% existing Kronos confidence, with opposing evidence subtracted and the result bounded to 0–100. Trusted volume is absent from the current scanner snapshot and remains explicitly unavailable.

Only complete, live, trending, directionally aligned evidence above the existing Kronos minimum can return `LONG` or `SHORT`. Conflict lowers confidence. Cached evidence returns non-actionable `WAIT` with degraded health; stale evidence returns blocked `NO_TRADE`; missing, malformed, inconsistent, or insufficient evidence returns unavailable/degraded without invented confidence. Every available assessment has reason codes and warnings identify data-quality limitations.

The existing technical dashboard area polls `/v1/oracle/assessment/{symbol}` through the same page-level interval and follows the existing symbol selector. It is labeled **TECHNICAL INTELLIGENCE** and compactly displays health, freshness, selected symbol/timeframe, bias, signal, confidence, regime, top reasons, warnings, maturity, and last update. There are no buttons, mutation controls, or fabricated entry/stop/target levels.

### Module Responsibility Freeze + Original Vision Restoration milestone

ADR-022 and `docs/CITADEL_MODULE_ARCHITECTURE.md` permanently separate eight responsibilities: ARGUS owns options positioning; KRONOS owns setup quality/timing; the current `OracleService` owns technical-market assessment as the Technical Market Engine; ATHENA owns advisory risk/capital intelligence; HERMES owns read-only news/events; canonical ORACLE owns personal coaching; AEGIS owns final multi-engine orchestration; and Risk Authorization retains absolute mutation veto.

The freeze is classification-first and non-destructive. Existing Oracle files, classes, routes, historical feature tooling, and internal frontend types remain compatibility aliases. No module behavior, strategy, broker integration, risk gate, paper-state path, API contract, or polling mechanism changed. The dashboard received only the preferred Technical Intelligence text label.

Future AEGIS work may begin from documented soft influences—Technical 25%, KRONOS 25%, ARGUS 20%, Personal Oracle 15%, HERMES 10%, and ATHENA 5%—but these are not implemented or optimized weights. Kill switch, Risk Authorization denial, critical stale/unavailable data, strategy ineligibility, duplicates, configured high-impact event blocks, and disabled live trading remain hard vetoes.

### ATHENA Risk & Capital Intelligence milestone

`src/athena/athena_service.py` is the authoritative advisory ATHENA service. It reads sanitized `ControlStatusAPI.risk_summary()` and `paper_summary()` projections and owns no persistence. It cannot call broker transport, place/modify/cancel an order, mutate Paper State, change the kill switch, generate technical/news/options signals, or become final approval.

The typed result contains source/health metadata, trading date, risk state, recommendation, bounded advisory size multiplier, daily realized/unrealized/total P&L, daily loss usage/headroom, trade usage, loss-streak usage, open-position capacity usage, current drawdown, risk headroom, optional capital/equity fields, reasons, warnings, missing inputs, and maturity. Every result is explainable and includes reason codes.

ATHENA uses deterministic thresholds over the highest hard-limit utilization: below 50% is `SAFE/CONTINUE/1.00`; 50–79.99% is `CAUTION/REDUCE` with 0.75 or 0.50; 80–99.99% is `HIGH_RISK/PAUSE/0.25`; and reached hard limits produce `STOP/0.00`. Active kill switch, an exposed latest Risk Authorization `DENY`, or unavailable/malformed required risk/paper state also produces a fail-safe stop. The multiplier is advisory only, is never converted into raw quantity/lots, and never overrides Risk Authorization.

Daily drawdown is the loss portion of authoritative total daily paper P&L. Exposure usage is explicitly open-position-capacity utilization because no rupee exposure/margin ledger exists. `PaperState.cash_balance` is exposed as available capital only when present. Blocked capital, current equity, weekly/monthly risk usage, rupee exposure, and a dedicated maximum-drawdown limit remain null and visibly warned when unavailable.

`GET /v1/athena/status` is canonical. `/v1/athena/wheel` remains a compatibility projection backed by the same service. The existing dashboard area now shows compact source-backed risk/capital intelligence through the same one-loop polling, timeout, abort, retry, stale preservation, malformed-response guard, responsive layout, and no-control boundary.

### HERMES News & Event Intelligence Foundation milestone

`src/hermes/` now owns typed provider-agnostic HERMES contracts and deterministic cached assessment. `HermesInput` supports scheduled economic events, market news, social-media catalysts, and official announcements. Providers return typed inputs; HERMES stores only bounded normalized fields and never retains raw provider payloads, auth headers, or credentials.

Normalization produces event identity, headline/summary, taxonomy/type, explicit impact and sentiment, timing/countdown, provider publication/receipt freshness, source category/confidence, sanitized URL, affected geography/market/index/sector/symbol scope, tags, reasons, warnings, confirmation state, duplicate group, conflict state, and source traceability. Unsupported sentiment stays `UNKNOWN`.

Central source-confidence policy maps official government/central-bank/exchange/regulator/authenticated publication to high confidence, approved newswire/provider to medium, secondary aggregator/unverified social/unknown publisher to low, and insufficient metadata to unknown. Low/unknown-confidence inputs cannot alone remain critical. Official scheduled evidence outranks rumor timing during duplicate merge.

Central timing windows are 30 minutes imminent, 15 minutes live-after-event, 120 minutes recent, six hours relevant, and five minutes provider-snapshot freshness. Timing is recalculated on cached reads without provider refresh. Duplicate grouping uses explicit taxonomy/date where available, otherwise normalized headline/time. Conflicting sentiment, timing, or impact is preserved and warned; merged groups retain all bounded source names.

Assessment maps no/low events to `NORMAL`, medium or non-imminent high impact to `CAUTION`, imminent high/breaking high/high-confidence conflicts to `WAIT`, and imminent/live critical evidence to `AVOID_NEW_TRADES`. Unconfigured, malformed, or missing provider state is `UNAVAILABLE/UNKNOWN/WAIT`; a stale snapshot is `STALE/UNKNOWN/WAIT`. HERMES remains advisory and never blocks execution itself.

`HermesService.refresh_from_provider()` is an explicit internal ingestion boundary. `GET /v1/hermes/status` and `/v1/hermes/events` only read the bounded in-memory cache and cannot trigger provider refresh. Production intentionally starts with no provider configured, so it exposes unavailable rather than fixture news. Offline in-memory/fixture providers support deterministic tests, and fixture data is labeled non-live.

The dedicated HERMES panel displays source-backed health, event risk, recommendation, sentiment, next major event/countdown, impact/timing/confidence, affected scope, bounded top events, conflicts, freshness, reasons, coverage warnings, maturity, and update time. It uses the existing one controlled interval and never shows a live badge for cached/fixture data.

Because the Git working tree already contained mixed user-owned changes including tracked secret/runtime paths, both pre-change and final milestones were captured as non-destructive reports under `docs/checkpoints/` rather than unsafe commits or tags.

### Market Candle Integrity milestone

The prior scan path could append flat, timestamp-less OHLC rows on each dashboard poll. Candle handling was changed to normalize timestamps in `Asia/Kolkata`, deduplicate by symbol/time bucket, update an existing bucket's high/low/close while preserving open, append a new bucket once, and ignore stale updates. Higher-timeframe aggregation now uses actual timestamp buckets.

Dhan quote receipt time is still an approximation where exchange timestamps are unavailable. Quote volume may remain unavailable/zero, but it is no longer invented from poll frequency.

### ARGUS Phase 1 — data engine foundation

ARGUS gained read-only Dhan expiry and option-chain retrieval, normalized CE/PE strike records, ATM/ITM/OTM selection, OI totals, PCRs, walls, price/OI relationship classification, and one reusable `OptionChainSnapshot`. No strikes, OI, direction, or confidence values are mocked.

### ARGUS Phase 2 — intraday baseline and intelligence

ARGUS separated Dhan previous-day deltas from intraday deltas. It persists a first-valid-session baseline keyed by date, symbol, expiry, strike, and option side. Persistence is atomic and corruption fails explicitly rather than silently replacing truth. Session states are reported clearly, cache behavior is bounded, and unsupported symbols/expiries return structured errors.

Classification semantics use intraday price and OI movement:

- price up + OI up: `LONG_BUILDUP`
- price down + OI up: `SHORT_BUILDUP`
- price up + OI down: `SHORT_COVERING`
- price down + OI down: `LONG_UNWINDING`
- changes inside configured neutral thresholds: neutral
- absent baseline/fields: insufficient evidence

Option-side context determines whether evidence contributes to call writing, put writing, call buying, or put buying. Dominance is calculated over an ATM-centered window from positive evidence contributions. Verdict and confidence are transparent deterministic formulas weighted by evidence coverage and directional separation; they are not an AI forecast.

### ARGUS Phase 3 — compact decision panel

The dashboard gained a single compact full-width ARGUS panel between Performance and the existing intelligence engines. It is optimized for an option buyer rather than presenting a full exchange chain. It displays a seven-row ATM ±3 window, session/baseline state, dominance, verdict, confidence, walls/zones, avoid flags, and concise evidence. It intentionally has no execution controls.

Supported symbols are `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, and `SENSEX`. Expiry validation remains backend-owned. The accepted Dashboard V1.1 exposes the supported symbol selector.

### ARGUS Phase 3.1 — runtime stability and data sanitation

Safari instability was reproduced and addressed without an architectural rewrite. The frontend uses one visibility-aware three-second loop, an in-flight guard, abort controllers, five-second request timeouts, bounded retry, mounted-state protection, and preservation of the last successful data. Market rows are sanitized before entering React state, and the ARGUS window is memoized.

The expensive full-width ARGUS backdrop treatment was removed while preserving the dark institutional appearance. Verification covered stable DOM counts, one panel/seven rows/one ATM row, responsive in-app viewports, backend suspension and recovery, and a ten-minute Safari soak. The UI correctly retained stale data and reported timeout/disconnection before automatic recovery. No console errors, warnings, or hydration failures were observed in the accepted verification run.

## Current frontend architecture

- Next.js 16 App Router with strict TypeScript.
- Primary dashboard composition and typed feed integration in `citadel-dashboard/src/app/page.tsx`.
- Theme and responsive visual system in `citadel-dashboard/src/app/globals.css`.
- One page-level polling coordinator refreshes 11 feeds every three seconds.
- Initial loading is per widget; failures preserve last successful data and surface feed errors/staleness.
- Hidden tabs pause and abort polling; foreground resumes safely.
- No WebSockets and no added state-management dependency.

Visible dashboard areas are the system/connection header, Mission Control, Market Matrix, Active Trade, Performance Nexus, ARGUS OI Positioning, Kronos, Technical Intelligence, Athena Risk & Capital Intelligence, Hermes News & Event Intelligence, and AI Insights.

Do not redesign, reorder, or edit `page.tsx` or `globals.css` during backend-infrastructure work.

## Current backend architecture and data ownership

- `app/main.py` owns the FastAPI application and read-only dashboard routes.
- `src/api/dashboard_api.py` composes scanner, local paper state, analytics, and optimizer results with a short process-local cache.
- `src/api/argus_api.py` validates ARGUS requests, coordinates caching/locking, and maps engine/baseline failures to explicit HTTP responses.
- `src/oracle/oracle_service.py` implements deterministic, read-only Technical Market Engine assessments under retained Oracle compatibility names.
- `src/athena/athena_service.py` owns deterministic advisory risk/capital assessments sourced from sanitized authoritative projections.
- `src/hermes/` owns normalized provider-independent event contracts, offline adapters, taxonomy, deterministic cached assessment, and read-only event/status projections.
- `src/broker/dhan_client.py` owns Dhan transport and the central mutation guard.
- `src/data/data_engine.py` owns quote-to-candle integrity.
- `src/timeframe/timeframe_engine.py` owns timeframe bucketing.
- `src/scanner/market_scanner.py` and deterministic strategy/engine modules produce market classifications.
- `src/argus/option_chain_engine.py` and `src/argus/baseline_store.py` own option-chain normalization, intelligence, and baseline persistence.
- Local paper execution and analytics use runtime files under `logs/`; they are not broker-reconciled state.

Current GET routes are `/`, `/citadel/snapshot`, `/v1/mission-control`, `/v1/market/matrix`, `/v1/trade/active`, `/v1/performance/stats`, `/v1/argus/oi`, `/v1/kronos/gauge`, `/v1/oracle/status`, `/v1/oracle/assessment/{symbol}`, `/v1/oracle/reasoning`, `/v1/athena/status`, `/v1/athena/wheel`, `/v1/hermes/status`, `/v1/hermes/events`, `/v1/ai/insights`, `/v1/performance/equity`, `/v1/performance/distribution`, and `/v1/performance/heatmap`.

## Strategy and intelligence truth

- The active strategy manager uses `SimplePullbackStrategy`.
- The `pullback_v3` setting/name and the separate unfinished pullback engine do not make Pullback V3 active.
- KRONOS is permanently Setup Quality & Timing Intelligence. Current deterministic scoring is partial and is not machine learning or final approval.
- The Technical Market Engine uses the latest cached scanner features and deterministic thresholds through the `OracleService` compatibility implementation; it is not Personal Oracle, an LLM, a prediction guarantee, or execution authority.
- Canonical ORACLE is permanently the future Personal AI Trading Coach. Legacy feature/performance readers are possible evidence tooling, not completion of that role.
- ATHENA is verified advisory Risk & Capital Intelligence over authoritative risk/paper projections. It never replaces or overrides hard Risk Authorization.
- HERMES has a verified provider-agnostic offline foundation and cached read-only frontend/API. No live provider is configured; AI Insights is not Hermes.
- AEGIS is permanently the Final Decision Controller and is not implemented; it can never bypass Risk Authorization.
- AI Insights wraps optimizer suggestions; it is not proof of a generative model call.
- ARGUS is decision support based on read-only option-chain evidence, not an execution or prediction engine.

## Environment and secret handling

The working configuration reports paper mode with live trading disabled. Secret values belong only in local environment files and must never enter prompts, logs, test fixtures, screenshots, or documentation.

`.gitignore` already ignores `.env`, environment variants except `.env.example`, Python caches, `.venv`, Node/Next outputs, and `logs/`. However, `.env` and several runtime CSVs are already tracked in the repository. Ignore rules do not untrack existing files. Their remediation and any credential rotation require an explicit, separately scoped safety task; documentation work must not inspect or mutate them.

## Validation history and test foundation

Broker safety, candle integrity, ARGUS intraday logic, and ARGUS API behavior have dedicated test modules. Milestones also used Python compilation, deterministic assertion harnesses, local endpoint probes, Next.js production builds, and browser verification. Phase 3.1 included a real backend failure/recovery drill and Safari soak.

The environment has reproducible dependency manifests and working pytest discovery. The safe offline suite collects and passes 193 tests: the previous 159 plus 30 HERMES model/service/API/safety cases and four frontend contract cases. Network sockets are blocked, dotenv loading is suppressed, and broker ALLOW verification uses only a mocked request method. The Next.js 16 production build and ESLint validation pass.

## Known approximations and technical debt

- Receipt-time candles are poll-derived rather than exchange-timestamp/tick accurate.
- HTTP polling creates broker overhead; WebSockets are intentionally deferred.
- Dashboard and ARGUS caches are process-local.
- The session calendar is not exchange-holiday aware.
- A late first in-session ARGUS request creates a late baseline.
- Historical Oracle-named feature/performance analytics remain separate derived CSV readers and are neither the Technical Market Engine authority nor a completed Personal Oracle.
- The Technical Market Engine compatibility implementation relies on an already-built process-local scanner snapshot. It is unavailable before first snapshot, does not refresh on read, and has no shared multi-worker cache.
- Its source time is backend scan completion rather than an exchange tick. The current snapshot has no trusted volume feature, so volume evidence is unavailable.
- Cached technical data is non-actionable and stale data is blocked; the engine intentionally provides no entry, stop, target, order, or authorization output.
- Multiple legacy paper components remain.
- Performance equity and heatmap routes include preview/stub data.
- A global kill switch, live risk authorization gate, and unified paper state exist, but broker state is not reconciled.
- The local risk store uses atomic replacement and an in-process lock, not shared multi-worker coordination.
- Raw quantity and entry-to-stop distance are used for per-trade risk because instrument lot/value metadata is not yet authoritative.
- Paper P&L excludes brokerage and slippage, and legacy journal rows do not contain explicit quantity or lot metadata.
- Paper cash balance remains unset, and the prior architecture did not provide a separate order/fill ledger to migrate.
- ATHENA cannot calculate blocked capital, current equity, rupee exposure/margin, weekly/monthly risk usage, or a separate maximum drawdown because authoritative inputs do not exist. Available paper cash remains null unless explicitly present in Paper State.
- ATHENA uses open-position slots as a disclosed capacity proxy, not financial exposure. Its size multiplier is relative advisory guidance, not quantity or lot sizing.
- The latest sanitized Risk Authorization decision has no applicability/freshness contract; ATHENA conservatively treats an exposed `DENY` as a hard stop.
- HERMES production has no external provider, durable/shared cache, market-session input, or exchange-holiday calendar; it truthfully starts unavailable.
- HERMES fixtures/in-memory inputs are test/development evidence, not live news. Source confidence is deterministic policy classification, not independent verification.
- Duplicate handling is stable key-based normalization rather than semantic NLP/entity resolution. Sentiment is never inferred from headline text.
- HERMES recommendations are advisory only and are not consumed by an implemented AEGIS controller.
- Local paper-state locking is in-process only; multi-worker/process coordination is not claimed.
- Static frontend contract tests exist; browser end-to-end automation is not established.
- The working tree contains pre-existing uncommitted application changes; future work must preserve unrelated user changes.

## User collaboration preferences

- Inspect the repository first, but do not repeat completed audits without cause.
- Edit repository files directly; do not send code for manual pasting.
- Use small, bounded milestones and stop at the requested boundary.
- Change the minimum files and do not rewrite architecture.
- Report exact files changed and verification outcomes.
- Prefer concise, clear commentary; Hinglish is welcome when useful.
- Never fabricate market values, signals, confidence, PnL, or capability claims.
- Preserve secrets and never print `.env` contents.
- Keep production and research repositories strictly separate.
- Model/workstream naming recorded for continuity: Sol for production implementation, Luna for review/verification, and Terra for separate research exploration. These are workflow labels, not claims about code behavior.

## Agreed production sequence

1. Dependency Manifest + Real Pytest Foundation — complete
2. Risk Authorization + Kill Switch — complete
3. Single Authoritative Paper State — complete
4. Safe Backend Checkpoint + Read-Only Frontend Wiring — complete
5. Technical Market Engine completion under Oracle compatibility names — complete
6. Module Responsibility Freeze + Original Vision Restoration — complete
7. ATHENA RISK & CAPITAL INTELLIGENCE — complete
8. HERMES NEWS & EVENT INTELLIGENCE FOUNDATION — complete
9. PERSONAL ORACLE DATA FOUNDATION — complete
10. PERSONAL ORACLE BEHAVIORAL & COACHING LAYER — complete
11. AEGIS DECISION FOUNDATION — complete
12. ORDER & FILL LEDGER FOUNDATION — complete, audit-only and GET-only
13. REAL-MARKET PAPER TRADING ACTIVATION — complete at readiness scope
14. OPEN-MARKET PAPER FORWARD VALIDATION — next; not started

KRONOS ALPHA upstream verification was completed separately, but local installation is blocked/not complete due to the host data volume reporting 100% capacity (about 1.4 GiB free), no discovered Python 3.10–3.13 interpreter, and no PyTorch. No runtime or frontend integration exists. `docs/KRONOS_ALPHA.md` records the pinned identities and future shadow-only, zero-influence boundary. KRONOS CORE remains the existing rule-based setup/timing module.

That blocked state is historical. The resumed V2 milestone installed pinned Kronos-small/tokenizer artifacts outside Git, isolated Python 3.11/PyTorch, passed real MPS inference and offline reload, and added `src/kronos_alpha/`, atomic bounded cache semantics, cached GET-only status/forecast routes, and an additive shadow dashboard panel. Production is still truthfully unavailable because authoritative 64+ closed NIFTY/5m history is not exposed to the controlled runner. KRONOS ALPHA has zero execution, AEGIS, and Risk Authorization influence; KRONOS CORE remains intact.

KRONOS ALPHA full activation subsequently added canonical NSE session/holiday truth, exact read-only Dhan NIFTY `IDX_I/13/INDEX/5m` input, restart-safe 256-candle backfill, one-job-per-close scheduling, 20 sampled paths, CE/PE option-buying quality, direction-neutral Forecast Quality, two responsive wheels, history ledger, and complete-horizon realization evaluation. On Saturday 2026-07-11 it is correctly `READY_FOR_NEXT_OPEN`, with first eligibility 2026-07-13 09:20:10 IST; no closed-market forecast was fabricated. Actual Monday observation remains pending. All influence stays 0% and KRONOS CORE is intact.
10. Continue the frozen module migration sequence only through separately authorized milestones
11. Add broker reconciliation and an audited order lifecycle
12. Consider controlled live-trading validation only after all safety gates are complete and explicitly authorized

Personal ORACLE and AEGIS remain complete and advisory. The Order & Fill Ledger now provides immutable audit evidence and read-only operations telemetry without broker or Paper mutation. The immediate next task is **PAPER EXECUTION ENGINE**, documented in `docs/NEXT_TASK.md`.

## Latest safety/readiness checkpoint

The single existing Risk Control persistence contract is now initialized and restart-readable: state `INACTIVE`, reason `INITIALIZED_SAFE_DEFAULT`, persistence `HEALTHY`, schema v1. It is not an approval. Risk Authorization still vetoes ACTIVE/UNKNOWN/CORRUPT, all prior limits remain, and `live_trading_enabled=false`.

AEGIS reads the same projection. Its current market-closed result is WAIT / MARKET_CLOSED rather than the former false kill-switch-unavailable BLOCK. Readiness and the ten-step next-session plan are GET-only, cached/read-only, sanitized, and visible in the existing AEGIS panel. No readiness read triggers provider refresh, KRONOS inference, broker transport, Paper mutation, Risk mutation, or execution.

The order/fill foundation described by that historical readiness checkpoint is now complete. Next production work is **PAPER EXECUTION ENGINE** only after explicit authorization. Do not mix it with the separate research repository.

## CHRONOS-2 challenger checkpoint

The official `amazon/chronos-2` model is installed outside Git with a dedicated Python 3.11 environment and pinned revisions. It reads only shared canonical closed NIFTY candles, runs isolated scheduled SHADOW inference, emits genuine quantiles, and keeps all directional/CE/PE metrics explicitly CITADEL-derived. Seven GET-only cache projections and a compact side-by-side KRONOS ALPHA/CHRONOS-2 frontend are complete.

No Chronos GET route triggers inference or provider refresh. Direct AEGIS and execution influence remain 0%. Timestamped option-chain history and realized calibration remain unavailable. The lifecycle-owned paper engine may observe their cached SHADOW status but never uses either model as execution authorization. The current next milestone is **OPEN-MARKET PAPER FORWARD VALIDATION**.
