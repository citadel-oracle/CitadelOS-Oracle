# Oracle Phase 6C-1 Truth-Surface Map

Audit captured before UI edits on 2026-08-02 IST from the production `/oracle` route, `GET /v1/oracle/live-workspace`, and `GET /v2/dashboard`. The browser showed exact TradingView chart `NSE:NIFTY260804C24400`, mapped security `65854`, timeframe `5m`. TradingView metadata was fresh; market, option, ARGUS, OSE and VOB evidence was from the 2026-07-31 session and therefore stale.

## Authority chain

| Surface | React binding | API | Backend producer | Authority |
|---|---|---|---|---|
| TradingView strip | `OracleWorkspacePanel.liveChart` | `/v1/oracle/live-workspace.chart_state` | `TradingViewAutoSyncService` | TradingView for identity metadata only; Dhan mapping for security identity |
| Decision center / thesis / proof | `liveDecision` | `/v1/oracle/live-workspace.decision` | `AnalysisSnapshotAssembler`, Phase-3 decision service, Phase-4 evidence enrichment, `TradingViewAutoSyncService` projection | `OracleDecisionEnvelope` |
| ARGUS | `exactOption.quote` plus exact-option ARGUS confirmation | `/v1/oracle/live-workspace.decision.exact_option` | `AnalysisSnapshotAssembler` reusing canonical ARGUS rank and Dhan quote | ARGUS for rank/pressure; Dhan normalized quote for price/OI/Greeks |
| VOB | `strategyLab.execution.nifty_vob.nearest_*` | `/v2/dashboard.feeds.strategy_lab` | `StrategyLabService` / existing VOB projection | VOB only |
| OSE | `liveDecision.exact_option.premium_*` | `/v1/oracle/live-workspace.decision.exact_option` | Phase-6A exact-option analysis reusing `OptionsStructureEngine` | OSE only |
| Risk | `riskStatus` | `/v2/dashboard.feeds.risk_status` | `ControlStatusService.risk_summary` via `app/main.py::risk_status` | `RiskAuthorizationService` / canonical risk state |
| Discipline | `personal_oracle.second_brain.discipline` | `/v1/oracle/live-workspace.personal_oracle` | `src/oracle_personal/second_brain.py` | deterministic Discipline Engine, advisory only |
| Position / Guardian | `paperStatus`, `phase5`, durable mission projection | `/v2/dashboard.feeds.paper_status` + `/v1/oracle/live-workspace.phase5` | `ControlStatusService.paper_summary`, Phase-5 stores and Independent Guardian | Paper Engine for positions/orders; Guardian for management |
| System drawer | health/provenance fields only | both APIs | the producers above | diagnostic only; no analysis vote |

## Before-to-after field disposition

| Before label/value | Producer and issue | Disposition | After role |
|---|---|---|---|
| Assessment Evidence | Mixed legacy assessment and Decision Envelope | RENAME + REBIND | MARKET THESIS |
| ARGUS generic BALANCED/PUT | Pair/global flow could be mistaken for exact selected option | RENAME + REBIND | OPTIONS FLOW — ARGUS, exact contract `65854` |
| VOB LIVE | Card used runtime status while nearest zones explicitly said `STALE` | KEEP + FIX | STRUCTURE — VOB, zone freshness wins |
| Options Engine, CE/PE pair | Pair contracts were not the displayed exact chart contract | REPLACE | PREMIUM STRUCTURE — OSE, exact contract only |
| Risk Control | Risk was useful but discipline was absent from orbit | MERGE | RISK + DISCIPLINE |
| Trade Planner | Duplicated center plan/Decision Envelope fields | REMOVE | center Decision Envelope only |
| OpenAlgo Analyzer | Diagnostic adapter was presented as intelligence | MOVE | SYSTEM / EXECUTION HEALTH, zero vote |
| Paper Engine | Unavailable null state looked like live zero activity | MERGE + FIX | POSITION + GUARDIAN |
| Guardian | Split the same held-position truth over two cards | MERGE | POSITION + GUARDIAN |
| Deployed strategy strip | Research/runtime implementation detail on primary surface | MOVE | registry link/count in system drawer |
| Demo-tour operational strip | Non-canonical fixture looked primary | MOVE | system drawer, explicitly non-canonical |
| Evidence quality / Confidence | Legacy heuristic categories could imply probability | REMOVE | setup quality, explicitly not probability |
| OpenAlgo-controlled footer | Implied OpenAlgo authority over execution | RENAME | broker submission disabled; OpenAlgo diagnostic only |

