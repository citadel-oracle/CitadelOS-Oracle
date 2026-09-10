# ARCHITECTURE DECISION RECORD: CITADEL ORACLE QWEN 3.5 9B + EXTERNAL CONTEXT CORE

**Status:** APPROVED & ADOPTED  
**Date:** 2026-09-02  
**Author:** Antigravity Engineering (Low-Latency Systems, Local-LLM & Quantitative Infrastructure)  
**Scope:** `src/oracle_sol`, `src/external_context`, `citadel-dashboard`

---

## 1. Context & Architectural Challenge

CITADEL's primary mission is deterministic, sub-millisecond execution and real-time market truth on Indian equity indices (NIFTY/BANKNIFTY). Previously:
1. External context relied on a fragile browser-automated "Gemini Spark" script that suffered from `SPARK_CONTEXT_MISSING`, lacked verified provenance, and introduced brittle execution hooks.
2. Market reasoning relied on remote models (Gemini 3.7 Flash or GPT-5.6 Sol) which suffered from rate limits, unpredictable network jitter, and zero local offline autonomy.
3. The host workstation is an Apple M1 with **8 GB unified memory** running near ~3.5 GB swap usage. Running a 9B parameter model (~6.6 GB Q4_K_M) alongside live market ingestion risks catastrophic memory pressure and swap thrashing if not ruthlessly isolated.

### Architectural Critique & Boundary Review
As low-latency, local-LLM, and quantitative systems engineers, we challenged the proposed design on 4 key friction points:

1. **Synchronous Coupling Risk:** Under no circumstances may an LLM inference call or external HTTP network request sit on the Dhan tick ingestion thread or Fast Lane SSE publishing loop.
2. **Backlog Explosion Under Revision Churn:** If Nifty moves rapidly, canonical state updates at 10–50 Hz. If Qwen 9B takes 4–10 seconds per inference, an FIFO queue would create an unrecoverable 500-job backlog of stale evaluations.
3. **Model Memory Illusion:** LLMs are stateless next-token predictors prone to hallucinations and drift. LLMs must NOT own session history or historical state transitions.
4. **Context Window Waste:** While Qwen 3.5 supports 256k tokens, feeding massive context wastes memory bandwidth, spikes TTFT, and degrades M1 memory pressure. CITADEL must compile a compact, event-sourced, diff-based "BrainPacket" (<2k tokens).

---

## 2. Inviolable Architectural Principles Adopted

The design strictly adopts and enforces the 8 foundational boundaries:

1. **One Dhan Owner:** PID 61253 retains exclusive ownership of the single production WebSocket to Dhan. No second socket or market connection shall ever be opened.
2. **Deterministic Hot Path Isolation:** The pipeline `Dhan -> decode -> Order Flow -> VOB / Options Engine -> Fast Lane -> Frontend` runs in memory-isolated processes/threads. Local Brain and External Context run strictly out-of-band on a background worker.
3. **Durable Session Memory Outside the Model:** CITADEL owns session state, canonical revisions, and the `ThesisGraph`. The LLM receives only a snapshot + diff + unseen events and returns a structured output.
4. **Evidence-Referenced LLM Output & Evidence Gate:** Every claim or verdict made by Qwen must reference valid canonical `evidence_ids` or verified `external_event_ids`. If an unsupported claim is detected, the Evidence Gate rejects the thesis (`MODEL_CLAIM_UNSUPPORTED`) and halts cursor progression.
5. **No Arbitrary Trading Thresholds:** Zero synthetic confidence scores (e.g. "87% bullish"). The model outputs discrete, structured reasoning across perspectives: `OBSERVER`, `CALL CASE`, `PUT CASE`, `NO-TRADE CASE`, `SKEPTIC`, `TEMPORAL ANALYST`, `OPTION BUYER ANALYST`, `EXTERNAL CONTEXT ANALYST`, and `SYNTHESIS` (`CALL`, `PUT`, `CALL_DEVELOPING`, `PUT_DEVELOPING`, `NO_TRADE`).
6. **Zero Live Execution Authority:** Qwen and Gemini operate as **SHADOW ONLY** (`paper_only=True`, `live_trading=False`, `broker_submission=False`, `execution_influence=0`).
7. **VOB Firewall:** Volume Order Block (VOB) calculations and algorithmic indicators remain 100% deterministic mathematical calculations (`src/vob/`). Neither Qwen nor external news feeds can alter VOB state.
8. **Resource Governor on 8 GB M1:** If Qwen inference triggers memory pressure warnings (system free memory < 15%, swap spikes > 1 GB delta, or Fast Lane latency degrades), the Governor immediately signals `keep_alive=0`, unloads the model, logs `QWEN_9B_LIVE_UNSAFE_ON_8GB`, and leaves CITADEL's hot path untouched.

---

## 3. Subsystem Architecture

### A. LocalModelAdapter (`src/oracle_sol/local_model_adapter.py`)
- Abstract base class: `LocalModelAdapter` defining `invoke_reasoning(...)` returning standardized telemetry: `model`, `request_id`, `started_at`, `ended_at`, `prompt_eval_count`, `eval_count`, `prompt_eval_duration`, `eval_duration`, `total_duration`, `load_duration`, `schema_status`.
- Concrete adapter: `OllamaQwenAdapter` communicating over `http://127.0.0.1:11434/api/generate` with strict local binding, `format="json"`, and strict structured schema.
- Prepared for drop-in `MLXLMAdapter` in future without architectural changes.

### B. BrainPacket Compiler (`src/oracle_sol/brain_packet_compiler.py`)
- Compiles:
  - Latest Canonical State (Revision $R_n$)
  - Previous Committed Thesis Summary & Watch Conditions
  - Unseen Canonical Market Events ($\Delta E$ since previous thesis cursor)
  - Verified External Events & External Quotes (from ExternalContextCore)
- **Coalescing Policy:** If revisions $R_{101} \dots R_{120}$ occur during inference, intermediate jobs are dropped. The next inference receives $R_{120}$ plus the full set of unseen event IDs $\{e_{101} \dots e_{120}\}$. Backlog depth is bounded at 1.

### C. Thesis Graph & Evidence Gate (`src/oracle_sol/thesis_memory.py`)
- Graph of immutable `ThesisNode` instances linked by `supersedes_thesis_id`.
- Gate checks:
  1. Strict JSON schema parsing.
  2. All cited `supporting_evidence_ids` and `contradicting_evidence_ids` exist in the input packet.
  3. No prohibited broker/trading keywords.
- Only a validated thesis advances the LocalBrain event cursor.

### D. ExternalContextCore (`src/external_context/core.py`)
- Autonomous polling service decoupled from market ingestion:
  - `OfficialIndiaAdapter`: RBI RSS, SEBI RSS, MoSPI release calendar (Tier A Official).
  - `FinanceNewsAdapter`: Marketaux REST API (100 req/day budget, deduplication).
  - `GlobalShockAdapter`: GDELT 2.0 API (~15-minute update cadence, keyless).
  - `WorldMarketAdapter`: Twelve Data Basic (8 req/min, 800 req/day, US ETFs/forex/commodities, explicitly labeled `EXACT` vs `PROXY`, `LIVE` vs `SESSION_LAST`).
- Outputs immutable `ExternalEvent` and `ExternalQuote` records.

### E. Spark Decommissioning
- Browser-based AppleScript automation scripts marked `RETIRED_PENDING_FINAL_REMOVAL`.
- Frontend dependencies on Spark replaced with typed `WorldContext` and `NewsContext` surfaces.
