# CITADEL OS — Engineering Bible

Status: permanent engineering source of truth  
Release boundary: Version 2, real-data paper-trading edition  
Updated: 2026-07-13

## 0. Runtime modes

CITADEL has two explicit paper-only runtime modes. They are separate systems, not settings applied to one mutable engine.

### Production Mode

Production Mode is the frozen Version 2 institutional pipeline documented below. It retains the original `SimplePullbackStrategy`, production AEGIS policy, production Risk Authorization, production Paper Execution, production Paper State, and production ledgers. Development code cannot alter its state, thresholds, decisions, files, or runtime lifecycle.

### Development Mode

Development Mode is a parallel evidence-collection system under `src/development`. It continuously observes the same authoritative closed NIFTY five-minute candle cache and cached module projections, but owns separate strategy, weighted policy, Risk instance, execution engine, runtime, Paper State, order/fill ledger, and hash-chained evidence journal.

Development Mode invariants:

- Paper only; `live_trading_enabled=false`.
- No broker submission surface.
- One NIFTY option lot and one open position.
- No averaging, pyramiding, or overnight holding.
- Authoritative Kill Switch, market session, closed-candle state, market freshness, isolated Paper State health, and Development Risk remain hard vetoes.
- Missing optional HERMES, ATHENA, ORACLE, or shadow-model evidence reduces score/coverage but does not independently freeze the engine.
- The dashboard toggle is stored only in browser session storage. It selects a projection and never starts, stops, or mutates a backend runtime.
- Development outcomes can inform later research proposals but cannot change production automatically.

The development stores are:

- `logs/development_paper_runtime.json`
- `logs/development_paper_state.json`
- `logs/development_order_fill_ledger.json`
- `logs/development_decision_evidence.jsonl`

They must never be substituted for production state.

## 0.1 Development weighted decision system

The development decision engine uses a fixed, versioned evidence score:

| Evidence | Weight |
|---|---:|
| Technical Intelligence | 30 |
| KRONOS CORE | 20 |
| ARGUS | 15 |
| KRONOS ALPHA | 10 |
| CHRONOS-2 | 10 |
| ATHENA | 5 |
| Personal ORACLE | 5 |
| HERMES | 5 |

Directional modules receive an aligned, neutral, opposed, or unavailable vote based only on their authoritative output and confidence. Categorical modules use a documented development-only evidence mapping. Missing evidence contributes zero rather than being normalized away, so absence lowers both score and coverage. The development allow threshold is 60/100. This threshold is not a production AEGIS threshold and has no production effect.

The weighted decision never overrides Development Risk. An `ALLOW` only permits contract resolution and a subsequent isolated Risk evaluation. Risk `DENY` remains final.

## 0.2 Development strategy profile

`SimplePullbackDevelopment` is an isolated clone. It retains KRONOS direction, EMA21/EMA38 inputs, EMA21 stop, and 2R target. Its sole relaxation is that close must be beyond both EMAs but EMA21 and EMA38 do not have to be ordered relative to each other. It adds no indicator, crossover, Pine logic, forced signal, quota, or synthetic trade.

The desired 5–20 trades in an active session is an evidence-collection objective, not a guarantee or quota. Market conditions, Development Risk, one-position ownership, stops/targets, and safety vetoes may produce fewer trades.

## 1. Vision

CITADEL OS is a truth-preserving, fail-closed institutional decision system for observing real Indian market data, evaluating a frozen trading pipeline, and executing only simulated paper orders. Its purpose is disciplined evidence collection and decision quality—not automatic live brokerage execution.

The governing principles are safety before availability, evidence before inference, immutable history before mutable presentation, and explicit unavailability before fabricated certainty.

## 2. Production architecture

The production repository is `/Users/ayushmudgal/Developer/CitadelOS`. The separate research repository `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` is never a production dependency and must not be modified from this project.

The active Version 2 paper scope is:

- Real Dhan market data.
- NIFTY underlying candles.
- Closed five-minute candles only.
- Frozen `SimplePullbackStrategy` only.
- Nearest-expiry ATM NIFTY option resolution after a directional strategy signal.
- One dynamically resolved lot, one open position, at most two paper trades per day.
- AEGIS advisory decision followed by absolute Risk Authorization.
- Simulated fills, authoritative Paper State, and immutable order/fill evidence.
- `live_trading_enabled=false`, no broker submission, no frontend execution.

