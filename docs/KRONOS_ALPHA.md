# KRONOS ALPHA — Local Small-Model Shadow Integration

Status: **REAL-DATA ACTIVATED / SHADOW / READY FOR NEXT VALID NSE CANDLE CLOSE**

## Permanent identity and boundary

- **KRONOS CORE** remains CITADEL's deterministic setup-quality and timing intelligence.
- **KRONOS ALPHA** is the local adapter for the official pretrained Kronos financial foundation model.
- KRONOS ALPHA supplements and never replaces KRONOS CORE.
- Mode: `SHADOW`; execution influence: `0%`; AEGIS influence: `0%`; Risk Authorization influence: `0%`.
- It has no broker, order, Paper State mutation, Risk Authorization mutation, HERMES ingestion, AEGIS, or live-trading dependency.

Official identities pinned on 2026-07-11:

- Source: `shiyu-coder/Kronos`, revision `67b630e67f6a18c9e9be918d9b4337c960db1e9a`
- Model: `NeoQuasar/Kronos-small`, revision `901c26c1332695a2a8f243eb2f37243a37bea320`
- Tokenizer: `NeoQuasar/Kronos-Tokenizer-base`, revision `0e0117387f39004a9016484a186a908917e22426`
- License: MIT; official requirement: Python 3.10+; official context limit: 512.
- Official model implementation is the pinned local source checkout. Hugging Face remote custom code is not trusted or executed.

## Local installation

- Python: managed CPython 3.11.15 installed user-locally by `uv 0.11.28`.
- Environment: `/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha`
- Resolved direct runtime/test pins: `requirements-kronos-alpha.txt`
- Model cache: `/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface`
- Source checkout: `/Users/ayushmudgal/Developer/models/kronos-alpha/source/Kronos`
- Cache including pinned source: 138,620 KiB.
- Environment: 741,904 KiB after resolved runtime and test-contract packages.
- Model weights: 98,980,656 bytes; tokenizer weights: 15,842,368 bytes. All files are non-empty and outside Git.

PyTorch 2.13.0 imports successfully. Apple MPS is built and available, and a real MPS tensor operation passed. CPU tensor execution also passed and is the fallback. The existing production `.venv` was not changed.

## Measured smoke test

The genuine local tokenizer and model loaded with `HF_HUB_OFFLINE=1`. On Apple M1/8 GiB using MPS:

- Tested fixture: 256 deterministic closed 5-minute OHLCV candles.
- Horizon: 12 candles / 60 minutes.
- Basic one-path inference: 2.944 seconds.
- Ten-sample official probabilistic call: 6.171 seconds.
- Warm ten-sample call: 3.944 seconds.
- Local model/tokenizer load: 0.728 seconds.
- Approximate peak resident memory reported by the process: 429,867,008 bytes.
- Output: 12 × 6, finite, uniquely ordered timestamps, with optional amount generated from supplied volume.
- A second integration test loaded and forecast entirely from the pinned local cache in offline mode.

The official predictor requires timestamp inputs as pandas Series. Models must be put into evaluation mode before MPS inference; otherwise PyTorch correctly rejects non-zero attention dropout on MPS. The isolated runner enforces evaluation and inference modes.

This is a runtime smoke test, not evidence of accuracy, profitability, or alpha. No fine-tuning occurred.

## Runtime architecture

```text
authoritative closed candles (future controlled trigger)
  -> .venv-kronos-alpha isolated runner
  -> official pinned model/tokenizer
  -> sampled forecast paths
  -> deterministic normalization and metrics
  -> atomic bounded JSON cache
  -> FastAPI cached GET projection
  -> dashboard SHADOW display
```

HTTP polling never imports PyTorch, downloads a model, invokes the runner, refreshes Dhan data, or triggers inference. A lifecycle-owned scheduler uses the narrow read-only Dhan Data API boundary to persist up to 512 validated NIFTY index candles and invoke one isolated job per unique confirmed five-minute candle close. On 2026-07-11 it persisted 256 genuine `IDX_I / 13 / INDEX / 5m` candles through 2026-07-10 15:25 IST. Because the current session is Saturday, no forecast was generated: the API truthfully reports `READY_FOR_NEXT_OPEN / INPUT_CACHED_MARKET_CLOSED`, null forecast metrics, and next eligibility at 2026-07-13 09:20:10 IST.

## Input contract

Initial supported production target is NIFTY/5m. Inputs require:

- explicit `closed=true` for every candle;
- ascending unique non-future timestamps (unsorted input is deterministically sorted; duplicates are rejected);
- finite numeric open/high/low/close with `high >= open,close,low` and `low <= open,close,high`;
- optional finite volume and amount;
- explicit source/freshness supplied by the controlled caller;
- at least 64 candles, runtime target 256, hard cap 512;
- no incomplete current candle.

The horizon is 12 candles and selected path count is 20. Actual MPS path-preserving benchmarks were 8.794 seconds for 10 paths and 10.731 seconds for 20 paths at the same approximate 398,884,864-byte peak RSS. Twenty paths remain comfortably inside the five-minute cycle.

## Derived metric formulas

For each valid sampled path `i`, terminal return is `r_i = 100 × (terminal_close_i / last_input_close − 1)`.