## Final visible-field map

The `React` column names the exact projection property used by `OracleWorkspacePanel`. “Hash/record” is the runtime lineage captured during the audit; later refreshes replace it with the corresponding new canonical record.

### TradingView compact strip

| UI label | React | API field | Identity / TF | Timestamp; hash | Freshness and audited value | Action |
|---|---|---|---|---|---|---|
| TRADINGVIEW | `live.sync_state` | `sync_state` | exact chart / 5m | projection generated `2026-08-01T18:21:05Z`; `live.content_hash` | `NO_TRADE` | KEEP |
| RAW / NORMALIZED | `liveChart.symbol.*` | `chart_state.symbol` | `NSE:NIFTY260804C24400` / `NIFTY260804C24400` | chart source `2026-08-01T18:21:04Z`; chart hash `1ec5…` | FRESH metadata | MERGE |
| TYPE | `liveChart.instrument.route` | `chart_state.instrument.route` | EXACT_OPTION / 5m | same chart record | AVAILABLE | RENAME |
| TIMEFRAME | `liveChart.timeframe` | `chart_state.timeframe` | security `65854` / 5m | same chart record | `5m` | KEEP |
| EXACT IDENTITY | `liveChart.option` | `chart_state.option` | `NIFTY260804C24400`, `65854` | Dhan mapping in chart record | AVAILABLE | KEEP |
| CHART READY | `liveChart.availability` | `chart_state.availability` | exact chart / 5m | same chart record | AVAILABLE | RENAME |
| SOURCE AGE | `live.health.state_age_seconds` | `health.state_age_seconds` | projection | projection timestamp | runtime age, never market-data freshness | KEEP |
| TRANSPORT | `frontend_transport.transport` | SSE client annotation | projection | SSE event ID | SSE or POLLING_FALLBACK | KEEP |
| CONDITION | `phase5.condition_state` | `phase5.condition_state` | condition identity when present | Phase-5 event hash | `NONE` | KEEP |
| PAPER ORDER | `phase5.paper_order_state` | `phase5.paper_order_state` | order identity when present | Phase-5 event hash | `NONE` | KEEP |
| GUARDIAN | `phase5.guardian_action` | `phase5.guardian_action` | position identity when present | Guardian heartbeat | `IDLE` | KEEP |

### Center Decision Envelope