```text
Real closed candle
  → Technical context
  → KRONOS CORE
  → Simple Pullback
  → ARGUS option-chain evidence
  → AEGIS advisory decision
  → Risk Authorization absolute veto
  → Paper order intent
  → Simulated fill
  → Order & Fill Ledger
  → Paper State / position / P&L
  → GET-only V2 projection
  → dashboard, history, evaluation, analytics
```

KRONOS ALPHA and CHRONOS-2 remain shadow forecasting systems with zero execution influence. ATHENA, HERMES, Personal ORACLE, and other contextual engines retain their documented advisory roles. No diagnostic or replay component may alter this ownership.

## 3. Permanent module responsibilities

| Module | Permanent responsibility | Execution influence | Safety boundary |
|---|---|---:|---|
| Technical Intelligence | Deterministic indicators and observable market structure | Strategy input | Closed authoritative candles only |
| ARGUS | Option-chain positioning, OI baselines, walls, regimes, contract evidence | AEGIS evidence and contract input | Read-only Dhan data; no orders |
| KRONOS CORE | Deterministic setup quality, regime, bias, and timing | Strategy and AEGIS evidence | Frozen calculations |
| KRONOS ALPHA | Genuine local probabilistic shadow forecast | 0% | No execution or direct AEGIS weight |
| CHRONOS-2 | Genuine isolated challenger forecast | 0% | Shadow only; no broker path |
| ATHENA | Risk/capital intelligence projection | Advisory sizing evidence | Cannot authorize execution |
| HERMES | News/event risk when an authoritative provider exists | AEGIS evidence | Unconfigured provider remains unavailable |
| Personal ORACLE | Immutable trade evidence, behavioral findings, coaching | Advisory only | No diagnosis and no execution mutation |
| AEGIS | Final multi-module advisory decision | Required advisory gate | Never grants broker permission |
| Risk Authorization | Absolute execution veto | Final paper authorization | Fails closed; kill switch authoritative |
| Kill Switch | Persisted emergency state | Absolute veto | One authoritative store |
| Order & Fill Ledger | Immutable order intent, event, fill, and cost evidence | Audit only | No broker transport |
| Paper Execution | Paper intent/fill sequencing | Paper only | No submission method |
| Paper State | Authoritative paper positions, counters, and P&L | Paper only | Idempotent mutation ownership |
| V2 Dashboard | One isolated read projection | None | GET-only, one poll, no side effects |
| Forensics | Immutable observation and replay | None | Write failures cannot change decisions |

## 4. Forecast architecture

KRONOS ALPHA and CHRONOS-2 use isolated local model environments and persisted forecast ledgers. A forecast publication is authoritative only when stored with its forecast ID, input origin, generation timestamp, model revision, input fingerprint, horizon, and raw projected values. Realization evaluation occurs only after the complete horizon is available.

Forecast truth rules:

- Never run inference from a GET route.
- Never backfill a missing forecast with a derived frontend value.
- Never compare models unless symbol, timeframe, origin, and horizon are aligned.
- Never declare calibration or trading edge from an insufficient sample.
- Preserve raw model units; projections may format but not reinterpret them.
- Shadow results have zero execution and zero direct AEGIS influence unless a future, separately approved milestone changes that boundary.

## 5. Scheduler architecture

Lifecycle-owned schedulers start with FastAPI, follow the NSE calendar, consume only completed candles, suppress duplicate candle origins, and remain waiting outside valid sessions. Frontend polling cannot wake schedulers or models.

The paper orchestrator independently locks each tick, rejects incomplete/future candles, persists `last_evaluated_candle`, evaluates at most one new origin, and fails closed on corrupt runtime or Paper State. Diagnostic evidence records orchestrator start, stop, accepted candle origins, decision envelopes, and paper-position evaluations. It does not modify scheduler timing.

## 6. Decision evidence and data lineage

`src/forensics` provides the permanent forensic boundary.

