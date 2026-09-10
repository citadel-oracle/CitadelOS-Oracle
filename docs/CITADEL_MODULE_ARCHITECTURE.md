# CITADEL OS — Permanent Module Architecture

Status: **Accepted and frozen**  
Effective date: 2026-07-11 (Asia/Kolkata)

This document is the permanent responsibility map for CITADEL OS production. It defines module ownership, dependencies, boundaries, compatibility names, decision flow, and migration order. It restores the original product vision without removing current safety or technical improvements.

Repository code remains authoritative for what is implemented today. This document is authoritative for which module may own each responsibility going forward. The separate research repository is never an implicit production dependency.

## Core separation

| Module | Permanent responsibility | Decision authority |
|---|---|---|
| ARGUS | Options Positioning Intelligence | Advisory confirmation only |
| KRONOS | Setup Quality & Timing Intelligence | Advisory eligibility/timing only |
| Technical Market Engine | Technical market direction and regime | Advisory technical assessment only |
| ATHENA | Risk & Capital Intelligence | Advisory capital/risk recommendation only |
| HERMES | News & Event Intelligence | Advisory event/news assessment only |
| ORACLE | Personal AI Trading Coach | Advisory evidence about Ayush's personal edge only |
| AEGIS | Final Decision Controller | Final orchestration decision, subject to hard vetoes |
| Risk Authorization | Absolute Hard Safety Gate | Final mutation veto; cannot be overridden |

No advisory module may place orders, mutate paper state, change the kill switch, or bypass Risk Authorization.

## Repository naming/responsibility conflict audit

| Existing location/name | Conflict with permanent architecture | Frozen interpretation / migration treatment |
|---|---|---|
| `src/oracle/oracle_service.py`, exported `Oracle*` assessment types | Implements market technical direction, not personal coaching. | Technical Market Engine implementation under compatibility names; keep behavior and add canonical names only later. |
| `/v1/oracle/status`, `/v1/oracle/assessment/{symbol}`, `/v1/oracle/reasoning` | Routes expose technical assessment under the future coach's name. | Retained Technical Market Engine compatibility routes; do not break consumers. |
| Frontend `OracleReasoning`, `OraclePanel`, Oracle feed state | Internal technical-panel names overlap canonical Personal ORACLE. | Internal compatibility only; user-facing section is **TECHNICAL INTELLIGENCE**. No polling/contract refactor in this freeze. |
| `OracleFeatureLogger`, `OracleReader`, `logs/oracle_features.csv`, performance/optimizer readers | Historical feature/performance utilities are neither the current technical authority nor a completed personal coach. | Derived evidence tooling and compatibility filenames; potential future Personal ORACLE input only after provenance/sufficiency work. |
| `/v1/ai/insights` response field `source: "Oracle"` | The content is current optimizer output, not Personal ORACLE, Technical Market Engine, or Hermes. | Legacy response label retained to avoid behavior/API change; documentation and UI must call the capability heuristic AI Insights, not personal coaching/news. Correct through a future versioned API migration. |
| Multiple Kronos paths (`src/kronos/*`, `src/core/kronos_engine.py`) and current gauge | Existing scoring emphasizes technical trend/momentum/regime and does not fulfill the complete setup/timing mandate. | KRONOS remains PARTIAL; consolidate only through a separate compatibility-safe milestone. |
| Strategy/scanner `trade`, Kronos gates, and current signal flags | Could be mistaken for final approval. | Strategy/setup eligibility only; none is AEGIS and none bypasses Risk Authorization. |
| `/v1/athena/wheel` | The former preview contract could be mistaken for authoritative Risk & Capital Intelligence. | Retained as a read-only compatibility projection over `AthenaService`; `/v1/athena/status` is canonical. |
| AI Insights / Optimizer | Names may suggest Hermes news or Personal Oracle coaching. | Heuristic optimizer suggestions only; never relabel as Hermes or completed Personal ORACLE. |
| `docs/CITADEL_PRODUCT_BIBLE.md` and `docs/AI_TRADING_BIBLE.md` | Older broad module/plugin language predates permanent responsibility boundaries. | Historical vision references. ADR-022 and this document supersede conflicting role interpretations without rewriting historical files. |
| Hermes and AEGIS names absent from runtime services/routes | Original roles are not implemented. | Explicitly NOT STARTED; no existing module is a substitute. |

