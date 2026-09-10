# CITADEL OS — Architecture Decision Records

## ADR-035 — Development evidence collection is a parallel paper-only system

Decision: CITADEL exposes frozen Production Mode and an isolated Development Mode. The development runtime owns separate strategy, weighted policy, Risk instance, execution engine, Paper State, ledgers, runtime, and forensic evidence. The browser toggle selects a read projection only and never mutates backend mode.

Reason: statistical improvement requires more naturally occurring paper evidence without weakening or contaminating production policy. Isolation permits a relaxed development profile and weighted optional evidence while preserving every production ownership boundary.

Boundary: Production AEGIS scoring, Production Risk, Production Paper Execution, strategy logic, models, broker safety, probabilities, and live-trading protection remain unchanged. Development evidence cannot be promoted automatically. Kill Switch, closed-candle truth, market freshness, live-trading state, Development Paper State health, and Development Risk remain hard vetoes.

## ADR-034 — Candle decisions require immutable forensic envelopes and read-only replay

Decision: future production closed-candle evaluations persist one idempotent, hash-chained decision envelope that copies authoritative module outputs, rejection evidence, contract observations, Risk/Paper status, timestamps, and lineage. Replay reads these envelopes and existing forecast ledgers without invoking production engines or mutating state.

Reason: live-session audits proved that bounded projection/lifecycle ledgers can lose detailed historical rejection evidence. Permanent forensics must be independent of dashboard traffic and must not create a second calculation or authorization authority.

Boundary: evidence-write failures cannot change a decision. Missing historical envelopes, option candles, model lifecycle timestamps, or Risk evaluations remain explicitly unavailable. No diagnostic calculation may replace KRONOS, CHRONOS, AEGIS, Risk, Paper, or broker ownership.

These accepted decisions apply to the production repository. Every ADR listed here is **Accepted** unless explicitly superseded by a later ADR.

## ADR-033 — Real Dhan data may drive lifecycle-owned paper execution only

**Decision:** A backend-lifecycle `RealMarketPaperOrchestrator` may evaluate the unchanged registered strategy once per unique canonical closed NIFTY five-minute candle, then require cached/current ARGUS evidence, AEGIS APPROVE, dynamic Dhan contract/lot metadata, and a separate fail-closed `PaperRiskAuthorization` before creating a paper-only intent. Frontend GET polling cannot invoke it.

**Execution:** Simulated fills use only observed Dhan ask/bid/LTP with explicit provenance. Complete entry fills apply exactly once to authoritative Paper State through the Order & Fill Ledger; partial entry fills remain unapplied until the full one-lot quantity completes. Positions are long CE/PE, while the existing strategy's NIFTY stop/target remain underlying triggers.

**Limits:** NIFTY options, one dynamic lot, one open position, at most two entries/trades per day, no averaging, pyramiding, overnight permission, or entry after 15:15 IST. Mandatory square-off begins at 15:20. Missing/corrupt state, stale data, absent lot/contract, AEGIS non-approval, active/unknown kill switch, or risk excess denies entry.

**Safety:** Broker `RiskAuthorizationService` remains unchanged and denies while live trading is false. Paper authorization never grants broker permission. No order/tradebook/position API is called and `live_trading_enabled=false` remains mandatory.

**Reason:** Paper forward validation requires real market inputs and authoritative accounting without weakening the proven broker boundary or allowing browser polling to create side effects.

## ADR-032 — Order and fill evidence is one audit-only append ledger

**Decision:** `OrderFillLedgerService` owns schema-v1 immutable `OrderIntent`, append-only `OrderEvent`, and immutable observed `FillEvent` evidence in one atomic corruption-aware runtime document. Missing state is a healthy empty ledger; corrupt/schema-invalid state fails closed and is never repaired by a read. Exact replay is idempotent and conflicting identity reuse fails.

**Safety:** This foundation has no broker submission, execution, live-order, automatic-fill, or Paper State application method. Risk ALLOW, INACTIVE kill switch, AEGIS APPROVE/APPROVE_REDUCED, and an open session are required provenance gates before an intent can be recorded as authorized; they do not cause execution. Live trading remains false.

