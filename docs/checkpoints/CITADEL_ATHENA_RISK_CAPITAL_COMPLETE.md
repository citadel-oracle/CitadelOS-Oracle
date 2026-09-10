# CITADEL OS — ATHENA Risk & Capital Intelligence Complete

Checkpoint date: 2026-07-11 (Asia/Kolkata)

## Scope completed

- Added one typed, deterministic, read-only `AthenaService`.
- Added canonical `GET /v1/athena/status` and retained `GET /v1/athena/wheel` as a compatibility projection.
- Upgraded the existing Athena preview panel in place to compact Risk & Capital Intelligence.
- Preserved Risk Authorization as the absolute final veto and preserved all broker, paper-state, strategy, ARGUS, Technical Intelligence, polling, layout, responsive, and footer behavior.
- Added deterministic backend/API/safety and frontend contract coverage.
- Updated durable architecture/status documentation and recorded HERMES as the exact next milestone.

## Files created

- `src/athena/__init__.py`
- `src/athena/athena_service.py`
- `tests/test_athena_service.py`
- `tests/test_athena_dashboard_contract.py`
- `docs/checkpoints/CITADEL_ATHENA_RISK_CAPITAL_COMPLETE.md`

## Files updated

- `app/main.py`
- `src/api/control_status_api.py`
- `citadel-dashboard/src/app/page.tsx`
- `citadel-dashboard/src/app/globals.css`
- `PROJECT_STATUS.md`
- `docs/CITADEL_CONTEXT.md`
- `docs/CITADEL_MODULE_ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/NEXT_TASK.md`

## Service architecture

ATHENA consumes two injected sanitized providers: `ControlStatusAPI.risk_summary()` and `ControlStatusAPI.paper_summary()`. It owns no state and has no DhanClient, broker mutation, execution, order, strategy, kill-switch mutation, or paper-position mutation dependency.

The assessment includes generated/trading time, ATHENA health, risk state, recommendation, bounded advisory size multiplier, daily P&L, daily loss usage/headroom, trade usage, loss-streak usage, open-position-capacity usage, exposure acceptability, current drawdown, optional capital/equity/drawdown-limit values, overall headroom, reason codes, explanation, warnings, missing inputs, maturity, and source metadata.

Risk Authorization remains final. Active kill switch, any exposed latest authorization `DENY`, reached daily-loss/trade/loss-streak/open-position limits, or unavailable/malformed required state maps to `STOP` and multiplier 0.00. ATHENA cannot turn a denial into permission.

Deterministic utilization policy:

- below 50%: `SAFE / CONTINUE / 1.00`
- 50–74.99%: `CAUTION / REDUCE / 0.75`
- 75–79.99%: `CAUTION / REDUCE / 0.50`
- 80–99.99%: `HIGH_RISK / PAUSE / 0.25`
- reached hard limit or veto: `STOP / 0.00`

The multiplier is advisory only. It is not broker quantity, does not assume lot size, does not alter settings, and cannot override Risk Authorization limits.

## API and frontend

- `GET /v1/athena/status` returns the full sanitized canonical contract.
- `GET /v1/athena/wheel` remains a legacy read-only projection from the same assessment.

The existing panel now displays ATHENA health, risk state, recommendation, advisory size, daily loss used, daily risk headroom, trades used, loss-streak usage, open positions, current drawdown, open-position-capacity exposure usage, overall risk headroom, available capital fields only when present, top reasons, warnings, maturity, and last update.

No buttons, order controls, kill-switch toggle, or other mutation control exists. Malformed responses fail visibly while the existing last-successful-data preservation behavior remains intact.

## Verification

- Python syntax validation: passed.
- Previous safe regression suite: 133 passed.
- New ATHENA suite: 26 passed (22 service/API/safety and four frontend contract cases).
- Pytest collection: 159 tests.
- Full command: `.venv/bin/python -m pytest -q -m 'not external_data'`.
- Full result: 159 passed, 0 failed, 0 skipped, 0 deselected.
- Frontend command: `npm run build`; passed with Next.js 16.2.10.
- Frontend command: `npm run lint`; passed with no reported errors or warnings.
- Scoped `git diff --check`: passed.
- `live_trading_enabled=false` remains protected by contract coverage.

No Dhan or other external API was called. No broker mutation, real/paper order simulation, paper-state mutation by ATHENA, kill-switch mutation, or strategy action occurred. Isolated tests verify that risk-control and authoritative-paper files remain byte-identical after assessment. No `.env` value, credential, or secret was read or printed.

The separate research repository `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` was not accessed or modified.

The working tree remains mixed with pre-existing user-owned, secret, runtime, staged, and unrelated changes. Nothing was reset, cleaned, discarded, committed, or tagged.

## Known limitations

- No authoritative blocked-capital, current-equity, broker-balance, margin, rupee-exposure, weekly/monthly risk-usage, or separate maximum-drawdown source exists.
- Paper cash balance is shown only when explicitly present; it remains null in the current production paper state.
- Exposure usage is open-position-capacity utilization, not financial exposure.
- Current drawdown is the negative portion of total daily paper P&L, not a peak-to-trough capital-equity series.
- The advisory multiplier is not instrument-, lot-, margin-, brokerage-, slippage-, or rupee-risk-normalized.
- The latest authorization projection has no request applicability/expiry contract; an exposed `DENY` is treated conservatively as a hard stop.
- ATHENA remains advisory and is not AEGIS or Risk Authorization.

## Next milestone

**HERMES NEWS & EVENT INTELLIGENCE FOUNDATION**

HERMES was not started during this milestone.
