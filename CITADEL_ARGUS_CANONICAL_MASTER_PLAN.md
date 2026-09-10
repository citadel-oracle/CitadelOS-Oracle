CITADEL / ARGUS Quant Research OS — Canonical Master Plan

Status: Locked source of truth
Purpose: Future prompts, implementation audits, Codex/Gemini work, and dashboard design must read this file first. No engine renaming, invented strategy counts, or premature completion claims.

────────

1. Core Goal

Build a quant-grade option-buying research operating system:

Real market data → canonical feature registry → single-factor probes → strategy-specific candidate engines → side-specific alpha → regime classification → contract ranking → entry timing → risk/fragility authorization → paper simulation → outcome attribution → validation and promotion.

Frontend is the final observability layer, not the primary objective.

────────

2. Locked Five ARGUS PRIME Engines

1. PRE — Premium Regime Engine
Determines option-buying environment: expansion, compression, continuation, reversal, buyer-dominant, seller-dominant, unstable/mixed.
2. PLI — Premium Lead Index
Measures CE-vs-PE premium lead/lag, persistence, velocity and acceleration. ATM Straddle is a PLI submodule, not a sixth engine.
3. SAE — Strike Attention Engine
Ranks/selects tradable strikes using liquidity, spread, volume, OI, momentum, IV, moneyness, responsiveness and freshness. It does not decide direction.
4. SME — Strike Migration Engine
Detects migration of attention/liquidity/OI/ranking across strikes, continuation, failed migration and reversal.
5. DGP — Dealer / Gamma Pressure
An inferred gamma-pressure proxy for pinning, escape, retest, amplification and fragility. It must never claim dealer inventory is directly observed.

Supporting systems such as VOB, OSE and Risk are important but are not the locked five ARGUS PRIME engines.

────────

3. Six Independent Contracts

ARGUS Prime must not output one universal choke-point score. It must expose six separable contracts:

A. Directional Alpha

CALL, PUT or NEUTRAL evidence from pressure, breadth, persistence, premium lead, spot/futures direction, VOB state and OI/PCR dynamics.

B. Regime

Expansion, compression, continuation, reversal, unstable, seller-dominant, buyer-dominant.

C. Entry Timing

Breakout, pullback, retest, rejection, acceleration, late entry, exhaustion.

D. Contract Quality

Correct side, strike, spread, liquidity, quote freshness, volume, OI, delta/moneyness and premium responsiveness.

E. Risk / Fragility

Melt risk, IV crush, spread/slippage, expiry risk, wall proximity, invalidation distance and late-move risk.

F. Data Confidence

VALID, STALE, MISSING, PARTIAL, WARMING or INCONSISTENT.

Mandatory pass condition

A loose independent strategy must be able to produce a candidate while Prime is HOLD, without bypassing risk controls and without creating real execution.

Candidate generation, contract selection and risk authorization are separate stages.

────────

4. Canonical Feature Registry

Every feature must define:

• canonical name
• meaning
• owner engine
• source data
• instrument
• timeframe
• unit
• normalization
• update cadence
• warm-up
• stale threshold
• missing-data state
• valid range
• directionality
• downstream consumers
• historical availability
• live availability

Feature families

Market direction: spot return, futures return, basis, velocity, acceleration, trend, breakout state.
Options premium: CE/PE return, velocity, acceleration, premium VWAP, rolling high/low, persistence, relative strength.
Structure: VOB lifecycle, supply/demand break, retest, rejection, continuation, reversal, entry spine, invalidation.
Participation: pressure, breadth, persistence, volume, OI, OI change, PCR level/velocity/acceleration.
Volatility: IV level/change/skew, ATM straddle level/change/velocity/acceleration, compression/expansion.
Strike intelligence: SAE rank, rank stability, attention shift, SME direction, migration velocity and persistence.
Gamma proxy: pin proximity, concentration, escape, retest, fragility and proxy confidence.

Anti-double-counting rule

Related transforms are one feature cluster, not independent confirmations. Example: premium return, velocity and acceleration must not count as three independent votes.