**Accounting:** Quantities are integers with optional lot consistency; monetary arithmetic is Decimal; weighted average fills and signed slippage retain reference provenance. Costs are versioned/itemized and explicitly estimated until broker reconciliation establishes actual values.

**Exposure:** All `/v1/orders*` and `/v1/fills*` routes are GET-only, bounded, and sanitized. The dashboard panel is read-only and always reports execution/broker/live safety state.

**Reason:** Future paper execution and eventual broker reconciliation require durable, auditable evidence without introducing an execution path or conflating order memory with authoritative Paper State.

**Limit:** Locking is process-local. No broker reconciliation, fill ingestion, actual statutory cost verification, automatic Paper application, or live execution exists.

## ADR-001 — Production and research repositories remain separate

**Decision:** `/Users/ayushmudgal/Developer/CitadelOS` is production. `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` is research and must not be edited, imported, or treated as production evidence during CITADEL OS milestones.

**Reason:** Experimental optimization work needs a different risk, data, and validation lifecycle.

## ADR-002 — Live trading is disabled by default

**Decision:** Production configuration remains in paper mode with `live_trading_enabled: false`. No milestone may enable live trading unless explicitly authorized after risk gates and reconciliation exist.

**Reason:** Read-only market intelligence and paper testing must never create accidental broker mutations.

## ADR-003 — Broker mutations are guarded at the transport boundary

**Decision:** `DhanClient` reloads settings at mutation time and blocks non-read-only requests before network I/O when live trading is not enabled. Missing or malformed configuration fails closed.

**Reason:** A central low-level guard protects against mistakes in higher layers and future callers.

## ADR-004 — Read-only Dhan POST exceptions are explicit

**Decision:** Only recognized Dhan market-data POST endpoints—option chain, expiry list, market feed, and charts—may bypass the mutation guard. Generic POST and PUT/PATCH/DELETE calls remain guarded.

**Reason:** Dhan uses POST for some reads; allowlisting exact read semantics avoids disabling useful data without opening order paths.

## ADR-005 — Candle identity is symbol plus IST time bucket

**Decision:** Normalize timestamps to `Asia/Kolkata`, keep one candle per symbol/time bucket, update same-bucket OHLC, append a new bucket once, and ignore stale updates.

**Reason:** Dashboard polling must not masquerade as market candles or corrupt indicators.

## ADR-006 — Higher timeframes use timestamp aggregation

**Decision:** Build 5m/15m and later aggregations from timestamp buckets rather than fixed row counts.

**Reason:** Row-count aggregation is invalid when input cadence is irregular or deduplicated.

## ADR-007 — ARGUS is read-only decision support

**Decision:** ARGUS may retrieve and classify option-chain evidence but must not expose order, entry, stop-loss, target, or execution controls.

**Reason:** Options intelligence is not sufficient authorization for a broker mutation.

## ADR-008 — Day and intraday option deltas are distinct

**Decision:** Day deltas compare with Dhan previous-day values; intraday deltas compare with the first valid persisted session baseline. Compatibility aliases may remain but semantics must be explicit.

**Reason:** Overnight positioning and current-session behavior answer different questions.

## ADR-009 — ARGUS baselines are durable and fail visibly

**Decision:** Key baselines by date, symbol, expiry, strike, and side; create only in a valid weekday session; write atomically; never silently replace corrupt state.

**Reason:** A reset baseline can invert or erase intraday evidence while appearing valid.

## ADR-010 — ARGUS classifications and confidence are deterministic

**Decision:** Use transparent price/OI relationships, neutral thresholds, evidence coverage, and documented dominance formulas. Missing evidence produces insufficient/unavailable states, never invented confidence.

**Reason:** Users must be able to audit why a verdict exists and distinguish it from ML/AI prediction.

## ADR-011 — Supported ARGUS symbols are a validated allowlist