Each future evaluated closed candle can produce one idempotent `CANDLE_DECISION_ENVELOPE` in `logs/decision_evidence.jsonl`. Records are append-only JSONL, protected by file locking, linked through SHA-256 hashes, and independently verifiable. Each envelope stores:

- Exact closed candle and source metadata.
- Technical indicators and structure/liquidity/FVG/order-block/timeframe outputs.
- KRONOS CORE output and regime.
- Independent frozen Simple Pullback condition results.
- Strategy decision, confidence, levels, and reason.
- AEGIS input snapshot, component scores, weighted contributions, conflicts, hard gates, missing inputs, fingerprint, and decision.
- ARGUS snapshot and observed ATM/adjacent candidates when evaluated.
- Resolved selected contract when resolution succeeds.
- Risk decision or explicit `NOT_EVALUATED` readiness state.
- Paper execution result or explicit `NOT_EVALUATED` state.
- First rejecting module, ordered rejection chain, reason, missing evidence, and timestamp.
- Source timestamps, limitations, and final production state.

An evidence write is deliberately non-authoritative. Failure to write evidence is isolated and cannot convert WAIT to APPROVE, create an order, suppress a veto, or change a production return value.

## 7. Replay methodology

`OpportunityReplayEngine` reconstructs only persisted evidence. It never imports or invokes a strategy, model, AEGIS calculation, Risk authorization, Paper mutation, broker client, or scheduler.

Given a candle origin with an immutable envelope, replay returns Technical, KRONOS CORE, KRONOS ALPHA publication, CHRONOS-2 publication, ARGUS, ATHENA, ORACLE, HERMES, AEGIS, Risk, Paper, final decision, rejection diagnostics, and expected trade. Forecast publications are joined by exact candle origin from their existing authoritative ledgers.

MFE and MAE are calculated only when the caller supplies an explicit outcome end timestamp and authoritative future underlying candles exist. Option P&L, option MFE, and option MAE remain unavailable until timestamp-aligned option candle history exists. Missing envelopes return `NOT_AVAILABLE`; replay never silently recalculates historical decisions.

## 8. Shadow methodology

Shadow systems may observe production inputs and persist predictions but cannot authorize, size, route, fill, or mutate a trade. Their evaluation must be origin-aligned, horizon-matured, timestamped, and reported with sample size and limitations. A shadow lead/lag observation is descriptive and must never become a trading rule without a separate evidence and governance milestone.

## 9. Dashboard architecture and philosophy

The Next.js 16 TypeScript dashboard polls one aggregated `GET /v2/dashboard?symbol=NIFTY` request every three seconds. The backend isolates module failures and publishes health, readiness, timestamps, trace identity, and evidence linkage. Widgets display authoritative backend values only; unavailable values remain explicitly unavailable. No widget can execute a trade, refresh a provider, invoke inference, or mutate a ledger.

The visual language is a restrained dark institutional terminal. Information hierarchy may improve, but backend ownership, units, labels, polling, and decision semantics may not be changed by presentation work.

## 10. Coding standards

- Python 3.11 is the verified runtime; declarations retain Python 3.9 compatibility where existing production code permits.
- TypeScript remains strict and dependency additions require evidence.
- Use typed immutable contracts at module boundaries.
- Use atomic replacement for mutable state and append-only/hash-chained storage for audit evidence.
- Make idempotency explicit for every mutation and evidence append.
- Use aware timestamps and name the timezone or UTC conversion.
- Keep GET routes side-effect free.
- Never catch a safety exception and continue as approved.
- Never add a fallback that changes unavailable data into a tradable value.
- Tests must require no credentials, network, broker mutation, or live trading.
- Business logic must not be changed merely to satisfy a test.

## 11. Production safety rules

1. `live_trading_enabled` remains `false` unless a separately authorized future release changes it.
2. No production class exposes broker submission from the paper path.
3. Risk Authorization is an absolute veto and follows AEGIS.
4. Kill-switch uncertainty fails closed.
5. Only closed candles may be evaluated.
6. No synthetic candles, signals, confidence, fills, prices, P&L, or health states.
7. No averaging, pyramiding, overnight positions, or hidden quantity conversion.
8. Runtime ledgers, caches, credentials, tokens, model weights, and `.env` values are never copied into documentation or source archives.
9. The research repository remains separate.
10. Diagnostics and replay have zero execution influence.