This audit changes interpretation and exposed technical labeling only. It does not authorize modifying the listed runtime compatibility paths.

## 1. ARGUS — Options Positioning Intelligence

| Property | Frozen definition |
|---|---|
| Permanent role | Explain options-market positioning around the underlying. |
| Inputs | Read-only option-chain/expiry data, strikes, CE/PE price, OI, previous OI, volume/IV when supplied, persisted intraday baseline, session time. |
| Outputs | OI changes, call/put walls, buyer/writer activity, buildup/unwinding, ATM-near positioning, breakout/breakdown zones, options confirmation, confidence/evidence quality, unavailable/stale states. |
| Allowed dependencies | Read-only Dhan market-data transport, ARGUS baseline store, session/time utilities, typed API projection. |
| Forbidden dependencies | Order placement/cancellation, Risk Authorization mutation, Paper State mutation, news feeds, personal journal coaching, final approval ownership. |
| Data ownership | Owns normalized option-chain snapshots, option positioning classifications, and its session baseline. It does not own market candles, risk state, journal truth, or final decisions. |
| Current implementation | **VERIFIED** for Phase 1–3.1 read-only option-chain intelligence, baseline persistence, API, cache, and dashboard panel. |
| Future implementation | Improve exchange-calendar awareness, shared cache/baseline coordination, and evidence depth without expanding into final approval. |
| Compatibility aliases | Existing `src/argus/*`, `ArgusAPI`, `GET /v1/argus/oi`, and dashboard ARGUS labels remain canonical. |
| No-overlap boundary | ARGUS confirms or contradicts an options setup; it never decides capital, personal suitability, news impact, or final execution. |

## 2. KRONOS — Setup Quality & Timing Intelligence

| Property | Frozen definition |
|---|---|
| Permanent role | Evaluate whether a setup is structurally valid, fresh, timely, and eligible now. |
| Inputs | Trend, momentum, structure, liquidity, candles, session/time, VOB/FVG/BOS/CHoCH/retest state when implemented, signal birth time, cooldown/holding/DTE rules. |
| Outputs | Setup-quality score, timing eligibility, freshness, structure/liquidity quality, confirmation delay, entry-window state, cooldown/holding constraints, expiry/DTE suitability, explainable reasons. |
| Allowed dependencies | Technical features/candles, structure and liquidity engines, session calendar, strategy eligibility metadata, read-only instrument expiry metadata. |
| Forbidden dependencies | Option-chain OI ownership, news/event ingestion, personal journal learning, capital allocation, order placement, final execution approval. |
| Data ownership | Owns setup/timing evaluations and their timestamps. It does not own raw option positioning, news, personal performance history, or hard risk state. |
| Current implementation | **PARTIAL**. Existing Kronos engines provide deterministic trend/momentum/regime/score context; the complete VOB, FVG, BOS/CHoCH, retest, timing-window, cooldown, holding-time, and DTE mandate is not yet production-integrated. |
| Future implementation | Complete the frozen setup/timing contract through separately tested milestones; do not absorb ARGUS, Hermes, Oracle, Athena, or AEGIS duties. |
| Compatibility aliases | Existing `src/kronos/*`, legacy `src/core/kronos_engine.py`, Kronos fields, and `GET /v1/kronos/gauge` remain compatible until a deliberate consolidation milestone. |
| No-overlap boundary | KRONOS decides setup/timing quality, not market OI, personal edge, news risk, position sizing, or final approval. |

## 3. Technical Market Engine — Current `OracleService`

