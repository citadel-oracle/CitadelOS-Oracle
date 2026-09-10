# Codex Oracle R3 final handoff — 2026-08-18

## Scope and final state

Read-only, local-evidence audit of committed R3 plus the current dirty worktree. No services were restarted, no benchmark or soak was rerun, and no production code was changed.

| State | Commit / tag |
|---|---|
| PRE_R3 | `db0a6e8` / `ACCEPTED_CODEX_R2_R2_1_PRE_R3_BASELINE` |
| M1 | `50bb09b` / `R3_MISSION1_PASSED` |
| M2 final | `a523214` / `R3_MISSION2_FINAL_PASSED` (implementation `e963ba1`) |
| M3 / current | `3e73e56841ffce6548ba7e9ef985659c80c22f52` / `R3_MISSION3_PASSED` |

Baseline-to-current committed diff: 97 files, 6,547 insertions, 112 deletions. The worktree is dirty. In particular, uncommitted production changes exist in `src/oracle/market_data_gateway.py` and `src/oracle_development/oracle_dev_service.py`; they are not R3-certified.

## Architecture preserved from R2/R2.1

`DHAN → Market Data Gateway → canonical live market/option state → isolated Flow + Live Analytics → ARGUS/OSE/VOB → isolated Strategy Lab/Price Action → cached Fast Lane → Oracle frontend`.

| Boundary | Audit result | Source evidence |
|---|---|---|
| Market Data Gateway isolated; single subscription owner | PARTIAL | Gateway fan-out remains in `app/main.py`; global Dhan guard works, but a single owner topology is not proven because static direct Option Chain callers remain. |
| Flow isolated | PASS | Gateway fan-out keeps Flow outside request handlers. |
| Live Analytics isolated | PASS | `IsolatedExecutionBoundary("citadel-live-analytics")` in `app/main.py`. |
| Strategy Lab / Price Action isolated | PASS | Separate Strategy Lab boundary and background producers remain. |
| Latest-state / Fast Lane | PASS | `OracleFastLanePublisher` uses cached providers and lean live projection. |
| Heavy analytics outside FastAPI request path | PARTIAL | Fast Lane/history read cache; `/health/ready` and diagnostic endpoints still have observed long timeouts. |

## R3 changes and audit result

### Mission 1 — reliability spine: PARTIAL

Changed `src/oracle/reliability.py`, `src/oracle/isolated_execution_boundary.py`, `src/oracle/canonical_runtime_truth.py`, `src/argus/tactical_store.py`, `src/strategy_lab/storage.py`, and `app/main.py`.

Proven by source and recorded fault artifacts: isolated worker supervision; CURRENT versus LAST_GOOD separation; bounded restart/crash-loop protection; rehydration before healthy; persistence failure degrades rather than kills the worker; VOB freshness model uses evaluation time rather than formation event time.

Recorded evidence: worker death detection 109.86 ms, recovery 122.40 ms; crash-loop threshold 5; rehydration remained unhealthy until first output.

Blocker: `CanonicalRuntimeTruth` is implemented and unit-tested, but current source does not wire it into `app/main.py` readiness. `/health/ready` still uses legacy `oracle_runtime.readiness`. Therefore a single shared Runtime Truth authority across readiness surfaces is not proven and the M1 acceptance claim is not fully preserved.

### Mission 2 — Dhan/provenance and mutation firewall: PARTIAL

Changed `src/broker/dhan_client.py`, `src/argus/tactical_edge.py`, `src/argus/tactical_store.py`, and related tests.

The class-level Dhan option-chain guard is source-proven at at least three seconds using a shared lock and monotonic timestamp. Provenance separates live subscribed LTP/LTT, bid/ask/depth, and subscribed OI/volume from REST Greeks/IV/full-chain/PCR context. Copy boundaries in Tactical Edge prevent cache mutation leaks. Git diff and recorded math identity evidence show no R3 trading-formula change.

Qualification: static direct Option Chain call paths exist outside the documented audit list (`option_chain_engine`, `premium_intelligence/ingest_v3`, API, auth/instrument helpers). The global guard covers DhanClient instances in this process, but an exclusive single-gateway-owner architecture is not proven.

Measured ARGUS fresh-compute medians/p50 from raw arrays: Tactical Edge 7.226 → 3.242 ms (2.23x), full analytics 9.850 → 4.540 ms (2.17x), publication 3.450 → 1.250 ms (2.76x).

### Mission 3 — lean Fast Lane/history split: PARTIAL

Changed `src/oracle/fast_lane_publisher.py` and `app/main.py`.

Live Fast Lane removes/moves history instead of recomputing it: live charts retain tails, ARGUS reduces live evidence/strike breadth, and strategy/Strategy Lab retain small live summaries. History endpoints read the existing canonical/cache projection. No duplicate history calculation was found in their HTTP path.

Measured current hydrated Fast Lane payload during the final 15-minute raw run: 489,580 bytes. Payload size is workload-dependent: a later one-hour workload recorded 1,186,896 bytes, so neither number is a universal contract.

The 10-minute SSE run recorded 1,555 frames, zero reconnects, resyncs, duplicates, or errors. The one-hour observation recorded four 8-second timeouts: three readiness/health calls and one runtime diagnostic call. Fast Lane requests themselves had no errors, but the endpoint failures prevent a full M3/runtime certification.

## Reliability and performance evidence

