# CITADEL SAFE SPARK EXTERNAL CONTEXT & GLOBAL SHOCK RADAR SPECIFICATION

## 1. Architectural Role of Spark
Gemini Spark serves exclusively as an **external market context and global shock radar**.

### Core Invariants:
1. **Not a Trading Authority**: Spark is strictly forbidden from issuing trading signals, directional recommendations (`CALL`, `PUT`), target prices, confidence scores, or probability estimates.
2. **Supplementary Background Only**: External context (US/global futures, Asian indices, India VIX / CBOE VIX, US 10Y yield, DXY, crude oil, macro calendars, central bank statements, geopolitical shocks) is provided to the Gemini 3.7 Flash reasoning brain as supplementary context.
3. **Primary Evidence Invariant**: Canonical microstructural market evidence (NIFTY spot LTP, futures basis, closed OI accumulation, order flow bursts, option surface pricing) remains PRIMARY.
4. **Transmission vs. Divergence**: A global shock is not automatically a NIFTY directional signal. The live Gemini reasoning brain compares external radar observations against domestic Indian market transmission (checking whether external weakness/strength is actively transmitting into domestic order flow/OI or diverging).
5. **Fail-Closed & Neutral**: Missing or stale external context degrades gracefully to `UNAVAILABLE` or `STALE` without impeding live derivatives reasoning.
6. **Strict Trust Boundary**: Public/HTTP external context payloads cannot self-declare CITADEL verification. In the absence of a trusted internal source connector, all live claims remain `UNVERIFIED`, and `source_verification_status` reports `NOT_CONNECTED`.

---

## 2. Expanded Radar Watchlist

The CITADEL Market Catalyst Monitor watches during market hours for material developments across:

| Radar Category | Assets / Focus Areas | Materiality Criteria |
| :--- | :--- | :--- |
| **US / Global Equity Futures** | Dow Jones futures, S&P 500 futures, Nasdaq futures | Sudden jump/decline, sharp reversal, unusual acceleration |
| **Asian Benchmarks** | Nikkei 225, Hang Seng, Kospi | Cross-market risk moves during Indian trading hours |
| **Volatility Radar** | India VIX, CBOE VIX | Abrupt volatility expansion or contraction |
| **Rates & FX** | US 10-Year Treasury Yield, DXY, USD/INR | Rapid yield spike/drop, currency pressure |
| **Commodities** | Brent Crude, WTI Crude | Energy price shocks affecting domestic constituent costs |
| **Macro & Central Banks** | RBI, Federal Reserve, ECB, MoSPI GDP / CPI releases | Policy rate decisions, commentary, inflation releases |
| **Index-Specific Shocks** | Heavyweight constituents (HDFC Bank, Reliance, etc.), MSCI rebalancing | Major structural rotation, constituent imbalances |
| **Geopolitical Risk** | Regional conflicts, diplomatic/trade escalations | Unexpected breaking macro risk events |

> [!IMPORTANT]
> **India VIX Canonical Rule**: Spark monitors India VIX from reliable public reporting for supplementary context only. Ultra low-latency India VIX monitoring must ultimately come directly from CITADEL's canonical market data feeds, not from Spark.

---

## 3. Strict Data Contract & Schema

### Root Fields
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `external_context_id` | `string` | Unique, deterministic identifier for the context payload. |
| `market_session_date` | `string (YYYY-MM-DD)` | Trading session date the context applies to. |
| `generated_at_utc` | `string (ISO 8601)` | Timestamp when context was prepared by Spark. |
| `generated_at_ist` | `string (HH:MM:SS)` | IST representation of preparation timestamp. |
| `received_at_utc` | `string (ISO 8601)` | Timestamp recorded by CITADEL at time of ingestion. |
| `received_at_ist` | `string (HH:MM:SS)` | IST representation of ingest timestamp. |
| `provider` | `string` | e.g. `"gemini_spark"`. |
| `source_type` | `string` | e.g. `"PRE_MARKET_BRIEF"`, `"GLOBAL_SHOCK_ALERT"`, `"BREAKING_UPDATE"`, `"TEST_FIXTURE"`. |
| `scheduled_events` | `array[ExternalFactItem]` | Pre-scheduled economic releases, MPC/FOMC calendars. |
| `breaking_events` | `array[ExternalFactItem]` | Unscheduled breaking geopolitical, global futures, or corporate updates. |
| `overnight_context` | `array[ExternalFactItem]` | US indices, global bond yields, crude oil, currency benchmarks. |
| `index_specific_events` | `array[ExternalFactItem]` | Nifty 50 constituent earnings, index rebalancing events. |
| `global_context` | `array[ExternalFactItem]` | Broad macroeconomic metrics, DXY, regional Asian markets. |
| `data_gaps` | `array[string]` | Explicit acknowledgments of missing or delayed data points. |
| `sources` | `array[SourceMeta]` | List of source institutions, feeds, and reliability tiers. |
| `is_test_fixture` | `boolean` | Flag indicating synthetic/test data vs live observations. |
| `provenance_hash` | `string (SHA-256)` | Cryptographic digest over canonical payload content. |