| UI label | React / API field | Authority | Identity / TF | Timestamp; hash | Audited value / freshness | Action |
|---|---|---|---|---|---|---|
| Action | `decision.action` | Decision Envelope | NIFTY exact chart / 5m | decision `decision_2b0af…`; hash `c846…` | NO_TRADE / STALE | KEEP, sole action |
| Underlying | `chart_state.symbol.normalized_symbol` | TradingView identity metadata + mapping | NIFTY / 5m | chart hash `1ec5…` | FRESH metadata | KEEP |
| Contract | `decision.exact_option.exact_contract.trading_symbol` | exact-option analysis | `NIFTY260804C24400`, `65854` | analysis snapshot `analysis_contracts_8b891…` | STALE | KEEP |
| Setup quality | `decision.setup_quality` | deterministic decision policy | same / 5m | decision hash | `84`, not probability | RENAME |
| Trigger | `decision.trigger` | Decision Envelope | same / 5m | decision hash | Confirmation pending | KEEP |
| Entry band | `decision.exact_option.executable_entry_band` | Dhan bid/ask, not LTP | `65854` / tick | quote `2026-07-31T15:29:53+05:30`; hash `970a…` | ₹67.95–₹68.08 / STALE | KEEP + FIX |
| Structural SL | `exact_option.premium_invalidation.level` fallback `decision.premium_stop` | OSE structural mapping | `65854` / 3m | evaluated through `2026-07-31T15:24+05:30`; zone ID `VOB-NIFTY-3M-BUL-e90…` | ₹70.60 / STALE | RENAME |
| Natural targets | `decision.targets` | Decision Envelope | same | decision hash | NOT REPORTED | KEEP truthful null |
| Trigger | `decision.trigger` | Decision Envelope | same / 5m | decision hash | Confirmation pending | KEEP |
| RR after costs | `decision.resulting_rr` | Decision Envelope | same | decision hash | NOT REPORTED | RENAME |
| Costs | `decision.costs` | Decision Envelope | same | decision hash | NOT REPORTED | KEEP |
| Mode / authority | immutable projection safety | safety contract | paper-only | schema/policy version | PAPER / FALSE | KEEP |
| WHY | `decision.why` | Decision Envelope | same | decision hash | bearish structure/setup invalidated/option blocked | RENAME |
| WHY NOT | proof conflict, then `risk_conflict` | Evidence Bundle | same | evidence/decision hash | material conflict or blocker | RENAME |
| Freshness / missing | chart, decision and exact-option freshness; missing count | each named authority | same | each record timestamp/hash | FRESH chart; STALE evidence; missing present | KEEP + SPLIT |
| WHY / PROOF action | opens MARKET THESIS drawer | no new authority | same | same records | read-only | ADD |

### MARKET THESIS

| UI field | React / API | Authority | Identity / TF / time / hash | Audited value and freshness |
|---|---|---|---|---|
| Direction | `assessment.directional_bias` | canonical market assessment | NIFTY / 5m / market as-of 2026-07-31 / dashboard assessment | BEARISH, stale |
| Regime | `assessment.regime` | canonical market assessment | same | RANGING, stale |
| HTF 1D/4H/1H/15m | evidence availability | Context Engine | NIFTY / named TFs / AnalysisSnapshot | not reported or missing; never inferred |
| Current location | `decision.structural_invalidation` | Market Analyst | decision identity/hash | ID reference or NOT REPORTED |
| Active setup | first `decision.reason_codes` | Decision policy | decision identity/hash | deterministic reason code |
| Trigger status | `decision.trigger` | Decision Envelope | decision identity/hash | Confirmation pending |
| Structural invalidation | `decision.structural_invalidation` | Decision Envelope | decision identity/hash | immutable reference |
| Setup quality | `decision.setup_quality` | Decision policy | decision identity/hash | 84, not probability |
| Main conflict | `why_proof.current_evidence.conflicts[0]` | Evidence Bundle | evidence hash / decision time | OSE/ARGUS conflict, stale |
| Missing evidence | `decision.missing_evidence` | Evidence Bundle | evidence IDs | five missing evidence lanes |
| Freshness | `decision.freshness` + projection age | Decision Envelope | decision hash/time | STALE |
| Lineage | decision ID/hash/source timestamp | AnalysisSnapshot + Decision Envelope | NIFTY / 5m | fully shown in drawer |

### OPTIONS FLOW — ARGUS

| UI field | React / API | Authority | Identity / TF / time / hash | Audited value and freshness |
|---|---|---|---|---|
| Contract / strike | `exact_option.exact_contract` | ARGUS-selected exact-option contract | `65854`, strike 24400 CE | exact and consistent |
| CE/PE participation, pressure, breadth, persistence | tactical ARGUS projection | ARGUS | NIFTY option-chain snapshot / chain timestamp/hash | shown only with availability/freshness |
| OI | `exact_option.quote.oi` | Dhan normalized quote | `65854` / tick / 2026-07-31 15:29:53 / quote hash `970a…` | 8,956,025 / STALE |
| OI change | no exact-contract authoritative field | none | same | NOT REPORTED |
| IV / Delta / Gamma / Theta | exact quote | Dhan normalized quote | same snapshot | 6.9678 / .47936 / .00218 / -13.68483, STALE |
| Bid / ask / depth / spread | exact quote | Dhan normalized quote | same snapshot | 67.70 / 67.95 / 325:520 / .37%, STALE |
| Snapshot age/availability | quote source timestamp/freshness | quote contract | same snapshot ID `analysis_contracts_8b891…` | HISTORICAL / STALE |
| Lineage | quote snapshot/content/source hashes | ARGUS + Dhan without recomputation | same | drawer exposes all |