- Bullish: `r_i > sideways_threshold`; bearish: `r_i < −sideways_threshold`; otherwise sideways. Default threshold is configurable at 0.15%.
- Each probability is its bucket count divided by valid path count × 100; the three buckets sum to 100 before display rounding.
- Expected/median return are the arithmetic mean/median of terminal returns.
- Expected high/low are the mean of each path's maximum high/minimum low.
- Forecast volatility combines mean projected high-low range percentage with the population standard deviation of step returns scaled by square root of horizon; labels are LOW/MODERATE/HIGH/EXTREME against configurable threshold multiples.
- Dispersion is terminal-return population standard deviation. Uncertainty is a bounded 0–100 composite of normalized dispersion (50%), path-direction disagreement (30%), and quantile-width instability (20%).
- Bullish persistence requires bullish terminal direction, at least 60% advancing closes, at least 50% higher-low progression, bounded adverse movement, bounded interruptions, and no final-candle dependency above 60%. Bearish persistence applies the mirrored lower-close/lower-high rules. Each probability uses only valid paths in that direction and is unavailable with fewer than two.
- Reversal requires a meaningful first-third extension beyond the sideways threshold followed by at least the larger of the threshold or 50% extension retracement. Direction-specific bullish/bearish reversal risk is calculated from corresponding initial paths.
- Upside/downside quantiles use deterministic nearest-index 90th/10th percentiles of sorted terminal returns.
- Official open/close values are retained. Only invalid forecast envelopes are normalized by expanding high to the maximum and low to the minimum of the returned OHLC values.

No metric is emitted without a valid finite path set. Production unavailable values remain null.

## Cache and API

`ForecastCache` uses schema version 1, sorted bounded JSON, temporary-file plus atomic replacement, revision/input fingerprint metadata, stale detection, restart-safe reads, and corruption-safe failure. Raw forecast paths are not persisted. Default runtime path: `logs/kronos_alpha_forecast.json` (ignored runtime state).

GET-only cached endpoints:

- `GET /v1/market/session`
- `GET /v1/kronos-alpha/status`
- `GET /v1/kronos-alpha/forecast`
- `GET /v1/kronos-alpha/outlooks`
- `GET /v1/kronos-alpha/history`
- `GET /v1/kronos-alpha/evaluation`

There are no mutation, download, inference, or trading-control routes. Responses expose no filesystem path or secret.

## Dashboard

The additive **KRONOS ALPHA — FOUNDATION FORECAST** panel reuses existing three-second polling, retry, stale preservation, loading, and connection logic. It contains exactly two primary rings: CE and PE OPTION-BUYING QUALITY. Ring segments are actual bullish/sideways/bearish path probabilities; the center is the CITADEL-derived quality score, never win probability. Supporting bars cover persistence, reversal, volatility, uncertainty, and forecast quality. Unavailable values render as `—`; weekend values remain frozen. Desktop and 390px mobile layouts have no horizontal overflow. KRONOS CORE remains visible and unchanged.

CE and PE quality use the exact centralized weights: directional probability 35%, direction-specific persistence 25%, volatility suitability 15%, inverse reversal risk 10%, inverse uncertainty 10%, and valid fresh input/model readiness 5%. States are STRONG_ALIGNMENT at 75+, MODERATE_ALIGNMENT at 60+, WEAK_ALIGNMENT at 45+, otherwise AVOID. Invalid or stale input is UNAVAILABLE, not zero.

Forecast Quality is separate from direction preference: path agreement 35%, inverse uncertainty 25%, valid-path coverage 20%, input freshness 10%, model health 5%, and inference completeness 5%. It is forecast clarity/reliability, not model confidence.

## Local runner operations

The runner is explicit and is never started by frontend/backend polling:

```text
.venv-kronos-alpha/bin/python -m src.kronos_alpha.runner \
  --input <sanitized-candle-request.json> \
  --output <temporary-forecast-result.json> \
  --source-root /Users/ayushmudgal/Developer/models/kronos-alpha/source/Kronos \
  --model-path <pinned-model-snapshot> \
  --tokenizer-path <pinned-tokenizer-snapshot> \
  --device mps
```

The runner remains one-shot. `KronosAlphaScheduler` owns backfill and the five-minute close lifecycle, applies a ten-second provider grace period, prevents duplicate/concurrent jobs, invokes the runner only during canonical OPEN/SPECIAL_SESSION state, atomically publishes output, appends history, and evaluates completed horizons. Weekend, holiday, unknown-calendar, pre-open, and post-close states suppress inference.

`ForecastHistoryLedger` stores immutable bounded forecast records separately from append-only realization records. Evaluation waits for all 12 actual closed candles, prevents duplicate/premature evaluation, and reports hit rate/error only with explicit EARLY_EVALUATION/PRELIMINARY/MATURE sample labels.

Offline verification uses `HF_HUB_OFFLINE=1` with the two pinned snapshot directories. To remove the installation safely, stop any explicit runner, then delete only `.venv-kronos-alpha` and `/Users/ayushmudgal/Developer/models/kronos-alpha`. Re-download must use the pinned revisions and re-run smoke/integration tests. Never delete the production `.venv`.

## Known limitations

- No genuine production forecast exists yet because activation occurred on a closed Saturday. The first actual open-session scheduler observation remains pending until after Monday's first confirmed 09:15–09:20 candle plus grace.
- Cache is local process/filesystem state and has no multi-worker coordination.
- MPS support depends on evaluation mode; CPU is slower but verified as a tensor fallback.
- Sampled outputs are probabilistic; smoke results do not establish forecast quality.
- No accuracy benchmark, calibration, trading influence, AEGIS integration, or fine-tuning exists.
- The verified local holiday calendar covers NSE CM 2026 and fails UNKNOWN/CLOSED for unavailable years; future official calendar versions require explicit refresh and verification.
- Only NIFTY/5m is activated by contract; other symbols/timeframes are future work.
