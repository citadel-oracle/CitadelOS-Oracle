# Oracle Phase 6C adversarial validation

Validated from `codex/runtime-truth-20260726` at baseline
`1b5bceb1df12561d4b4dfba2bd82f14ab686946a` on 2026-08-02 IST.

## A. Adversarial test matrix

| Area | Adversarial cases | Authority/proof | Result |
|---|---|---|---|
| TradingView context | Rapid symbol/timeframe flips, underlying/exact-option routing, stale/forming/future context, disconnect/reconnect, restart checkpoint | `TradingViewAutoSyncService`; Phase 6A tests; runtime chart hash `d657c58f...`, `NSE:NIFTY260804C24400`, security `65854`, `5m` | PASS |
| Dhan/exact contract | Symbol/security/expiry/strike/side match, missing/stale quote, rollover, wrong mapping | `ExactOptionAnalysisService`, canonical Dhan mapping/quote; Phase 6A and new Phase 6C identity tests | PASS |
| ARGUS | Antigravity tactical schema, chain/rank lineage, pressure/breadth/persistence, stale/unavailable, cross-contract and cross-expiry rejection | ARGUS tactical edge + canonical Dhan chain; 180 ARGUS/risk/paper tests; new projection tests | PASS |
| VOB | Completed-bar ownership, timeframe, zone lifecycle, stale/fresh transitions | Existing VOB stores and completed-candle services; VOB focused suites | PASS |
| OSE | Exact premium identity, completed candles, EMA/Supertrend/structure, unavailable fields, no fabricated VWAP/Greeks/spread | Existing OSE and completed-option-candle services; OSE focused suites | PASS, with one pre-existing test-harness assertion noted below |
| Decision Envelope | BUY/WAIT/NO_TRADE gates, deterministic WHY/WHY NOT, target/stop/RR lineage, probability-null boundary, provider non-authority | Phase 3/4/6B tests and runtime `NO_TRADE`, execution authority false | PASS |
| Risk/discipline | Cold/failed/stale data, REVIEW/COOLDOWN, duplicate thesis, post-loss re-entry, overtrade, unavailable controls | RiskAuthorizationService + Oracle Discipline V1; Phase 5/6B/risk tests | PASS |
| Position/Guardian | No position, pending/authorized condition, partial/full fill, protection, stop/target, stale feed, disagreement, restart | Isolated `NON-LIVE FIXTURE` Phase 5/paper/Guardian tests only; production phase5 projection unchanged and empty | PASS |
| Transport/runtime | SSE headers, replay/dedup tests, polling fallback, browser reload, rapid changes, frontend/backend restart, parallel GET load | SSE endpoint tests, runtime `SSE_PRIMARY`, 20/20 unique event IDs/hashes, restart recovery health | PASS with performance caveats |
| Knowledge/memory | Relevant retrieval, material conflicts, missing evidence, insufficient history, Constitution, Personal Oracle, Obsidian unavailable/no-sync truth | Phase 4/6B tests and runtime WHY/PROOF | PASS |

## B. Failures found

1. ARGUS provider health could be derived from the exact-option quote before the
   ARGUS snapshot. A fresh quote could therefore mask stale ARGUS evidence.
2. The dashboard adapter represents stale feeds through `feed.error`; the card's
   generic feed helper converted a valid retained `DEGRADED_STALE` ARGUS snapshot
   to `UNAVAILABLE` instead of `STALE`.
3. Exact-contract availability was gated only by the existence of an ARGUS rank
   status, not a full underlying/expiry/strike/side/security-ID chain-leg match.
4. Same-underlying ARGUS evidence could remain visible across an exact-option
   expiry rollover.
5. The prior compact ARGUS card had no deterministic three-row structural spine
   and no expandable seven-strike quantitative lineage.

## C. Repairs made

- Added a pure, deterministic ARGUS provider projection.
- Made the ARGUS tactical snapshot the provider freshness authority; retained
  last-good data is visibly `STALE`, never freshened by a separate quote.
- Added strict current underlying, expiry, chart security ID, option side,
  strike, and exact pressure-leg security-ID checks. Any mismatch removes the
  verdict, pressure, security identity and strike spine from the surface.
- Added the requested compact verdict, CE/PE pressure, three-row ATM/lower/upper
  spine, breadth, persistence, wall/magnet, gamma/blast proxy disclosure,
  provider output, canonical read and WHY.
- Kept all seven strikes and quantitative details in the existing inspection
  drawer. No CSS, geometry, card count, decision policy or backend algorithm was
  changed.

## D. Tests and runtime proof

Focused final results:

- `176 passed, 1 deselected` across Oracle Phase 3/4/5/6A/6B/6C, OSE and VOB.
- `180 passed` across ARGUS tactical/API/v2/reshuffle/market snapshot/intraday,
  risk authorization, paper state and paper autopilot.