| Property | Frozen definition |
|---|---|
| Permanent role | Produce deterministic technical market direction, regime, confidence, reasons, and freshness state. |
| Inputs | Existing scanner snapshot; EMA 21/38, VWAP, RSI, ADX/ATR availability, multi-timeframe bias, scanner bias/trade eligibility, regime, liquidity classification, existing Kronos confidence. |
| Outputs | Technical `LONG`, `SHORT`, `WAIT`, or `NO_TRADE`; bullish/bearish/neutral bias; regime; bounded confidence; reason codes; typed features; cached/stale/unavailable status. |
| Allowed dependencies | Existing read-only DashboardAPI snapshot cache, deterministic configuration thresholds/weights, scanner feature contracts. |
| Forbidden dependencies | Broker transport, paper-state mutation, Risk Authorization mutation, kill-switch mutation, personal journal learning, news ingestion, final approval ownership. |
| Data ownership | Owns only the derived technical assessment and its process-local fallback. Scanner/candle sources remain owned by their existing modules. |
| Current implementation | **VERIFIED** as `src/oracle/oracle_service.py`, with deterministic offline tests and read-only frontend exposure. |
| Future implementation | Introduce canonical Technical Market Engine names only through additive aliases/migration. Do not destructively rename working classes, files, routes, or stored historical artifacts. |
| Compatibility aliases | `OracleService`, `OracleAssessment`, `OracleFeatureSummary`, `OracleSourceMetadata`, `/v1/oracle/status`, `/v1/oracle/assessment/{symbol}`, `/v1/oracle/reasoning`, frontend `OracleReasoning`/`OraclePanel`, and historical Oracle feature filenames are legacy technical compatibility names. |
| No-overlap boundary | This engine assesses the market technically. It does not learn Ayush's behavior, own setup timing, interpret options OI/news, allocate capital, or approve execution. |

Preferred user-facing label: **TECHNICAL INTELLIGENCE**.

## 4. ATHENA — Risk & Capital Intelligence

| Property | Frozen definition |
|---|---|
| Permanent role | Convert authoritative risk and paper state into truthful capital/risk advice. |
| Inputs | Risk Authorization status/limits, kill-switch state, authoritative Paper State, realized/unrealized P&L, daily/weekly/monthly usage when genuinely available, positions, quantity/lot metadata, loss streak, capital configuration. |
| Outputs | Daily drawdown and risk usage, headroom, trade/loss-streak/open-position utilization, advisory size multiplier, available capital fields when authoritative, and `CONTINUE`, `REDUCE`, `PAUSE`, or `STOP` with provenance. Weekly/monthly and rupee values remain unavailable until authoritative sources exist. |
| Allowed dependencies | Read-only projections from Risk Authorization, Risk Control, Paper State, verified instrument metadata, and configuration sanitizers. |
| Forbidden dependencies | Direct broker mutation, technical/option/news signal ownership, journal coaching, final decision ownership, silent state repair, invented capital or risk values. |
| Data ownership | Owns derived risk/capital intelligence only. Risk Authorization owns hard limits/vetoes; Paper State owns paper positions/P&L; kill-switch storage remains independent. |
| Current implementation | **VERIFIED**. `AthenaService` consumes sanitized risk/paper projections, produces deterministic advisory recommendations and a bounded multiplier, exposes `GET /v1/athena/status`, and powers the compact panel. Risk Authorization remains the hard veto. |
| Future implementation | Add weekly/monthly risk ledgers, authoritative capital/equity/margin/rupee-exposure data, dedicated drawdown configuration, and instrument-normalized sizing only through separate source-of-truth milestones. |
| Compatibility aliases | Existing Athena panel remains in place; `/v1/athena/wheel` remains a legacy read-only projection backed by the canonical service. |
| No-overlap boundary | ATHENA recommends risk quality and capital posture; it does not generate technical/news/OI signals or issue final approval. Risk Authorization may veto regardless of Athena advice. |