Every parameter must be available, measurable, timestamped, historically reproducible, or explicitly NOT_AVAILABLE. No dummy values.

────────

5. Existing 10 APEX Strategies — Locked Baselines

Do not delete or overwrite them.

• C1/P1: Independent / loose baseline. Prime HOLD must not silently block candidate generation.
• C2/P2: Prime-assisted moderate. Prime improves confirmation but does not erase the candidate.
• C3/P3: Prime-required strict.
• C4/P4: Big Move Escape / blast strategy. Must have a dedicated acceleration/escape lifecycle and must not wait only for a conventional pullback.
• C5/P5: Wall / reversal strategy. Must measure absorption, failed break, wall defence, premium divergence and migration failure rather than being blocked by continuation-only structure.

Mandatory repairs

• Candidate generation occurs before global contract authorization.
• First blocking gate and counterfactual downstream gates are logged.
• NIFTY/SENSEX scope is explicit.
• Variants are materially distinct.
• Candidates are non-zero where intended.
• No forced trades and no threshold curve-fitting.

────────

6. Strategy Universe

Target

• 22 CALL archetypes
• 22 mirrored PUT archetypes
• 44 shadow/paper research hypotheses total
• Existing 10 APEX baselines are mapped into this universe.

CALL archetypes

1. Premium Breakout Persistence
2. Premium Reclaim — ₹50/session VWAP/key premium level
3. Cross-Side Premium Acceleration
4. Spot–Futures–Option Lead Alignment
5. PCR Acceleration Confirmed
6. OI Build/Unwind Confirmed
7. VOB First Break
8. SAE Liquid-Strike Momentum
9. VOB Break–Retest Continuation
10. Pressure–Breadth Persistence
11. Pressure–Breadth Divergence Reversal
12. Continuation-vs-Reversal Selector
13. Entry-Spine Pullback
14. Blast Integrity Continuation
15. Melt-Risk Avoidance/Re-entry
16. Premium Regime Transition — PRE
17. Premium Regime Continuation — PRE
18. Straddle Expansion + Side Dominance — PLI
19. Straddle Compression → Directional Release — PLI
20. Strike Migration Continuation — SME
21. Failed Migration Reversal — SME
22. Gamma Escape/Pin/Retest Composite — DGP + SAE

PUT archetypes are exact semantic mirrors, not shallow sign inversions.

Earlier 15+15 matrix retained as research history

The earlier matrix of 15 CALL + 15 PUT variants remains a valid starting framework, but the optimized locked target is 22 + 22.

Prime dependency classification

Every strategy must be explicitly one of:

• Prime-independent
• Prime-assisted
• Prime-required

Mandatory strategy specification fields

• Strategy ID
• Hypothesis
• Market regime
• Primary trigger
• Independent confirmations
• Disqualifiers
• Required features
• Optional features
• Entry lifecycle
• Contract-selection policy
• Invalidation
• Exit hypothesis
• Strictness
• Prime dependency
• Expected frequency
• Known failure mode
• Forward labels
• Testable null hypothesis

Loose/moderate/strict/ultra-strict must represent genuinely different hypotheses, not score-threshold clones.

────────

7. Strictness Design

Loose

One primary alpha event, valid data, acceptable liquidity, risk controls, no Prime authorization, high candidate frequency.

Moderate

Primary event + one genuinely independent confirmation + compatible regime + acceptable contract quality.

Strict

Primary event + at least two independent confirmations + persistence/retest + stronger contract quality + Prime alignment or specialized-engine agreement.

Ultra-strict

Multi-engine agreement + strong entry timing + calibrated positive EV + low fragility + risk authorization; rare by design.

Correlated variables must be clustered and contribution-capped.

────────

8. Mandatory Per-Evaluation Telemetry

Data availability

AVAILABLE, STALE, MISSING, INVALID, WARM-UP_INCOMPLETE.

Raw features

• spot return/velocity/acceleration
• option premium return/velocity/acceleration
• CE/PE relative strength
• volume and volume acceleration
• total OI and change in OI
• PCR level/change/acceleration
• IV level/change/skew
• straddle premium/change/velocity
• VOB lifecycle
• pressure
• breadth
• persistence
• SAE rank
• SME state
• DGP state/proxy quality
• spread/liquidity
• distance/moneyness
• delta/theta/gamma where reliable

