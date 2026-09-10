# CITADEL GOLDEN RECOVERY STATE — 2026-08-07

## INCIDENT
An accidental recovery/rollback operation caused the primary CITADEL repository/runtime to temporarily expose an old July 2026 state.

The old runtime was also being auto-respawned from:
`/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend`

This made the visible CITADEL/Oracle appear approximately one month old.

## PROVEN PRE-INCIDENT STATE

Canonical pre-incident HEAD:

`46e040510b5e554b02e63da37b384f9f431437d8`

Short:
`46e0405`

Commit:
`fix(eye): enforce explicit live capture duration contract and forensic truth`

Timestamp:
`Fri Aug 7 10:43:54 2026 +0530`

THIS IS THE PRIMARY RECOVERY ANCHOR.

## BROKEN / ACCIDENTAL STATE

Broken merge/recovery HEAD:

`d10083f8871f8cb420f96b02974bfbdf512ebb2e`

Do NOT treat this as canonical production state.

Rescue branch preserving incident state:

`rescue/accidental-oracle-rollback-20260807`

## IMPORTANT LINEAGE PRESENT IN 46e0405

Eye Engine lineage includes:

- 0bedb4b
- 77f8cc8
- e8e32c8
- 2ca74a0
- b05c2b0
- 68a3d6e
- 5131cec
- 366ba4c
- c0b88c4
- 059bd91
- 9d406de
- 4db6dfd
- 3b535ba
- 30b28ff
- 5bfbc5f
- 46e0405

Oracle/frontend lineage includes important commits such as:

- 2a9045a — Single Store frontend
- 7227a56
- 34331fa
- 8632791

Never restore CITADEL by selecting an older branch merely because it is attached to the primary worktree.

Git commit/reflog ancestry is recovery truth.

## PRIMARY REPOSITORY

Canonical repository:

`/Users/ayushmudgal/Developer/CitadelOS`

Backend must run from this repository when production/local persistent CITADEL is intended.

Frontend must run from:

`/Users/ayushmudgal/Developer/CitadelOS/citadel-dashboard`

## WRONG RUNTIME SOURCE THAT CAUSED REGRESSION

Do NOT allow backend/frontend watchers to silently serve:

`/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend`

unless explicitly requested for isolated testing.

Before accepting runtime health always prove:

- PID
- process command
- cwd
- listening port
- git HEAD of serving repository

## EXPECTED PORTS

Backend:
`127.0.0.1:8000`

Frontend:
`127.0.0.1:3000`

Runtime validation must verify actual CWD, not merely successful HTTP response.

## INCIDENT RECOVERY RESULT

Latest recovery reported:

`LATEST_CITADEL_PRE_INCIDENT_STATE_RESTORED`

Recovered:
- 90+ tracked files
- all relevant untracked files preserved
- Eye worktrees untouched
- frontend build successful
- main pre-incident repository state restored

Untracked files specifically reported preserved include:

- scripts/start_citadel.sh
- src/broker/openalgo_adapter.py
- src/broker/openalgo_client.py
- tests/test_openalgo_integration.py
- .agents/
- .claude/
- .playwright-cli/
- docs/architecture/
- docs/audits/

## RECOVERY ARTIFACTS

Incident/recovery material exists under:

`/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/`

Files matching:

`ACCIDENTAL_ROLLBACK_*`

must be preserved.

## OBSIDIAN ROLE

Obsidian is documentation/recovery context.

Git commit graph + reflog remain source-of-truth for executable repository recovery.

Never use an Obsidian statement by itself to overwrite a newer proven Git state.

## EYE WORKTREES

All Eye worktrees were reported untouched during the incident.

Do not delete, reset, prune, or recreate Eye worktrees during Oracle/CITADEL recovery unless separately audited.

## CRITICAL SAFETY INVARIANTS

Maintain:

paper_only=true
live_trading_enabled=false
broker_submission=false
advisory_only=true
execution_influence=ZERO
execution_authority=false

Never change these as part of recovery unless explicitly authorized.

## PERMANENT RECOVERY RULE

Before ANY future CITADEL rollback, reset, checkout, merge, worktree switch, runtime migration, or recovery:

1. Record current HEAD.
2. Record `git status`.
3. Record `git reflog -n 20`.
4. Record all worktrees.
5. Record backend/frontend PID + CWD.
6. Create rescue branch at current HEAD.
7. Preserve uncommitted work.
8. Never reset the full repository merely to repair Oracle/frontend.
9. Repair the smallest proven scope.
10. Restart only from explicitly verified canonical repository.
11. Verify visible production dashboard after restart.
12. Never declare recovery successful solely because tests pass.

## GOLDEN RECOVERY ANCHOR

As of this incident:

`46e040510b5e554b02e63da37b384f9f431437d8`

is the proven pre-incident CITADEL recovery anchor.

DO NOT silently replace this anchor.

If a later canonical milestone supersedes it, create a NEW dated Golden Recovery State note containing:
- previous anchor
- new anchor
- reason for promotion
- full validation evidence.
