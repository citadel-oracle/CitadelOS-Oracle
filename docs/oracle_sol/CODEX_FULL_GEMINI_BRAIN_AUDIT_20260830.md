# CITADEL GEMINI MARKET BRAIN — CODEX ADVERSARIAL AUDIT

Audit date: 2026-08-30 (IST)  
Repository: `/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9`  
Auditor role: independent principal engineer / adversarial architecture reviewer  
Mission mode: audit only; no production repair, trading-logic change, VOB change, commit, reset, stash, checkout, or revert performed.

## 1. EXECUTIVE VERDICT

**NOT_READY**

The current implementation is not ready for a prospective live shadow test. The primary blocker is not Gemini's reasoning quality; it is that the live handoff does not match the extractor's contract. `app/main.py` passes an `OracleAssessment`, a nested ARGUS projection, and a differently shaped Order Flow projection into an extractor that expects flat sensorium fields. The runtime snapshot observed during this audit consequently contained no spot, futures, basis, option/OI, flow, volatility, or GEX facts and remained `UNAVAILABLE`.

Six P0 defects can create false semantics, contaminate trust/provenance, cross a session boundary, or leak credentials. The most dangerous UI case is exact: when domestic data is `HEALTHY` but Gemini is unavailable or returns malformed output, the backend correctly emits `market_verdict=null`; React then converts that to the `NO_TRADE` state and passes `operationalStatus="HEALTHY"`, rendering the balanced `NO TRADE` experience. A separate transport outage preserves the last CALL/PUT indefinitely.

Spark is supplementary in the prompt and has no broker methods, but its effective trust boundary fails: an unauthenticated local POST caller may set `is_test_fixture=true`, supply a mock verification record, and thereby obtain `VERIFIED` / `CONNECTED` status that is projected to Gemini. The current quarantined incident ID `ctx_spark_radar_20260830_1720` is absent from the active store and all searched projections, but the direct ledger rewrite left no tombstone or reconstructable quarantine trail.

VOB isolation is **proven for the current, actually wired request path**: the selected sources are Oracle assessment, direct Order Flow, and pre-VOB ARGUS coherent projection; VOB and Option Buyer projections are not passed. This proof is narrower than the self-declared field registry and is partly vacuous because the live projection is empty. Future wiring of `OptionBuyerIntelligence` requires a fresh lineage review because its contract selection reads `vob.current_itm1_contracts`.

Finding count: **P0 6 · P1 15 · P2 7 · P3 3**.

## 2. AUDIT SCOPE

The audit started from the actual working tree and runtime, not prior reports. Eighty directly related files were inspected or searched in these categories:

- All 19 files under `src/oracle_sol/`, plus `src/api/oracle_sol_api.py` and the integration points in `app/main.py`.
- Seven upstream lineage/ownership files: `src/oracle/oracle_service.py`, `src/oracle/isolated_market_data_gateway.py`, `src/oracle/fast_lane_publisher.py`, `src/oracle/option_buyer_intelligence.py`, `src/oracle/resolver_engine.py`, `src/oracle_development/oracle_dev_service.py`, and `src/vob/reversal.py`.
- Nine frontend/config/test files: both Gemini/Living Market Forces TSX and CSS modules, the integration test, `OracleWorkspacePanel.tsx`, institutional exports, `package.json`, and `tsconfig.json`.
- All five MP4s under `citadel-dashboard/public/market_forces/`.
- Both Oracle/Sol backend test files; the real-smoke, Spark-ingest, Spark-test, keychain, and frontend-rebuild scripts.
- All 11 files in `data/sol_shadow/` and all 16 existing `docs/oracle_sol/` documents (prior reports were treated as claims, not proof).
- `.env`, `.gitignore`, `.vscode/settings.json`, and `requirements.txt`.
- Live processes, listeners, `GET /v1/oracle/sol/state`, `GET /v1/oracle/sol/external-context`, `GET /v1/oracle/runtime-diagnostic`, `GET /v2/dashboard`, the served `/oracle` page, state response sizes, and build/runtime timestamps.

Safe verification performed:

- Backend: **54 passed, 1 deliberately deselected** in an isolated temporary working directory with Gemini credentials unavailable and bytecode/cache disabled. The deselected test requires a repository-relative historical log.
- Frontend: **15 passed** via `npm run test:gemini-brain`.
- Next production build: compiled successfully and completed its TypeScript/static output; `.next/BUILD_ID` updated. No service restart was performed.
- Runtime GETs and process inspection only; no POST, synthetic ingest, broker action, session mutation, provider call, or trade action was made.

## 3. CURRENT GIT / RUNTIME STATE

### Required preservation record

| Item | Observed value |
|---|---|
| `CURRENT_HEAD` | `3fa6c89248408a62aac17bfc50d166c842a01e44` |
| Branch | `checkpoint/vob-photonic-preintegration-current-oracle-20260816` |
| Tracked dirty files | 167 |
| Untracked entries | 36 |
| Total porcelain entries before this report | 203 |
| `git diff --stat` | 167 files changed, 4,667 insertions, 983 deletions |

The worktree was not cleaned. Relevant untracked areas include all of `src/oracle_sol/`, the Sol API router, both new UI components and test, five videos, `data/`, `docs/oracle_sol/`, fixtures, scripts, and `tests/oracle_sol/`. Relevant tracked changes include `app/main.py`, Oracle integration/UI/store files, Option Buyer, Resolver, VOB, OSE, ARGUS, tests, `package.json`, and `tsconfig.json`. The implementation being audited is intentionally not limited to a clean commit.

### Runtime evidence

| Runtime fact | Evidence |
|---|---|
| Backend owner | PID 19254, bound to `127.0.0.1:8000`, cwd is this repository |
| Backend start | 2026-08-30 14:08:34 IST, without `--reload` |
| Stale backend proof | `service.py` mtime 16:29:56 and `external_context.py` mtime 17:23:19, both after process start |
| Python environment | Interpreter comes from `/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha`, not this checkout |
| Frontend owner | One `next-server` PID 34760 on port 3000; production `next start` |
| Frontend build | Source predates current `.next/BUILD_ID`; served `/oracle` returned 200 with Gemini/Radar markers |
| Dhan owner | `WS_OWNER_COUNT=1`, child PID 19290; one isolated gateway in code and runtime |
| Dhan status | DOWN / reconnect wait; last rejection HTTP 429; two expected instruments stale |
| Sol state | `system_status=UNAVAILABLE`, `market_verdict=null`, `reasoning_status=NOT_INVOKED` |
| Sol snapshot | All requested market-value domains null/unavailable; identity degraded, replay-stable false |
| Provider | Configured model `gemini-3.7-flash`; key-present boolean true; successful calls 0 |
| Shadow ledger | 1,355 valid JSONL cycles, 7.1 MB; sessions include 2026-08-21/28/29/30 and missing session values; no successful Gemini verdict observed |
| External context | Active ID `ctx_spark_radar_20260830_1414`; 11 items, all unverified, source verification not connected |

The backend/source timestamp mismatch means source inspection and live GET evidence describe different revisions. Both were audited; runtime behavior must not be used as proof that the currently saved Python source is deployed.

## 4. ARCHITECTURE VERIFIED

| Boundary | Result | Evidence-backed conclusion |
|---|---|---|
| CITADEL owns calculations | **PARTIAL** | Extractor does not recalculate basis or metrics, but the actual producer handoff does not supply the declared fields. |
| Gemini contextual/temporal only | **PASS, conditional on input** | Prompt forbids calculation; request contains snapshots/events/prior thesis/external context; no broker or execution call exists. |
| Frontend presentation only | **FAIL** | React resolves contradictory verdict/developing-state combinations and converts missing verdicts to `NO_TRADE`. |
| Spark supplementary only | **PARTIAL** | No direct verdict setter or broker action; trust/authentication and staleness controls fail. |
| VOB-free Gemini path | **PASS for current path** | Exact call graph excludes VOB/Option Buyer feeds; see §12. |
| VOB subsystem preserved | **PASS in audit scope** | No VOB files were modified by this audit; integration ordering is chart → Gemini → VOB command. |
| One-way animation | **PASS** | Video/canvas state never writes market verdict or calls backend. |
| Single Dhan owner | **PASS in audited process** | One isolated gateway constructor/start and runtime `WS_OWNER_COUNT=1`. |
| Operational vs market state | **FAIL** | Healthy-data/provider-failure becomes semantic `NO_TRADE`; stale transport retains previous market state. |
| Live/replay/shadow separation | **FAIL** | Replay flag is never set by a production path; shadow ledger mixes test/historical/live cycles. |

## 5. P0 FINDINGS

### P0-01 — Provider failure or invalid output is rendered as semantic NO_TRADE

- **ID:** P0-01
- **SEVERITY:** P0
- **SUBSYSTEM:** Five-state frontend / truth firewall
- **FILE:** `citadel-dashboard/src/components/institutional/GeminiMarketBrainSection.tsx:232-262`; `LivingMarketForcesViewport.tsx:87-101`
- **LINE / FUNCTION:** `GeminiMarketBrainSection` state decomposition and `derivedState`; viewport operational fallback
- **OBSERVED CODE/EVIDENCE:** Backend failure paths deliberately return `system_status=HEALTHY`, `market_verdict=None`, and `DEGRADED_ADVISORY`/`OUTPUT_INVALID` when market data is healthy but Gemini is offline or malformed. React sets `isSystemUnavailable=true` because verdict is absent, then sets `operationalStatus` to the beacon's value (`HEALTHY`), defaults `derivedState` to `NO_TRADE`, and the viewport therefore treats the system as operational and shows `NO TRADE / BALANCED`.
- **WHY IT IS A PROBLEM:** `UNAVAILABLE != NO_TRADE` is a non-negotiable truth-firewall invariant. A missing/invalid model answer becomes a financial interpretation.
- **REAL FAILURE MODE:** Healthy Dhan/ARGUS data plus Gemini 429, 503, timeout, malformed JSON, invalid citation, or invalid verdict produces a convincing balanced NO_TRADE display instead of reasoning unavailable.
- **CURRENT TEST COVERAGE:** Frontend test 9 manually passes `operationalStatus="UNAVAILABLE"`; it never renders the real healthy-data/null-verdict combination. Backend quota/malformed tests assert only `beacon.market_verdict is None`.
- **MINIMAL REPAIR SUGGESTION:** Add an explicit non-market renderer state (or pass `UNAVAILABLE` operational status) whenever verdict is null or reasoning is not active; do not map that branch through `LivingMarketState`.
- **TEST THAT SHOULD PROVE THE REPAIR:** Mount with `system_status=HEALTHY`, `market_verdict=null`, each failure reasoning status, and assert no NO_TRADE label, balanced semantic label, or canonical five-state class appears.
- **CONFIDENCE:** HIGH

### P0-02 — Unauthenticated Spark callers can self-promote mock verification to VERIFIED

