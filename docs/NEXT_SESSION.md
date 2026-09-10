# CITADEL OS — Next Engineering Session Handover

Updated: 2026-07-13

## Start here

1. Read `docs/CITADEL_ENGINEERING_BIBLE.md`.
2. Read `docs/CITADEL_PROJECT_STATE.md`.
3. Inspect `git status --short`; preserve the dirty working tree.
4. Do not read or print `.env` values.
5. Confirm `config/settings.json` still contains `live_trading_enabled=false` without changing it.
6. Use `.venv-kronos-alpha/bin/python` for the verified Python 3.11 backend/test runtime.
7. Never modify `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer`.

## Current priority

Validate, do not optimize. The first priority is open-market verification of `logs/decision_evidence.jsonl` coverage and hash integrity for every newly evaluated NIFTY five-minute candle.

The second priority is a read-only Development Mode isolation audit. Verify `logs/development_*` changes while the production runtime, Paper State, order/fill ledger, AEGIS decisions, and production strategy outputs remain unchanged except for their own independent market lifecycle.

Check:

- Exactly one `CANDLE_DECISION_ENVELOPE` per evaluated candle origin.
- `EvidenceJournal.verify()` remains valid.
- Strategy WAIT and actionable signals both preserve independent pullback conditions.
- Every actionable rejection contains first rejecting module, rejection chain, hard/soft reasons, missing evidence, confidence, and timestamp.
- AEGIS-approved paths preserve resolved contract, Risk decision, and Paper result.
- Evidence failures never change the orchestrator result.
- No broker call, manual model invocation, forced signal, or state replay occurs.
- Development decisions persist weighted scores, module votes, contributions, missing optional evidence, Why Trade/Why Not Trade, and replay IDs.
- Completed development trades persist entry, stop, target, exit, underlying/option MFE and MAE, planned/realized RR, and winner/loser truth.
- The browser toggle changes only visible projection; both backend modes continue independently.
- A missing optional module lowers development coverage/score without becoming a hard veto.

## Safe changes

- Tests, documentation, validation scripts, and read-only diagnostic projections.
- Append-only evidence fields that copy existing authoritative outputs without recalculation.
- Replay joins based on exact IDs or timestamps.
- Explicit unavailable/not-evaluated states.
- Retention and archive design after tests prove it cannot delete or mutate evidence.
- Frontend presentation only when separately requested and without data-semantic changes.

## Unsafe changes

- Strategy rules, thresholds, stops, targets, or signal definitions.
- KRONOS, CHRONOS, ARGUS, ATHENA, ORACLE, HERMES, or forecast calculations.
- AEGIS weights, scoring, gates, conflicts, confidence, or thresholds.
- Risk formulas, limits, ordering, kill-switch behavior, or authorization semantics.
- Paper fill, order, position, P&L, or ledger mutation behavior.
- Broker client or order transport.
- Polling, scheduler cadence, inference timing, or provider refresh behavior without an explicit milestone.
- Derived option prices, synthetic candles, fabricated missing fields, or retrospective favorable contract selection.
- Git reset/stash/clean, environment recreation, model download, or research-repository edits.

## Do not touch

- `.env`, credentials, tokens, secrets, broker authentication headers.
- `logs/paper_trades.csv` and existing runtime ledgers except through their owning services.
- Model weights and Hugging Face caches.
- Frozen strategy logic.
- Production dashboard unless the user explicitly authorizes frontend work.
- Existing checkpoints.

## Recommended milestone order

1. **Development Mode Open-Market Evidence Validation** — observe isolation, natural frequency, weighted decisions, and forensic completeness without parameter changes.
2. **Forensic Evidence Open-Market Validation** — read-only production observation and integrity verification.
3. **Authoritative Option Candle Archive Design** — architecture and tests first; no provider activation until approved.
4. **Option Candidate Resolution Evidence** — cache/provider-load review before resolving ATM+1 and ITM.
5. **Forecast Lifecycle Instrumentation** — timestamps only, no model/math/scheduler change.
6. **Multi-Session Decision Quality Report** — use predeclared labels and mature horizons.
7. **Security Remediation** — rotate exposed credentials and remove tracked `.env` in a separately authorized history procedure.
8. **Maintenance** — FastAPI lifespan migration and evidence archival policy.

## Mode handover

- Production Mode files and services remain the only production authority.
- Development Mode backend runs continuously when the application runs; do not tie it to the UI toggle.
- The UI toggle is session-local presentation state and sends no mode mutation request.
- Development weighted policy is in `src/development/decision.py`.
- Development strategy profile is in `src/development/strategy.py`.
- Development runtime/execution is in `src/development/orchestrator.py` and `src/development/execution.py`.
- Never reuse development Paper State or ledger as production input.
- Never tune weights or threshold while collecting a validation sample.

## How future work should proceed

- Begin with a recovery checkpoint and baseline.
- State the exact files to change.
- Separate observation from calculation and calculation from authorization.
- Prefer immutable evidence over mutable summary counters.
- Add deterministic offline tests before runtime activation.
- Run targeted tests first, then the full safe suite once.
- Run genuine model tests only in their existing isolated environments and only when required.
- Run frontend build/lint only when frontend files change.
- Report unavailable evidence and incomplete work explicitly.
- Stop at the requested milestone; never begin optimization automatically.

## Replay quick reference

```python
from src.forensics import OpportunityReplayEngine

replay = OpportunityReplayEngine()
result = replay.replay(
    "2026-07-13T12:50:00+05:30",
    outcome_until="2026-07-13T13:20:00+05:30",
)
integrity = replay.verify_evidence()
```

Replay is read-only. If no immutable envelope exists, it returns `NOT_AVAILABLE`; do not regenerate the historical decision. Without an explicit outcome horizon or authoritative future candles, outcome is `NOT_DETERMINABLE`. Option P&L remains unavailable until authoritative timestamp-aligned option candles exist.

## Strategy Lab handover

Current priority is **Trading Workspace Read-Only UI Foundation**, only after this paper-engine checkpoint is accepted. The workspace must consume the existing GET-only Strategy Lab portfolio/capital/position/order/fill/statistics/trade APIs. It must not add execution controls, broker providers, strategy mutation, or alternative calculations.

Safe next steps:

1. Preserve `paper_engine_state.json` as the authoritative materialized aggregate and `paper_transactions.jsonl` as its immutable recovery/event source.
2. Consume the GET-only APIs without recalculating P&L, statistics, exposure, drawdown, or leaderboard values in the frontend.
3. Keep the sole portfolio ID `portfolio_strategy_lab_default`; do not enable multi-portfolio behavior yet.
4. Keep `PaperExecutionProvider` as the only provider. Do not create a broker implementation without a separate explicitly approved milestone.
5. Continue PULLBACK MASTER parity work separately; do not activate its scheduler until exported TradingView fixtures pass.
6. Run tournament comparison only on the same authoritative context and rank only completed paper trades.

Do not expose browser deployment controls, broker methods, shared state paths, automatic promotion, or automatic AI strategy generation. Do not reuse Production/Development ledgers, journals, Risk, execution, or scheduler instances. A Strategy Lab runtime must remain removable without changing either existing mode.