## 12. Validation methodology

Validation proceeds in this order:

1. Recovery checkpoint and dirty-tree preservation.
2. Syntax and import validation.
3. Targeted deterministic tests.
4. Full credential-free safe backend suite.
5. Genuine-model tests in isolated offline environments only when model behavior changed or release verification requires them.
6. Frontend build and lint when frontend files changed.
7. Runtime HTTP and browser checks when runtime/UI changed.
8. Open-market forward validation without forced signals or manual inference.
9. Evidence-backed defect classification and a new checkpoint.

Market performance, forecast accuracy, and option-buying edge require multiple independent sessions and authoritative timestamp-aligned data. One session is evidence, not proof.

## 13. Audit history and major fixes

Completed engineering milestones include:

- Broker mutation safety and read-only Dhan exceptions.
- Candle identity, closed-candle integrity, and poll-safe data handling.
- Dependency manifests and real pytest foundation.
- Risk Authorization, persisted Kill Switch, and read-only safety projections.
- Single authoritative Paper State.
- ARGUS Phases 1, 2, 3, and 3.1.
- Technical/ORACLE service completion and frontend exposure.
- Permanent module-responsibility freeze.
- ATHENA and HERMES advisory foundations.
- Personal ORACLE evidence, behavior, and coaching layers.
- AEGIS deterministic advisory foundation.
- Genuine KRONOS ALPHA and CHRONOS-2 shadow installations.
- Open-market readiness and next-session plan.
- Order & Fill Ledger Foundation.
- Real-market paper orchestrator and Paper Execution Engine.
- Version 2 aggregated dashboard and truth projection.
- Production stabilization: GET-idempotent AEGIS projections, truthful unconfigured HERMES semantics, CHRONOS maturity handling, Paper mutation timestamps, and dashboard truth corrections.
- Institutional decision forensics and the permanent evidence/replay foundation.

Detailed immutable milestones remain in `docs/checkpoints/` and architecture decisions in `docs/DECISIONS.md`.

## 14. Current readiness

Engineering readiness for continued paper validation is high but not equivalent to trading readiness. The previously verified engineering score is 90/100 for paper validation. No authoritative trading-intelligence score exists; assigning one would fabricate precision.

Production-ready boundaries:

- Safety controls, paper-only execution, ledgers, Paper State, GET-only APIs, V2 aggregation, frozen strategy pipeline, and offline tests.

Experimental or evidence-collecting boundaries:

- KRONOS ALPHA and CHRONOS-2 predictive value.
- Forecast calibration and lead/lag usefulness.
- Personal ORACLE maturity.
- Open-market option-buying edge.

Unavailable or disabled boundaries:

- Live broker execution.
- Configured HERMES external provider.
- Authoritative current ATHENA cash/equity/exposure and weekly/monthly usage.
- Timestamp-aligned option candle archive for rejected opportunities.

## 15. Known limitations and technical debt

- Evidence envelopes begin after this foundation is deployed; historical decisions without envelopes cannot be perfectly reconstructed.
- Timestamp-aligned option candles are not available. ARGUS option-chain snapshots are not candle history.
- ATM+1 and ITM candidates can be observed from ARGUS, but only the selected ATM contract is currently resolved through the instrument master. Adding extra resolution calls would change provider/runtime load and was intentionally not done.
- CHRONOS-2 is not an AEGIS input; exact lead/lag is available only when a matching persisted forecast can be joined by origin.
- Risk readiness after an upstream veto is recorded as `NOT_EVALUATED`; duplicating Risk calculations would create a second authority.
- Model scheduler inference-start/inference-finish lifecycle is not retroactively available in every existing forecast record. Model code was intentionally untouched.
- The AEGIS decision ledger is bounded; permanent candle envelopes now preserve lifecycle evidence independently.
- HERMES remains unconfigured.
- ATHENA remains degraded when authoritative capital inputs are absent.
- Forecast samples remain preliminary and do not prove edge.
- FastAPI lifecycle still uses deprecated `on_event` hooks.
- `.env` is historically tracked by Git and requires separate secret rotation and history remediation; never print its contents.

## 16. Roadmap