- **ID:** P0-02
- **SEVERITY:** P0
- **SUBSYSTEM:** Spark trust boundary / API authorization
- **FILE:** `src/api/oracle_sol_api.py:104-129`; `src/oracle_sol/external_context.py:272-330, 408-415, 455-477`; `spark_mcp_boundary.py:70-87`
- **LINE / FUNCTION:** `ingest_external_context`, `validate_external_context_payload`, `CitadelFactVerificationEngine.verify_fact_item`
- **OBSERVED CODE/EVIDENCE:** The POST endpoint has no authentication, capability token, request-origin restriction, or production/test-mode gate. Payload controls `is_test_fixture` or `source_type=TEST_FIXTURE`. That branch trusts caller-supplied `verification_record`, `authoritative_source_id`, `evidence_hash`, and `match_verdict`, promoting `MATCH` to `VERIFIED`. Verified items make `source_verification_status=CONNECTED` and are projected to Gemini.
- **WHY IT IS A PROBLEM:** The code comment says the fixture path is permitted strictly inside tests, but the public local endpoint exposes it in the production service. Any local process/browser-capable attacker can manufacture authoritative external facts.
- **REAL FAILURE MODE:** A caller POSTs a same-session test fixture with a forged MATCH record; Oracle shows CONNECTED/VERIFIED and the next eligible Gemini cycle treats it as verified external context.
- **CURRENT TEST COVERAGE:** Tests prove both live records remain unverified and test records promote; none proves production ingress rejects test fixtures or requires authorization.
- **MINIMAL REPAIR SUGGESTION:** Reject test-fixture flags at the production HTTP boundary; require a local capability/auth token for ingest and reload; keep mock verification construction inside test-only code.
- **TEST THAT SHOULD PROVE THE REPAIR:** Production-router test POSTing `is_test_fixture=true` and `source_type=TEST_FIXTURE` must return 403/422; unauthenticated live ingest/reload must fail; an isolated test-only store may still exercise mock verification.
- **CONFIDENCE:** HIGH

### P0-03 — Test and custom-storage services write into the production shadow ledger

- **ID:** P0-03
- **SEVERITY:** P0
- **SUBSYSTEM:** Shadow persistence / live-replay-test isolation
- **FILE:** `src/oracle_sol/service.py:64-76`; `src/oracle_sol/shadow_ledger.py:28-40`; tests at `test_oracle_sol.py:201-222, 393-418, 491-506` and `test_external_context.py:175-196`
- **LINE / FUNCTION:** `SolMarketBrainService.__init__`
- **OBSERVED CODE/EVIDENCE:** `storage_dir` is passed to story, event, thesis, and external stores, but `self.shadow_ledger = SolShadowLedger()` ignores it. Tests constructing `SolMarketBrainService(storage_dir=tmp_path)` therefore append cycles to relative `data/sol_shadow/sol_shadow_cycles.jsonl` unless the whole process cwd is changed. Current ledger evidence: 1,355 cycles across multiple sessions (including 2026-08-21/28/29/30 and null session values), test context IDs, and no successful model calls.
- **WHY IT IS A PROBLEM:** The claimed immutable live audit ledger is cross-contaminated by tests, historical frames, and arbitrary service instances. Replay and certification evidence cannot be classified reliably.
- **REAL FAILURE MODE:** A test or smoke script run from repository root records a healthy replay CALL beside live cycles; downstream review mistakes it for live shadow behavior or duplicate writers contend on DuckDB.
- **CURRENT TEST COVERAGE:** Tests pass only because they do not assert ledger path ownership; the audit had to move pytest's cwd to an isolated temporary directory to avoid contaminating the repository.
- **MINIMAL REPAIR SUGGESTION:** Derive shadow JSONL/DuckDB paths from the same `storage_dir`, require an explicit runtime mode in every record, and prohibit production path use from test mode.
- **TEST THAT SHOULD PROVE THE REPAIR:** Instantiate two services with distinct temp roots, process cycles, and assert byte-for-byte that neither writes outside its root and that records carry `LIVE/REPLAY/TEST` mode.
- **CONFIDENCE:** HIGH

### P0-04 — Loss of both frontend transports preserves a stale CALL/PUT as live indefinitely

- **ID:** P0-04
- **SEVERITY:** P0
- **SUBSYSTEM:** Frontend freshness / operational state
- **FILE:** `citadel-dashboard/src/components/institutional/GeminiMarketBrainSection.tsx:180-222, 264-276`
- **LINE / FUNCTION:** `useEffect` fetch/SSE transport
- **OBSERVED CODE/EVIDENCE:** Poll failures are silently caught without clearing or aging `data`; EventSource has no `onerror` state. No client receipt timestamp, server revision, or expiry condition exists. All presentation continues from the last object.
- **WHY IT IS A PROBLEM:** A last known CALL/PUT can remain visually dominant after backend death, network partition, CORS failure, laptop sleep, or server restart.
- **REAL FAILURE MODE:** UI receives CALL while healthy; backend stops; every 3-second GET fails and SSE closes; CALL video, LIVE telemetry, and thesis remain unchanged forever.
- **CURRENT TEST COVERAGE:** No mounted client test, transport failure test, fake-timer test, or stale-state expiry test exists.
- **MINIMAL REPAIR SUGGESTION:** Track last successful canonical receipt/revision and transition operational state to `UNAVAILABLE` on transport loss without altering the stored market verdict.
- **TEST THAT SHOULD PROVE THE REPAIR:** Fake GET/SSE success with CALL, then fail both transports and advance time; assert operational unavailable, explicit last-known labeling, and no dominant animation.
- **CONFIDENCE:** HIGH

### P0-05 — Secrets are exposed to repository and URL-level leakage paths

- **ID:** P0-05
- **SEVERITY:** P0
- **SUBSYSTEM:** Secrets / repository security / Gemini REST fallback
- **FILE:** tracked `.env`; `src/oracle_sol/gemini_adapter.py:202-214`
- **LINE / FUNCTION:** REST fallback URL construction
- **OBSERVED CODE/EVIDENCE:** `.env` is tracked (`git ls-files .env`) and contains live-looking broker/API credentials, including a JWT-shaped Dhan access token; no value is reproduced here. Gemini REST fallback interpolates the Gemini API key into the query string. Query strings may appear in exceptions, HTTP/proxy diagnostics, access logs, browser/history tooling, and tracing systems.
- **WHY IT IS A PROBLEM:** Credential disclosure can permit data access or broker/account abuse. The mission severity definition explicitly classifies secret leakage as P0.
- **REAL FAILURE MODE:** Repository copy/history exposes current broker credentials; REST request logging captures a full Gemini URL containing the key.
- **CURRENT TEST COVERAGE:** `test_gemini_key_never_exposed_in_state_or_logs` only serializes initial service state and searches two strings. It does not inspect Git, URLs, exceptions, request mocks, or access logs.
- **MINIMAL REPAIR SUGGESTION:** Rotate exposed credentials; remove `.env` from tracking/history under an approved secret-remediation procedure; send Gemini key in `x-goog-api-key` header and redact request URLs/errors.
- **TEST THAT SHOULD PROVE THE REPAIR:** Secret scanner over tracked history; mocked REST request asserts no key in URL/body/logs/errors and key only in redacted header handling.
- **CONFIDENCE:** HIGH

### P0-06 — An old-session in-flight Gemini result can overwrite the new session

- **ID:** P0-06
- **SEVERITY:** P0
- **SUBSYSTEM:** Session concurrency / reasoning worker
- **FILE:** `src/oracle_sol/service.py:152-184, 186-235`; `reasoning_protocol.py:268-315`; `thesis_memory.py:288-315`
- **LINE / FUNCTION:** `ingest_snapshot`, `_process_snapshot_sync`, `update_thesis`
- **OBSERVED CODE/EVIDENCE:** The single worker serializes calls, but session rotation occurs on the ingest thread while a prior provider call may still be in flight. Rotation resets shared thesis/story/memory immediately. The old call carries no session generation check; on return, orchestrator writes its old-session thesis into the newly reset `ThesisMemory`, then service publishes its beacon as latest.
- **WHY IT IS A PROBLEM:** Session isolation is violated precisely at the market-date boundary, allowing yesterday's evidence to become today's current interpretation.
- **REAL FAILURE MODE:** Friday's slow CALL request is in flight; Monday/opening-session snapshot rotates state; Friday response returns and becomes a live CALL in Monday's UI/active thesis.
- **CURRENT TEST COVERAGE:** The “session rotation” test exercises only story-builder baseline reset with no worker/provider overlap. No concurrency barrier test exists.
- **MINIMAL REPAIR SUGGESTION:** Capture session ID/generation at enqueue and compare immediately before every thesis/beacon/ledger commit; discard or explicitly ledger-tag obsolete results.
- **TEST THAT SHOULD PROVE THE REPAIR:** Blocking fake adapter spans a session change; release old response and assert it cannot mutate new-session thesis/beacon/history.
- **CONFIDENCE:** HIGH

## 6. P1 FINDINGS

### P1-01 — The live Gemini input handoff does not match the extractor contract

- **ID:** P1-01
- **SEVERITY:** P1
- **SUBSYSTEM:** Canonical sensorium integration
- **FILE:** `app/main.py:2603-2625`; `src/oracle_sol/snapshot_extractor.py:80-311`; `src/oracle/oracle_service.py:55-76`
- **LINE / FUNCTION:** `_oracle_fast_base_projection`, `extract_sol_evidence_snapshot`
- **OBSERVED CODE/EVIDENCE:** Sol receives `oracle_service.assess().to_dict()` (fields such as `input_features.close`, not `spot_ltp`/`dhan_connected`), `order_flow_service.latest_projection`, and `cached_argus_projection`. The extractor expects flat values in each feed's `data`; the cached ARGUS projection itself contains another `data` layer. Option Buyer/OSE are not passed despite the field registry naming Option Buyer as owner. Runtime snapshot had every requested value unavailable.
- **WHY IT IS A PROBLEM:** The market brain cannot observe the system it claims to reason over.
- **REAL FAILURE MODE:** Even when upstream producers recover, most or all fields remain null or nested out of reach; provider invocation stays suspended or reasons from materially incomplete evidence.
- **CURRENT TEST COVERAGE:** Backend fixtures manufacture the extractor's ideal flat shape; no test feeds an actual `_oracle_fast_base_projection` or captured `/v2/dashboard` document end to end.
- **MINIMAL REPAIR SUGGESTION:** Add one explicit backend projection adapter from real producer contracts to `SolEvidenceSnapshot`; do not change calculations or trading rules.
- **TEST THAT SHOULD PROVE THE REPAIR:** Feed a captured real Fast Lane revision through the exact production handoff and assert field availability/source IDs/timestamps against upstream values.
- **CONFIDENCE:** HIGH

### P1-02 — Frontend snapshot schema is incompatible and falsely labels empty domains AVAILABLE

