# CITADEL OS — HERMES News & Event Intelligence Foundation Complete

Checkpoint date: 2026-07-11 (Asia/Kolkata)

## Scope completed

- Added one typed, deterministic, provider-agnostic, read-only HERMES foundation.
- Added normalized contracts for scheduled economic events, market news, social-media catalysts, and official announcements.
- Added centralized India/global taxonomy, event windows, source-confidence rules, duplicate grouping, conflict preservation, freshness, and advisory event-risk assessment.
- Added explicit offline in-memory and fixture providers without activating any external provider.
- Added cache-only GET routes and a compact HERMES dashboard section that never triggers provider refresh.
- Preserved all frozen modules, broker/risk/paper safety, dashboard V1.1 structure, single polling loop, responsive behavior, and footer.
- Updated durable documentation and recorded Personal Oracle Data Foundation as the exact next milestone.

## Files created

- `src/hermes/__init__.py`
- `src/hermes/models.py`
- `src/hermes/providers.py`
- `src/hermes/taxonomy.py`
- `src/hermes/hermes_service.py`
- `tests/test_hermes_service.py`
- `tests/test_hermes_dashboard_contract.py`
- `docs/checkpoints/CITADEL_HERMES_FOUNDATION_COMPLETE.md`

## Files updated

- `app/main.py`
- `citadel-dashboard/src/app/page.tsx`
- `citadel-dashboard/src/app/globals.css`
- `PROJECT_STATUS.md`
- `docs/CITADEL_CONTEXT.md`
- `docs/CITADEL_MODULE_ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/NEXT_TASK.md`

## Service architecture and contracts

`HermesService.refresh_from_provider()` is the explicit ingestion boundary. Providers return bounded typed `HermesInput` records. `assessment()` and `events_payload()` only retime and read the current process-local normalized cache; they never invoke the provider.

Immutable contracts cover input kind, event type, impact, sentiment, timing, source type/confidence, affected scope, normalized event, assessment, source metadata, and freshness metadata. Normalized output retains bounded safe fields and source traceability but no raw payload, auth header, credential, or unbounded provider content. Source URLs are restricted to HTTP(S) origin/path and lose userinfo, query, and fragment. Raw provider IDs are exposed only when they match a restrictive safe identifier policy.

Central timing defaults:

- imminent: within 30 minutes
- live: scheduled time through 15 minutes after
- recent: within 120 minutes
- relevant: six hours
- provider snapshot stale: five minutes
- top assessment events: five
- events API maximum: twenty

Source-confidence policy:

- high: official government, central bank, exchange, regulator, authenticated official publication
- medium: recognized newswire or approved provider
- low: secondary aggregator, unverified social, unknown publisher
- unknown: insufficient metadata

Low/unknown-confidence evidence cannot alone remain `CRITICAL`. Unverified social input is always low confidence even when its claimed source category is official.

Duplicate identity uses taxonomy/date for known events and normalized headline/time otherwise. The highest-confidence record supplies representative timing; all source names remain traceable. Impact, sentiment, or timing disagreement is explicitly marked `CONFLICTING_SOURCES`. No conflicting official source is silently discarded.

Assessment policy:

- no/low material event: `NORMAL`
- medium or non-imminent high impact: `CAUTION`
- imminent/live high, high breaking news, or high-confidence conflict: `WAIT`
- imminent/live critical evidence: `AVOID_NEW_TRADES`
- missing/unconfigured/malformed source: `UNAVAILABLE / UNKNOWN / WAIT`
- stale provider snapshot: `STALE / UNKNOWN / WAIT`

HERMES is advisory only and has no direct execution block.

## Provider and API status

Production uses `HermesService(provider=None)`. No fixture or sample headline is activated. Production therefore truthfully reports provider-not-configured and unavailable until an explicitly approved provider is refreshed outside GET polling.

- `GET /v1/hermes/status` — bounded cached assessment
- `GET /v1/hermes/events` — bounded cached normalized event list

Both routes are GET-only, sanitized, deterministic, and `external_refresh_on_read=false`.

## Frontend

The existing intelligence grid now includes **HERMES — NEWS & EVENT INTELLIGENCE** before System Insights. It shows health, provider mode, freshness, overall event risk, recommendation, sentiment, next major event/countdown, impact, timing, source confidence, affected scope, bounded headlines, conflicts, reasons, missing-data warnings, maturity, and last update.

Fixture/in-memory mode is visibly labeled `Fixture / development intelligence · Not live news`. `READY` HERMES data uses cached—not live—status treatment. Unknown, stale, and unavailable values remain explicit. No refresh, action, order, ticker, or trade control exists.

## Verification

- Python syntax validation: passed.
- Previous safe regression suite: 159 passed.
- New HERMES suite: 34 passed (30 model/service/API/safety and four frontend contract cases).
- Pytest collection: 193 tests.
- Full command: `.venv/bin/python -m pytest -q -m 'not external_data'`.
- Full result: 193 passed, 0 failed, 0 skipped, 0 deselected.
- Frontend command: `npm run build`; passed with Next.js 16.2.10.
- Frontend command: `npm run lint`; passed with no reported errors or warnings.
- Scoped `git diff --check`: passed.
- `live_trading_enabled=false` remains protected by the existing safety contract.

The offline suite retains a socket-level network block. No external news/calendar/social API, Dhan API, web crawler, scraper, or paid provider was called. No broker, Risk Authorization, kill-switch, Paper State, strategy, or execution mutation occurred. No `.env` value, credential, token, or secret was inspected or printed.

The separate research repository `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` was not accessed or modified.

The working tree remains mixed with pre-existing user-owned, secret, runtime, staged, and unrelated changes. Nothing was reset, cleaned, discarded, committed, or tagged.

## Known limitations

- No production external provider, durable/shared cache, scheduler, source-coverage SLA, exchange-holiday calendar, or market-session input exists.
- Process-local cache is empty after restart and must be explicitly refreshed by a future approved ingestion workflow.
- Offline fixture/in-memory data proves behavior but is not live market news.
- Source confidence is category policy, not independent fact verification.
- Duplicate matching is stable taxonomy/headline/time normalization, not semantic NLP entity resolution.
- Sentiment is accepted only as normalized provider evidence and is never inferred from headlines.
- Event taxonomy provides deterministic default type/impact/scope only when an explicit taxonomy key is supplied.
- HERMES advisory output is not consumed by AEGIS because AEGIS is not implemented.

## Next milestone

**PERSONAL ORACLE DATA FOUNDATION**

Personal Oracle work was not started during this milestone.