| Claim | Evidence | Classification |
|---|---|---|
| Queue debt | 15-minute raw: 0; 25-minute raw max: 1; no recorded Flow drops | MEASURED |
| 10-minute SSE | 1,555 frames; reconnect/resync/error/duplicate = 0 | MEASURED |
| Fast Lane, 15-minute steady state | p50 10.621 ms, p95 25.616 ms, p99 211.331 ms, max 301.101 ms; >50 ms 2.97%, >100 ms 2.05%, >200 ms 1.14% | MEASURED |
| Fast Lane, 25-minute plateau run | p50 2.678 ms, p95 20.146 ms, p99 150.096 ms, max 305.144 ms | MEASURED |
| Fast Lane, one-hour live run | p50 2.340 ms, p95 74.010 ms, p99 253.000 ms, max 1,743.740 ms; zero Fast Lane errors | MEASURED |
| Fast Lane composer/HTTP PRE→POST | Raw fair-comparison data exists, but no matched, universal PRE/POST claim was established in this audit | UNPROVEN |
| Overall Oracle speed multiplier | No valid single matched workload | UNPROVEN |

### Memory and latency interpretation

Memory is **STABILIZING, not freeze-certified**. The final 15-minute observer series was non-monotonic: approximately 688 MB start, 803 MB at five minutes, 877 MB at ten, and 816 MB at fifteen. The 30-minute series rose then contracted; its plateau flag was `NO`. This is evidence against a monotonic accumulating leak in these windows and supports no observed unbounded container, but it is not profiler/object evidence of a root cause. The broad process observer can include Uvicorn/related process accounting, so allocation/GC attribution remains a plausible inference, not proof.

Latency distributions differ from microbenchmarks because the longer observations include hydrated payloads, polling/load, startup and background activity. Raw data establishes bounded outliers, not their cause. No sequential raw evidence shows Oracle becoming progressively slower over the observed 15/25/30/60-minute windows. The four one-hour health/diagnostic timeouts are real; their root cause is unproven.

## Runtime Truth and safety invariants

- CURRENT must be fresh, healthy, and rehydrated; LAST_GOOD is separately retained and must never present as CURRENT.
- VOB formation timestamp is content event time, never engine freshness. Freshness must use evaluated-at/heartbeat/source progression.
- Persistence/storage failure must degrade availability, not terminate analytics.
- Dhan subscribed live fields: LTP/LTT from WebSocket Tick; bid/ask/depth from WebSocket Full Depth; subscribed OI/volume from WebSocket Quote. REST supplies Greeks, IV, full-chain/PCR context and must retain its own timestamp.
- `paper_only=true`, `live_trading_enabled=false`, `broker_submission=false`, execution influence ZERO. No R3 broker-execution path was added.

## Remaining certification gaps

1. Wire the existing Canonical Runtime Truth into all readiness/current-state surfaces, then re-certify stale-truth behavior.
2. Resolve/restrict the remaining direct Option Chain caller topology and prove one Dhan gateway owner in production runtime.
3. Diagnose and remove the observed `/health/ready`/diagnostic timeouts with timestamp-correlated evidence.
4. Establish next-open-session source-to-glass latency and live-market certification.
5. VOB/Pine numerical parity, genuine stored 1M proof, and Pullback V2 Track-A parity are intentionally outside R3 certification.

## Future Codex VOB boundary

Oracle R3 is the infrastructure foundation. Future VOB work must not rewrite process isolation, persistence firewall, supervision, Runtime Truth semantics, Dhan guard/provenance, lean Fast Lane, or move heavy work into HTTP paths. It must not alter ARGUS/OSE/Flow mathematics unless a separately evidenced math defect requires it.

The original Pullback V2 Pine source is golden authority. Underlying NIFTY VOB, live ITM-1 option contracts, OSE anchors, frozen episode contracts, and historical parity contracts remain distinct. Track A `VOB_ONLY` must reproduce Pine’s predicate independently of ARGUS/Flow confirmation; Track B confirmed reversal remains separate. One-minute certification requires genuine stored one-minute option candles—never synthetic one-minute data—and replay must be deterministic O(N) or cached, never O(N²) prefix replay.

## Do not regress

1. One Dhan rate guard of at least three seconds; do not timestamp-launder REST fields.
2. Isolated workers, bounded restart, rehydration-before-healthy, and CURRENT/LAST_GOOD separation.
3. Market Data Gateway/Flow/Live Analytics/Strategy Lab/Price Action process boundaries.
4. Fast Lane latest-state cache and on-demand history contract.
5. No heavy analytics or history rebuilding on FastAPI request paths.
6. Paper-only/no broker submission safety state.
7. Separate VOB content event time from engine freshness.
8. No unreviewed production changes in the R3 freeze candidate; current dirty gateway logging and 60-second development refresh changes require separate review.

## Final verified freeze closure

- `FINAL_HEAD=e48f63a9e3108b9834c979623fed4fee7f969225`
- `FINAL_TAG=R3_INFRA_FREEZE_VERIFIED`
- `ORACLE_INFRA_STATUS=FROZEN` after the exact-HEAD regression suite.
- Canonical Runtime Truth is the sole public readiness authority; legacy readiness output cannot override its public status fields.
- Exactly one continuous Option Chain producer is registered by startup: `argus.start_cache_producer` → `ArgusAPI._cache_producer_loop` → `ArgusAPI._get_oi` → `DhanClient.get_option_chain`, with the ARGUS market snapshot callback retained in the same producer fanout.
- The topology test includes an in-memory second-producer negative control and rejects the duplicate.
- Health-timeout repair remains closed; Dhan production delta is guard-only and safe; no production trading math or safety invariant changed.

## Final verdict

`CODEX_R3_AUDIT=PASS`. `ORACLE_INFRA_FREEZE_READY=YES`; `ORACLE_INFRA_FROZEN=YES`; `READY_FOR_CODEX_VOB=YES`.

Pending by design: next-open live-market certification, source-to-glass measurement, VOB/Pine exact parity, and genuine real-data 1M VOB parity.
