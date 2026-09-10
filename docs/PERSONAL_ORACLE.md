# Personal ORACLE Data Foundation

## Role, ownership, and safety boundary

Personal ORACLE is Ayush's personal trading-intelligence evidence layer. It describes completed personal paper-trading behavior and outcomes; it does not predict the market, authorize trades, mutate paper/risk/broker state, invoke KRONOS, or influence AEGIS/execution. The existing `src/oracle/` service remains the Technical Market Engine compatibility implementation.

`src/oracle_personal/` owns schema version 1. One `OracleEvent` represents one authoritative completed Paper State close. Stable identity is derived from `PAPER_STATE|close_event_id`; an immutable canonical source hash preserves provenance. Events cover source identity, timestamps, instrument/option/quantity, prices/outcome, strategy, day sequence, entry-time intelligence, behavioral fields, quality, and warnings. Missing facts remain null/unknown. Raw free-form notes are excluded; only a bounded opaque `notes_reference` is permitted. `ManualJournalRecord` is a typed future import contract only—there is no write route or UI.

## Ledger and capture

`logs/personal_oracle.json` is a Git-ignored runtime ledger with append-only event/enrichment contracts, duplicate protection, a 5,000-event bound, an in-process lock, fsync, and atomic replacement. Corruption reports unavailable and is never silently overwritten. Enrichments cannot mutate original events.

After an authoritative Paper State close succeeds, Paper Execution attempts an isolated Personal ORACLE append; failure cannot affect the completed lifecycle. Startup idempotently backfills `PaperState.closed_trades`. Derived journal and legacy Oracle CSVs are never authoritative.

Entry intelligence requires a parseable provenance timestamp at or before trade entry. Later context is rejected. Historical backfill always ignores current engine snapshots and marks context unavailable. Strategy/version, stop/target, R, costs, and behavioral labels remain unavailable when the source did not persist them.

## Analytics and maturity

Deterministic analytics provide wins/losses/flats, win rate, authoritative net P&L, mean P&L expectancy, gross-profit/gross-loss profit factor, average available R, chronological streaks, and context coverage. Segments cover instrument, CE/PE, strategy, weekday, time, day sequence, regime, Technical, ARGUS, KRONOS, ATHENA, HERMES, previous outcome, cooldown, early/late timing, and mistake tags.

Central thresholds are: segment evidence 10, preliminary 20, stable 50, mature 100. Findings require at least two qualified comparative segments, include sample evidence and limitations, and claim association only. Recommendations review qualified evidence or return `INSUFFICIENT_EVIDENCE`.

## Read-only exposure

- `GET /v1/personal-oracle/status`
- `GET /v1/personal-oracle/summary`
- `GET /v1/personal-oracle/findings`
- `GET /v1/personal-oracle/segments`
- `GET /v1/personal-oracle/recommendations`
- `GET /v1/personal-oracle/events?limit=25` (bounded 1–100)

GET handlers read the ledger only. The dashboard's additive `ORACLE — PERSONAL TRADING INTELLIGENCE` section uses existing polling/retry/stale behavior, exposes no controls, and labels itself read-only with no execution influence.

## Privacy, backfill, and limitations

No credentials, environment values, request headers, provider payloads, unbounded notes, or raw private notes belong in the ledger or API. Sixty authoritative completed trades were backfilled. All lack option/lot metadata and timestamp-aligned intelligence context; Paper State also lacks historical stop/target, strategy/version, confidence, brokerage, slippage, and manual behavioral labels. Context coverage is therefore zero and unavailable values remain truthful. Locking is process-local, and analytics are descriptive paper-history evidence—not causal or validated live-performance claims.

Future live ingestion and any AEGIS relationship require separately authorized contracts. Current AEGIS/execution influence is exactly 0%.

## Behavioral observation and coaching layer

`BehavioralObservation` classifies only observable structured facts. Plan/stop/target/cooldown use `YES/NO/UNKNOWN`; entry timing uses `EARLY/ON_TIME/LATE/UNKNOWN`; exit timing uses `EARLY/PLAN_BASED/LATE/UNKNOWN`. Sequence, size, context-compliance, and the fixed mistake-tag vocabulary remain null/unknown unless their required sources exist.

Rules are centralized in `BehaviorPolicy`: 5-minute late-entry threshold 180 seconds, cooldown 10 minutes, post-loss observation 30 minutes, default daily trade guidance 3, weak-quality threshold 50, high uncertainty/reversal threshold 0.65, and near-daily-limit threshold 80%. These are observation policies, not trading/risk settings. Current context is never used to reconstruct history.

`BehavioralEnrichment` is versioned, timestamped, duplicate-safe, and separate from immutable events. It permits fixed mistake tags, bounded setup tags, tri-state plan fields, 0–100 pre/post confidence, review state/time, and an optional 160-character sanitized opaque note reference. No write API or UI exists.

Behavioral comparisons report sample size, win rate, expectancy, average available R/points, profit factor, holding time, loss severity, deltas, standardized effect size, maturity, and limitations. They cover sequence/outcome, cooldown, entry/exit/stop/target, uncertainty/reversal, Technical/ARGUS/KRONOS alignment, HERMES/ATHENA state, size, CE/PE, and manual overrides. Segments require 10 observations; coaching requires at least 20 combined evidence with each side qualified; stable/mature thresholds remain 50/100.

Findings describe observable associations only and contain typed IDs, evidence samples, metrics, effect size, maturity/confidence band, reason codes, limitations, date range, and last update. They never diagnose emotions or personality. Coaching returns at most three advisory recommendations with evidence, sample, maturity, measurable benefit only where available, and explicit false execution/risk/strategy authority.

The scorecard independently gates Plan Adherence, Entry Discipline, Exit Discipline, Cooldown Compliance, Risk Discipline, Context Alignment, and Review Coverage at 10 observed values. Missing categories show unavailable. There is no combined or personality score. Trends compare the latest 10 trades with the prior 10 and report `IMPROVING/STABLE/DETERIORATING/INSUFFICIENT_DATA`; monthly windows are also descriptive.

UI terminology: **Cooldown Compliance** is the existing score—the percentage of observed trades whose configured cooldown was respected. When available, the UI also displays **Cooldown Violation Rate** as `100 − Cooldown Compliance`; this is a presentation-only complement and does not change the underlying score formula. **Trades With Tagged Mistakes** is the percentage of trades in the displayed trend window containing at least one structured mistake tag. Overall Oracle maturity is shown as **Limited Context** while entry-context coverage is 0%, independently of any stable individual finding.

Additional GET-only routes are `/behavior`, `/coaching`, `/scorecard`, `/trends`, and `/mistakes`. Responses are bounded and exclude note references. The compact dashboard shows status/coverage, category cards, one top-pattern state, at most three recommendations, and a four-metric trend strip without mutation controls.
