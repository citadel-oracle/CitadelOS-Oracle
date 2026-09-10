# CHRONOS-2 — Multivariate Forecast Challenger

## Official identity and installation

- Official source: `https://github.com/amazon-science/chronos-forecasting`
- Pinned upstream/tag revision: `7dc4435706a4454feb79df44ca9f33631f3027bf` (`v2.3.1`)
- Official package: `chronos-forecasting==2.3.1`
- Official model: `amazon/chronos-2`
- Pinned model revision: `29ec3766d36d6f73f0696f85560a422f50e8498c`
- License: Apache-2.0
- Runtime class: `Chronos2Pipeline`
- Isolated Python: `.venv-chronos-2` (Python 3.11; measured approximately 1.0 GiB)
- Model location: `/Users/ayushmudgal/Developer/models/chronos-2` (outside Git; measured approximately 456 MiB)
- Weight: 477,930,472 bytes; SHA-256 `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`

Online official download verification, local load, CPU inference, genuine Apple MPS inference, and fresh-process `HF_HUB_OFFLINE=1` CPU reload/inference passed. Production invokes only the pinned local path through an isolated bounded subprocess; GET requests never load or invoke the model.

## Permanent role and safety

CHRONOS-2 is an independent multivariate forecast challenger. It does not replace KRONOS ALPHA, approve CE/PE trades, mutate Paper State/Risk/kill-switch/strategy state, call broker transport, or directly influence AEGIS. Permanent output flags are `shadow_mode=true`, `advisory_only=true`, `execution_influence=0`, and `aegis_direct_influence=0`.

## Inputs and forecast modes

The production scheduler reads the same persisted canonical KRONOS closed-candle cache; it does not create another Dhan poll. Inputs are validated as sorted, unique, finite, completed NIFTY 5-minute candles with no look-ahead. Initial context is 256 candles and horizon is 12 completed five-minute steps. Future timestamps use the canonical NSE calendar and skip session gaps, weekends, and holidays without forward filling.

`UNIVARIATE` uses NIFTY close. `MULTIVARIATE` uses timestamp-aligned historical close plus available open, high, low, volume, rolling realized volatility, and normalized ATR. Current genuine input coverage is 100% across seven model columns. Missing volume reduces coverage; insufficient covariates truthfully fall back to univariate.

The ARGUS adapter emits sanitized numerical current-snapshot features and provenance, but no timestamped ARGUS history exists. Therefore option-chain values are not inserted into the historical model frame and current chain state is never backfilled into old timestamps. ARGUS may contribute optional current alignment to the separate derived quality heuristic; stale evidence receives a penalty.

## Quantile contract and range

Each forecast contains exactly 12 ordered rows with P10, P25, P50, P75, and P90. The displayed lower range is the minimum P10 across the horizon and the upper range is the maximum P90. This is a probabilistic prediction interval, not a guaranteed market high/low. Terminal P10/P50/P90, median terminal move, interval width, and average dispersion remain separate fields.

## CITADEL-derived analytics

Chronos-2 does not natively provide trading direction, confidence, persistence, reversal, or option quality. Every such field is labeled **CITADEL-DERIVED FROM CHRONOS-2 FORECAST**.

Directional Confidence is a bounded 0–100 heuristic—not a calibrated probability—combining P50 path direction, steps above/below origin, terminal move normalized by recent volatility, quantile agreement, path persistence, and an uncertainty penalty. Bias is BULLISH, BEARISH, SIDEWAYS, MIXED, or UNAVAILABLE.

Upward/downward persistence use the fraction of P50 levels above/below origin, step direction, and P25/P75 support. Reversal Risk uses median-path sign changes, interval crossing around origin, interval dispersion, and early/terminal opposition. Uncertainty uses interval width relative to recent volatility. Forecast Quality is pre-realization readiness and remains separate from realized evaluation performance.

## CE and PE Option-Buying Quality

The centralized starting weights are direction 25%, direction-specific persistence 20%, normalized favorable move 15%, inverse reversal risk 10%, inverse uncertainty 10%, ARGUS alignment 10%, and side-specific IV/liquidity suitability 10%.

Missing optional evidence is excluded and weights re-normalize only above the minimum evidence threshold. Missing IV/liquidity never becomes positive evidence. Stale ARGUS is penalized. Sideways/high-uncertainty states are penalized and high reversal risk caps quality. CE and PE are independent, both may be low, and neither emits BUY/SELL or a recommendation. These are uncalibrated SHADOW heuristics, not official Chronos formulas or backtested edge.

## Scheduling, persistence, and evaluation

`Chronos2Scheduler` reuses the canonical NSE calendar, shared closed-candle cache, ten-second post-close grace, a one-worker non-blocking lock, duplicate origin protection, and bounded subprocess timeout. It never infers on closed sessions and never queues overlapping work.

The latest forecast and a dedicated bounded history/evaluation ledger use schema-versioned atomic `fsync` plus replacement. Semantic model/input/mode identity prevents duplicates. Original forecast records are immutable; realization records append only after all 12 authoritative future candles exist.

Evaluation includes terminal P50 error, path MAE, directional correctness, P10–P90 and P25–P75 coverage, observed high/low containment, persistence/reversal outcomes, and CE/PE directional outcomes. Maturity is COLLECTING below 20, PRELIMINARY at 20–49, STABLE at 50–99, and MATURE at 100+.

KRONOS comparison requires matching symbol, timeframe, forecast origin, genuine closed-candle forecasts, and compatible horizon. It reports AGREE, PARTIAL, CONFLICT, or UNAVAILABLE without merging scores. No winner is permitted before 20 comparable forecasts.

## Read-only API and frontend

GET-only routes are `/v1/chronos-2/status`, `/forecast`, `/outlook`, `/history`, `/evaluation`, `/comparison/kronos-alpha`, and `/features`. They read bounded caches only—no inference, model download, provider refresh, or mutation.

The dashboard places CHRONOS-2 beside KRONOS ALPHA on wide screens and immediately after it on narrower/mobile layouts. It shows Directional Bias, Directional Confidence, Expected Median Move, Probabilistic Forecast Range, Uncertainty, two CE/PE quality wheels, Persistence, Reversal Risk, Forecast Quality, terminal quantiles, and permanent SHADOW/zero-influence labels.

## Current genuine result and limitations

The genuine cached NIFTY run used 256 closed candles ending 2026-07-10 15:25 IST in MULTIVARIATE mode with seven columns and MPS inference. Its 12-step range is 24,138.9805–24,253.9023, terminal P50 is 24,205.9414, derived bias is SIDEWAYS, Directional Confidence 37.34, CE Quality 15.37, and PE Quality 16.62. It is displayed as a historical last forecast while the market is closed, never as current actionable evidence.

There is no timestamped historical ARGUS/IV/bid-ask series, no completed realization sample, no calibrated directional probability, and no evidence to declare a superior model. The first live-session scheduler observation and future calibration remain pending.