### `ExternalFactItem` Fields
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `fact_id` | `string` | Unique identifier for the individual fact. |
| `title` | `string` | Concise factual headline. |
| `factual_summary` | `string` | Objective narrative summary of observed development. |
| `status` | `CONFIRMED \| DEVELOPING \| UNCONFIRMED` | Upstream status of the event. |
| `event_time_utc` | `string \| null` | Actual or scheduled event occurrence timestamp. |
| `event_time_ist` | `string \| null` | IST representation of event timestamp. |
| `observed_or_published_at`| `string \| null` | Publication timestamp by upstream source. |
| `source_name` | `string` | Primary publisher / regulatory body / exchange. |
| `source_url` | `string \| null` | Verifiable URL reference. |
| `source_timestamp` | `string \| null` | Raw source publication timestamp. |
| `relevance_note` | `string \| null` | Factual macro relevance (must NOT contain trading terms). |
| `upstream_verification_status` | `string` | Self-declared claim from upstream Spark (NOT trusted by CITADEL). |
| `verification_status` | `UNVERIFIED \| SOURCE_UNAVAILABLE \| VERIFIED \| CONFLICTED \| SYNTHETIC_TEST` | CITADEL's independent verification verdict. |
| `conflict_detail` | `object \| null` | Preserves discrepancy details if verified source differs from Spark claim. |

---

## 4. Prohibited Content Rules (Firewall)

CITADEL strictly rejects any payload containing:
1. **Trading Signals or Bias Terms**:
   `CALL`, `PUT`, `calls`, `puts`, `bullish`, `bearish`, `buy`, `sell`, `long`, `short`, `target`, `targets`, `stoploss`, `support`, `resistance`, `probability`, `confidence score`, `expected direction`, `overweight`, `underweight`.
2. **Broker Credentials or Order Commands**:
   `dhan_token`, `access_token`, `client_id`, `account_id`, `password`, `secret`, `api_key`, `place_order`, `modify_order`, `cancel_order`, `order_type`, `quantity`, `trade_id`.

---

## 5. Spark Monitor Agent System Instructions

When executing the Spark Market Catalyst & Global Shock Monitor skill, the agent operates under these strict instructions:

```text
You are CITADEL's External Market Radar.

During Indian market hours, monitor current public information for material global-market, volatility, macro, geopolitical, and index-specific developments that could affect NIFTY intraday conditions.

Watch:
- Dow futures, S&P 500 futures, Nasdaq futures
- Nikkei, Hang Seng, Kospi
- India VIX, CBOE VIX
- US 10-Year Treasury Yield, DXY, USD/INR
- Brent, WTI crude oil
- RBI, Federal Reserve, major macro events
- Major index constituent developments, MSCI rebalances
- Geopolitical shocks and unexpected global risk developments

Report only genuinely meaningful developments.
Do not provide trading signals or infer NIFTY direction.

For every alert provide:
- What changed
- Actual magnitude if reliable
- IST timestamp
- Known catalyst if verified
- Source
- Status (CONFIRMED / DEVELOPING / UNCONFIRMED)
- What remains unknown (data gaps)

Do not invent percentage thresholds or missing values.
Output valid JSON adhering to CITADEL external-context schema only.
```

---

## 6. Ingestion & Persistence Architecture

- **Ingest Endpoint**: `POST /v1/oracle/sol/external-context/ingest`
- **Durable History**: `data/sol_shadow/external_context_history.jsonl`
- **Zero Look-Ahead Invariant**: `ExternalContextStore.get_context_as_of(session_date, timestamp_utc)` ensures that historical cycle replay never sees future context.

---

## 7. Operational Transport Path & Truth Alignment

### A. Current Transport Path
```text
[Spark Browser Scan in Gemini Spark]
               ↓ (Manual / Browser DOM Extraction)
[Browser / UI Extraction]
               ↓ (Formatting)
[Local Conversion to Canonical JSON Schema]
               ↓ (Local HTTP POST)
[CITADEL Ingest: POST /v1/oracle/sol/external-context/ingest]
```
> [!IMPORTANT]
> **No Autonomous Push**: Direct autonomous server-to-server Spark → CITADEL push delivery is **NOT IMPLEMENTED**. Ingestion currently operates via browser extraction and local JSON ingest bridge.

### B. Unverified Upstream Observations
- While `source_verification_status = NOT_CONNECTED`, **NO** Spark observation or scan result (including "NO MATERIAL BREAKING SHOCK DETECTED") is labeled `VERIFIED`.
- Spark findings are stored strictly as `UNVERIFIED` upstream intelligence.

### C. GDP Discrepancy Case Study
- *Observed Incident:* Spark reported India Q1 FY2026-27 GDP release schedule at 17:30 IST. Official MoSPI documentation states 16:00 IST.
- *Architectural Lesson:* Demonstrates why external LLM-scraped claims must never self-promote or be treated as ground truth without an independent authoritative retrieval connector.

---

## 8. Live Market Session Observation & Latency Protocol

During prospective live shadow market sessions, CITADEL records the following audit timeline for every external radar development:

### Telemetry Timestamps Recorded:
1. `T_event`: Timestamp the underlying external move actually occurred (if reliably timestamped by exchange/primary source).
2. `T_spark`: Timestamp Spark recorded or generated the observation.
3. `T_extract`: Timestamp the observation was extracted from the browser environment.
4. `T_ingest`: Timestamp CITADEL ingested the payload (`received_at_utc`).
5. `T_reasoning`: Timestamp the live Gemini reasoning brain executed its analysis cycle incorporating the context.

### Latency Measurement Breakdown:
- **SPARK DETECTION LATENCY**: $T_{\text{spark}} - T_{\text{event}}$
- **TRANSPORT LATENCY**: $T_{\text{ingest}} - T_{\text{spark}}$
- **GEMINI REASONING LATENCY**: $T_{\text{reasoning}} - T_{\text{ingest}}$
- **TOTAL EVENT → BRAIN LATENCY**: $T_{\text{reasoning}} - T_{\text{event}}$

### Transmission & Omission Audit:
- Record whether live Gemini reasoning recognized the external development.
- Record subsequent NIFTY spot, futures basis, closed OI delta, and option response.
- Record any false alerts or material cross-market shocks that Spark failed to detect.