## 5. HERMES — News & Event Intelligence

| Property | Frozen definition |
|---|---|
| Permanent role | Provide source-aware, read-only news, macro, geopolitical, and scheduled-event intelligence. |
| Inputs | RBI/Fed calendars, CPI/PMI/GDP/jobs releases, Indian/US market news, geopolitical/election events, official/credible sources, publication/event timestamps. |
| Outputs | Event countdowns, affected sectors/indices, bullish/bearish/neutral sentiment, impact/severity, source credibility, conflicts, freshness, and advisory block windows. |
| Allowed dependencies | Read-only news/calendar providers, source normalization, credibility/conflict rules, market/session clock. |
| Forbidden dependencies | Broker or paper mutation, technical indicator ownership, option OI ownership, personal coaching, capital allocation, final execution approval. |
| Data ownership | Will own normalized news/event records, source provenance, conflict state, and derived event impact. |
| Current implementation | **VERIFIED FOUNDATION**. Typed inputs/events/assessment, India/global taxonomy, centralized windows/source confidence, deduplication/conflicts, explicit refresh, cached GET routes, offline providers, and compact dashboard panel are tested. Production has no external provider and reports unavailable. |
| Future implementation | Integrate approved official calendar/news providers through explicit out-of-band refresh, durable/shared cache, coverage monitoring, and exchange/session calendar context. Preserve advisory-only semantics. |
| Compatibility aliases | None. `GET /v1/hermes/status` and `/v1/hermes/events` are canonical. Generic AI Insights/optimizer output is not Hermes and must not be relabeled as news. |
| No-overlap boundary | HERMES explains events/news only; it does not calculate technical setups, personal expectancy, risk size, or final approval. |

## 6. ORACLE — Personal AI Trading Coach

| Property | Frozen definition |
|---|---|
| Permanent role | Optimize Ayush's decisions and habits using evidence from his trading history; it optimizes the trader, not the market. |
| Inputs | Authoritative journal and paper trades; later explicitly reconciled live trades; instrument/setup/time/confidence/weekday/side/sequence/holding/entry/exit/outcome metadata; validated feature context. |
| Outputs | Best instrument/setup/time/confidence range, best/worst weekday, CE-vs-PE performance, first-vs-later trade performance, repeated mistakes, revenge patterns, holding/entry/exit mistakes, setup expectancy, evidence-backed personal recommendations, sufficiency/uncertainty. |
| Allowed dependencies | Read-only authoritative trade/journal history, validated performance analytics, future consented coaching models, non-secret user preferences. |
| Forbidden dependencies | Raw market direction ownership, option OI/news/risk ownership, order placement, paper-state mutation, kill-switch mutation, final approval, claims without sufficient evidence. |
| Data ownership | Will own derived personal-edge/coaching models and recommendations. Authoritative trades remain owned by Paper State/journal or future reconciled execution records. |
| Current implementation | **NOT STARTED** as the personal coach. Existing `OracleFeatureLogger`, `OracleReader`, performance analytics, and optimizer suggestions are legacy/partial evidence tooling, not a completed Personal Oracle. Current `OracleService` is explicitly the Technical Market Engine compatibility implementation. |
| Future implementation | Build only after authoritative evidence definitions, sufficiency rules, privacy boundaries, and deterministic offline evaluation are agreed. Live-trade learning requires later broker reconciliation. |
| Compatibility aliases | Existing technical `OracleService`, `/v1/oracle/*`, frontend internal Oracle types/components, `oracle_features.csv`, and `OracleReader` retain compatibility names temporarily; none establishes personal-coach completion. |
| No-overlap boundary | Personal ORACLE measures Ayush's edge and behavior. It does not decide raw market direction, timing eligibility, news impact, capital limits, or final execution. |

## 7. AEGIS — Final Decision Controller