### STRUCTURE — VOB

| UI field | React / API | Authority | Identity / TF / time / record | Audited value and freshness |
|---|---|---|---|---|
| Support | `nearest_support` | VOB | NIFTY / 3m / source candle 2026-07-31 / zone ID | 24,357.85–24,364.15, STALE |
| Resistance | `nearest_resistance` | VOB | NIFTY / 3m / source candle 2026-07-31 / zone ID | 24,394.48–24,407.05, STALE |
| Lifecycle | zone `status` | VOB | same zones | TESTED / TESTED |
| Strength | zone `strength_score` | VOB | same zones | 7 / 27 |
| Distance | zone `distance_points` | VOB | same zones | 19.45 / 10.88 points |
| Active interaction | support/resistance status | VOB | same zones | TESTED interaction |
| Thesis relevance | exact-option VOB confirmation | Evidence Bundle referencing VOB | exact option decision | confirmed true, stale source |
| Freshness | zone `freshness` | VOB | each zone | STALE; the old misleading LIVE label is removed |

### PREMIUM STRUCTURE — OSE

| UI field | React / API | Authority | Identity / TF / time / hash | Audited value and freshness |
|---|---|---|---|---|
| Contract / decision | exact contract + `verdict` | exact-option OSE projection | `NIFTY260804C24400`, `65854` | INSUFFICIENT_EVIDENCE / STALE |
| Trend / structure | `premium_features.trend/structure` | OSE | `65854` / 1m+3m+5m / evaluated through 2026-07-31 | ULTRA BEARISH / BULLISH |
| Completed alignment | premium candle counts | Dhan completed-candle authority | `65854`; 5624/1874/1124 completed bars | available history, stale now |
| Trigger / invalidation | premium predicates | OSE | `65854` / 3m | close above 100.05 / structure failure 70.60 |
| Spread / Greeks / IV | exact quote | Dhan quote reused by OSE context | quote snapshot/hash | .37%, .47936, .00218, -13.68483, 6.9678 / STALE |
| Entry extension | executable ask band | Dhan bid/ask | `65854` / tick | 67.95–68.075, stale |
| OSE confirmation | exact confirmation | OSE | decision hash | true; clear call advantage, stale |
| Better candidate | verified `alternative_contract` only | option selection authority | exact alternative record required | NOT REPORTED; no candidate fabricated |
| ARGUS → OSE | exact-option confirmation and premium authority | ARGUS selects/ranks; OSE analyzes premium | same contract `65854` | explicit dependency |
| Lineage/freshness | snapshot ID, quote hash, evaluated-through | OSE/Dhan | exact contract | drawer exposes STALE and missing quote evidence |

### RISK + DISCIPLINE

| UI field | React / API | Authority | Identity / time / hash | Audited value and freshness |
|---|---|---|---|---|
| Risk allowed | `risk.risk_state_available` | RiskAuthorizationService | paper account / 2026-08-02 risk projection | UNAVAILABLE; fail closed |
| Mode | immutable safety | safety contract | PAPER | PAPER |
| Risk/trade | `risk.limits.max_risk_per_trade` | RiskAuthorizationService | paper account / policy | ₹500 |
| Daily limit/usage | risk limit + paper state | Risk + Paper | paper account | ₹1,000 / UNAVAILABLE; no zero |
| Open positions / trades today | paper state | Paper Engine | paper account | NOT REPORTED because canonical state unavailable |
| Kill switch | risk state | RiskAuthorizationService | paper account / last update | INACTIVE; risk still unavailable |
| Discipline action/cooldown | second brain discipline | Discipline Engine | current Decision Envelope / second-brain hash | unavailable until projection refresh, then deterministic value |
| Duplicate / post-loss / FOMO | discipline warning codes only | Discipline Engine | current second-brain evaluation | NOT REPORTED unless an objective warning exists |
| Constitution | second-brain constitution version/hash | Oracle Constitution | immutable policy | version/hash exposed when available |
| Behavioral influence | fixed safety | Discipline contract | current decision | advisory, execution influence ZERO |