### P0

- Run several paper-only open-market sessions and verify evidence-chain integrity after each session.
- Add an authoritative timestamp-aligned option-candle archive through a separately reviewed read-only provider design.
- Validate that every rejected actionable signal has one complete decision envelope.
- Forward-validate Development Mode isolation, weighted evidence, trade frequency, and complete trade forensics over multiple sessions.

### P1

- Add an instrument-master-resolved candidate service for ATM, ATM+1, and ITM only after provider-load and cache semantics are approved.
- Add passive lifecycle instrumentation to KRONOS ALPHA and CHRONOS-2 only through a dedicated no-math-change milestone.
- Configure and validate HERMES with an authoritative provider.
- Supply authoritative ATHENA capital and exposure inputs.
- Accumulate multi-session forecast and decision-quality evidence.
- Compare Production and Development decisions only from aligned candle origins. Pre-register metrics before evaluating alternative weights or entry strictness.

### P2

- Migrate FastAPI lifecycle hooks to lifespan without behavioral changes.
- Define retention, archival, signing, and external backup policy for forensic evidence.
- Profile V2 projection cost before introducing any shared cache.

## 17. Open research questions

- Does either shadow model demonstrate calibrated directional or range value across independent sessions?
- Does CHRONOS lead production eligibility reliably, or was the observed lead session-specific?
- Which predeclared option contract and horizon definitions best support honest edge evaluation?
- Can event risk be made complete and timely enough for AEGIS without introducing unavailable-provider false gates?
- What evidence threshold is required before any shadow signal may be proposed for policy review?
- How should option liquidity, spread, and timestamp alignment be incorporated without theoretical-price substitution?

No open question authorizes a production rule change.

## 18. Future optimization workflow

Development evidence may support future proposals only through this sequence:

1. Freeze the mode version, weights, strategy profile, and outcome definition before a session.
2. Collect several independent sessions without changing parameters mid-sample.
3. Verify hash-chain integrity, replay IDs, missing evidence, fills, exits, MFE, MAE, planned RR, realized R, and winner/loser labels.
4. Compare Development decisions against Production on identical candle origins.
5. Separate opportunity detection, policy acceptance, Risk authorization, execution, and option outcome.
6. Report sample size, uncertainty, regime distribution, and data gaps.
7. Propose one change at a time in research; never mutate production from the analysis.
8. Require explicit approval, deterministic tests, paper shadow validation, and a new production milestone before any production adoption.

## 19. Strategy Lab research environment

Strategy Lab is CITADEL's permanent third runtime plane. It is neither Production nor Development and has no authority over either mode. The reviewed PULLBACK MASTER package is registered but remains scheduler-gated as `PROVISIONAL_PENDING_PARITY_VALIDATION`; no signal, fill, or result is fabricated.

### Isolation and ownership

Every deployed strategy receives its own strategy adapter, daemon scheduler, lock/failure boundary, institutional paper account, Risk policy, order/fill state, positions, journal, replay, evidence, statistics, event stream, and logs under `logs/strategy_lab/runtimes/<strategy_id>/`. No Strategy Lab path is reused by Production or Development. The default execution path is the isolated `InstitutionalPaperTradingEngine` using only `PaperExecutionProvider`; broker submission and live trading are absent. If capital and limits are not explicitly configured in strategy metadata, actionable signals fail closed with `PAPER_RISK_POLICY_REQUIRED`.

### Institutional paper execution architecture

`ExecutionProvider` is the permanent provider boundary. OMS, positions, capital, statistics, replay, journal, and portfolio code depend only on this interface. The sole implementation is `PaperExecutionProvider`. No Dhan, Zerodha, IBKR, or other broker provider exists in Strategy Lab, and provider selection is not exposed through an API or dashboard control.

One paper aggregate is authoritative per strategy. Its immutable `paper_transactions.jsonl` event stream records lifecycle events and committed state snapshots; `paper_engine_state.json` is an atomic materialized projection recovered from the last valid committed snapshot. Existing order/fill JSONL files are event projections for audit, not competing state owners. `paper_state.json` and `statistics.json` are compatibility/read projections. Account, position, order, fill, trade, and statistics values are calculated by the paper aggregate only.

