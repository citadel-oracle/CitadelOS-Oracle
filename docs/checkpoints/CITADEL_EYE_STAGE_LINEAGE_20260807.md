# CITADEL EYE ENGINE — STAGE LINEAGE MANIFEST (2026-08-07)

## Overview
This manifest records the proven, verified Git commit lineage for all completed Eye Engine milestones leading up to Phase E7B (Personal Strategy Deployment & Visual Parity). Every recorded commit is a verified ancestor of `HEAD`.

---

## Proven Stage Lineage

| STAGE | COMMIT | DATE | COMMIT MESSAGE / PURPOSE | ANCESTOR OF HEAD |
| :--- | :--- | :--- | :--- | :--- |
| **E0** | `0bedb4b` | 2026-08-06 | `feat(eye): add deterministic event contracts and versioned rule registry` | TRUE |
| **E1** | `77f8cc8` | 2026-08-06 | `fix(eye): harden canonical contracts and close E1 verification gaps` | TRUE |
| **E2A** | `e8e32c8` | 2026-08-06 | `feat(eye): add source-preserving adapters and replay parity harness` | TRUE |
| **E2B** | `2ca74a0` | 2026-08-06 | `feat(eye): add non-repainting atomic structure and liquidity detectors` | TRUE |
| **E2BC** | `b05c2b0` | 2026-08-06 | `fix(eye): validate and harden atomic detector semantics` | TRUE |
| **E2BD** | `68a3d6e` | 2026-08-06 | `fix(eye): correct detector evidence and validation benchmarks` | TRUE |
| **E3** | `5131cec` | 2026-08-06 | `feat(eye): add deterministic multi-event setup composer` | TRUE |
| **E3D** | `366ba4c` | 2026-08-06 | `fix(eye): verify composer evidence and setup semantics` | TRUE |
| **E3E** | `c0b88c4` | 2026-08-06 | `fix(eye): close composer revision and multi-event semantics` | TRUE |
| **E4A** | `059bd91` | 2026-08-06 | `feat(eye): add exact option evidence and market-data contracts` | TRUE |
| **E4AC** | `9d406de` | 2026-08-06 | `fix(eye): verify option evidence sources and metadata truth` | TRUE |
| **E4AD** | `4db6dfd` | 2026-08-06 | `fix(eye): close immutable option-data and historical binding truth` | TRUE |
| **E4AE** | `3b535ba` | 2026-08-07 | `feat(eye): add read-only exact option data capture` | TRUE |
| **E4AF** | `30b28ff` | 2026-08-07 | `fix(eye): validate dhan binary packet and execute live capture pilot` | TRUE |
| **E4AG2** | `5bfbc5f` | 2026-08-07 | `fix(eye): validate extended live option capture stability` | TRUE |
| **E5B/E6** | `d26c800` | 2026-08-07 | `fix(eye): complete Phase E5B Eye to Oracle real live binding closure` | TRUE |
| **E7B** | `CURRENT` | 2026-08-07 | `chore(golden): freeze Eye E7B personal strategy deployment state` | TRUE |

---

## Lineage Restoration Command

To restore working tree to any stage checkpoint:
```bash
git checkout <COMMIT>
```
To create an isolated worktree for a stage:
```bash
git worktree add /path/to/target <COMMIT>
```
