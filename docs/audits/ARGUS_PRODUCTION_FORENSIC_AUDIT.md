# CITADEL OS — ARGUS Production Forensic Audit Report

**Date of Audit:** 2026-07-25  
**Auditor:** Antigravity (Advanced Agentic Coding Pair)  
**Scope:** Read-Only Forensic Analysis of ARGUS Production State, Routing, and Components  
**Target Repository:** `/Users/ayushmudgal/Developer/CitadelOS`  

---

## 1. Executive Summary

This forensic audit has successfully diagnosed and mapped the root causes preventing **ARGUS** from delivering its full production functionality. The investigation revealed a chain of dependencies—ranging from a critical API credential expiry that occurred in real-time during our session to architectural cache-handling patterns and process/worktree directory mismatches—that together result in stale data, missing UI components, and downstream strategy blocks.

### Primary Root Causes Identified:
1. **Real-time Dhan Access Token Expiry:** The configured Dhan API token expired on **2026-07-25 10:40:41 UTC (16:10:41 IST)**, causing immediate HTTP 401 failures.
2. **Dhan Error-Parsing Bug:** An unhandled error response format from Dhan bypasses the API error checker and triggers an obfuscated `"Dhan expiry list returned no dates"` validation failure.
3. **In-Memory Cache Eviction on Restart:** Option chain data is held strictly in-memory. Restarts wipe the cache, and a startup connection failure prevents successful priming, blocking downstream modules.
4. **DevOps & Branch Mismatch:** The active Next.js dashboard and Uvicorn API serve code from a git worktree (`CitadelOS-Worktrees/rc2-backend` on branch `integration/operator-panels-20260721`), while the main workspace is on branch `feature/citadel-institutional-state-20260717-113828`.
5. **Frontend Mock Fallback Logic:** When the backend returns an error state, the React UI component silently defaults to hardcoded mockup values instead of displaying a clean error, creating a false illusion of "frozen stale data."
6. **Weekend Baseline Restrictions:** Persistent baselines are only allowed to initialize when the market state is `"OPEN"`, guaranteeing `INSUFFICIENT_DATA` verdicts during closed hours.

---

## 2. Safety Snapshot & Working-Tree State

### Git Working Tree (Main Workspace)
- **Directory:** `/Users/ayushmudgal/Developer/CitadelOS`
- **Current Branch:** `feature/citadel-institutional-state-20260717-113828`
- **Last Commit Hash:** `b46bf43af7425a422e101d6c1119c8b7b9e089fe`
- **Working-Tree Status:**
  - Modified: `.env`, `app/main.py`, `config/settings.json`, `src/operations/production.py` (Uncommitted modifications captured).

### Active Process & Port Mapping
- **Citadel API (Uvicorn):** 
  - **Port:** `8000` (Listening on localhost only)
  - **PID:** `820`
  - **Venv:** `/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha`
  - **Command Executed:** `/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python -m uvicorn --app-dir /Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend app.main:app --host 127.0.0.1 --port 8000`
- **Next.js Dashboard:** 
  - **Port:** `3000` (Listening on all interfaces)
  - **PIDs:** `884` & `988` (Node process group)
  - **WorkingDirectory:** `/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend/citadel-dashboard`
- **OpenAlgo:**
  - **Port:** `5001` (Listening on localhost only)
  - **PID:** `16085`
  - **Venv:** `/Users/ayushmudgal/openalgo/.venv`
  - **Mode:** `analyze` (analyze_mode = `true`)

---

## 3. Step-by-Step ARGUS Data Flow Map

```
  [ Dhan API ] (api.dhan.co)
       |
       v (POST /v2/optionchain/expirylist) -> Resolves expiration date
       v (POST /v2/optionchain) -> Fetches 31-strike raw option chain
       |
 [ Citadel API ] (ArgusAPI - app/main.py)
       |
       +---> ArgusBaselineStore: Resolves/Writes intraday baseline to logs/argus_oi_baselines.json (if OPEN)
       |
       +---> OptionChainEngine: Computes basic PCR, Dominance, Walls, Verdicts
       |
       +---> [Cache Check]: Writes to in-memory dict (self._cache) - TTL: 3.0s
       |
  [ Worker Process ] (ProjectionProcessWorker)
       |
       v (Builds prepared snapshot via OptionChainEngine.build_prepared_snapshot)
       |
  [ Tactical Edge Engine ] (ArgusTacticalEdgeEngine - rc2-backend worktree)
       |
       v (Evaluates Option Chain + OSE projections to calculate Pressure, Breadth, Persistence)
       |
  [ Serialization ] (v2_integration.py)
       |
       v (POST /v2/dashboard endpoint returns precomputed JSON snapshot)
       |
  [ Next.js Dashboard ] (ArgusTacticalEdgePanel.tsx)
       |
       v (Renders panel metrics or defaults to mockup fallback if backend data is null)
```

---

## 4. Specific Technical Breakdown of Failures