- The deselected test is
  `test_argus_selected_contract_technicals_reuse_completed_option_candles`.
  The product result is identical except for truthful per-call performance
  metadata (`cache_hit=false` on first call, `cache_hit=true` on the second),
  while the old assertion requires the complete dictionaries to be identical.
  The touched code does not affect OSE or this test.
- Focused ESLint passed for both touched frontend modules.
- Next.js production build passed, including TypeScript and all production
  routes.

Runtime proof:

- Production `/oracle` rendered exactly six provider cards and one decision hub.
- Current chart: `NSE:NIFTY260804C24400`, normalized
  `NIFTY260804C24400`, exact option security `65854`, expiry `2026-08-04`,
  strike `24400`, `CE`, timeframe `5m`.
- ARGUS: `STALE`, chain source `2026-07-31T15:29:53.286461+05:30`,
  snapshot `524e73f225d8`, CE/PE pressure `44.92/55.08`, breadth `2C/5P`,
  persistence `PUT 1/3`, exact lineage `VERIFIED`.
- Center remained `NO_TRADE`; ARGUS displayed `NO CLEAN SIDE`; the provider did
  not change the center action.
- SSE returned HTTP 200 with `X-Citadel-Transport: SSE_PRIMARY`; no unchanged
  event was emitted during a bounded four-second window. Replay/dedup semantics
  are covered by the Phase 6A endpoint tests.
- Runtime event history contained 20 unique record IDs and 20 unique record
  hashes in the inspected window.
- Frontend restart recovered on bounded attempt 2. Backend restart recovered
  with `restart_recovered=true`, `worker_alive=true`, `backend_owned=true`,
  `browser_page_required=false`, `llm_required=false`.
- The in-app validation browser blocks direct navigation to local port 8000
  (`ERR_BLOCKED_BY_CLIENT`), so its direct mission-runtime fetch surface showed
  `Failed to fetch`; canonical API/CORS checks and the production API tests
  passed independently. This is a validation-client limitation, not evidence of
  mission-store mutation.

## E. Remaining market-hours-only checks

- Observe an actual fresh ARGUS chain transition through `LIVE -> STALE -> LIVE`
  without using retained prior-session data.
- Switch a real chart between underlying, CE and PE, then across the live expiry
  boundary; confirm the new strict lineage gate before and after each switch.
- Observe a completed VOB touch/break/retest sequence and OSE 1m/3m/5m premium
  confirmation on current candles.
- Capture a real SSE change event and reconnect replay while the event producer
  is active.
- Re-measure the deterministic analysis and live-workspace GET path under normal
  market load; current closed-market samples include slow persistence and
  upstream retrievals.
- Validate Obsidian read-only/unavailable transition on the user's actual vault;
  the current runtime truth is `NO_COMPLETED_TRADE_SYNC`.

## F. Safety and no-mutation proof

Before and after values were identical:

```text
paper_only=true
live_trading_enabled=false
broker_submission=false
advisory_only=true
execution_influence=ZERO
execution_authority=false
```

Canonical before/after hashes:

```text
safety + Phase5 projection  e72a6c861e5c68e8bdd18b9461751f492abeaf6c82b63eebc430efa976471e66
mission list                892b4f99a3928a973b23ebc35b4dd9108be3a59a96c96382c691992b20b0c430
paper state                 6ccd0dc0e00c4352633beee4877a268c00c72702613a7ab3615879a74c4d905a
risk state                  c2fe086ba3f9c7c51bab6abac4908884fc07924bb47e4b76b8d39b8b7b5c3aed
```

There was no active mission, authorization, condition, order, position,
protection or Guardian action. No POST trading endpoint was called.

## Performance

- Pure ARGUS projection, 20,000 local iterations: mean `0.0048 ms`, p50
  `0.0027 ms`, p95 `0.0088 ms`, max `1.8683 ms`.
- Parallel read-only load: live-workspace GET 60 samples p95 `2.539 s`;
  dashboard GET 40 samples p95 `0.757 s`; frontend `/oracle` 30 samples p95
  `0.175 s`.
- Runtime telemetry: event publication p95 `1.033 ms`; API serialization p95
  `3.391 ms`; ARGUS retrieval p95 `204.818 ms`; decision envelope p95
  `1.211 ms`; deterministic analysis p95 `8.575 s` with 7 recorded errors in
  11 samples. These are soak observations, not hidden as passing targets.

## G. Market-hours soak decision

**GO for a bounded, paper-only market-hours soak.** This is not approval for
live trading or Phase 7. The soak must retain every safety lock, require exact
lineage on every switch, and treat the latency observations above as explicit
exit/review criteria.