Gate truth

• each gate PASS/FAIL/NA
• first blocking gate
• all secondary failures
• actual value
• threshold
• candidate despite blocked contract
• selected strike and reason
• rejected strike and reason

Forward outcome labels

• MFE at 1/3/5/10/15/30 minutes
• MAE
• time to +10/+20/+30 premium points
• stop-first or target-first
• maximum underlying move
• option-premium capture
• IV contribution
• delta contribution
• theta/decay contribution
• spread/slippage estimate

Every strategy must answer: “Why did I trade or not trade at this timestamp?”

────────

9. Single-Factor Diagnostic Probes

Measure individual predictive contribution instead of making every parameter a live strategy.

Mandatory probes

1. Pressure
2. Breadth
3. Persistence
4. Previous OI and fresh OI
5. PCR level, velocity and acceleration
6. CE/PE premium relative strength
7. Premium velocity and acceleration
8. IV level/change/skew
9. ATM straddle level/change/acceleration
10. VOB lifecycle
11. Entry spine/retest/rejection
12. SAE rank and rank stability
13. SME migration velocity and persistence
14. DGP pin/escape/retest proxy
15. Premium attribution: delta/gamma/IV/decay
16. Blast integrity
17. Melt/exhaustion risk
18. Contract spread and liquidity
19. Spot–futures basis
20. Time-of-day and expiry regime
21. Data freshness and missingness

Each probe tracks forward option/underlying returns, MFE/MAE, target-first vs stop-first, time to target, continuation/reversal probability, net expectancy after costs, and performance by instrument, expiry, time and regime.

────────

10. Prime Score Calibration Rules

Never blindly lower the global threshold.

Required score audit

• p10/p25/p50/p75/p90/p95 distribution
• maximum score per session
• bullish and bearish sessions separately
• NIFTY and SENSEX separately
• expiry and non-expiry separately
• score 5/10/15 minutes before large moves
• remaining move after score crossing
• missing-component frequency
• per-component contribution
• duplicate/correlated penalties
• theoretical vs empirically reachable maximum
• score-decile MFE, MAE and net expectancy

Threshold adjustment is justified only if evidence shows the threshold is unreachable, lagging, distorted by missing data, or double-penalized by correlated gates.

Green means calibrated out-of-sample positive expected value after costs, valid data, acceptable contract quality and passed risk controls—not an arbitrary raw score crossing.

────────

11. Research Lab Implementation

All 44 strategies are initially shadow only.

They may

• evaluate
• generate/reject candidates
• select hypothetical contracts
• calculate entries/exits
• track MFE/MAE and forward outcomes
• produce analytics

They may not

• place broker orders
• modify live trading state
• influence another module
• claim proven profitability
• auto-promote themselves

Mandatory per-strategy telemetry

• evaluations
• skipped evaluations
• candidates
• first blocking gate
• all failing gates
• qualifying signals
• hypothetical entries/exits
• MFE/MAE
• target-first/stop-first
• data quality
• selected contract
• rejection reason
• evaluation latency

────────

12. Quant Validation Standard

Data integrity

• exact historical option chain available at that timestamp
• no future expiry/strike knowledge
• no future candle use
• correct bar-close semantics
• survivorship-safe contract selection
• realistic spread/slippage
• quote-aware fills where available

Validation methodology

• chronological walk-forward
• train/validation/test separation
• purging for overlapping labels
• embargo
• untouched final holdout
• expiry-specific testing
• NIFTY/SENSEX separation
• time-of-day and regime segmentation
• live shadow/paper observation

Multiple-testing controls

• trial registry
• no hidden discarded trials
• false-discovery control
• White Reality Check
• Hansen SPA
• Probability of Backtest Overfitting
• Deflated Sharpe Ratio

Promotion metrics

• net expectancy after costs
• profit factor
• median trade
• average win/loss
• tail loss
• maximum drawdown
• minimum trade count
• stability across folds
• PBO
• DSR
• slippage sensitivity
• parameter stability
• regime concentration
• correlation with existing strategies
• probability calibration
• live shadow drift