**Decision:** Production ARGUS supports `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, and `SENSEX`; expiry validity is broker/backend owned and strikes are never hardcoded.

**Reason:** Explicit validation prevents malformed broker calls while allowing real chain discovery.

## ADR-012 — Polling is three seconds with bounded broker load

**Decision:** Reuse a three-second frontend poll and short process-local backend caches/locks. Do not introduce WebSockets until a separate architecture milestone.

**Reason:** This cadence meets the MVP need while limiting duplicate broker requests.

## ADR-013 — Preserve last successful data during failures

**Decision:** Each widget retains stale data on transient failure and separately reports loading, timeout, disconnected, cached, stale, or closed state. Hidden tabs pause/abort polling and resume safely.

**Reason:** Replacing truth with zeros or empty cards during a disconnect is misleading and operationally disruptive.

## ADR-014 — Dashboard V1.1 visual state is frozen

**Decision:** Preserve the accepted premium dark institutional dashboard, section order, responsive behavior, and Vihaann dedication. Avoid expensive full-width backdrop composition. Backend-foundation milestones must not edit `page.tsx` or `globals.css`.

**Reason:** The current UI is accepted, and Safari stability was verified after targeted compositor reduction.

## ADR-015 — Capability labels must reflect implementation truth

**Decision:** Use only VERIFIED, PARTIAL, STUBBED, or NOT STARTED for backend maturity. Rule-based modules must not be presented as trained AI, paper state must not be called broker state, and preview data must not be called live.

**Reason:** Institutional tooling depends on provenance and honest uncertainty.

## ADR-016 — Runtime files and secrets stay out of documentation

**Decision:** Never print or copy `.env` values. Keep environment variants, logs, caches, virtual environments, and build outputs ignored. Already tracked secret/runtime files require an explicit remediation task rather than incidental deletion.

**Reason:** Documentation and unrelated milestones must not expand credential exposure or destroy user-owned runtime state.

## ADR-017 — Establish real dependency and pytest foundations before new production behavior

**Decision:** Establish **Dependency Manifest + Real Pytest Foundation** before new production behavior. The completed foundation declares dependencies, configures pytest, stabilizes discovery/imports, and runs safety/candle/ARGUS tests without changing runtime behavior.

**Reason:** Existing tests and assertion harnesses provided evidence, but the environment previously lacked a reproducible manifest and working pytest installation.

## ADR-018 — Every broker mutation requires centralized risk ALLOW

**Decision:** Every non-read-only mutation crossing `DhanClient._request` must receive an explicit ALLOW from `RiskAuthorizationService`. The service owns deterministic reason codes, typed limits, request validation, fresh-data checks, persistent kill-switch/daily state, duplicate reservation, limit enforcement, and non-secret audit decisions. Any unavailable or unexpected condition returns DENY.

**Reason:** A disabled-live boolean alone cannot authorize live risk. One transport-boundary decision prevents alternate callers from bypassing risk controls and preserves a provable zero-network path on DENY.

**Persistence:** `logs/risk_control_state.json` is the single atomic local control document. It is never silently repaired or reset. Kill-switch changes require actor and reason. Daily state resets only after a verified later IST trading date.

**Limit:** This decision does not enable live trading. Paper/execution counters were unified by ADR-019; cross-process locking remains absent and broker reconciliation remains future work.

## ADR-019 — Paper lifecycle and risk counters share one authoritative state

**Decision:** `PaperStateService` is the sole persisted owner of paper positions, closed trades, realized/unrealized P&L, daily counters, accepted request IDs, and lifecycle event IDs. `PaperExecution` is a compatibility facade, while CSV journal and Oracle feature files are derived outputs. `RiskAuthorizationService` consumes paper-state projections directly; kill-switch persistence remains independent.

**Reason:** Active trade JSON, journal summaries, in-memory managers, and risk counters previously represented overlapping truths. One atomic state prevents restart drift and caller-supplied counter overrides.

**P&L:** Long P&L is price difference multiplied by raw quantity. SELL/SHORT compatibility reverses direction. Brokerage and slippage are excluded. Lot count is derived only when an actual lot size is supplied.

**Persistence:** `logs/paper_state.json` uses schema version 1, atomic replacement, validation on every read, and verified IST trading-date rollover. Historical closed trades and open positions survive rollover; daily counters reset only when the date advances.

**Limit:** Locking is in-process, not multi-worker. Legacy journal imports have implicit raw quantity one and unavailable lot metadata because older rows did not store those fields. This decision does not enable live trading.

## ADR-020 — Frontend safety telemetry uses sanitized GET projections only

**Decision:** The dashboard may observe risk and paper state only through `/v1/risk/status` and `/v1/paper/status`. These routes whitelist non-secret fields, return null for unavailable metrics, and expose no activation, deactivation, order, or mutation capability. The frontend must reuse its existing polling/failure architecture and preserve stale values only with a visible stale label.

**Reason:** Direct browser access to runtime JSON or configuration would couple UI to persistence, risk secret leakage, and bypass backend validation. Separate read projections preserve one authoritative backend while keeping the dashboard operationally useful and non-mutating.

**Limit:** A missing kill-switch file appears as degraded/unknown rather than being initialized by a read. Read-only telemetry never repairs or mutates operational state.

## ADR-021 — Oracle assessments are deterministic reads of existing scanner snapshots

**Decision:** `OracleService` is the single authoritative current-market Oracle path. It may consume only the latest already-built `DashboardAPI` scanner snapshot through an injected read-only provider. Oracle reads must never refresh the scanner, call broker transport, authorize risk, mutate paper state, change the kill switch, or expose an execution action. Legacy Oracle feature/performance files remain derived historical analytics, not current signal truth.

**Decision contract:** Oracle returns typed symbol/timeframe, source and generation timestamps, freshness and health, bias, signal, bounded confidence, regime, reasons, input features, warnings, maturity, and source/fallback metadata. It uses existing accepted indicator weights and thresholds; every available decision is explainable by reason codes. `LONG`/`SHORT` requires complete live, trending, aligned evidence. Cached evidence is degraded and non-actionable, stale evidence is blocked, and missing/malformed evidence is unavailable without fabricated confidence.

**Reason:** Separating assessment from data acquisition and execution makes the service deterministic, offline-testable, and unable to create hidden network or trading side effects. Explicit freshness semantics prevent preserved data from appearing tradable.

**Limit:** Snapshot and fallback caches are process-local, the source timestamp is backend scan completion rather than an exchange tick, and trusted volume is unavailable in the current scanner contract. Oracle is not an LLM, a predictive guarantee, or an execution/risk authorization engine.

## ADR-022 — Module responsibilities and original product vision are permanently frozen

**Decision:** The permanent production roles are:

- ARGUS is **Options Positioning Intelligence**.
- KRONOS is **Setup Quality & Timing Intelligence**.
- The current deterministic `OracleService` implementation is the **Technical Market Engine**, exposed to users as **TECHNICAL INTELLIGENCE**.
- ATHENA is **Risk & Capital Intelligence**.
- HERMES is **News & Event Intelligence**.
- The canonical ORACLE product role is **Personal AI Trading Coach**, optimizing Ayush rather than predicting the market.
- AEGIS is the **Final Decision Controller**.
- Risk Authorization is the **Absolute Hard Safety Gate** and may veto any AEGIS approval.

**Compatibility:** ADR-021's implemented assessment behavior remains accepted, but its product classification is clarified by this ADR: `OracleService`, its types/files, and `GET /v1/oracle/status`, `GET /v1/oracle/assessment/{symbol}`, and `GET /v1/oracle/reasoning` are retained as Technical Market Engine compatibility aliases. No destructive rename, route removal, data migration, or consumer break is authorized. Historical Oracle feature/logger/reader names also remain until a separately approved migration. The current technical dashboard section uses the preferred label **TECHNICAL INTELLIGENCE** without changing its API, polling, layout, styling, or behavior.

**Boundaries:** Specialist modules own only their typed advisory evidence. ARGUS cannot approve trades; KRONOS cannot own OI/news/personal coaching; the Technical Market Engine cannot become Personal ORACLE; ATHENA cannot become the final controller; HERMES begins read-only; Personal ORACLE cannot place orders; and AEGIS cannot dispatch directly to broker transport. Risk Authorization remains the only hard mutation ALLOW/DENY boundary and fails closed.

**Starting soft influences:** Future AEGIS design begins conceptually with Technical Market Engine 25%, KRONOS 25%, ARGUS 20%, Personal ORACLE 15%, HERMES 10%, and ATHENA 5%. These are product-design influences only—not implemented trading weights, optimized parameters, or authorization thresholds.

**Hard vetoes:** Kill switch active, Risk Authorization `DENY`, stale/unavailable critical data, strategy ineligibility, duplicate request, a configured blocked high-impact event after Hermes exists, and `live_trading_enabled=false` on a live path override every soft influence.

**Reason:** Earlier naming allowed the technical Oracle implementation, historical analytics files, aspirational AI labels, and final-decision responsibilities to overlap conceptually. Permanent ownership prevents module drift while preserving all verified runtime and safety work.

**Authoritative detail:** `docs/CITADEL_MODULE_ARCHITECTURE.md` defines inputs, outputs, dependencies, ownership, compatibility, no-overlap boundaries, flow, and migration sequence for every frozen module.

## ADR-023 — ATHENA is advisory intelligence over authoritative read projections

**Decision:** `AthenaService` is the one deterministic ATHENA assessment path. It consumes sanitized read-only risk and authoritative-paper projections, owns no operational state, and returns risk condition, recommendation, utilization/headroom, a bounded 0.0–1.0 advisory size multiplier, reasons, warnings, missing inputs, maturity, and source metadata. `GET /v1/athena/status` is canonical; `GET /v1/athena/wheel` remains a compatibility projection over the same service.

**Recommendation policy:** ATHENA evaluates the highest utilization among daily loss, daily trade count, consecutive losses, and open-position capacity. Below 50% is `SAFE/CONTINUE`; 50–79.99% is `CAUTION/REDUCE`; 80–99.99% is `HIGH_RISK/PAUSE`; a reached hard limit is `STOP`. Active kill switch, an exposed Risk Authorization `DENY`, or unavailable/malformed required state also maps to a fail-safe stop. ATHENA may be more conservative than authorization but can never turn `DENY` into permission.

**Sizing:** The multiplier is relative advisory guidance only. It is never translated into broker quantity/lots, never assumes lot size, never changes configuration, and never overrides raw-quantity, per-trade-risk, open-position, or other Risk Authorization limits.

**Source truth:** Current drawdown is the negative portion of authoritative total daily paper P&L. Exposure percentage uses open-position capacity and must be labeled as a non-rupee proxy. Existing `PaperState.cash_balance` may be exposed as available capital when present. Blocked capital, current equity, rupee/margin exposure, weekly/monthly risk usage, and a dedicated maximum-drawdown limit remain null until authoritative sources exist.

**Safety:** ATHENA has no broker, order, execution, strategy, kill-switch mutation, or paper-position mutation dependency. Risk Authorization remains the absolute hard veto immediately before any broker mutation. Live trading remains disabled.

**Reason:** A separate advisory layer makes risk utilization understandable without duplicating state ownership or weakening the proven fail-closed safety boundary.

**Limit:** The latest authorization projection does not identify request applicability or expiry, so ATHENA conservatively treats an exposed latest `DENY` as blocking. Position-capacity utilization is not capital exposure, and full capital-aware sizing remains unavailable.

## ADR-024 — HERMES separates explicit provider refresh from cached advisory reads

**Decision:** HERMES is a provider-agnostic normalized event engine. Providers return typed `HermesInput` records for scheduled economic events, market news, social catalysts, or official announcements. `HermesService.refresh_from_provider()` is the only ingestion boundary. `GET /v1/hermes/status`, `GET /v1/hermes/events`, and frontend polling read only the bounded in-memory cache and never invoke provider refresh or network activity.

**Production state:** No external provider is configured by this foundation milestone. Production therefore returns `UNAVAILABLE/UNKNOWN/WAIT` with `EXTERNAL_PROVIDER_NOT_CONFIGURED`. Offline in-memory and fixture providers exist for deterministic testing; their mode is explicit, and fixture/development data must never receive a live badge.

**Normalization:** HERMES retains only bounded typed fields, safe provenance, sanitized query-free URLs, event/source identifiers when safe, timing/freshness, affected scope, reasons, warnings, and duplicate/conflict traceability. It never retains unbounded raw payloads, headers, tokens, or credentials. Sentiment remains `UNKNOWN` unless supplied as normalized evidence.

**Source confidence:** One centralized policy maps official government/central-bank/exchange/regulator/authenticated publication to high, approved newswire/provider to medium, secondary/unverified social to low, and insufficient metadata to unknown. Low/unknown-confidence input cannot alone retain critical impact. Source-confidence labels are deterministic policy categories, not independent verification of truth.

**Time and risk:** Central defaults are 30 minutes imminent, 15 minutes live-after-event, 120 minutes recent, six hours relevant, and five minutes provider-snapshot freshness. No/low evidence may be normal; medium/non-imminent high is caution; imminent high, breaking high, or high-confidence conflict is wait; imminent/live critical is avoid-new-trades. Missing, malformed, or stale provider state can never default to normal.

**Duplicates/conflicts:** Explicit taxonomy/date identity controls recognized scheduled events; otherwise normalized headline/time identity is used. Duplicate groups retain bounded source names. The highest-confidence source controls representative timing, while conflicting sentiment/timing/impact remains marked and warned rather than silently discarded.

**Safety:** HERMES is read-only and advisory. It has no Dhan, broker, Risk Authorization, kill-switch, Paper State, strategy, technical-signal, or execution dependency. `AVOID_NEW_TRADES` does not directly block execution; future AEGIS integration requires a separate decision contract.

**Reason:** Separating ingestion from cached reads prevents three-second frontend polling from amplifying provider/network load and makes fixture, stale, unavailable, and future live-provider provenance operationally distinguishable.

**Limit:** Cache is process-local and non-durable; no live provider, session calendar, source-coverage SLA, semantic entity resolution, or independent fact verification exists yet.

## ADR-025 — KRONOS CORE and KRONOS ALPHA are distinct, shadow-only responsibilities

**Decision:** **KRONOS CORE** remains CITADEL's deterministic setup-quality and timing intelligence. **KRONOS ALPHA** is reserved for a future local adapter to the official pretrained `NeoQuasar/Kronos-small` model and official `NeoQuasar/Kronos-Tokenizer-base`. KRONOS ALPHA supplements and never replaces KRONOS CORE.

**Boundary:** KRONOS ALPHA must run in a dedicated dependency/runtime boundary, keep weights and caches outside Git, publish only a sanitized bounded forecast cache, and expose cached GET-only telemetry. It has no broker, execution, paper-state mutation, risk mutation, HERMES ingestion, or direct AEGIS dependency. Frontend polling may never trigger model loading, download, or inference.

**Safety:** Its mode is permanently `SHADOW` for the initial integration, with execution, AEGIS, and Risk Authorization influence all exactly 0%. No fine-tuning is authorized by the installation milestone. Derived probabilities and uncertainty must come from valid sampled paths with documented formulas; unavailable inference can never be replaced by fixture or fabricated values.

**Historical gate and resumed result:** The first attempt stopped because the host volume had about 1.4 GiB free and only Python 3.14. After capacity exceeded the required 10 GB gate, the resumed milestone installed managed Python 3.11 and PyTorch in `.venv-kronos-alpha`, pinned official weights outside Git, verified real MPS inference plus CPU fallback, and added the isolated runner, bounded cache, cached GET routes, and additive shadow panel. Production remains truthfully unavailable until authoritative closed-candle history exists. See `docs/KRONOS_ALPHA.md` and the preserved blocked checkpoint plus V2 completion checkpoint.

## ADR-026 — NSE session truth and KRONOS ALPHA inference are lifecycle-owned

**Decision:** `NSESessionCalendar` is the only production market-open authority. It uses Asia/Kolkata, an explicitly verified/versioned NSE CM holiday document, weekend closure, configured special-session overrides, and an injectable clock. Missing calendar certainty fails `UNKNOWN/CLOSED`. Connectivity, cached prices, snapshots, and local clock hour alone can never imply OPEN.

**Data and scheduling:** KRONOS ALPHA uses only NIFTY underlying index `IDX_I / securityId 13 / INDEX / 5m` through `DhanMarketDataClient`, a narrow read-only adapter. `KronosAlphaScheduler` backfills/persists validated closed candles and runs at most one isolated model job per unique confirmed candle close after a ten-second grace period during canonical OPEN/SPECIAL_SESSION. Frontend GET polling cannot backfill, infer, download, or control the scheduler.

**Forecast semantics:** Twenty genuine sampled paths feed deterministic direction probabilities, direction-specific persistence/reversal, range/volatility, disagreement uncertainty, CE/PE OPTION-BUYING QUALITY, and direction-neutral Forecast Quality. These are CITADEL-derived advisory metrics, not model-native confidence, win probability, orders, or execution permission.

**Persistence:** Forecast cache, candle cache, and bounded history/evaluation ledger use local atomic JSON. Original forecasts remain immutable; realization records append only after the complete 12-candle horizon. Small samples retain explicit calibration warnings.

**Safety:** KRONOS ALPHA remains SHADOW with execution, AEGIS, and Risk Authorization influence 0%. It has no order, Paper State mutation, risk mutation, HERMES/ARGUS/ATHENA logic, or trading-control route. KRONOS CORE remains unchanged.

## ADR-027 — Personal ORACLE owns immutable personal-trade evidence, not execution

**Decision:** Personal ORACLE owns one versioned event per authoritative completed Paper State close in a separate bounded atomic append-only ledger. Original facts are immutable; later facts use separate idempotent enrichment records. Derived journal/legacy Oracle CSVs are not authoritative.

**No look-ahead:** Entry intelligence is eligible only when timestamped at or before entry. Historical backfill never attaches current Technical, ARGUS, KRONOS, ATHENA, or HERMES snapshots. Missing fields remain null/unknown.

**Evidence:** Segments require 10 samples; maturity is preliminary at 20, stable at 50, and mature at 100. Findings are deterministic associations with evidence and limitations, never causal claims. Recommendations are advisory and default to insufficient evidence.

**Privacy and safety:** Raw/private notes, secrets, credentials, headers, and unbounded payloads are forbidden. A bounded opaque notes reference is allowed. Personal ORACLE has no mutation API and 0% AEGIS/execution influence.

## ADR-028 — Personal ORACLE coaching is observable, sample-gated, and non-authoritative

**Decision:** Behavioral observations come only from persisted source fields or separately typed user review enrichments. Fixed tri-state/timing vocabularies and fixed mistake tags prevent free-form psychological interpretation. Original events remain immutable and no enrichment write route/UI is exposed.

**Rules:** Timing, cooldown, sequence, size, and module-alignment classifications require their explicit inputs. Unknown inputs produce unknown classifications. Current snapshots never reconstruct historical behavior. Thresholds are 10 per segment/category/window, 20 preliminary coaching, 50 stable, and 100 mature.

**Outputs:** Findings provide comparison samples, deterministic metrics/effect size, maturity/confidence, limitations, dates, and association-only language. Recommendations are bounded to three and carry no execution, risk override, or strategy mutation authority. Category scores never form a personality/overall score. Trend labels require two comparable 10-trade windows.

**Boundary:** No emotion diagnosis, unrestricted notes, broker/paper/risk mutation, model/provider call, KRONOS inference, strategy change, or AEGIS influence exists. Personal ORACLE remains advisory and frontend read-only.

## ADR-029 — AEGIS is advisory orchestration beneath the absolute Risk Authorization veto

**Decision:** AEGIS deterministically orchestrates existing cached/read-only specialist evidence into APPROVE, APPROVE_REDUCED, WAIT, REJECT, or BLOCK. It owns no market/provider refresh, operational state, strategy parameters, or execution authority. Every output is advisory-only with execution permission false.

**Veto order:** Hard gates run before scoring. Kill switch, Risk Authorization DENY, disabled live path, duplicate request, and severe critical-state failure BLOCK. No score or module can override BLOCK or Risk Authorization. Unknown critical state fails closed.

**Scoring:** Frozen weights are Technical 25, KRONOS CORE 25, ARGUS 20, Personal ORACLE 15, HERMES 10, and ATHENA 5. KRONOS ALPHA direct weight is 0 and remains SHADOW context only. Optional unavailable inputs reduce coverage; mandatory unavailable inputs WAIT. Staleness/opposition/conflicts use documented deterministic penalties.

**Sizing and strategy:** AEGIS may reduce ATHENA size but never increase it. Simple Pullback compatibility is explicit; unknown strategy fails closed. No strategy optimization is authorized.

**Persistence and API:** Decisions use semantic fingerprints in a bounded atomic duplicate-safe audit ledger. Six routes are GET-only. Polling cannot trigger broker calls, Paper/risk mutation, KRONOS inference, HERMES refresh, or ARGUS provider refresh.

## ADR-030 — One persisted kill switch and read-only market-readiness validation

**Decision:** `RiskControlStore` remains the sole kill-switch authority. Its existing atomic schema-v1 document is projected as ACTIVE, INACTIVE, UNKNOWN, or CORRUPT. No frontend/environment/AEGIS duplicate source is permitted. The audited store was genuinely absent and was initialized once, under explicit policy, as INACTIVE with reason `INITIALIZED_SAFE_DEFAULT`; valid state is never overwritten by initialization.

**Fail closed:** Missing projects UNKNOWN; unreadable or schema-invalid projects CORRUPT. Both deny Risk Authorization and block AEGIS with distinct reasons. INACTIVE merely continues other gates. The persisted production state survives a new store instance and exposes sanitized health through GET-only status routes.

**Readiness:** Open-market readiness uses canonical session truth and existing cached/read-only projections. A static AEGIS readiness contract avoids decision-ledger writes. It never refreshes ARGUS/HERMES, runs KRONOS inference, calls a broker, or mutates Paper/Risk state. The next-session plan derives timestamps but marks every step unobserved.

**Frontend:** Risk and AEGIS panels show the same state, persistence health, readiness, and plan without controls. Market closed remains WAIT rather than a forced approval or false green state.

## ADR-031 — CHRONOS-2 is an isolated zero-influence multivariate challenger

**Decision:** Official `amazon/chronos-2` revision `29ec3766d36d6f73f0696f85560a422f50e8498c` runs only through `chronos-forecasting==2.3.1` in `.venv-chronos-2`. Weights remain outside Git. CHRONOS-2 supplements but never replaces KRONOS ALPHA.

**Inputs:** The scheduler reuses the canonical persisted closed NIFTY 5-minute candle cache and NSE calendar. It adds no provider poll. OHLCV plus timestamp-derived realized volatility and normalized ATR form the initial genuine multivariate frame. Current ARGUS state cannot become historical model data without a timestamped history.

**Output:** Official model output is limited to multi-step quantiles. Directional Confidence, persistence, reversal risk, Forecast Quality, and independent CE/PE Option-Buying Quality are explicitly CITADEL-derived, inspectable, uncalibrated SHADOW heuristics.

**Authority:** `shadow_mode=true`, `advisory_only=true`, execution influence 0, direct AEGIS influence 0. GET routes are cache-only and cannot infer, refresh, download, or mutate. Original forecasts are immutable and evaluated only after the complete horizon.