Account state contains initial capital, equity, cash, buying power, margin, available margin, open risk, realized/unrealized/daily P&L, fees, peak equity, drawdown, maximum drawdown, and recovery. Positions contain immutable IDs, contract, side, quantity, entry/exit, average/current price, P&L, MFE, MAE, duration, RR, stop/target, and status. OMS supports pending, partial, filled, rejected, cancelled, and expired states with timestamps and reasons. Every fill records its order, strategy, time, price, quantity, fees, and slippage.

Sizing policies are metadata-owned and isolated: fixed lots, fixed rupee risk, or fixed percent. Explicit max daily loss, max concurrent positions, and max trades per day are mandatory before authorization. Capital and all limits belong to one strategy workspace; a strategy cannot access another account.

### Event bus and lineage

The internal synchronous publish/subscribe bus emits immutable domain events: `SignalCreated`, `OrderCreated`, `OrderFilled`, `PositionOpened`, `PositionClosed`, `RiskRejected`, `TradeCompleted`, `JournalCreated`, `ReplayCreated`, `StatisticsUpdated`, and `DashboardUpdated`. The event recorder is a subscriber. The execution provider returns reports and never mutates OMS, positions, accounts, journals, replay, or portfolio state.

Every signal, order, fill, position/trade, journal, replay, statistics snapshot, and dashboard/portfolio update has an immutable ID, parent ID, and lineage list. Runtime finalization links the execution entity to the Strategy Lab journal and replay before statistics and dashboard publication. Duplicate evaluation IDs return the persisted result; immutable streams use idempotency keys and hash chains.

### Portfolio readiness

The only portfolio is `portfolio_strategy_lab_default`. It aggregates independently owned strategy accounts into total equity, P&L, open/closed trades, win rate, profit factor, expectancy, drawdown, and exposure. The contract declares `multi_portfolio_ready=true` and `multi_portfolio_enabled=false`; no multi-portfolio allocation, routing, or mutation behavior is implemented.

Immutable JSONL streams are idempotent and hash chained. Each evaluation persists its market context, result, latency, and a forensic envelope covering entry/exit, Why Trade/Why Not Trade, Technical, KRONOS, CHRONOS, ARGUS, ATHENA, ORACLE, AEGIS, Risk, module votes, weights, confidence, coverage, MFE, MAE, and replay ID when supplied by the deployed adapter. Missing inputs remain null; the Lab does not derive or invent them.

### Deployment lifecycle

1. Review a strategy package and its isolated risk/paper adapters.
2. Construct immutable metadata: name, ID, version, author, input type, markets, timeframes, RR, risk model, status, parameters, and source reference.
3. Compile or adapt the source to the narrow `StrategyAdapter.evaluate(context)` contract.
4. Register one independent workspace and runtime.
5. Start its scheduler without changing other runtimes.
6. Observe GET-only V2 and Strategy Lab projections.
7. Rank only after completed paper trades exist.
8. Stop or quarantine the individual runtime without affecting peers.

The architecture declares interfaces for Pine Script, Python, manual rules, JSON configuration, Git repositories, ZIP packages, and AI-generated strategies. Reviewed adapter injection and the hash-pinned PULLBACK MASTER event adapter exist today. Native Pine parsing, automatic compilation, and automatic strategy generation are explicitly not implemented.

### Tournament mode

Tournament fanout can evaluate the same immutable market context across selected independent runtimes. A failure is caught inside the affected strategy boundary. Winner, runner-up, and worst remain null until completed paper-trade statistics exist. Ranking order is expectancy, profit factor, win rate, drawdown, Sharpe, net P&L, completed trades, and RR; incomplete or open trades never qualify.

### Research workflow and safety

Strategy Lab exposes GET-only status, dashboard, strategy list, leaderboard, strategy detail, portfolio, capital, positions, orders, fills, statistics, open-trade, and closed-trade APIs. The root dashboard consumes it through the existing single V2 aggregate poll. Deployment remains an internal reviewed Python operation; no browser execution control exists.

Strategy Lab never shares Paper State, ledgers, schedulers, strategy state, journals, or execution state with Production or Development. It cannot call a broker, mutate production/development state, change model math, or promote a strategy automatically.