- **ID:** P1-02
- **SEVERITY:** P1
- **SUBSYSTEM:** Frontend canonicality / “GEMINI IS READING”
- **FILE:** `GeminiMarketBrainSection.tsx:50-65, 280-286, 668-710`; backend `contracts.py:224-261`
- **LINE / FUNCTION:** `SolSnapshotState`, reading strip, evidence deck
- **OBSERVED CODE/EVIDENCE:** React expects `spot_price`, `futures_price`, `total_call_oi`, `pcr_oi`, `iv_skew`, dominant strikes, and `expected_move`. Backend emits `spot_ltp`, `futures_ltp`, `strike_ladder`, `skew_25d/10d`, and `expected_move_pts`, and never emits totals/PCR/walls. When no expected number exists but a snapshot object exists, React reports `AVAILABLE` for Futures, Options/OI, Flow, and Volatility.
- **WHY IT IS A PROBLEM:** The UI claims Gemini is reading domains that are unavailable and blanks facts that do exist under different names.
- **REAL FAILURE MODE:** Current runtime shows an empty snapshot yet active-colored AVAILABLE chips; users overestimate evidence coverage.
- **CURRENT TEST COVERAGE:** The SSR test checks labels exist; it never injects the real backend JSON or asserts chip values.
- **MINIMAL REPAIR SUGGESTION:** Generate/validate the TS contract from backend schema and drive domain status from backend `availability_matrix`, never object existence.
- **TEST THAT SHOULD PROVE THE REPAIR:** Contract fixture from `/state` must render backend field values and `UNAVAILABLE` for empty domains.
- **CONFIDENCE:** HIGH

### P1-03 — Contradictory five-state combinations are legal and React chooses financial precedence

- **ID:** P1-03
- **SEVERITY:** P1
- **SUBSYSTEM:** Five-state contract
- **FILE:** `contracts.py:360-367`; `reasoning_protocol.py:197-227`; `GeminiMarketBrainSection.tsx:239-262`
- **LINE / FUNCTION:** structured schema, model parsing, `derivedState`
- **OBSERVED CODE/EVIDENCE:** Schema independently permits any verdict and developing state. Orchestrator does not reject `CALL + PUT_DEVELOPING` or `PUT + CALL_DEVELOPING`; invalid developing state silently becomes `NONE`. React applies precedence: CALL, PUT, CALL_DEVELOPING, PUT_DEVELOPING, NO_TRADE, fallback NO_TRADE.
- **WHY IT IS A PROBLEM:** React performs forbidden market-state resolution, and backend does not own one canonical state.
- **REAL FAILURE MODE:** Model emits CALL with PUT_DEVELOPING; UI displays CALL and hides contradiction. Null/invalid verdict with a developing state may display developing; any other invalid combination becomes NO_TRADE.
- **CURRENT TEST COVERAGE:** No conflict matrix exists.
- **MINIMAL REPAIR SUGGESTION:** Backend validates allowed verdict/developing pairs and emits one canonical five-state field; invalid combinations fail closed operationally.
- **TEST THAT SHOULD PROVE THE REPAIR:** Exhaustive cross-product test of verdict/developing values plus frontend assertion that it renders only backend canonical state.
- **CONFIDENCE:** HIGH

### P1-04 — External-context time, staleness, and as-of semantics are unsafe

- **ID:** P1-04
- **SEVERITY:** P1
- **SUBSYSTEM:** Spark temporal trust / TODAY filtering
- **FILE:** `external_context.py:401-415, 590-598, 604-680`; `GeminiMarketBrainSection.tsx:300-385`
- **LINE / FUNCTION:** validator timestamps, `get_context_as_of`, health summary, Today filter
- **OBSERVED CODE/EVIDENCE:** Producer controls received/generated/event times without ISO parsing or future checks. As-of uses lexical string comparison and latest append, not normalized instant/max receipt. No age computation ever emits `STALE`; any active same-session payload is `AVAILABLE`. React compares UTC date prefixes to an IST session date, treats items with only `event_time_ist` as today, treats every non-today date (including future) as prior/“LAST AVAILABLE,” and has no browser-independent timestamp normalization. The current payload's 2026-08-31 GIFT scheduled event is eligible for a “LAST AVAILABLE” market-movement label on 2026-08-30.
- **WHY IT IS A PROBLEM:** Lookahead, stale reuse, old-news-as-today, and future-event mislabeling are possible.
- **REAL FAILURE MODE:** Friday observation with only IST time appears in Sunday Today; an offset-equivalent timestamp sorts incorrectly; a future scheduled instrument fact appears as last observed market movement.
- **CURRENT TEST COVERAGE:** One lexical Z-format as-of happy path; no offset, malformed, future, weekend, closed-market, only-IST, or stale-age cases.
- **MINIMAL REPAIR SUGGESTION:** Normalize/validate instants server-side, stamp receipt server-side, emit explicit temporal class (`TODAY`, `LAST_AVAILABLE`, `FUTURE_EVENT`, `TIMESTAMP_UNKNOWN`, `STALE`), and let React only render it.
- **TEST THAT SHOULD PROVE THE REPAIR:** IST midnight, Friday-to-Sunday, future Monday event, offset-equivalent ISO, unknown timestamp, and stale payload table tests.
- **CONFIDENCE:** HIGH

### P1-05 — External-context identity, reload, and quarantine history are mutable and ambiguous

- **ID:** P1-05
- **SEVERITY:** P1
- **SUBSYSTEM:** Spark store / quarantine / reload endpoint
- **FILE:** `external_context.py:495-510, 535-584`; `oracle_sol_api.py:140-148`; `external_context_history.jsonl`
- **LINE / FUNCTION:** context ID, `ExternalContextStore.append/reload`
- **OBSERVED CODE/EVIDENCE:** Producer controls `external_context_id`; duplicates are appended without same-ID/hash collision checks. Current file contains `ctx_spark_real_20260830_1253` four times with four distinct provenance hashes. Store/reload has no lock; reload clears live dictionaries before silent best-effort hydration and endpoint is unauthenticated. Append flushes but does not fsync. The quarantined ID has zero occurrences and there is no tombstone/quarantine event.
- **WHY IT IS A PROBLEM:** Identity is not immutable, reload can race reasoning/ingest, and direct removal destroys reconstructability.
- **REAL FAILURE MODE:** Same ID means four payloads; reload during read yields transient none or older append; a corrupt line is silently skipped; a rewritten ledger cannot prove what was quarantined or why.
- **CURRENT TEST COVERAGE:** No duplicate collision, reload race, durability, corrupt-line telemetry, or append-only quarantine test.
- **MINIMAL REPAIR SUGGESTION:** Server-generate/validate ID from content, reject same-ID/different-hash, lock atomic rehydrate/swap, fsync, and quarantine with append-only revocation/tombstone records.
- **TEST THAT SHOULD PROVE THE REPAIR:** Duplicate same/different payload tests, concurrent reload/read/append test, corrupt-line health test, and tombstone replay proof.
- **CONFIDENCE:** HIGH

### P1-06 — Event/baseline/thesis persistence is not transactionally ordered as claimed

- **ID:** P1-06
- **SEVERITY:** P1
- **SUBSYSTEM:** Event-sourced memory / durability
- **FILE:** `service.py:161-184`; `event_sourced_memory.py:135-175`; `event_story_builder.py:107-118`; `thesis_memory.py:173-183, 238-285`; `shadow_ledger.py:143-190`
- **LINE / FUNCTION:** ingest transaction, append batch, baseline/thesis/ledger writes
- **OBSERVED CODE/EVIDENCE:** Service publishes `_latest_snapshot` before event commit. Batch append is a loop of individually durable records, so a batch can partially commit. Baseline assigns `_last_snapshot` before a non-atomic, non-fsynced overwrite and swallows write failure. Thesis/expectation/evaluation writes mutate memory before non-atomic writes and mostly lack fsync. Shadow JSONL lacks flush/fsync and records success independently of DuckDB.
- **WHY IT IS A PROBLEM:** Memory, JSON, JSONL, and DuckDB can disagree after crash or I/O failure.
- **REAL FAILURE MODE:** Partial event batch survives, baseline advances only in memory, API exposes uncommitted snapshot, or active thesis file truncates during power loss.
- **CURRENT TEST COVERAGE:** Failure injection mocks event append only and checks in-memory baseline; it does not fail baseline write, crash mid-batch, or restart from partial files.
- **MINIMAL REPAIR SUGGESTION:** Atomic temp-write+fsync+rename for state files, one durable batch transaction/commit marker, and publish in-memory state only after commit.
- **TEST THAT SHOULD PROVE THE REPAIR:** Crash/failure injection at every ordering boundary followed by fresh-process hydration and exact state comparison.
- **CONFIDENCE:** HIGH

### P1-07 — Snapshot identity and replay proof do not protect same-ID/different-payload or unavailable cycles

- **ID:** P1-07
- **SEVERITY:** P1
- **SUBSYSTEM:** Identity / duplicate handling / replay
- **FILE:** `snapshot_extractor.py:98-123, 319-334`; `event_story_builder.py:169-171`; `replay.py:33-75`; `reasoning_protocol.py:319-359`
- **LINE / FUNCTION:** snapshot ID generation, duplicate check, replay verifier
- **OBSERVED CODE/EVIDENCE:** Missing source timestamp substitutes wall-clock now, generating a new snapshot ID each poll for identical missing data. Story builder treats identical `snapshot_id` as duplicate without comparing payload hash, so a manually supplied same ID/different payload is silently skipped then committed. Identical snapshots still enqueue/reason/ledger. Unavailable cycles store empty `input_hash`; replay declares them verified whenever original hash is absent.
- **WHY IT IS A PROBLEM:** Duplicate/collision guarantees and “bit-exact replay” claims are false at important edges.
- **REAL FAILURE MODE:** Empty feed creates thousands of unique fail-closed cycles; same ID with changed facts produces no events; empty-envelope replay reports verified.
- **CURRENT TEST COVERAGE:** Tests assert ID length and one happy replay hash; no same-ID/different-payload, missing timestamp dedupe, or empty-hash rejection.
- **MINIMAL REPAIR SUGGESTION:** Require canonical timestamp/ID for live eligibility, bind ID to payload hash, reject collision, suppress duplicate reasoning, and require nonempty original hash for replay success.
- **TEST THAT SHOULD PROVE THE REPAIR:** Cases M/N/O from §22 with restart and collision assertions.
- **CONFIDENCE:** HIGH

### P1-08 — SSE frames are malformed after the initial event and polling can overwrite newer SSE state

- **ID:** P1-08
- **SEVERITY:** P1
- **SUBSYSTEM:** API streaming / frontend race
- **FILE:** `service.py:354-365`; `oracle_sol_api.py:36-67`; `GeminiMarketBrainSection.tsx:184-212`
- **LINE / FUNCTION:** `_broadcast_sse`, `event_generator`, client state merge
- **OBSERVED CODE/EVIDENCE:** Service queues an already formatted Python string containing `event:`/`data:`. API then executes `bytes + frame + bytes`, a `TypeError` for the first broadcast. Separately, SSE beacon and 3-second whole-state GET have no revision/timestamp guard; a slow older GET can overwrite a newer SSE beacon.
- **WHY IT IS A PROBLEM:** Real-time updates fail and remaining dual transports race.
- **REAL FAILURE MODE:** Initial SSE/heartbeats work, first market update terminates stream; or new CALL SSE is overwritten by old GET state.
- **CURRENT TEST COVERAGE:** No API streaming test or client transport race test.
- **MINIMAL REPAIR SUGGESTION:** Queue JSON bytes/object only, frame once at API, attach monotonic revision, and reject older updates in one state owner.
- **TEST THAT SHOULD PROVE THE REPAIR:** ASGI SSE test through first broadcast plus delayed-GET/newer-SSE ordering test.
- **CONFIDENCE:** HIGH