| Property | Frozen definition |
|---|---|
| Permanent role | Combine advisory intelligence into one explainable final trade decision before hard authorization. |
| Inputs | Technical Market Engine, ARGUS, KRONOS, HERMES, Personal ORACLE, ATHENA, strategy eligibility, data freshness/availability. |
| Outputs | `APPROVE`, `APPROVE_REDUCED`, `WAIT`, `REJECT`, or `BLOCK`, with component evidence, soft influences, conflicts, hard-veto reasons, and maturity. |
| Allowed dependencies | Read-only typed outputs from the six advisory engines, strategy eligibility, and Risk Authorization request interface. |
| Forbidden dependencies | Owning raw market/news/journal/risk state, direct broker dispatch, bypassing Risk Authorization, overriding a hard veto, hidden weights, silent fallbacks. |
| Data ownership | Will own only the composed decision record and evidence trace. Source modules retain their data and assessments. |
| Current implementation | **NOT STARTED**. Existing scanner `trade` flags, strategy checks, Oracle technical signals, or optimizer suggestions are not AEGIS. |
| Future implementation | Define a typed, explainable controller after required advisory modules exist. It must call Risk Authorization for any mutation path and preserve every veto. |
| Compatibility aliases | None. No current module may be presented as AEGIS. |
| No-overlap boundary | AEGIS composes; it does not replace specialist engines or the hard safety gate. An approval is advisory until Risk Authorization allows the exact request. |

## 8. Risk Authorization — Absolute Hard Safety Gate

| Property | Frozen definition |
|---|---|
| Permanent role | Provide the final fail-closed ALLOW/DENY decision immediately before any broker mutation. |
| Inputs | Live-trading flag, kill switch, fresh market data, typed order/risk request, authoritative Paper State counters/positions/P&L/accepted IDs, configured hard limits. |
| Outputs | `ALLOW` or `DENY`, stable reason codes, calculated risk/limit values, non-secret audit record, duplicate reservation on ALLOW. |
| Allowed dependencies | Broker transport boundary, Risk Control store, authoritative Paper State, sanitized typed configuration, verified clock/freshness. |
| Forbidden dependencies | Advisory-module overrides, frontend authority, hidden defaults, silent state repair, unvalidated caller counters, bypass on AEGIS approval. |
| Data ownership | Owns authorization decisions/audit and hard-limit evaluation. Kill-switch persistence stays in Risk Control; paper lifecycle stays in Paper State. |
| Current implementation | **VERIFIED** with persistent kill switch, fail-closed validation, limits, duplicate protection, audit, and transport-boundary enforcement. Live trading remains disabled. |
| Future implementation | Add broker reconciliation, authoritative instrument risk normalization, and audited order lifecycle before any controlled live validation. Never weaken veto authority. |
| Compatibility aliases | Existing `RiskAuthorizationService`, `/v1/risk/status`, broker mutation guard, and control-state/audit schemas remain authoritative. |
| No-overlap boundary | Risk Authorization does not create trade ideas or rank setups. It can veto any AEGIS result and is the only component that may authorize broker mutation. |

## Data ownership summary

| Data/decision | Sole owner |
|---|---|
| Option-chain positioning and ARGUS baseline | ARGUS |
| Setup quality and timing assessment | KRONOS |
| Technical market assessment | Technical Market Engine |
| Risk/capital recommendation | ATHENA |
| News/event assessment and provenance | HERMES |
| Personal-edge/coaching recommendation | ORACLE |
| Composed final advisory decision | AEGIS |
| Hard broker-mutation ALLOW/DENY | Risk Authorization |
| Paper positions, lifecycle, P&L, counters | Paper State |
| Kill-switch state | Risk Control store |
| Broker transport | DhanClient transport boundary |

## Final system flow

