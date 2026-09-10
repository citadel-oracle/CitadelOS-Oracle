# CITADEL_RISK_PAPER_FRONTEND_WIRED

Recorded: 2026-07-10 Asia/Kolkata

## Checkpoint type

Non-destructive local report. No commit/tag was created because the pre-existing dirty tree cannot be safely separated from user-owned staged, unstaged, untracked, secret, and runtime changes.

## Git reference

- Branch: `main`
- HEAD: `4086c44b5cc2b0433e34d090baacd1da824bc4ca`

## Verified result

- Python syntax validation: passed
- Safe pytest collection: 101
- Safe pytest result: 101 passed, 0 failed, 0 skipped
- Full safe command: `.venv/bin/python -m pytest -q -m 'not external_data'`
- Next.js production command: `npm run build`
- Next.js production result: passed
- Frontend lint command: `npm run lint`
- Frontend lint result: passed with zero errors or warnings
- Live trading: disabled
- Dhan Trading API calls: none
- Broker mutations: none

## Intended checkpoint files

- Backend: `src/api/control_status_api.py`, `app/main.py`
- Frontend: `citadel-dashboard/src/app/page.tsx`, `citadel-dashboard/src/app/globals.css`
- Tests: `tests/test_control_status_api.py`, `tests/test_risk_paper_dashboard_contract.py`
- Documentation: `PROJECT_STATUS.md`, `docs/CITADEL_CONTEXT.md`, `docs/DECISIONS.md`, `docs/NEXT_TASK.md`, `docs/checkpoints/`

## Read-only contracts

- `GET /v1/risk/status`
- `GET /v1/paper/status`

Both responses are sanitized projections. No frontend mutation control or direct runtime-file access was added.

## Protected frontend hashes after wiring

- `citadel-dashboard/src/app/page.tsx`: `219a0738aaad76d0e8b86f35ad6a25232c1cb9426f8deca860212db4a5ffc3e6`
- `citadel-dashboard/src/app/globals.css`: `a2f5c70396c42a837b1c951df1efae542e360517d1fb470f08ef063deafcb67a`

## Explicit exclusions

This checkpoint does not include `.env`, credentials, `logs/paper_state.json`, runtime CSVs, caches, `node_modules`, `.next`, or recovery backup files. No secret values are recorded.
