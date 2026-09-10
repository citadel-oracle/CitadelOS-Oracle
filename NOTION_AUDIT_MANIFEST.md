# CITADEL Oracle Notion Audit Manifest

This private repository is a sanitized GitHub/Notion audit snapshot of the CITADEL Oracle codebase. It is not the authoritative production runtime checkout.

- Authoritative live local workspace: `/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9`
- Snapshot timestamp UTC: `2026-09-10T07:50:41.798771+00:00`
- Source branch: `checkpoint/vob-photonic-preintegration-current-oracle-20260816`
- Source HEAD: `b1bccd46f01edd145fb7aed59042875d294de822`
- Audit evidence package: `notion_audit/2026-09-10/`
- Runtime/live evidence: compact 2026-09-10 soak summaries derived from local telemetry.
- Offline evidence: source code, tests, docs, and lightweight configs copied with secrets/runtime dumps excluded.

## Current Model State

- Sol Option Specialist: PAUSED · INPUT HARDENING (`sol_paused=True`)
- Gemini Fast Scout: PAUSED · INPUT/ARCHITECTURE HARDENING (`gemini_paused=True`)
- Luna: CURRENT in current cognitive status

## Safety Invariants

- `AI_EXECUTION_INFLUENCE` must remain `0`.
- `BROKER_SUBMISSION` must remain `false`.
- `AI_VOB_INFLUENCE` must remain `0`.
- Sol/Gemini are paused for hardening and must not be resumed by audit work.
- Repository/runtime evidence outranks previous summaries.

## Inspect First

- `src/broker/`
- `src/oracle/`
- `src/vob/`
- `src/oracle_sol/`
- `src/order_flow/`
- `src/api/`
- `citadel-dashboard/src/components/institutional/`
- `citadel-dashboard/src/app/`
- `citadel-dashboard/src/dashboard/`
- `tests/`
- `notion_audit/2026-09-10/*.json`

## Known Current Problems To Audit

- Gemini/Sol stale displayed states can be bound to different receipts during the 30-minute soak.
- Sol readiness is incomplete and should be gated before paid dispatch when required option-economic inputs are missing.
- Challenger reads can be unavailable while Luna is current; distinguish intentional pause from frontend/projection failure.
- Fast Lane payloads are large and tail latency should be traced through serialization and endpoint payload shape.
- VOB active zone count was zero during the captured soak; do not infer a frontend bug without tracing backend state and projection contract.

## Do Not Infer

- Missing evidence does not mean the market condition did not exist.
- A successful JSON response does not mean useful intelligence.
- Stale/UNAVAILABLE UI state may come from provider pause, EvidenceGate rejection, stale receipt rejection, missing input evidence, projection bugs, frontend freshness bugs, inference in flight, or actual absence of accepted state.
- This audit snapshot is read-only evidence for Notion, not a runtime deployment target.
