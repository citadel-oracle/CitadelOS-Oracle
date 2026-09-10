# CITADEL OS — Module Responsibility Freeze Checkpoint

Checkpoint date: 2026-07-11 (Asia/Kolkata)

## Architecture decision

ADR-022 permanently freezes the production module map:

- ARGUS — Options Positioning Intelligence
- KRONOS — Setup Quality & Timing Intelligence
- current `OracleService` — Technical Market Engine
- ATHENA — Risk & Capital Intelligence
- HERMES — News & Event Intelligence
- canonical ORACLE — Personal AI Trading Coach
- AEGIS — Final Decision Controller
- Risk Authorization — Absolute Hard Safety Gate

`docs/CITADEL_MODULE_ARCHITECTURE.md` records each module's role, inputs, outputs, allowed and forbidden dependencies, data ownership, current/future status, compatibility aliases, no-overlap boundaries, final flow, initial soft influences, hard vetoes, and migration sequence.

The soft influences—Technical 25%, KRONOS 25%, ARGUS 20%, Personal ORACLE 15%, HERMES 10%, ATHENA 5%—are documentation-only starting philosophy. No production score, strategy, or authorization behavior was changed. Risk Authorization retains absolute veto over every future AEGIS approval.

## Files created

- `docs/CITADEL_MODULE_ARCHITECTURE.md`
- `tests/test_module_architecture_contract.py`
- `docs/checkpoints/CITADEL_MODULE_RESPONSIBILITY_FREEZE.md`

## Files updated

- `PROJECT_STATUS.md`
- `docs/CITADEL_CONTEXT.md`
- `docs/DECISIONS.md`
- `docs/NEXT_TASK.md`
- `citadel-dashboard/src/app/page.tsx`
- `tests/test_oracle_dashboard_contract.py`

## Compatibility and dashboard label

The verified technical engine remains implemented by `src/oracle/oracle_service.py`. `OracleService`, its types/files, historical feature tooling, frontend internal types/components, and these routes remain compatibility aliases:

- `GET /v1/oracle/status`
- `GET /v1/oracle/assessment/{symbol}`
- `GET /v1/oracle/reasoning`

No file, class, route, payload, or stored artifact was destructively renamed. The current dashboard section label changed to **TECHNICAL INTELLIGENCE**, and `Oracle signal` changed to `Technical signal`. Loading/placeholder wording follows the same classification. Layout, styling, API calls, data mapping, polling, failure handling, responsive behavior, section position, and footer are unchanged.

## Verification

- Python syntax validation: passed.
- Pytest collection: 133 tests.
- Full safe offline command: `.venv/bin/python -m pytest -q -m 'not external_data'`.
- Result: 133 passed, 0 failed, 0 skipped, 0 deselected.
- Frontend production command: `npm run build`; passed with Next.js 16.2.10.
- Frontend lint command: `npm run lint`; passed with no reported errors or warnings.
- Scoped `git diff --check`: passed.
- Contract coverage protects permanent role names, Risk Authorization veto language, Oracle route compatibility, the Technical Intelligence label, one polling interval, ARGUS/Risk & Paper/footer presence, and `live_trading_enabled=false`.

No Dhan API or other external API was called. No broker mutation, paper trade, strategy action, risk-state mutation, or live order simulation occurred. The offline suite retained its socket-level network block. No `.env` value, credential, or secret was read or printed.

The separate research repository `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` was not accessed or modified.

The existing working tree remains mixed with pre-existing user-owned, secret, runtime, staged, and unrelated changes. Nothing was reset, cleaned, discarded, committed, or tagged as part of this checkpoint.

## Next milestone

**ATHENA RISK & CAPITAL INTELLIGENCE**

Athena implementation was not started during this responsibility-freeze milestone.
