# CITADEL OS — CHRONOS-2 Challenger Complete

Completed: 2026-07-12 IST

## Recovery and baseline

- Secret-safe recovery: `/Users/ayushmudgal/Developer/CitadelOS_backups/20260711T164100Z_pre_chronos_2_challenger`.
- Git bundle, tracked/staged binary patches, Git metadata, untracked manifest, 246-entry allowlist archive, archive manifest, checksums, restore instructions, and state snapshot verified.
- Prohibited archive and allowlist paths: zero.
- Frozen baseline: 377 backend tests passed, 2 genuine KRONOS tests passed, frontend build/lint passed.

## Official identity and installation

- Official repository: `amazon-science/chronos-forecasting`.
- Upstream/package revision: `7dc4435706a4454feb79df44ca9f33631f3027bf` / `v2.3.1`.
- Package: `chronos-forecasting==2.3.1`.
- Official model: `amazon/chronos-2`.
- Model revision: `29ec3766d36d6f73f0696f85560a422f50e8498c`.
- License: Apache-2.0.
- Official runtime class: `Chronos2Pipeline`.
- Isolated runtime: `.venv-chronos-2`, Python 3.11, approximately 1.0 GiB.
- Model directory: `/Users/ayushmudgal/Developer/models/chronos-2`, approximately 456 MiB.
- Weight: 477,930,472 bytes; SHA-256 `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`.

Online official acquisition/local load passed. CPU quantile inference passed in approximately 0.95 seconds. Genuine Apple MPS inference passed in approximately 2.40 seconds without fallback. Fresh-process offline CPU reload/inference passed in approximately 0.71 seconds.

## Real NIFTY forecast

- Input: 256 canonical completed NIFTY 5-minute candles from the shared KRONOS closed-candle cache.
- Context end: 2026-07-10 15:25 IST.
- Mode: MULTIVARIATE.
- Model columns: close, open, high, low, volume, realized volatility, normalized ATR.
- Coverage: 100%.
- Horizon: 12 completed five-minute timestamps, calendar-aware across the weekend gap.
- Device: MPS.
- Inference duration: 1,764.005 ms.
- Forecast ID: `25e3f6e8ad10ff6599a4aef9`.
- P10/P90 horizon range: 24,138.9805–24,253.9023.
- Terminal P50: 24,205.9414.
- Derived bias: SIDEWAYS.
- Directional Confidence: 37.34 (not a calibrated probability).
- CE Quality: 15.37, VERY WEAK, 80% evidence coverage.
- PE Quality: 16.62, VERY WEAK, 80% evidence coverage.

The forecast is labeled LAST_FORECAST/HISTORICAL while the market is closed and is not actionable. Current ARGUS/IV/liquidity history was not fabricated; missing ARGUS and liquidity components remain excluded.

## Delivered foundation

- Typed schema-v1 forecast with P10/P25/P50/P75/P90, range, terminal estimates, dispersion, freshness, device, duration, features, warnings, and permanent SHADOW flags.
- Deterministic closed-candle validation, session-gap calendar mapping, univariate fallback, and genuine multivariate mode.
- Sanitized ARGUS numerical adapter that explicitly refuses current-snapshot historical backfill.
- Centralized CITADEL-derived Directional Confidence, direction-specific persistence, reversal risk, uncertainty, Forecast Quality, and independent CE/PE Option-Buying Quality.
- Atomic, bounded, restart-safe, duplicate-safe forecast/evaluation ledger with immutable original forecasts.
- Complete-horizon realization evaluator and non-merging KRONOS ALPHA comparison with collecting/preliminary/stable/mature thresholds.
- Shared-cache scheduler with ten-second grace, closed-session/incomplete/duplicate/overlap protection, bounded isolated subprocess, and no frontend trigger.
- Seven GET-only cache projections: status, forecast, outlook, history, evaluation, KRONOS comparison, and features.

## Frontend

The compact CHRONOS-2 Multivariate Challenger panel shows Directional Bias, Directional Confidence, Expected Median Move, Probabilistic Forecast Range, Uncertainty, CE/PE wheels, Persistence, Reversal Risk, Forecast Quality, terminal quantiles, historical freshness, SHADOW, AEGIS 0%, and execution 0%.

At 1440px it sits directly beside KRONOS ALPHA with equal width and compact independent height. At 390px it appears immediately after KRONOS ALPHA. No unrelated section was redesigned.

## Verification

- Deterministic Chronos target suite: 25 passed.
- Impacted KRONOS/AEGIS/architecture/dashboard suite: 115 passed.
- Final safe backend suite: 402 passed, 0 failed, one exact module skip because genuine Chronos tests require the isolated environment; four existing FastAPI lifecycle deprecation warnings.
- Genuine KRONOS ALPHA suite: 2 passed.
- Genuine offline CHRONOS-2 suite in `.venv-chronos-2`: 2 passed.
- Next.js 16 production build: passed.
- ESLint: passed.
- All seven live GET routes: HTTP 200.
- Desktop: no document overflow; KRONOS ALPHA then CHRONOS-2 side-by-side; no empty oversized Chronos card.
- 390px: 362px panel, correct ordering, no clipping/horizontal overflow/single-letter wrapping.
- Browser console: zero errors.

## Safety and limitations

Runtime verification used FastAPI with lifespan disabled so no scheduler/provider refresh ran. No Dhan provider/trading/order call, Paper State mutation, Risk mutation, kill-switch mutation, HERMES refresh, live-trading change, or AEGIS integration/influence occurred. No secrets were printed. Research repository was untouched.

CHRONOS-2 remains `shadow_mode=true`, `advisory_only=true`, `aegis_direct_influence=0`, and `execution_influence=0`. Timestamped ARGUS/IV/bid-ask history, completed realization samples, directional calibration, first live open-session scheduler observation, and any evidence of model superiority remain unavailable.

## Exact next milestone

**ORDER & FILL LEDGER FOUNDATION** — not started.