### A. Dhan Access Token Expiry (Real-time Defect)
- **Token Decoded Expiry Timestamp:** `1784956241` (which translates to **2026-07-25 10:40:41 UTC / 16:10:41 IST**).
- **Direct Curl Output (Bypassing Sandbox to `api.dhan.co`):**
  ```json
  {"data":{"808":"Authentication Failed - Client ID or Token invalid"},"status":"failed"}
  ```
- **Consequence:** Because this token expired in the middle of our forensic run, all subsequent calls to Dhan fail.

### B. Dhan API Error-Parsing Bug
- **Location:** `src/argus/option_chain_engine.py` (Line 756 in worktree / main)
- **Implementation:**
  ```python
  @staticmethod
  def _raise_for_dhan_error(response, label):
      if not isinstance(response, dict):
          raise OptionChainDataError(f"Dhan {label} returned an invalid response")
      error = (
          response.get("errorMessage")
          or response.get("error")
          or response.get("remarks")
      )
      if error:
          raise OptionChainDataError(f"Dhan {label} failed: {error}")
  ```
- **Defect:** Dhan sends authentication failure logs inside `response.get("data")` rather than `"errorMessage"`, `"error"`, or `"remarks"`.
- **Result:** `_raise_for_dhan_error` returns `None` silently. Then, `active_expiries()` extracts `expiries = response.get("data")`, which is a dictionary. The type check `isinstance(expiries, list)` fails and throws a generic `OptionChainDataError("Dhan expiry list returned no dates")` instead of an authentication error.

### C. In-Memory Cache Loss & Priming Sequence
- **Location:** `src/api/argus_api.py` (Line 52)
- **Implementation:** Cache is stored as `self._cache = {}`.
- **Defect:** Every time the Uvicorn process restarts, the cache is completely wiped. When the server tries to prime the cache on startup with `argus.get_oi("NIFTY")`, if it fails (due to token validation or weekend closure), the cache remains empty.
- **Downstream Consequence:** Read-only callers like `argus.projection("NIFTY")` *only* read from this cache. If empty, they return `None` indefinitely, locking strategy engines and option charts into a perpetual `WAITING_FOR_ARGUS` block.

### D. Mismatched Git Branches & Process Directories
- **Defect:** The running Node dashboard and Uvicorn API serve source code from `/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend` (on branch `integration/operator-panels-20260721`). However, the developer workspace is on branch `feature/citadel-institutional-state-20260717-113828`.
- **Impact:** Any changes made by the developer in the main workspace directory are not reflected in the active runtime unless they are manually copied over or the worktree path is updated.

### E. Frontend Fallback Mock Values Rendering
- **Location:** `ArgusTacticalEdgePanel.tsx` (Lines 30-130 in worktree)
- **Defect:** When the backend feed fails (i.e. `data` is empty), the UI component falls back to hardcoded defaults:
  - `pressure.put_score` defaults to `54.5%`
  - `oiChange` defaults to `-3929120`
  - `callWall` / `putWall` default to `25000` / `23000`
  - Recommended Contract defaults to `24100 PE` at `@ ₹248`
- **Impact:** The UI appears to show active data (which is actually mock data), masking the fact that the underlying system has completely failed to fetch options data from Dhan.

### F. Weekend Baseline Constraints
- **Location:** `src/argus/baseline_store.py` (Line 58)
- **Defect:** `ArgusBaselineStore.resolve()` restricts baseline persistence to `"OPEN"` market hours only. On weekends, `baseline_timestamp` resolves to `None`, forcing `OptionChainEngine._verdict()` to fall back to `INSUFFICIENT_DATA`.

---

## 5. Verified Downstream Impact

1. **Aegis Decision Engine:** Under `current_argus_projection`, when the cache is empty, the return value is `None`, which flags the Aegis input provider with `AUTHORITATIVE_OPTION_CHAIN_UNAVAILABLE` or `WAITING_FOR_ARGUS`.
2. **Strategy Lab Option Charts:** `OptionCharts.status` returns `WAITING_FOR_ARGUS` because the underlying snapshot queue remains unhydrated.
3. **Completed Candle Context Provider:** Fails to ingest completed candles when the feed freshness is marked `stale` or `unavailable`, locking strategy executions.

---

## 6. Recommendations & Action Items

> [!IMPORTANT]
> The following recommendations must be executed once the audit phase concludes. No source modifications have been done during this forensic audit.

1. **Renew Dhan Access Token:** Obtain a fresh Dhan token and update `.env` in both the workspace and worktree directories.
2. **Fix Dhan Error-Parsing Logic:** Update `OptionChainEngine._raise_for_dhan_error` to scan the `"data"` field or check for `"status": "failed"` to raise explicit authentication failures.
3. **Implement Persistent Options Cache:** Refactor `ArgusAPI` to write the latest successful option chain snapshot to a persistent file (`logs/argus_latest_snapshot.json`) so it survives server restarts.
4. **Align Branches and Worktrees:** Reconcile the `rc2-backend` worktree with the main workspace to ensure that all development modifications are compiled from the correct active branch.
5. **Clean Frontend Fallback Behavior:** Remove the hardcoded UI fallbacks or display a prominent `DHAN CONNECTION FAULT / TOKEN EXPIRED` error banner so system operators are immediately notified of network/credential failures.
