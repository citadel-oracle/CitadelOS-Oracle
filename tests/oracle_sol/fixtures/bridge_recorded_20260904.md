# Frozen bridge lifecycle evidence

Copied on 2026-09-05 from `data/sol_shadow/sol_last_snapshot_2026-09-04.json`
and the first 12 rows of `sol_session_events_2026-09-04.jsonl`.
Source values and event records are preserved; only trailing whitespace was normalized.

- Snapshot SHA256: `10751976b08cc140b0680616a64154779c6c38277b60f6d4f1ff37324438e025`
- Events SHA256: `73f84fd4b221394406b6f11ed10916d77b67a0e91a4c933534a4a30d1c02be93`

This is a **degraded session snapshot**, not proof of a healthy market frame.
Missing spot remains null. Lifecycle tests simulate session-control states and
mock responses cite an attached real event, not missing spot. No production
record is rewritten. Tests for populated numeric lineage separately use the
existing `fast_lane_revision_1333.json` recording.