### POSITION + GUARDIAN

| UI field | React / API | Authority | Identity / time / record | Audited value and freshness |
|---|---|---|---|---|
| Mode / active position | Phase-5 position ID | Paper Engine | paper account | PAPER / NO ACTIVE POSITION |
| Guardian standby/state | Phase-5 Guardian action/health | Independent Guardian | worker policy v5 | STANDBY; worker healthy |
| Reconciliation | paper availability / Guardian error | Paper Engine + Guardian | account/worker | UNAVAILABLE while paper state unavailable |
| Contract/security/quantity/fill | durable Guardian/order projection | Paper Engine | position/order IDs when active | NOT REPORTED when inactive |
| Executable premium | Guardian reconciled quote | Guardian quote authority | held security/tick | NOT REPORTED when inactive |
| Unrealised P&L | paper state | Paper Engine | paper position | NOT REPORTED, not zero |
| Hard stop/targets/protection | durable protection | Guardian / Paper Engine | held position | NOT REPORTED when inactive |
| Action/heartbeat/reason | Guardian projection | Independent Guardian | Guardian event/hash/time | STANDBY / no heartbeat / no reason |
| Stale/disconnect | Guardian health error | Independent Guardian | worker heartbeat | truthfully empty or error |
| Read-only behavior | no card/drawer mutation handler | frontend | n/a | subscriber only |

### WHY / PROOF drawer

| UI field | API field | Authority | Audited truth |
|---|---|---|---|
| Supporting/conflicting/missing | `decision.why_proof.current_evidence` | Evidence Bundle | exact lists preserved |
| Visual claims | `decision.visual_certainty` and visual evidence IDs | Visual Claim Verifier | UNVERIFIED claims remain non-actionable |
| ARGUS/VOB/OSE lineage | `exact_option.confirmations` | named existing engines | no logic duplicated |
| Knowledge cards/locators | `why_proof.principle` | Knowledge Vault | exact source title/location/locator shown; principles do not create probability |
| Principle conflicts | `why_proof.principle_conflicts` | Knowledge Vault | material contradictions visible |
| Historical evidence | `why_proof.historical_evidence` | Similarity/calibration services | INSUFFICIENT_SAMPLE, N=0, probability unavailable |
| Personal Oracle / journals | second-brain explainability | Personal Oracle | only eligible links; none fabricated |
| Constitution | second-brain constitution refs | Oracle Constitution | versioned principle references |
| Snapshot lineage | live, decision, quote, cohort and calibration hashes | each named owner | exact hashes/IDs/timestamps surfaced |

### Secondary SYSTEM / EXECUTION HEALTH and footer

| UI field | Source | Meaning / audited value | Disposition |
|---|---|---|---|
| TradingView sync | live health/chart freshness | metadata sync only | MOVED |
| Dhan mapping/data | mapping status + quote availability | mapping available; quote historical | MOVED |
| OpenAlgo diagnostic | mission route health if checked | NOT CHECKED; zero analysis vote | MOVED |
| Backend/frontend | worker + transport | worker/SSE truth | MOVED |
| SSE/recovery | delivery/backoff | INITIAL/LIVE/REPLAY and backoff | MOVED |
| Last successful update/errors | live projection health | exact timestamp/error | MOVED |
| Mission runtime | existing durable mission state | operational, not intelligence | MOVED |
| Frontend p95 | measured receipt/visible samples | performance diagnostic | MOVED |
| Strategy registry | `/strategies` link + deployed count | registry navigation only | MOVED |
| Demo fixture | existing demo status | explicitly NON-CANONICAL | MOVED |
| Footer safety | immutable projection safety | paper-only, live/broker disabled, OpenAlgo diagnostic | RENAME |