### P1-09 — Gemini 3.7 provider configuration is mislabeled and operationally incomplete

- **ID:** P1-09
- **SEVERITY:** P1
- **SUBSYSTEM:** Gemini adapter / provider contract
- **FILE:** `gemini_adapter.py:75-86, 111-160, 198-279`; `requirements.txt`
- **LINE / FUNCTION:** `GeminiModelAdapter.invoke_reasoning`
- **OBSERVED CODE/EVIDENCE:** Model ID `gemini-3.7-flash` is current. However telemetry/envelope report `thinking_level="medium"` while SDK and REST send `thinking_budget=1024`. Official Google guidance recommends `thinkingLevel` for Gemini 3 and lists 3.7 Flash levels low/medium/high; 1024 is not proof of medium. SDK client ignores `timeout_seconds` and explicit retry configuration even though installed SDK supports `HttpOptions.timeout/retry_options`. 429 returns immediately; 503 retry uses string matching/fixed sleeps. `google-genai` 2.20.0 is installed in the borrowed runtime venv but not declared in repository requirements, making the REST fallback likely on a clean install.
- **WHY IT IS A PROBLEM:** Runtime behavior and telemetry diverge; calls can hang and clean deployments take a less-tested secret-bearing fallback.
- **REAL FAILURE MODE:** Operator believes medium thinking is active; provider call exceeds expected 30 seconds; clean deploy falls back to REST; quotas cause burst failures.
- **CURRENT TEST COVERAGE:** Mock only checks JSON parse and model name; no config introspection, timeout, retry, 429/503 sequence, Retry-After, or clean dependency installation.
- **MINIMAL REPAIR SUGGESTION:** Use documented `thinking_level="medium"`, configured `HttpOptions`, declare/pin SDK, and centralize bounded retry policy.
- **TEST THAT SHOULD PROVE THE REPAIR:** Inspect mocked SDK config/client options; deterministic 429/503/timeout tests; clean-environment import test.
- **CONFIDENCE:** HIGH

