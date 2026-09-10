# CITADEL OS — Oracle Complete + Frontend Wired Checkpoint

Checkpoint date: 2026-07-10 (Asia/Kolkata)

## Scope completed

- Added one deterministic, explainable, read-only current-market Oracle service.
- Added sanitized GET-only Oracle health and symbol assessment routes.
- Replaced the existing Oracle dashboard area's legacy reasoning feed with the selected-symbol authoritative assessment contract.
- Preserved the accepted Dashboard V1.1 layout, existing sections, symbol selector, one three-second polling loop, retry/timeout/abort behavior, stale-data preservation, responsive system, and footer.
- Added deterministic backend/API and frontend contract tests.
- Updated the durable production documentation and recorded Athena Enforcement as the next milestone.

## Files created

- `src/oracle/oracle_service.py`
- `tests/test_oracle_service.py`
- `tests/test_oracle_dashboard_contract.py`
- `docs/checkpoints/CITADEL_ORACLE_COMPLETE_FRONTEND_WIRED.md`

## Files updated

- `app/main.py`
- `src/api/dashboard_api.py`
- `src/oracle/__init__.py`
- `citadel-dashboard/src/app/page.tsx`
- `citadel-dashboard/src/app/globals.css`
- `PROJECT_STATUS.md`
- `docs/CITADEL_CONTEXT.md`
- `docs/DECISIONS.md`
- `docs/NEXT_TASK.md`

The repository had a mixed pre-existing working tree containing user-owned, secret, runtime, staged, and unrelated changes. This checkpoint did not reset, clean, discard, or include those changes in a commit. HEAD observed during the milestone was `4086c44b5cc2b0433e34d090baacd1da824bc4ca`; no commit or tag was forced.

## Oracle contract and logic

The assessment returns symbol, timeframe, generated/source times, data age/status, Oracle health, directional bias, signal, bounded confidence/label/formula, regime, reason codes, human reasoning, typed input features, warnings, maturity, and source/fallback metadata.

Existing production scanner evidence is used: EMA 21/38 structure, price versus VWAP, RSI, ADX/ATR availability, multi-timeframe bias, scanner bias/trade state, regime, liquidity classification, and existing Kronos confidence. Trusted volume is not present in the scanner snapshot and is explicitly unavailable.

Confidence is deterministic: 75% normalized directional feature alignment plus 25% existing Kronos confidence, with opposing evidence subtracted and the result bounded to 0–100. `LONG`/`SHORT` requires complete live, trending, aligned evidence above the existing Kronos threshold. Cached data is degraded/non-actionable `WAIT`; stale data is blocked `NO_TRADE`; missing/malformed/insufficient data cannot fabricate confidence or an actionable signal.

## Read-only endpoints

- `GET /v1/oracle/status`
- `GET /v1/oracle/assessment/{symbol}`
- `GET /v1/oracle/reasoning` — NIFTY compatibility alias to the same service

Supported symbols are `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, and `SENSEX`. Unsupported symbols receive a structured 404. Oracle reads only an existing process-local DashboardAPI cache and never triggers market refresh or broker transport.

## Frontend wiring

The existing Oracle panel now displays health, selected symbol/timeframe, freshness, directional bias, signal, confidence, regime, data age, top reason codes, warnings, maturity, and last update. No order, kill-switch, paper-state, or other mutation control was introduced. No entry, stop-loss, or target is fabricated.

## Verification

- Python syntax validation: passed.
- Pytest collection: 129 tests.
- Previous regression suite: 101 passed.
- New Oracle suite: 28 passed (24 service/API and four frontend contract cases).
- Full safe offline suite command: `.venv/bin/python -m pytest -q -m 'not external_data'`.
- Full safe result: 129 passed, 0 failed, 0 skipped, 0 deselected.
- Frontend lint command: `npm run lint`; passed with no reported errors or warnings.
- Frontend production build command: `npm run build`; passed on Next.js 16.2.10.
- Scoped `git diff --check`: passed.
- `config/settings.json` selected safety field: `live_trading_enabled=false`.

No Dhan Trading API or other network call was made for this milestone. Oracle has no `DhanClient`, broker mutation, Risk Authorization mutation, kill-switch mutation, or `PaperStateService` dependency. Its paper-state non-mutation test verifies unchanged bytes in an isolated temporary state file. No production paper state or trade journal was written by Oracle.

No `.env` value, credential, or secret was read or printed. The separate research repository `/Users/ayushmudgal/Documents/trading/dhan_codex_optimizer` was not accessed or modified.

## Known limitations

- Oracle is deterministic rule-based intelligence, not an LLM, predictive guarantee, or execution authority.
- It consumes only a previously built process-local dashboard snapshot and cannot refresh it; before the first snapshot it is unavailable.
- Snapshot and fallback caches are not shared across workers.
- `market_data_as_of` means backend scan completion, not exchange tick time.
- Trusted volume is absent from the current scanner contract, so no volume conclusion is produced.
- Existing indicator weights and thresholds were accepted as-is and were not optimized.
- Cached evidence is intentionally non-actionable and stale evidence is blocked.
- Oracle returns no entry, stop, target, order, risk authorization, or position action.
- Historical Oracle feature/performance CSV readers remain for derived analytics and are not the authoritative current assessment path.

## Next milestone

**Athena Enforcement**

Athena Enforcement was not started in this checkpoint.