### Header, canonical readout, controls, alerts and navigation

| UI field | React / API authority | Audited runtime value | Disposition |
|---|---|---|---|
| CITADEL OS / instrument / route status | `CitadelPrimaryNavigation` from exact chart and `sync_state` | `NIFTY260804C24400 · ORACLE`; NO_TRADE | KEEP |
| PROD | static production-route identity | PROD | KEEP |
| WORKSPACE / STRATEGIES / ORACLE / ORACLE DEVELOPMENT | `CitadelPrimaryNavigation` route configuration | existing route links; ORACLE active | KEEP |
| CITADEL ORACLE / Execution workspace | static route identity | unchanged | KEEP |
| ADVISORY ONLY / EXECUTION INFLUENCE ZERO | immutable safety projection wording | unchanged | KEEP |
| Canonical readout: Trigger | `decision.trigger` only | Confirmation pending | KEEP; removed confidence fallback |
| Canonical readout: Executable entry | plan maximum entry only after canonical plan, otherwise exact-option ask band | NOT REPORTED because exact quote unavailable | KEEP |
| Canonical readout: Structural SL | exact premium invalidation, then canonical plan stop | ₹70.60, stale and non-executable | RENAME |
| Canonical readout: Natural targets | Decision Envelope targets or canonical plan targets | NOT REPORTED | KEEP |
| Canonical readout: Resulting R/R | Decision Envelope or canonical plan | NOT REPORTED | KEEP |
| Canonical readout: Mode/authority | immutable safety | PAPER / FALSE | RENAME |
| Paper mode / LIVE LOCKED / MAX 1 TRADE | mission-control policy | unchanged, clearly paper-only | KEEP |
| Analyse | existing `OracleMissionRuntime.analyse`; server authorization remains authoritative | disabled while runtime unavailable | KEEP existing pattern |
| Create Plan | existing `OracleMissionRuntime.createPlan`; canonical gate required | disabled | KEEP existing pattern |
| Paper Execute | existing `OracleMissionRuntime.paperExecute`; exact paper-only gates required | disabled | KEEP existing pattern |
| Reject / Cancel | existing `OracleMissionRuntime.cancel`; durable mission rules required | disabled | KEEP existing pattern |
| Exit Now | existing `OracleMissionRuntime.exitNow`; canonical OPEN Guardian required | disabled | KEEP existing pattern |
| Mission control status | durable mission GET state | Failed to fetch / unavailable | KEEP truthful limitation; moved operational diagnosis to system drawer |
| Alert toast type/message | `live.alert_event.event_type/message` | AUTHORITY_CONFIRMATION_LOST for current stale authority state | KEEP |
| Alert count/history | append/deduplicated browser-local alert history | persisted count; no event fabricated | KEEP |
| Mute/unmute | browser-local preference | MUTED in audit | KEEP |
| Browser notifications | browser permission + local preference | continues in-app if denied | KEEP |
| Volume | browser-local preference | persisted range value | KEEP |
| Critical only / market-hours only | browser-local preference | persisted filters | KEEP |
| Per-event preferences | browser-local event allowlist | includes discipline REVIEW/COOLDOWN plus market/condition/paper/Guardian events | KEEP + EXTEND |
| Alert dedup/cooldown | canonical `deduplication_key` and `cooldown_seconds`, browser seen-state | unchanged events do not re-alert | KEEP |
| Strategy Lab health/readiness footer | `/v2/dashboard.feeds.strategy_lab.status` | DEGRADED / BLOCKED | KEEP as secondary footer status |
| Assessment reasoning footer | canonical assessment reasoning | “Market price is unavailable” or deterministic evidence text | KEEP, truthfully stale/unavailable |

## Locked safety audit

Before and after required values are identical:

```text
paper_only=true
live_trading_enabled=false
broker_submission=false
advisory_only=true
execution_influence=ZERO
execution_authority=false
```

No UI render, provider card, inspection drawer, GET route, or truth-map operation creates a mission, condition, risk authorization, order, position, or Guardian mutation.