```text
Market/candle features ──> Technical Market Engine ─┐
Structure/session data ─> KRONOS ───────────────────┤
Option-chain data ──────> ARGUS ────────────────────┤
News/event sources ─────> HERMES ───────────────────┼─> AEGIS decision
Trade history ──────────> ORACLE personal edge ─────┤       │
Risk/paper projections ─> ATHENA advice ────────────┘       │
                                                            v
                                               Risk Authorization
                                               absolute ALLOW/DENY
                                                            │
                                          DENY: stop         │ ALLOW
                                                            v
                                            audited broker mutation path
```

No direct arrow from an advisory engine to broker transport is allowed. AEGIS cannot bypass Risk Authorization.

### Order & Fill Ledger ownership

- Owns immutable order intent, lifecycle event, observed fill, reconstruction, accounting projection, and reconciliation evidence only.
- Receives AEGIS/Risk/kill-switch/session provenance; it does not rerun or override those engines.
- Has no broker transport or execution dependency and cannot mutate authoritative Paper State.
- Exposes only bounded GET projections. Future Paper Execution may consume `FillApplicationRequest`, but application is fixed false in this foundation.
- Remains separate from Risk Control, AEGIS decision audit, broker state, and Paper State ownership.

### Real-market paper execution ownership

- Backend lifecycle owns orchestration; GET routes and frontend polling are projection-only.
- Consumes the shared canonical closed NIFTY candle cache, unchanged strategy, ARGUS option chain, AEGIS decision, Dhan instrument metadata, Paper Risk Authorization, and read-only option quotes.
- Creates only paper intents and simulated fills. It has no broker order/tradebook/position dependency.
- Order & Fill Ledger owns immutable execution evidence; Paper State owns positions and P&L; the orchestrator owns only restart-safe scheduling/timeline state.
- KRONOS ALPHA and CHRONOS-2 remain SHADOW at 0% execution influence.

### Kill-switch and readiness ownership

- `RiskControlStore` is the only authoritative kill-switch state owner. The dashboard and AEGIS consume projections only.
- Missing/corrupt state fails closed; valid INACTIVE only permits subsequent gate evaluation.
- Open-market readiness owns no trading state. It composes canonical session truth and cached/read-only health projections and exposes a deterministic unobserved plan.
- AEGIS exposes a static API-readiness projection for this validator so readiness cannot append a decision or build live inputs.
- No readiness or frontend route may refresh a provider, invoke a model, call broker transport, mutate Paper/Risk state, or expose a control.

### CHRONOS-2 challenger ownership

- CHRONOS-2 owns an independent quantile forecast, its immutable forecast/evaluation ledger, and explicitly CITADEL-derived shadow analytics.
- It consumes the shared closed NIFTY candle cache and canonical NSE calendar. It owns no Dhan polling, option-chain history, strategy parameters, trading state, or authorization.
- KRONOS ALPHA and CHRONOS-2 remain separate identities and separate scores. Comparison never merges them or declares a winner below 20 comparable forecasts.
- CHRONOS-2 has no direct AEGIS input, hard gate, score, size, execution, Paper, Risk, or kill-switch authority. Frontend GET polling reads caches only.

### KRONOS naming extension

- **KRONOS CORE** is the existing rule-based setup-quality and timing intelligence shown in the system flow as KRONOS.
- **KRONOS ALPHA** is a reserved future local pretrained-model input: closed candles → isolated official Kronos-small runner → sanitized forecast cache → KRONOS CORE context/future AEGIS evidence.
- KRONOS ALPHA is locally installed through an isolated Python 3.11 runner, pinned official model/tokenizer cache outside Git, exact read-only NIFTY `IDX_I/13/INDEX/5m` input, canonical NSE calendar, lifecycle-owned candle-close scheduler, deterministic metrics/outlooks, bounded atomic caches/history/evaluation, cached GET projections, and two additive CE/PE wheels. It remains `SHADOW`, read-only, and at 0% execution/AEGIS/Risk Authorization influence. Polling never triggers data refresh, inference, or download. It cannot replace KRONOS CORE or connect directly to any mutation boundary.

## Starting soft influences

These are initial design influences for future AEGIS work, not optimized production weights, trading logic, or authorization thresholds.

