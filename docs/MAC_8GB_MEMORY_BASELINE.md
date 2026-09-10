# CITADEL 8GB MAC — AUTHORITATIVE MEMORY BASELINE & RUNBOOK

## 1. Executive Summary & Root Cause Forensic
This Mac workstation operates with **8 GB Physical RAM**. Previously, the system experienced severe freezes and UI hangs (stalling up to 30–60 seconds). 

### Root Causes Proven:
1. **Unbounded Antigravity Language Server**: PID 1420 had run continuously for 3+ days, holding **4.46–5.66 GB physical footprint** and **553 open file handles** (502 pointing to historical conversation screenshots/transcripts).
2. **Unbounded DuckDB Buffer Pool in Sentinel**: DuckDB had no explicit memory cap on a 2.6 GB database with 61k+ rows, expanding up to **3.13–3.60 GB footprint**.
3. **Next.js Development Server Overhead**: `launchd` was running `npm run dev` (Webpack in-memory HMR compiler, unminified ASTs), consuming **1.58 GB footprint** for a simple dashboard.
4. **Resulting Memory Collapse**: Total tracked process footprint exceeded **15.5 GB**, forcing macOS into deep swap exhaustion (**~6.1 GB swap**), triggering sustained disk thrashing (**457 MB/s @ 9,578 TPS**) and kernel thread starvation.

---

## 2. Permanent Frozen Memory Settings

### A. Sentinel DuckDB Memory Bounds
* Location: `/Users/ayushmudgal/CITADEL-Edge-Sentinel/src/config.py` & `storage.py`
* Authoritative Configuration:
  ```python
  DUCKDB_MAX_MEMORY = "512MB"
  DUCKDB_THREADS = 2
  preserve_insertion_order = False
  wal_autocheckpoint = "1GB"
  ```
* Measured Empirical Performance: Ingestion throughput: **685 rows/sec** (1,000 writes in 1.45s), Analytical queries: **15.7 ms**, Physical Footprint: **~518–691 MB** (down from 3,128 MB). Zero dropped frames, zero OOMs.

### B. Sentinel Service Lifecycle (Launchd)
* Location: `/Users/ayushmudgal/Library/LaunchAgents/com.citadel.edge-sentinel.plist`
* Manages Sentinel as a canonical daemon (`RunAtLoad=true`, `KeepAlive: { SuccessfulExit: false }`).
* Enforces single supervisor instance (`SENTINEL_OWNER_COUNT = 1`) backed by kernel file locks (`FLOCK_FILE`).

### C. Oracle Frontend Production Enforcement
* Location: `/Users/ayushmudgal/Library/LaunchAgents/com.citadel.frontend.plist`
* Permanently runs pre-compiled standalone production bundle:
  ```xml
  <key>ProgramArguments</key>
  <array>
      <string>/usr/local/bin/npm</string>
      <string>run</string>
      <string>start</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
      <key>NODE_ENV</key>
      <string>production</string>
  </dict>
  ```
* Measured Footprint: **~56–69 MB** (reclaiming **~1,520 MB** from dev server).

---

## 3. Expected Process Memory Classes (8GB Workstation Budget)

| Component | Target Memory Class | Typical Working Set | Notes |
| :--- | :--- | :--- | :--- |
| **macOS OS & WindowServer** | ~1,200–1,500 MB | ~1,350 MB | Base system services |
| **Oracle Backend (Uvicorn + Workers)** | ~1,200–1,800 MB | ~1,700 MB | Parent + 4 multiprocessing workers |
| **Next.js Production Frontend** | ~50–80 MB | ~68 MB | `next start` production runtime |
| **Sentinel Supervisor (512MB Bound)** | ~500–750 MB | ~520 MB | Live tick ingestion + DuckDB storage |
| **Antigravity Language Server** | ~150–250 MB | ~180 MB | Post-restart clean Go heap |
| **Antigravity UI & Helpers** | ~800–1,200 MB | ~1,000 MB | Electron pair programming workspace |
| **TradingView Desktop + MCP** | ~800–1,400 MB | ~1,300 MB | Electron charting terminal + Node MCP |
| **Safari (1 Oracle HUD Tab)** | ~300–450 MB | ~350 MB | Single `/oracle` HUD viewport |
| **Total Daily Workstation Stack** | **~5,000–6,800 MB** | **~6,468 MB** | **Fits securely within 8GB physical RAM** |

---

## 4. Operational Workflows & Tooling

### A. Running Fast Memory Preflight (<2 Seconds)
Run before opening heavy workflows or after startup:
```bash
/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/scripts/citadel_memory_preflight.sh
```
* Checks RAM, swap usage, memory pressure, individual component footprints, and audits for configuration drift.
* Outputs: `MEMORY_PREFLIGHT = GREEN / WARNING / CRITICAL`.

### B. Safe Frontend Rebuild & Deployment Workflow
Whenever editing frontend UI/dashboard code:
```bash
/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/scripts/rebuild_oracle_frontend.sh
```
* **Step 1**: Runs `npm run build` inside `citadel-dashboard`.
* **Step 2**: If build fails, **aborts immediately without killing the existing server** (zero downtime).
* **Step 3**: If build succeeds, kickstarts `com.citadel.frontend` via launchd.
* **Step 4**: Performs automated health checks on `/` and `/oracle` (HTTP 200) and Fast Lane SSE feed.
* **Step 5**: Prints active Build ID and confirms memory footprint (~68 MB).

*Note: `npm run dev` remains available manually for intentional local debugging only.*

### C. Lightweight Passive Resource Guard
* Service: `com.citadel.resourceguard` (PID managed by launchd).
* Script: `/Users/ayushmudgal/Developer/CitadelOS-Tooling/runtime/citadel-resource-guard.sh`
* Cadence: Samples every 30s with bounded circular logging (2,000 lines max in `logs/resource_guard.log`).
* Overhead: **<0.01% CPU**.
* Early Warning Policy:
  * `WARNING` (Yellow memory pressure or sustained swapouts): macOS notification `"CITADEL Memory Pressure Rising"`.
  * `CRITICAL` (Red memory pressure or heavy paging): macOS notification `"CITADEL Memory Pressure Critical"` with recommended action.
  * `Language Server Runaway` (>2.5 GB sustained): Notification `"Antigravity Runaway Warning"`.
  * `Safari Reminder`: Alerts user if background Safari tabs exceed 2.5 GB.
  * **ZERO AUTO-KILL**: Never automatically terminates processes.

### D. Safe Language Server Recovery
If Antigravity `language_server` ever accumulates stale handles over multi-day sessions and exceeds 2.5 GB:
1. Do **NOT** delete `~/.gemini/antigravity/brain` or conversation history.
2. Gracefully restart language server once:
   ```bash
   pkill -f "language_server.*--standalone"
   ```
3. Antigravity Main App automatically respawns a clean `language_server` instance (~180 MB footprint, 58 file handles) with zero state loss.

---

## 5. Absolute Safety Invariants
1. **NEVER AUTO-KILL**: Do not configure automated process killers on Oracle, Sentinel, TradingView, or Antigravity.
2. **NEVER DELETE RESEARCH / BRAIN DATA**: Historical DuckDB tick databases, parquet bundles, EOD reports, and Antigravity conversation logs must never be deleted.
3. **NEVER VACUUM PROD DUCKDB UNDER MEMORY PRESSURE**: VACUUM locks memory blocks during rewrite.
4. **PRESERVE TRADING FORMULAS**: Do not alter VOB, ARGUS, OSE, Flow, Dhan ownership, or R3 architecture.