No strategy is promoted on win rate alone.

────────

13. Engine Implementation Order

Implement and validate one engine at a time:

1. PRE
2. PLI — ATM Straddle inside PLI
3. SAE
4. SME — depends on SAE ranking history
5. DGP — last due to highest inference and data risk

Per-engine PASS gate

1. Contract
2. Historical availability
3. Deterministic calculation
4. Unit tests
5. Replay parity
6. Shadow output
7. Real production visibility
8. Missing-data behaviour
9. Performance budget
10. Strategy integration

Only after one engine passes should the next engine begin.

────────

14. Paper Strategy Tournament

Only historical-validation survivors enter paper deployment.

Groups

• A — Loose
• B — Moderate
• C — Strict
• D — Specialist: reversal, gamma escape, migration, compression release, expiry-specific

Rules

• minimum observation window
• no strategy editing during evaluation window
• no same-day threshold adjustment
• historical-vs-live drift tracking
• natural market data only
• no fake trades
• no real broker orders

Outcomes

• retain
• recalibrate
• demote to research
• retire
• insufficient sample

────────

15. Dashboard / Observability — Final Phase

The dashboard must not merely say SCANNING.

For every strategy it must show:

• Status
• Current instrument
• Current side
• Prime dependency
• Last evaluated
• Primary setup state
• First blocking gate
• Actual value
• Required threshold
• Candidate status
• Contract status
• Data confidence
• Closest trigger
• Distance to trigger
• Last hypothetical/paper trade

Five-engine UI must use the correct taxonomy: PRE, PLI, SAE, SME, DGP. ATM Straddle is nested under PLI. Supporting VOB/OSE/Risk may be shown separately but never substituted for the five locked engines.

All final intelligence should be consolidated in one clear surface below ARGUS Prime, with no duplicates and no fabricated values.

────────

16. Current Truthful Progress Baseline

Approximate status at time of freeze:

• Research architecture and roadmap: ~95%
• Six contracts specification: ~90%
• Canonical Feature Registry: ~25%
• Existing 10 APEX repair: ~10%
• 44-strategy specification: ~55%
• 44-strategy backend implementation: ~5%
• PRE: partial (~40%)
• PLI + ATM Straddle: partial (~45%)
• SAE: 0%
• SME: 0%
• DGP: 0%
• Single-factor probes/outcome attribution: ~10%
• Historical validation framework: ~10%
• Paper tournament: 0%
• Final accurate dashboard/observability: ~20%

Weighted overall completion: approximately 25%.

Do not claim 100% until backend contracts, strategies, validation and live evidence genuinely pass.

────────

17. Canonical Execution Order

1. Freeze six contracts and Prime separation.
2. Build canonical feature registry.
3. Implement single-factor probes.
4. Audit and repair current 10 APEX strategies.
5. Freeze full 44-strategy specification.
6. Build shadow Research Lab and mandatory telemetry.
7. Complete PRE.
8. Complete PLI with ATM Straddle.
9. Implement SAE.
10. Implement SME.
11. Implement DGP.
12. Activate engine-dependent strategies.
13. Historical walk-forward and multiple-testing controls.
14. Paper Strategy Tournament.
15. Final unified dashboard and observability.

────────

18. Non-Negotiable Safety Invariants

• paper_only = true
• live_trading_enabled = false
• broker_submission = false
• execution_influence = ZERO until explicit future approval
• no dummy market values
• no fake dealer-position certainty
• no silent missing-data conversion to zero
• no universal Prime choke-point for independent strategies
• no strategy promotion without out-of-sample evidence

────────

19. Instruction for Future AI Sessions

Before any CITADEL/ARGUS work:

1. Read this file fully.
2. State the exact phase being worked on.
3. Audit existing implementation before editing.
4. Preserve locked engine names and strategy counts.
5. Report compactly: Progress / Strong / Weak / Research improvement / Next prompt.
6. Never infer completion from tests alone.
7. Never redesign frontend before backend source-of-truth and evidence are ready.
