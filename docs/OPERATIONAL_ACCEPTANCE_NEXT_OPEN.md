# CITADEL ORACLE — NEXT MARKET-OPEN ACCEPTANCE PROCEDURE (5–10 MINUTE CHECKLIST)

## Pre-Conditions
- Time: 09:15–15:30 IST (Regular Market Trading Hours).
- Serving backend running on port 8000.
- Serving frontend dashboard running on port 3000 (`http://localhost:3000/oracle`).
- Single Dhan client connection active (0 duplicate owners).

---

## 1. Automated Acceptance Command
Run the unified 5-minute non-soak verification script:
```bash
/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python scripts/citadel_live_open_market_audit.py --duration 300
```

---

## 2. Real-Time Verification Checklist

| Step | Item to Verify | Expected Evidence | Inspection Command / UI Indicator |
| :--- | :--- | :--- | :--- |
| **1** | **Dhan Feed Ingestion** | 11/11 expected instruments actively ticking | `curl -s http://127.0.0.1:8000/v1/oracle/fast-lane/health \| jq .` |
| **2** | **Fast Lane Revisions** | Revision count monotonically advancing | Fast Lane UI header revision counter increments |
| **3** | **Market Data Dynamics** | NIFTY spot, futures, ATM CE/PE prices update naturally | `curl -s http://127.0.0.1:8000/v1/oracle/sol/state \| jq '.snapshot.nifty_spot_price, .snapshot.nifty_futures_price'` |
| **4** | **OI & Flow Hydration** | 5L MLOFI, Strike ladder closed OI, and IV populate | `curl -s http://127.0.0.1:8000/v1/oracle/sol/state \| jq '.reading_domains'` |
| **5** | **Sol Snapshots Advance** | `processed_count` increments in worker telemetry | `curl -s http://127.0.0.1:8000/v1/oracle/sol/state \| jq '.worker'` |
| **6** | **Reasoning Eligibility** | `reasoning_status` transitions from `AWAITING_EVIDENCE` / `OFF_MARKET` to `LIVE` | `curl -s http://127.0.0.1:8000/v1/oracle/sol/beacon \| jq .reasoning_status` |
| **7** | **Gemini Provider Call** | Exactly one real Gemini provider call observed per candidate cycle | Backend logs: `[GeminiModelAdapter] Provider call -> HTTP 200` |
| **8** | **Thesis Commit** | Strict structured schema validation passes, new thesis stored | `curl -s http://127.0.0.1:8000/v1/oracle/sol/beacon \| jq '.market_verdict, .why_bullets'` |
| **9** | **Spark Context in Envelope** | Active external context present in model request envelope | `curl -s http://127.0.0.1:8000/v1/oracle/sol/state \| jq '.external_context.external_context_id'` |
| **10** | **Frontend Parity** | Rendered /oracle cards match backend state revision exactly | Compare UI metrics against `/v1/oracle/sol/state` |
| **11** | **Animal Animation** | Living Market Forces Viewport displays natural animal (NO_TRADE, BULL, BEAR) only upon verified state change | `/oracle` hero animal video controller |
| **12** | **Connection Stability** | Zero reconnect loops; reconnect count remains stable | `curl -s http://127.0.0.1:8000/health/ready \| jq .` |
| **13** | **Single Dhan Owner** | Exactly 1 process PID owning Dhan socket | `lsof -i :8000 -i :3000` |

---

## 3. Post-Run Decision Gate
- **PASS**: All 13 items verified with live exchange data and HTTP 200 reasoning response.
- **DEGRADED**: Market data live, but Gemini quota returns HTTP 429 -> System remains truthfully fail-closed with `DEGRADED_ADVISORY`.
- **FAIL**: Any duplicate process, reconnect loop, VOB contamination, or ungrounded signal generation.