Official verification: [Gemini 3.7 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash), [Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking), and [Python Gen AI SDK HTTP options](https://googleapis.github.io/python-genai/).

### P1-10 — Structured output strictness and evidence validation are incomplete

- **ID:** P1-10
- **SEVERITY:** P1
- **SUBSYSTEM:** Gemini structured output / grounding
- **FILE:** `gemini_adapter.py:58-69, 138-196`; `provenance_guard.py:144-183`; `reasoning_protocol.py:197-290`
- **LINE / FUNCTION:** schema cleaner, evidence validator, output parse
- **OBSERVED CODE/EVIDENCE:** Adapter strips every `additionalProperties`, although current official Gemini structured-output docs support it. Parsed JSON is not validated against the local schema. Evidence validator rejects unknown refs only when strings begin `evt_` or `snap_`; arbitrary citations pass. Invalid developing enum silently becomes `NONE`; list/string shapes are weakly coerced later.
- **WHY IT IS A PROBLEM:** “Strict schema” and “every evidence reference validated” are overstated; malformed but parseable output can become an active thesis.
- **REAL FAILURE MODE:** Model returns extra keys, wrong list shapes, or `evidence_references=["made_up_source"]`; output reaches active thesis despite schema claim.
- **CURRENT TEST COVERAGE:** One fake `evt_...` citation and invalid JSON; no full JSON-schema validation cases.
- **MINIMAL REPAIR SUGGESTION:** Preserve supported strictness, validate parsed payload locally before any expectation/thesis mutation, and require typed reference prefixes/membership.
- **TEST THAT SHOULD PROVE THE REPAIR:** Property-based invalid payload corpus and arbitrary-reference rejection.
- **CONFIDENCE:** HIGH

Official verification: [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

### P1-11 — The live backend is stale relative to source and shares an environment/state default with another checkout

- **ID:** P1-11
- **SEVERITY:** P1
- **SUBSYSTEM:** Deployment/runtime ownership
- **FILE:** runtime process; `app/main.py` state-root defaults near lines 180-270; `docs/FRONTEND_PRODUCTION_WORKFLOW.md`; `scripts/rebuild_oracle_frontend.sh`
- **LINE / FUNCTION:** launch/runtime configuration
- **OBSERVED CODE/EVIDENCE:** Backend PID started at 14:08; audited Sol files were edited at 16:29/17:23; uvicorn has no reload. Interpreter is from `/Developer/CitadelOS/.venv-kronos-alpha`. Multiple default state roots in `app/main.py` point to `/Users/ayushmudgal/Developer/CitadelOS/logs`, not this checkout. Frontend is current and has a documented rebuild path; no equivalent backend build/restart/served-revision proof was found.
- **WHY IT IS A PROBLEM:** Source, process code, dependencies, and persisted state may come from different checkouts.
- **REAL FAILURE MODE:** Audit/fix appears present on disk while stale Python continues serving old trust logic; restart reads another repository's logs.
- **CURRENT TEST COVERAGE:** None verifies deployed source hash or state-root identity.
- **MINIMAL REPAIR SUGGESTION:** Emit build/commit/source-file digest and resolved roots in health, use checkout-owned environment/config, and implement build/restart/GET verification guardrail.
- **TEST THAT SHOULD PROVE THE REPAIR:** Deployment smoke asserts served commit/hash, venv root, cwd, state root, and endpoint schema all match intended release.
- **CONFIDENCE:** HIGH

### P1-12 — Replay/test/manual sources can impersonate live because mode is never propagated

- **ID:** P1-12
- **SEVERITY:** P1
- **SUBSYSTEM:** Live/replay/shadow presentation
- **FILE:** `contracts.py:333-347`; `service.py`; `replay.py`; `GeminiMarketBrainSection.tsx:270, 425-429`; `scripts/ingest_real_spark_report.py:243-264`
- **LINE / FUNCTION:** `SolBeaconOutput.replay_mode`, reasoning result construction
- **OBSERVED CODE/EVIDENCE:** `replay_mode` defaults false and is never set by production reasoning/service code; search finds assignment only in a unit-test constructor. Replay engine reconstructs records but has no mode handoff. Smoke/manual scripts directly process historical snapshots through the same service. Frontend labels replay only if the unused flag is true and does not visibly label active Spark test fixtures.
- **WHY IT IS A PROBLEM:** Historical/test analysis has the same visual vocabulary as live.
- **REAL FAILURE MODE:** A healthy historical snapshot or test fixture processed in the singleton produces a fresh-looking CALL/PUT with no replay/test badge.
- **CURRENT TEST COVERAGE:** Test 17 asserts a manually constructed boolean, not propagation.
- **MINIMAL REPAIR SUGGESTION:** Make provenance mode required on snapshot/cycle/beacon/context and prohibit mode loss at boundaries.
- **TEST THAT SHOULD PROVE THE REPAIR:** True end-to-end replay and test-fixture cycles must show REPLAY/TEST across Beacon, brain, animation, history, and Radar and never LIVE.
- **CONFIDENCE:** HIGH

### P1-13 — Session restart/history hydration is incomplete and corrupt lines fail inconsistently

- **ID:** P1-13
- **SEVERITY:** P1
- **SUBSYSTEM:** Thesis/history/session persistence
- **FILE:** `event_sourced_memory.py:70-133, 249-279`; `thesis_memory.py:85-171, 189-213, 288-315`; frontend history lines 897-934
- **LINE / FUNCTION:** hydration/reset/history
- **OBSERVED CODE/EVIDENCE:** Constructor hydrates current calendar session, but runtime rotation resets event/thesis memory without hydrating already persisted target-session records. Thesis `_history` is memory-only, unbounded, and not restored; only active thesis returns after restart. Any corrupt expectation/evaluation line fails the entire thesis hydration; event hydration rejects the entire file; external and shadow stores silently skip corrupt lines. Timestamps named `*_utc` are created using IST in multiple thesis methods. Frontend slices UTC text without IST conversion and displays null history verdict as `NO TRADE`.
- **WHY IT IS A PROBLEM:** Restart behavior, ordering, session history, and displayed time are not trustworthy.
- **REAL FAILURE MODE:** Restart loses Gemini transition history; rotating back/forward to an existing session ignores its ledger; one partial line removes all active expectation recovery.
- **CURRENT TEST COVERAGE:** Existing docs cite two restart tests that do not exist in current `tests/oracle_sol/`.
- **MINIMAL REPAIR SUGGESTION:** Persist/hydrate bounded thesis transitions, normalize UTC, hydrate on rotation, and expose explicit corrupt-tail recovery status.
- **TEST THAT SHOULD PROVE THE REPAIR:** Fresh-process restart, preexisting-session rotation, corrupt final/full line, UTC/IST display, and cap/prune tests.
- **CONFIDENCE:** HIGH

### P1-14 — Worker/provider health can report success while current processing has failed

- **ID:** P1-14
- **SEVERITY:** P1
- **SUBSYSTEM:** Operational telemetry / queue backpressure
- **FILE:** `worker.py:51-102`; `service.py:270-323`
- **LINE / FUNCTION:** worker loop and `get_latest_state`
- **OBSERVED CODE/EVIDENCE:** Worker catches every callback exception without recording error or failed count and still refreshes heartbeat. When queue is full it removes an item without `task_done`. `brain_worker=WATCHING` reflects thread heartbeat only. `ai_provider=CONNECTED` forever after any historical success because successful count is checked before current provider error. `pending_events_count` is hardcoded 0 rather than queue/events.
- **WHY IT IS A PROBLEM:** Health surfaces can be green while processing is failing or backlogged.
- **REAL FAILURE MODE:** Ledger exception is swallowed; UI says WATCHING/CONNECTED and NEW EVENTS 0 while no current result can commit.
- **CURRENT TEST COVERAGE:** No callback exception, queue overflow, health transition, or post-success provider-failure test.
- **MINIMAL REPAIR SUGGESTION:** Record last success/failure/current state, queue depth/drop counts, and current provider result; balance queue accounting.
- **TEST THAT SHOULD PROVE THE REPAIR:** Inject callback exception and queue overflow; assert degraded health and exact counters.
- **CONFIDENCE:** HIGH

### P1-15 — Rapid animation state changes can reactivate the wrong video and hidden videos keep playing

- **ID:** P1-15
- **SEVERITY:** P1
- **SUBSYSTEM:** Living Market Forces animation lifecycle
- **FILE:** `LivingMarketForcesViewport.tsx:117-220, 499-546`
- **LINE / FUNCTION:** video transition effect and loop enforcers
- **OBSERVED CODE/EVIDENCE:** Every state starts target playback, but inactive videos are only made transparent, never paused. `play().then/catch` has no generation/cancellation guard. On rapid switches, an older play promise may resolve last and reapply its old target class. Non-balanced loop boundaries equal media duration (10/20/30 seconds) and rely only on `timeupdate`, with no `ended` fallback. All five files exist and durations fit configured starts.
- **WHY IT IS A PROBLEM:** A visual market state may lag/reverse independently of the latest canonical prop, while multiple decoders continue consuming resources.
- **REAL FAILURE MODE:** CALL_DEVELOPING → PUT_DEVELOPING quick flip ends with bull video visible; an ended clip freezes instead of hold-looping.
- **CURRENT TEST COVERAGE:** Static HTML confirms file names only; no media lifecycle or rapid-switch test.
- **MINIMAL REPAIR SUGGESTION:** Tokenize each transition, ignore stale promises, pause/reset inactive videos after crossfade, and add ended/seek guards.
- **TEST THAT SHOULD PROVE THE REPAIR:** Controlled media promises resolved out of order, rapid five-state transitions, autoplay rejection, ended event, and cleanup assertions.
- **CONFIDENCE:** HIGH

## 7. P2 FINDINGS

### P2-01 — Component-local hardcoded fetch duplicates the established dashboard data architecture

- **ID:** P2-01
- **SEVERITY:** P2
- **SUBSYSTEM:** Frontend maintainability/networking
- **FILE:** `GeminiMarketBrainSection.tsx:180-222`; `citadel-dashboard/AGENTS.md`
- **LINE / FUNCTION:** component `useEffect`
- **OBSERVED CODE/EVIDENCE:** Component fetches and subscribes directly to hardcoded `http://127.0.0.1:8000`, bypassing established provider/repository/adapter/store/selectors and environment configuration.
- **WHY IT IS A PROBLEM:** It creates a second state owner, CORS/deployment coupling, and untestable races.
- **REAL FAILURE MODE:** Remote/proxied deployment or HTTPS page cannot reach localhost API; Oracle store and Gemini panel disagree.
- **CURRENT TEST COVERAGE:** SSR does not run effects.
- **MINIMAL REPAIR SUGGESTION:** Add Sol state to the existing centralized data flow or one dedicated canonical store with configurable API base.
- **TEST THAT SHOULD PROVE THE REPAIR:** Store/selector integration with reconnect and revision ordering.
- **CONFIDENCE:** HIGH

### P2-02 — Video/canvas design has avoidable foreground and background cost

- **ID:** P2-02
- **SEVERITY:** P2
- **SUBSYSTEM:** Performance
- **FILE:** `LivingMarketForcesViewport.tsx:222-497, 499-546`; five MP4s
- **LINE / FUNCTION:** RAF loops/preload
- **OBSERVED CODE/EVIDENCE:** Five 1280×720 H.264/AAC MP4s totaling ~19 MB use `preload="auto"`; two independent perpetual RAF loops draw blurred rays and 46 particles. Hidden tabs skip drawing but continue scheduling RAF. Inactive videos are not paused.
- **WHY IT IS A PROBLEM:** Oracle is already heavy; simultaneous downloads/decoders/canvases raise memory, bandwidth, thermal, and background CPU risk.
- **REAL FAILURE MODE:** 8 GB Mac/Safari decoder pressure, dropped frames, and background battery/CPU usage.
- **CURRENT TEST COVERAGE:** No performance/visibility/memory measurement.
- **MINIMAL REPAIR SUGGESTION:** Preload active/adjacent assets only, pause inactive media/RAF on visibility, and measure before choosing further changes.
- **TEST THAT SHOULD PROVE THE REPAIR:** Browser performance trace with memory/CPU/network budgets and hidden-tab assertions.
- **CONFIDENCE:** HIGH

### P2-03 — Passing tests create false confidence on the highest-risk behavior

- **ID:** P2-03
- **SEVERITY:** P2
- **SUBSYSTEM:** Test quality
- **FILE:** `geminiMarketBrainIntegration.test.tsx`; both `tests/oracle_sol/` files; `docs/oracle_sol/P0_3_PERSISTENCE_AND_RECOVERY.md`
- **LINE / FUNCTION:** whole suites
- **OBSERVED CODE/EVIDENCE:** All frontend tests use `renderToStaticMarkup`; no effects or browser media run. Backend relies on ideal fabricated feed shapes and mocked SDK responses; no production handoff, genuine provider contract, session/provider overlap, runtime restart, or ASGI SSE. Documentation claims restart tests by names absent from current tests. Normal test service construction can write default ledger.
- **WHY IT IS A PROBLEM:** 69 passing checks do not cover the failure modes users rely on.
- **REAL FAILURE MODE:** Release is certified while input is empty, SSE breaks, test ledger contaminates live, and null verdict renders NO_TRADE.
- **CURRENT TEST COVERAGE:** This finding describes the gap.
- **MINIMAL REPAIR SUGGESTION:** Prioritize boundary/E2E/failure tests; keep provider calls mocked but validate exact SDK request objects.
- **TEST THAT SHOULD PROVE THE REPAIR:** Suites listed in §24.
- **CONFIDENCE:** HIGH

### P2-04 — Radar UI fabricates optimistic absence prose and semantic instrument labels

- **ID:** P2-04
- **SEVERITY:** P2
- **SUBSYSTEM:** External Radar presentation
- **FILE:** `GeminiMarketBrainSection.tsx:302-358, 830-879`
- **LINE / FUNCTION:** `findFact`, `formatInstrument`, empty states
- **OBSERVED CODE/EVIDENCE:** Arbitrary title/summary regexes classify S&P/Dow/Nasdaq facts and relabel them “Futures,” so cash closes/composites can be mislabeled. Values are whole prose, not canonical instrument fields. Empty list says `NO MATERIAL BREAKING EVENTS FOR TODAY`; empty gaps says `NO CURRENT DATA GAPS REPORTED`, even when source is unavailable/incomplete.
- **WHY IT IS A PROBLEM:** Absence of data becomes absence of events/gaps, and cash/index/future semantics can be wrong.
- **REAL FAILURE MODE:** “Dow Jones Industrial Average closed…” is displayed under Dow Jones Futures; unavailable Spark says no breaking events.
- **CURRENT TEST COVERAGE:** Tests assert hardcoded labels exist and therefore reinforce the issue.
- **MINIMAL REPAIR SUGGESTION:** Require typed instrument/venue/contract/observation fields from backend; render unavailable when no canonical observation.
- **TEST THAT SHOULD PROVE THE REPAIR:** Cash-vs-future/composite cases and empty/unavailable source cases.
- **CONFIDENCE:** HIGH

### P2-05 — Shadow/history growth and polling work are unbounded or redundant

- **ID:** P2-05
- **SEVERITY:** P2
- **SUBSYSTEM:** Performance/storage
- **FILE:** `shadow_ledger.py:193-208`; `thesis_memory.py:65, 209-213`; `GeminiMarketBrainSection.tsx:196-207`
- **LINE / FUNCTION:** ledger reads/history/polling
- **OBSERVED CODE/EVIDENCE:** JSONL grows without rotation; replay scans entire file for the last 1,000 and frontend history memory has no cap. Missing timestamp produced high-rate unique fail-closed cycles (1,355 records/7.1 MB on audit day). SSE plus 3-second GET is partly duplicative and unordered, though current `/state` is only ~8.2 KB.
- **WHY IT IS A PROBLEM:** Long-running sessions accumulate disk/read/memory cost and unnecessary renders.
- **REAL FAILURE MODE:** Large ledger replay latency and storage growth during feed outage.
- **CURRENT TEST COVERAGE:** No soak/storage cap test for Sol ledger/history.
- **MINIMAL REPAIR SUGGESTION:** Deduplicate unchanged unavailable snapshots; index/rotate with retention policy; cap persisted history; consolidate update ownership.
- **TEST THAT SHOULD PROVE THE REPAIR:** 8-hour unavailable-feed soak with size/cycle/render budgets.
- **CONFIDENCE:** HIGH

### P2-06 — Deployment guardrails do not prove the served build/revision

- **ID:** P2-06
- **SEVERITY:** P2
- **SUBSYSTEM:** Build workflow
- **FILE:** `scripts/rebuild_oracle_frontend.sh:24-73`; `docs/FRONTEND_PRODUCTION_WORKFLOW.md`
- **LINE / FUNCTION:** rebuild health check
- **OBSERVED CODE/EVIDENCE:** Workflow is documented and current source builds, but script verifies only HTTP 200 and prints built ID; it never proves served page/chunks use that ID. `pgrep ... | head -1` may select another Next process. Backend has no parallel source-revision guardrail. Audit itself found stale Python source at runtime.
- **WHY IT IS A PROBLEM:** The prior stale-runtime incident can recur undetected.
- **REAL FAILURE MODE:** Old server returns 200 after build; deploy script declares success.
- **CURRENT TEST COVERAGE:** None.
- **MINIMAL REPAIR SUGGESTION:** Expose served build/source ID and exact owner PID/cwd; compare after restart.
- **TEST THAT SHOULD PROVE THE REPAIR:** Deliberately serve old build and ensure deployment verification fails.
- **CONFIDENCE:** HIGH

### P2-07 — Repository hygiene mixes source, runtime ledgers, generated media, and dangerous operator scripts

- **ID:** P2-07
- **SEVERITY:** P2
- **SUBSYSTEM:** Git/repository hygiene
- **FILE:** current `git status`; `.gitignore`; `data/`; `public/market_forces/`; `test_token2.py`; `test_identities.py`; scripts
- **LINE / FUNCTION:** repository-wide
- **OBSERVED CODE/EVIDENCE:** 203 pre-report dirty entries; runtime JSON/JSONL data untracked; five large generated videos untracked; many audit/generated artifacts modified; standalone scripts can open another Dhan websocket or import `app.main`; test and live fixtures coexist in data.
- **WHY IT IS A PROBLEM:** Review scope, reproducibility, secret safety, and single-owner operations are fragile.
- **REAL FAILURE MODE:** Runtime ledger/assets accidentally committed; debug script creates second feed owner; source change hidden among artifacts.
- **CURRENT TEST COVERAGE:** None.
- **MINIMAL REPAIR SUGGESTION:** Commit reviewed source/tests/config/docs; ignore runtime ledgers/secrets; store sanitized fixtures separately; document or LFS-manage approved media; quarantine dangerous diagnostics.
- **TEST THAT SHOULD PROVE THE REPAIR:** CI tracked-secret/generated-runtime-file policy and package manifest check.
- **CONFIDENCE:** HIGH

## 8. P3 FINDINGS

### P3-01 — Canvas rendering ignores devicePixelRatio and container-only resize

- **ID:** P3-01
- **SEVERITY:** P3
- **SUBSYSTEM:** Animation quality
- **FILE:** `LivingMarketForcesViewport.tsx:231-239, 369-377`
- **LINE / FUNCTION:** both canvas `resize` functions
- **OBSERVED CODE/EVIDENCE:** Backing resolution equals CSS pixels and resize listens only to `window`, not element changes.
- **WHY IT IS A PROBLEM:** Retina output is soft and layout/container resizing can leave wrong resolution.
- **REAL FAILURE MODE:** Blurry rays/particles or stretched canvas after panel resize.
- **CURRENT TEST COVERAGE:** None.
- **MINIMAL REPAIR SUGGESTION:** Apply bounded DPR transform and `ResizeObserver`.
- **TEST THAT SHOULD PROVE THE REPAIR:** DPR 1/2 and container resize visual test.
- **CONFIDENCE:** HIGH

### P3-02 — Developer scripts and runtime defaults hardcode paths to another checkout

- **ID:** P3-02
- **SEVERITY:** P3
- **SUBSYSTEM:** Developer environment
- **FILE:** `test_token2.py:8`; `app/main.py` state-root defaults; workflow/rebuild scripts
- **LINE / FUNCTION:** hardcoded paths
- **OBSERVED CODE/EVIDENCE:** Several paths point to `/Users/ayushmudgal/Developer/CitadelOS` while audited workspace is `CitadelOS-Oracle-Post-E9`.
- **WHY IT IS A PROBLEM:** Local behavior depends on unrelated checkout layout.
- **REAL FAILURE MODE:** Clean machine or renamed checkout reads wrong config/logs or fails.
- **CURRENT TEST COVERAGE:** None.
- **MINIMAL REPAIR SUGGESTION:** Centralize explicit resolved root configuration and fail when it targets another checkout unexpectedly.
- **TEST THAT SHOULD PROVE THE REPAIR:** Startup config test in a relocated clone.
- **CONFIDENCE:** HIGH

### P3-03 — Names and comments materially overstate implemented guarantees

- **ID:** P3-03
- **SEVERITY:** P3
- **SUBSYSTEM:** Documentation/code quality
- **FILE:** module docstrings across `src/oracle_sol/`; `spark_mcp_boundary.py`; existing `docs/oracle_sol/`
- **LINE / FUNCTION:** claims such as “authenticated,” “strict,” “atomic,” “100% exact,” and “UTC”
- **OBSERVED CODE/EVIDENCE:** Source/comments claim authenticated ingest, strict structured output, atomic batches, replay proof, and UTC timestamps where current code does not provide those guarantees. Several docs still name GPT-5.6 Sol after Gemini activation.
- **WHY IT IS A PROBLEM:** Reviewers and operators rely on assertions that tests/code contradict.
- **REAL FAILURE MODE:** Future work treats a claim as proof and omits necessary controls.
- **CURRENT TEST COVERAGE:** None checks documentation against contracts.
- **MINIMAL REPAIR SUGGESTION:** After engineering repair, update docs to state only proven guarantees and include evidence/test links.
- **TEST THAT SHOULD PROVE THE REPAIR:** Documentation checklist tied to named executable tests and runtime fields.
- **CONFIDENCE:** HIGH

## 9. INVESTIGATION / UNPROVEN

- **REST JSON field casing:** The fallback uses mixed snake_case/camelCase. Official REST schema documents lowerCamel JSON while some legacy examples show selected snake_case fields. Without a real fallback contract test, whether every current field is accepted is **UNPROVEN**, not a confirmed defect.
- **External source facts:** The audit did not validate the truth of current Spark headlines/values against the internet because the mission asked to audit trust handling, not re-research every item. They remain correctly marked `UNVERIFIED` in the current store.
- **External Dhan 429 cause:** Runtime has one audited socket owner, but repeated HTTP 429 may originate from provider policy, prior sessions, or another host/process. No second active repository websocket was found; root cause is unproven.
- **Safari loop granularity:** Exact `timeupdate` behavior at media duration is browser-dependent. Missing ended guard is confirmed; whether every Safari version visibly freezes is unproven.
- **Direct ledger rewrite actor/time:** Current file and code cannot reconstruct who rewrote the known incident. Absence of tombstone is proven; the historical payload content cannot be independently recovered from this workspace.
- **Provider-side logging/storage:** SDK call is stateless at application level (new client, one content string, no chat/history/cached ID). Provider account logging policy was not inspected; no claim is made beyond application statelessness.

## 10. REVIEWED AND NOT A BUG

- The current Gemini request path does not import or pass `vob_reversal`, VOB state, VOB horsepower, pullback command, or Option Buyer output.
- ARGUS coherent projection is produced before VOB ingestion in the live-analytics child; VOB later observes ARGUS, not vice versa.
- Gemini has no broker connectivity, order placement, modification, cancellation, or execution method.
- External context alone cannot directly set Beacon verdict; it is a separate request field.
- For non-test live payloads, incoming self-declared `verification_status=VERIFIED` is rejected and remains `UNVERIFIED`/`SOURCE_UNAVAILABLE`.
- `ctx_spark_radar_20260830_1720` has zero exact occurrences in searched active/history/cycle/source/UI/test/doc paths; active ID is `ctx_spark_radar_20260830_1414`.
- Per-event append writes disk before memory, flushes, fsyncs, rejects same event ID/different hash, and idempotently skips same hash.
- Malformed JSON, invalid verdict enum, and recognized invalid event/snapshot references fail closed in backend with null verdict.
- Provider failure preserves prior thesis as last known rather than overwriting it with a fake thesis; the UI includes a stale banner when backend status reaches it. The separate P0 is the animation/state mapping.
- Application-level Gemini requests are stateless: one `generate_content` call, no chat object, no previous interaction ID, no hidden application conversation memory.
- Five video assets exist, are 1280×720 H.264, and configured starts are within their 10/20/30-second durations. The previously reported developing-state early-return is fixed: target lookup occurs before ray branches and `play()` is reached.
- Animation is one-way. Video time, completion, CSS, ray intensity, and particles never mutate verdict or backend state.
- Canvas RAF IDs and resize/timeupdate listeners are cleaned up on unmount.
- Basis sign color/formatting is presentation only; it does not derive a CALL/PUT state.
- Older items with an explicit non-today UTC date are excluded from Today's News. The defect is incomplete/incorrect semantics for offsets, IST-only, future, and stale cases.
- Current runtime has one Next owner on port 3000 and one Dhan WebSocket owner.
- `tsconfig.json` exclusion of `public/market_forces` is safe because it contains MP4 assets, not production TS/TSX. `.vscode` watcher/search exclusions do not alter TypeScript or test discovery.
- All current frontend source compiled; no Gemini API secret or `NEXT_PUBLIC_*GEMINI*` reference exists in frontend source/bundle paths searched.

## 11. GEMINI INPUT LINEAGE MAP

### Exact request envelope

`reasoning_protocol.py:117-140` sends one stateless request containing:

| Request field | Source / calculated by | Provenance / VOB-free | Current vs last-known | Required | Missing behavior |
|---|---|---|---|---|---|
| `cycle_id` | UUID in orchestrator/service | Service-owned; VOB-free | Current cycle | Required | Generated |
| `snapshot` | `extract_sol_evidence_snapshot` | Selected Oracle/Order Flow/ARGUS fields; current path VOB-free | Intended current; runtime is unavailable | Required for eligible call | UNAVAILABLE/OFF_MARKET prevents provider call |
| `active_market_story` | deterministic event memory | Derived from durable session events; VOB-free | Session aggregate | Required | Initialized “awaiting” story |
| `recent_event_timeline` | story builder → event store | Deterministic snapshot deltas; VOB-free | Last up to 25 | Required array | Empty array |
| `previous_thesis` | prior Gemini thesis | Model-generated prior state | Last-known session thesis | Required object | Initialization thesis |
| `external_context` | active same-session `ExternalContextStore` | Spark payload, split verified/unverified/conflicted | Latest appended, not freshness-safe | Optional | `null`; domestic reasoning continues |

### Snapshot field-level map

All numeric fields are optional in the dataclass and missing values become `None` plus `availability_matrix=UNAVAILABLE`. The only provider gate is aggregate `system_status`. “Current runtime” below refers to the GET observed during audit.

| Field | Extractor source | Calculated by / provenance | VOB-free? | Current/last-known | Current runtime / missing behavior |
|---|---|---|---|---|---|
| `snapshot_id` | hash of selected evidence/timestamp/source hashes | Sol extractor identity | Yes | Current | Generated even for empty feed; wall clock causes churn |
| `canonical_snapshot_id` | root/ARGUS/Oracle ID/revision | Upstream | Yes | Current if supplied | `null` |
| `market_session_date` | parsed source timestamp or current IST date | Extractor | Yes | Current/inferred | Current IST date; invalid timestamp incorrectly authentic |
| `identity_quality`, `replay_stable` | timestamp branch | Extractor | Yes | Current metadata | `DEGRADED/false` with missing timestamp |
| `timestamp_utc`, `timestamp_ist` | Oracle/ARGUS source time or wall clock | Upstream/extractor formatting | Yes | Current/inferred | Wall clock when missing |
| `system_status` | Dhan/market flags + spot/futures availability | Extractor health logic | Yes | Current | `UNAVAILABLE`; no provider call |
| `upstream_source_health` | feed `ok`, Oracle Dhan/open flags | Extractor | Yes | Current | Shape claims feeds OK while market flags absent |
| quote/flow/chain ages | Oracle `dhan_quote_age_ms`, Order Flow/ARGUS `age_ms` | Upstream | Yes | Current | All null |
| `spot_ltp` | Oracle `spot_ltp/spot_price/spot`; ARGUS root/market snapshot fallback | Dhan/upstream; no local math | Yes | Intended current | Null because Oracle Assessment shape and ARGUS nesting do not match |
| `futures_ltp` | Oracle; Order Flow; ARGUS futures/market snapshot | Dhan/upstream | Yes | Intended current | Null |
| `futures_basis` | Oracle/ARGUS canonical basis | Upstream derived; not recalculated | Yes | Intended current | Null |
| `session_vwap` | Oracle `session_vwap/vwap` | Intended Strategy Lab/upstream | Yes | Intended current | Null; actual Oracle Assessment has `input_features.vwap` nested |
| `spot_to_vwap_pts` | Oracle canonical distance | Upstream derived | Yes | Intended current | Null |
| `active_expiry` | ARGUS root/underlying/futures/market snapshot | Option-chain resolver | Yes | Intended current | Null |
| `atm_strike` | Oracle or ARGUS root | Option-chain resolver | Yes | Intended current | Null |
| `futures_security_id` | Oracle or ARGUS futures | Dhan/resolver | Yes | Intended current | Null |
| `sudden_oi_call/put` | `argus_data.sudden_oi.CALL/PUT` | Registry claims Option Buyer | Current path no VOB, but producer claim not wired | Intended current | Null; Option Buyer not passed |
| `strike_ladder` | ARGUS `chain_strikes` or `atm_window`, Oracle `strike_ladder`; max 10 | Upstream OI/quote/fair-response fields, projected allowlist | Current selected ARGUS is pre-VOB | Intended current | Empty; option deltas are dropped |
| per-strike option quotes | `ce_ltp/pe_ltp` within ladder | Dhan/ARGUS | Yes | Intended current | Not ingested at runtime |
| per-strike OI changes | `ce/pe_closed_5m/15m_oi` or ARGUS `intraday_change_oi` | Upstream closed-window logic | Yes on current path | Intended current | Not ingested; no total OI or PCR contract exists |
| buildup states | `ce_structure/pe_structure` or ARGUS `positioning` | Upstream | Yes on current path | Intended current | Not ingested |
| `mlofi_5l` | Order Flow `mlofi/current_mlofi` | Order Flow service | Yes | Intended current | Null due actual projection shape |
| `current_flow_x` | Order Flow `flow_x/current_flow_x` | Direct Order Flow projection; registry says Resolver | No current VOB chain found | Intended current | Null |
| `mlofi_session_extreme` | Order Flow `is_extreme/mlofi_is_session_extreme` | Order Flow service | Yes | Intended current | Null |
| option delta | No projected field | N/A | N/A | Not sent | Never ingested into Gemini snapshot |
| `ce_pricing/pe_pricing` | ARGUS root pricing objects | Registry claims Option Buyer | Current Option Buyer not passed | Intended current | Null |
| fair-value/option response | pricing objects and per-strike `*_fair_gap_pct` | Upstream | Current path pre-VOB | Intended current | Not ingested |
| `atm_straddle_price` | Oracle or ARGUS straddle | Upstream | Yes | Intended current | Null |
| `straddle_change_5m` | ARGUS root | Upstream | Yes | Intended current | Null |
| `atm_iv` | Oracle root only | Intended option intelligence | Yes by selected path | Intended current | Null |
| `skew_25d`, `skew_10d` | Oracle root only | Intended option intelligence | Yes by selected path | Intended current | Null |
| `expected_move_pts` | Oracle root only | Intended option intelligence | Yes by selected path | Intended current | Null |
| `net_gex_inr`, `highest_gex_strike`, `zero_gamma_level` | Oracle root only | Intended GEX engine | Yes by selected path | Intended current | All null |
| `availability_matrix` | extractor per-field | Sol metadata only | Yes | Current | Present; frontend ignores it |
| `source_hashes` | hashes of selected subfeeds | Sol provenance metadata | Yes | Current payload hashes | Present even for empty/mismatched shapes |
| `vob_free_verified` | hardcoded claim after key allowlist | Sol guard | Narrowly true for current path | Current assertion | Does not prove semantic upstream lineage by itself |

### Stories and visible narratives

`positioning_story`, `oi_story`, `flow_story`, `option_response_story`, `core_narrative`, cases, contradiction, expectations, and evidence references are **Gemini output fields**, persisted in `ThesisState`. On the next cycle, only prior verdict/developing/core narrative/active expectations are sent back under `previous_thesis`; the four prior stories/cases are not resent. They are not deterministic market inputs and must not be described as separate calculations received from CITADEL.

## 12. VOB-FREE PROVENANCE RESULT

**Result: PROVEN for the current active request path, with a material future-lineage caveat.**

Exact chain:

1. `_oracle_fast_base_projection` selects only `oracle_service.assess("NIFTY")`, `order_flow_service.latest_projection`, and `cached_argus_projection("NIFTY")`.
2. `cached_argus_projection` reads `_argus_coherent_projection`, built by `_enrich_argus_projection` from ARGUS and market snapshot/OSE tactical data before VOB consumes it.
3. The live-analytics child then feeds ARGUS/OSE/Flow into VOB and builds `option_buyer_intelligence`, but neither VOB nor Option Buyer output is included in `sol_feeds`.
4. Extractor projects only `oracle`, `order_flow`, and `argus`; unknown root feeds are ignored. Selected ladder/pricing objects are recursively key-checked and the final snapshot is allowlisted.
5. Gemini receives only final snapshot/events/story/prior thesis/external context.

No direct or indirect VOB-derived field was found in the current actual handoff. This is not proven merely by the UI text or `vob_free_verified`; it is proven by the call graph above. The caveat is exact: `OptionBuyerIntelligenceWorker.prepare(argus, vob, flow)` reads `vob.current_itm1_contracts` in `src/oracle/option_buyer_intelligence.py:1059`. The registry labels several Option Buyer fields VOB-free, but they are currently unavailable because Option Buyer is not wired. If those fields are wired later, contract selection lineage must be separated or explicitly adjudicated before retaining a VOB-free claim.

## 13. SPARK / EXTERNAL CONTEXT TRUST RESULT

**FAIL**

- Known incident ID `ctx_spark_radar_20260830_1720`: absent from active API, external history, shadow-cycle text, source/UI/tests/docs searched; Gemini cannot retrieve it from the current store and Oracle cannot show it as current.
- No derived projection retaining that exact ID was found.
- Current active payload is `ctx_spark_radar_20260830_1414`, 11 unverified items, not a test fixture.
- General trust fails because caller-controlled fixture mode can promote mock verification through unauthenticated ingress.
- Producer controls ID and timestamps; invalid fact status silently becomes `CONFIRMED`; same ID/different hash duplicates survive; no staleness; lexical as-of; append order wins; corrupt hydration is silent; reload is unlocked/unauthenticated; durability lacks fsync.
- Current store includes two historical test fixtures and four same-ID/different-hash live payloads. They are not active now, but demonstrate store-class mixing and ambiguous identity.
- Direct history rewrite removed the incident rather than appending a quarantine/tombstone. The current ledger therefore cannot reconstruct the provenance trail. Duplicate removal by ID alone would also be unsafe because the four surviving same IDs have distinct content hashes.

## 14. LIVE / REPLAY / STALE RESULT

**FAIL**

- Live/replay mode is represented in Beacon but never propagated from a production path.
- Shadow ledger does not require runtime mode and currently mixes test, replay/historical, unavailable, and live-service cycles.
- Active Spark fixture mode is returned by backend but not visibly rendered as test mode.
- Backend-reported unavailable state does suspend verdict, but healthy-data/provider failure becomes NO_TRADE in the UI.
- Backend transport loss after a previously live state leaves the old UI state indefinitely.
- Historical thesis is shown with an explicit stale banner when new backend status arrives; this narrow behavior is correct.
- Explicit older UTC dates are excluded from Today's News, but stale, future, offset, and IST-only semantics fail.

## 15. FIVE-STATE SEMANTICS RESULT

**FAIL**

Actual current conflict behavior:

| Backend verdict | Developing state | System | React result |
|---|---|---|---|
| CALL | anything, including PUT_DEVELOPING | HEALTHY | CALL |
| PUT | anything, including CALL_DEVELOPING | HEALTHY | PUT |
| NO_TRADE/null/invalid | CALL_DEVELOPING | HEALTHY | CALL_DEVELOPING |
| NO_TRADE/null/invalid | PUT_DEVELOPING | HEALTHY | PUT_DEVELOPING |
| NO_TRADE | NONE/UNRESOLVED | HEALTHY | NO_TRADE |
| null/invalid | NONE/UNRESOLVED | HEALTHY | NO_TRADE |
| any | any | non-HEALTHY | NO_TRADE passed to viewport; overlay depends on operational mapping |

Backend invalid verdict fails closed; invalid developing state silently becomes NONE. Provider failure after a prior CALL retains the old thesis but emits null beacon. If backend is reachable, UI shows stale thesis banner yet NO_TRADE animation; if frontend transport is lost, stale CALL animation remains dominant. Session rotation resets state, but P0-06 permits an old in-flight result to overwrite it.

## 16. FRONTEND TRUTH-FIREWALL RESULT

**FAIL — FRONTEND MARKET LOGIC FOUND**

Frontend derivation classification:

| Derivation | Classification | Result |
|---|---|---|
| Basis sign color and number formatting | PRESENTATION ONLY | Allowed |
| CALL/PUT/developing precedence | MARKET LOGIC | Forbidden; P1-03 |
| Null/invalid/nonhealthy → NO_TRADE | MARKET LOGIC | Forbidden; P0-01 |
| Regex title/summary → instrument class/futures label | MARKET SEMANTIC LOGIC | Unsafe; P2-04 |
| Snapshot object → domain AVAILABLE | INVENTED DATA AVAILABILITY | Unsafe; P1-02 |
| External status AVAILABLE → CURRENT | INVENTED FRESHNESS | Unsafe; P1-04 |
| Non-today date → LAST AVAILABLE | INVENTED TEMPORAL CLASSIFICATION | Unsafe; P1-04 |
| Thesis narrative/cases/stories direct rendering | PRESENTATION ONLY | Correct mapping |
| Stale banner from operational/reasoning state | PRESENTATION ONLY | Correct intent, incomplete transport handling |

No hardcoded market prices/OI/IV were found in the new Gemini component. The integration tests explicitly guard several old example numbers. Hardcoded fallback reasoning prose was removed, but optimistic status/absence prose remains (`NONE REPORTED`, `NO MATERIAL BREAKING EVENTS FOR TODAY`, `NO CURRENT DATA GAPS REPORTED`).

## 17. ANIMATION ENGINE RESULT

**PARTIAL**

- State/assets mapping is correct: NO_TRADE→balanced, CALL_DEVELOPING→Bull Pressure, CALL→Bull Dominant, PUT_DEVELOPING→Bear Pressure, PUT→Bear Dominant.
- Files exist at exact public paths; durations: balanced 10s, bull pressure 30s, bull dominant 10s, bear pressure 20s, bear dominant 10s. Configured starts/hold loops are within duration.
- Previously fixed premature return is actually fixed; developing states reach playback.
- One-way financial decoupling is proven.
- Cleanup of listeners and RAF on unmount is present.
- Failures: stale play-promise race, inactive videos never paused, duration-edge loop dependence, 19 MB auto preload, two ongoing RAF schedulers, no DPR, no ResizeObserver. Autoplay rejection shows a frame but may remain frozen. Hidden tabs skip drawing but continue requesting frames.

## 18. SECURITY / SECRET RESULT

**FAIL overall; Gemini frontend secret isolation passes.**

- No Gemini secret, Gemini env reference, or `NEXT_PUBLIC` Gemini key path was found in frontend source.
- Backend exposes only `api_key_present` boolean, not the key.
- Keychain/env retrieval does not print the key in normal adapter code.
- Gemini REST fallback query string is an avoidable leak path.
- Tracked `.env` contains live-looking non-Gemini credentials and must be treated as compromised; values are intentionally omitted.
- Tests do not prove logs/exceptions/proxies are redacted.
- Untracked `test_token2.py` loads the other checkout's `.env` and constructs a Dhan WebSocket token query; executing it would create an additional feed client outside the canonical owner.

## 19. CONCURRENCY / SESSION RESULT

**FAIL for Sol session/concurrency; PASS for single Dhan ownership.**

- One Dhan WebSocket owner is verified in code/runtime.
- Sol provider calls are single-thread serialized within one service worker, so ordinary request overlap in one process is prevented.
- Queue coalesces at 10 but has broken unfinished-task accounting and no drop telemetry.
- Old-session in-flight result race is P0-06.
- Event store per-event locks are correct, but batch atomicity is not.
- External store/reload has no lock and can race reasoning/ingest.
- Multiple service instances can write the same default shadow ledger and DuckDB.
- Worker exceptions are swallowed while heartbeat remains healthy.
- Current runtime has one backend parent plus expected isolated analytics/flow/gateway children; no second broker acquisition owner was found.

## 20. PERFORMANCE RESULT

**PARTIAL / MATERIAL RISKS**

- Five MP4s: ~19 MB total, all auto-preloaded, all previously activated videos continue playing invisibly.
- Two canvas loops with blur/particles; hidden tabs still reschedule.
- Sol GET is currently ~8.2 KB every 3 seconds, so bandwidth alone is modest; SSE is beacon-only while GET carries full state, so they are not exact duplicates. Their unordered writes and broken SSE framing are the larger risks.
- Existing `/v2/dashboard` response is ~986 KB, but Gemini component does not fetch it directly.
- Missing source time generated 1,355 shadow cycles/7.1 MB during an unavailable day; dedupe is ineffective.
- No empirical Safari/8 GB Mac trace, decoder count, long-task profile, or full-page rerender measurement exists.

## 21. TEST QUALITY RESULT

**WEAK for readiness claims despite passing suites.**

What tests prove:

- Ideal-shaped snapshot extraction, zero preservation, some event types, basic VOB-key rejection.
- JSON parse failure and recognized fake `evt_` citation fail closed.
- Non-test self-declared verification remains unverified; test fixture verification promotes.
- External session dictionary isolation and one lexical as-of happy path.
- Static presence of UI sections/assets and no selected hardcoded example numbers.

What they do not prove:

- Actual `app.main` producer → extractor → Gemini field contract.
- Browser transport effects, SSE, polling races, stale timeout, five-state conflicts, rapid animation switches, autoplay/Safari/hidden tab.
- Provider request contract, declared thinking level, timeout/retry, REST fallback, real schema enforcement.
- Restart/session hydration, concurrent session rotation/provider, partial/corrupt lines, same ID/different payload.
- Current Spark Today/weekend/future/IST cases, reload auth/race, fixture rejection at router.
- Real live/replay mode propagation.
- Documentation cites nonexistent restart tests.
- Test storage isolation unless cwd is externally changed.

## 22. FAILURE-MODE MATRIX

| Scenario | Current actual behavior | Safety |
|---|---|---|
| A. Gemini unavailable | Backend null verdict, previous thesis retained; healthy-data UI shows NO_TRADE | **FAIL** |
| B. Malformed response | Backend `OUTPUT_INVALID`, null verdict; healthy-data UI shows NO_TRADE | **FAIL** |
| C. Dhan/live feed unavailable | Snapshot UNAVAILABLE, provider not invoked, UI unavailable overlay | **PASS fail-closed**, animation still balanced underneath |
| D. Spark absent | `external_context=null`; domestic reasoning may continue | **PASS** |
| E. Spark stale | No stale computation; same-session active remains AVAILABLE/current | **FAIL** |
| F. External conflicted | Separated stream, but unauth test fixture can manufacture conflict/verification | **FAIL trust** |
| G. Session date changes | Resets shared state; old in-flight result can overwrite; no target-session hydration | **FAIL** |
| H. Restart mid-session | Active thesis/events/baseline attempt hydration; history lost; corrupt lines inconsistent | **PARTIAL** |
| I. Frontend reload mid-analysis | Starts null; GET/SSE may race; SSE partial state can arrive first | **PARTIAL** |
| J. Rapid CALL_DEVELOPING→PUT_DEVELOPING | Canonical prop changes, but stale play promise can reactivate bull video | **FAIL visual** |
| K. CALL→provider failure | Backend nulls beacon, retains stale thesis; UI turns animation into NO_TRADE | **FAIL semantics** |
| L. Replay while closed | Replay flag not propagated; direct healthy replay can look live | **FAIL** |
| M. Duplicate snapshot | No events, but baseline rewrite, enqueue, provider cycle, and ledger still occur | **FAIL efficiency/proof** |
| N. Same ID/different payload | Story builder treats as identical and emits no events; no collision check | **FAIL** |
| O. Partial/corrupt history line | Events/thesis may lose whole hydration; external/shadow silently skip line | **FAIL diagnostics/recovery** |

## 23. MINIMAL REPAIR PLAN

### P0 first

1. Separate `NO_TRADE` from operational/reasoning unavailable in UI; make null verdict impossible to enter the five-state renderer.
2. Require authentication/capability for Spark ingest/reload and reject fixture mode on production routes.
3. Propagate `storage_dir` and required runtime mode to every Sol persistence component; isolate test/replay/live ledgers.
4. Add transport receipt/revision state so failed GET+SSE deactivates current visual dominance without rewriting market verdict.
5. Rotate/remove exposed credentials under a controlled security procedure; move Gemini key to header-only REST auth and redact errors.
6. Add session generation checks before thesis/beacon/ledger commit.

### Then P1

7. Build one explicit adapter from actual producer contracts to `SolEvidenceSnapshot`; verify all required domains with captured frames.
8. Generate frontend types/statuses from backend and emit one backend canonical five-state value.
9. Normalize external timestamps server-side; emit explicit Today/Last Available/Future/Unknown/Stale classes.
10. Enforce external ID/hash collision rules, locked atomic reload, fsync, and append-only quarantine tombstones.
11. Repair persistence ordering/atomicity, collision handling, duplicate suppression, and replay hash requirements.
12. Frame SSE once and make all state updates revision-aware.
13. Align Gemini 3.7 config with documented thinking level, SDK timeout/retry, declared dependency, strict local output validation, and typed evidence refs.
14. Add deployed source/build/root identity and restart verification for backend/frontend.
15. Require live/replay/test mode end to end; restore bounded session history correctly.
16. Make worker/provider health current and error-aware.
17. Tokenize video transitions, pause inactive media, and guard ended loops.

### Then P2

18. Move Sol transport into the established frontend state architecture.
19. Reduce media/background work based on measured budgets.
20. Replace string-only tests with boundary/E2E/failure suites.
21. Replace radar regex semantics and optimistic absence text with typed backend fields.
22. Add ledger retention/dedupe and served-build verification.
23. Separate commit-worthy source/tests/docs/media from runtime data, secrets, artifacts, and dangerous diagnostics.

No step requires a trading threshold, score, weight, indicator formula, entry gate, or execution change.

## 24. TESTS REQUIRED AFTER REPAIR

1. Captured actual Fast Lane → production handoff → snapshot → request-envelope golden contract.
2. Field-by-field availability/provenance test including missing and observed zero.
3. VOB lineage test using actual upstream call graph; Option Buyer must fail until VOB-free contract selection is proven.
4. Full verdict/developing conflict cross-product and null-verdict operational UI tests.
5. Provider unavailable/429/503/timeout/malformed/schema-extra/wrong-type/evidence-ref tests.
6. Inspect exact Gemini SDK request for `thinking_level=medium`, timeout, retry, schema, model ID, and statelessness.
7. Production router authentication and fixture-rejection tests for ingest/reload.
8. External timestamp matrix: IST midnight, UTC offset, Friday→Sunday, closed market, future event, unknown time, stale payload.
9. Same context ID same/different hash, reload/read/append race, corrupt line, fsync failure, tombstone replay.
10. Restart mid-session with active thesis/events/history/expectations and session rotation to preexisting data.
11. Blocking old-session provider response released after new-session reset.
12. Duplicate snapshot and same ID/different payload tests across live and restart.
13. ASGI SSE initial/heartbeat/first broadcast/disconnect tests.
14. Mounted React tests for delayed GET vs SSE, total transport loss, page reload mid-analysis, and stale CALL.
15. Real media mocks for out-of-order play promises, rapid flips, autoplay rejection, ended/timeupdate, inactive pause, unmount cleanup.
16. Browser performance trace with five videos, both canvases, hidden tab, Safari, DPR, resize, and 8 GB memory budget.
17. Clean checkout dependency/build/start test and served source/build ID comparison.
18. Repository policy test rejecting tracked env secrets/runtime JSONL/DuckDB and unclassified replay/test artifacts.

## 25. WHAT SHOULD NOT BE CHANGED

- Do not change VOB calculations, state, videos' financial meaning, or VOB Pullback Command behavior.
- Do not add CALL/PUT thresholds, confidence scores, weights, formulas, strategy gates, entries, exits, or auto-execution.
- Do not give Gemini broker connectivity or trading authority.
- Do not make Spark a low-latency market feed or direct trading authority.
- Do not move financial classification into React.
- Do not remove fail-closed null verdicts from backend provider/error paths; repair their presentation instead.
- Do not weaken per-event fsync/collision rejection or the explicit separation of verified/unverified/conflicted context.
- Do not infer missing values as zero.
- Do not treat `NO_TRADE` as an operational status.
- Do not rewrite event/history ledgers for quarantine; preserve append-only provenance.
- Do not introduce a second Dhan/broker owner.
- Do not perform a large rewrite where explicit adapters, validation, generation tokens, and atomic swaps suffice.

## 26. FINAL PROSPECTIVE-LIVE READINESS CHECKLIST

- [ ] All P0 findings repaired and independently retested.
- [ ] All P1 findings affecting truth/provenance/session/provider repaired and independently retested.
- [ ] Served backend source hash matches reviewed workspace/release.
- [ ] One Next owner and one Dhan WebSocket owner proven at runtime.
- [ ] Actual Fast Lane frame populates spot, futures, basis, contract/OI, flow, volatility, GEX/response fields as explicitly available/unavailable.
- [ ] Every Gemini request has a nonempty canonical snapshot ID/time/session and mode.
- [ ] VOB-free proof repeated after final sensorium wiring; Option Buyer lineage resolved before inclusion.
- [ ] Null/invalid/degraded reasoning cannot render any five-state market interpretation.
- [ ] Last-known CALL/PUT cannot appear live after transport/provider failure.
- [ ] Backend owns one canonical five-state value; React has no conflict precedence.
- [ ] Spark production endpoint rejects fixture mode and requires authorization.
- [ ] Spark receipt time is server-owned; timestamps normalized; stale/future/weekend classes proven.
- [ ] Known quarantined incident has append-only tombstone and cannot reactivate.
- [ ] Live/replay/test mode visible across Beacon, Gemini Brain, animation, history, and Radar.
- [ ] Gemini 3.7 request uses documented medium thinking level, bounded timeout/retry, strict schema, and full local validation.
- [ ] No secret appears in tracked files, frontend, URLs, logs, exceptions, tests, or fixtures.
- [ ] Event/baseline/thesis/shadow persistence survives crash/restart without partial-state divergence.
- [ ] Old-session provider responses are discarded after rotation.
- [ ] SSE first real update works; GET/SSE revision ordering is deterministic.
- [ ] Animation rapid-switch, autoplay, Safari, hidden-tab, resize, and resource budgets pass.
- [ ] Runtime data/ledgers are excluded from source commits; approved media ownership is documented.
- [ ] Independent audit reviews the repaired changeset before any prospective live shadow session.

**Current readiness: NO. Do not begin prospective live shadow testing until the P0/P1 repair set and required proof tests are complete.**