| Advisory input | Starting soft influence |
|---|---:|
| Technical Market Engine | 25% |
| KRONOS | 25% |
| ARGUS | 20% |
| ORACLE personal edge | 15% |
| HERMES | 10% |
| ATHENA advisory risk quality | 5% |

The percentages document product intent only. They must not be wired into production until AEGIS has a separately approved contract, sufficient inputs, conflict handling, deterministic tests, and calibration evidence.

## Hard veto rules

Any of the following blocks the relevant action regardless of soft influence:

- kill switch active;
- Risk Authorization returns `DENY`;
- critical data is stale or unavailable;
- strategy is not eligible;
- duplicate request;
- HERMES identifies a configured blocked high-impact event after Hermes exists;
- `live_trading_enabled=false` for any live path.

Additional validated hard limits owned by Risk Authorization remain in force. Advisory confidence can never override a veto.

## Compatibility and naming migration

The responsibility freeze changes classification and labels, not current runtime behavior.

1. Keep `OracleService`, `OracleAssessment`, files under `src/oracle/`, and `/v1/oracle/*` working as Technical Market Engine compatibility aliases.
2. Use **TECHNICAL INTELLIGENCE** as the preferred dashboard label for the current technical panel.
3. In new backend work, introduce additive technical-engine names/contracts before deprecating any Oracle compatibility name.
4. Reserve the canonical product name **ORACLE** for the future Personal AI Trading Coach. Never infer personal-coach completion from legacy Oracle filenames or routes.
5. Keep historical `OracleFeatureLogger`, `OracleReader`, and CSV names until a separately authorized data migration proves lossless compatibility.
6. Do not relabel current AI Insights as Hermes, existing scanner decisions as AEGIS, or ATHENA advisory intelligence as final authorization.
7. Deprecation or removal requires a versioned migration plan, consumer inventory, tests, and explicit approval; no destructive rename is implied by this freeze.

## Migration sequence

1. **Responsibility freeze and compatibility label** — this documentation milestone; no behavior change.
2. **ATHENA RISK & CAPITAL INTELLIGENCE** — complete: truthful advisory risk/capital contract backed by authoritative services; no final-decision authority.
3. **HERMES NEWS & EVENT INTELLIGENCE FOUNDATION** — complete: read-only cached news/events with provenance, freshness, conflict, and advisory event-risk semantics.
4. **PERSONAL ORACLE DATA FOUNDATION** — complete: schema-v1 authoritative completed-trade evidence, separate append-only ledger/enrichments, no-look-ahead capture, deterministic analytics, GET-only APIs, and read-only presentation. It has no broker, paper, risk, KRONOS, execution, or AEGIS mutation/influence. Raw/private notes remain outside the ledger.
5. Complete the frozen KRONOS setup/timing contract through bounded, separately tested work.
6. Introduce additive canonical Technical Market Engine names while retaining Oracle compatibility aliases.
7. **PERSONAL ORACLE BEHAVIORAL & COACHING LAYER** — complete: observable behavior only, immutable structured enrichments, threshold-gated comparisons/coaching/scorecards/trends, no psychology or execution authority.
8. **AEGIS DECISION FOUNDATION** — complete: deterministic final advisory orchestration, absolute Risk Authorization veto, no execution permission, KRONOS ALPHA direct weight 0%, fail-closed strategy eligibility, and bounded decision audit.
9. **ORDER & FILL LEDGER FOUNDATION** — complete at audit-only scope.
10. **REAL-MARKET PAPER TRADING ACTIVATION** — complete at readiness scope.
11. **OPEN-MARKET PAPER FORWARD VALIDATION** — next; do not begin without explicit authorization.
12. Add broker reconciliation only through a separately authorized milestone.
13. Consider controlled live validation only after all safety gates are complete and explicit authorization is granted.

This sequence does not authorize implementation of any later milestone during the responsibility-freeze task.
