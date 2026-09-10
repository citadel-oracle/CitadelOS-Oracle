# AEGIS Decision Foundation

## Permanent role

AEGIS is the deterministic Final Decision Controller over existing advisory projections. It never places an order, grants execution permission, mutates broker/Paper State/risk/kill-switch/strategy state, triggers KRONOS inference, or refreshes HERMES/ARGUS providers. Risk Authorization remains the absolute hard veto immediately before any future execution path.

Outputs are `APPROVE`, `APPROVE_REDUCED`, `WAIT`, `REJECT`, or `BLOCK`. Every result is `advisory_only=true`, `execution_permission=false`, and `risk_authorization_required=true`.

## Input contract

Schema-v1 `AegisInputSnapshot` captures identity, symbol/timeframe/strategy/requested side/session; Technical, cached ARGUS, KRONOS CORE, cached KRONOS ALPHA, ATHENA, cached HERMES, Personal ORACLE; sanitized Risk Authorization/kill-switch/live flag/Paper health/freshness/duplicate state; strategy eligibility; required-input presence; and source timestamps. Missing values remain null/unknown.

Frontend polling reads cached projections. `ArgusAPI.projection()` never refreshes Dhan. KRONOS ALPHA status reads its existing cache and retains direct execution and AEGIS weight 0%. HERMES assessment reads its in-memory cache only.

## Hard gates

Hard gates run before scoring. BLOCK: active kill switch, Risk Authorization DENY, duplicate request, disabled live path, or malformed/severely unavailable critical system state. WAIT: closed market, critical stale/mandatory unavailable data, ATHENA pause, HERMES wait, high-confidence module conflict, or no requested side. REJECT: ineligible strategy, opposite Technical signal, strongly opposite mandatory ARGUS, invalid KRONOS timing, side mismatch, high reversal/low persistence, or insufficient option-buying quality when available.

No score overrides BLOCK or Risk Authorization DENY. Unknown critical system state fails closed.

## Scoring

Frozen weights: Technical 25%, KRONOS CORE 25%, ARGUS 20%, Personal ORACLE 15%, HERMES 10%, ATHENA 5%. Scores are normalized 0–100. Optional unavailable modules are excluded and reduce coverage; mandatory absence gates WAIT. Stale Technical/ARGUS evidence receives a 0.75 multiplier. Directional opposition lowers component score and typed conflicts apply LOW 2, MEDIUM 5, HIGH 10, or CRITICAL 20 point penalties. Available-weight contributions are normalized and the final score is bounded 0–100.

Thresholds after gates: 80+ APPROVE; 65–79.99 APPROVE_REDUCED; 45–64.99 WAIT; below 45 REJECT. With requested side NONE, output is assessment-only WAIT.

KRONOS ALPHA is contextual only: direction, persistence, reversal, volatility, uncertainty, forecast quality, and CE/PE option-buying quality may gate or explain a side, but direct weighted contribution remains exactly zero.

## Conflicts and side logic

Typed conflicts cover Technical vs ARGUS/KRONOS CORE, KRONOS ALPHA reversal/uncertainty, requested-side mismatch, HERMES event risk, and ATHENA caution/pause. Each includes modules, severity, resolution, score impact, and reason codes. UI shows at most three.

CE requires bullish requested direction and supportive non-opposed Technical/ARGUS/KRONOS timing; PE uses bearish equivalents. The logic is explicit rather than mirrored through fabricated values. Missing requested side can never approve.

## Strategy eligibility

The read-only compatibility policy recognizes `simple_pullback`, NIFTY-family watchlist symbols, 5m timeframe, OPEN/SPECIAL_SESSION, known regimes, mandatory Technical/KRONOS CORE/ARGUS/ATHENA, maximum freshness 30 seconds, minimum setup quality 50, and optional option-buying quality minimum 50. Existing expiry/DTE policy is unavailable and is exposed as such. Unknown strategies fail closed. No strategy parameter is optimized.

## Size and audit

AEGIS may pass through ATHENA size on APPROVE or reduce it on APPROVE_REDUCED. It can never exceed ATHENA. WAIT/REJECT/BLOCK size is zero.

`logs/aegis_decisions.json` is a local ignored, atomic, restart-safe, duplicate-safe, immutable, 1,000-record bounded audit ledger. Semantic input fingerprints prevent repeated closed-market decisions from changing or duplicating when evidence is unchanged. It contains no secrets or order data.

## API and frontend

GET-only routes: `/v1/aegis/status`, `/assessment/{symbol}`, `/decision/{symbol}`, `/conflicts/{symbol}`, `/history`, and `/strategy-eligibility/{strategy_id}`. There are no mutation or execution routes.

The AEGIS Final Decision Intelligence console shows market-closed state, decision/score/quality/coverage/size, advisory/execution/Risk Authorization flags, six hard gates, six component rows, three conflicts, reasons, warnings, missing inputs, and the mandatory no-execution disclaimer. It exposes no controls.

## Authoritative kill switch and readiness

AEGIS consumes the typed read projection from the sole Risk Control store. ACTIVE, UNKNOWN, and CORRUPT each BLOCK with an exact reason; INACTIVE removes only that kill-switch gate and never forces approval. The initialized production state is valid INACTIVE with reason `INITIALIZED_SAFE_DEFAULT`. Closed-market policy therefore remains the current exact hard gate and returns WAIT / MARKET_CLOSED.

`GET /v1/system/open-market-readiness` inspects cached/read-only module projections, the canonical NSE session, Risk Authorization, kill-switch health, and a static AEGIS API-readiness contract. It does not call provider refresh, model inference, broker transport, or state mutation. `GET /v1/system/next-session-plan` derives the next open, first 5-minute close, ten-second grace completion, and ten planned validation steps; every step is explicitly unobserved until the eligible session.

The frontend adds compact readiness and next-session plan projections inside the existing AEGIS console. Existing three-second polling, stale preservation, and advisory-only boundaries remain unchanged.

## Current limitations

ARGUS is weekend-stale, HERMES has no live provider, Personal ORACLE context coverage is limited, and KRONOS ALPHA has no current genuine forecast until an eligible candle-close inference. Readiness therefore reports WAITING_FOR_MARKET with disclosed limitations rather than claiming live readiness. These states are shown truthfully and never replaced with placeholders.

CHRONOS-2 is an independent SHADOW challenger and is deliberately absent from AEGIS input weights and hard gates. Its direct AEGIS influence remains exactly 0%; no Chronos forecast or derived CE/PE quality can approve, size, reject, or block an AEGIS decision in this milestone.

## Order-ledger handoff boundary

The Order & Fill Ledger may store an immutable AEGIS decision identifier, decision value, size cap, source time, and related Risk/session provenance. It never asks AEGIS to execute and never treats advisory approval as broker permission. `WAIT`, `REJECT`, and `BLOCK` fail closed; `APPROVE_REDUCED` must reduce authorized quantity. Risk Authorization remains the absolute veto, and the ledger exposes no broker or Paper mutation path.
