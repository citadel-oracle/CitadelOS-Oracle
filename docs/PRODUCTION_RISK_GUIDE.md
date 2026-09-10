# CITADEL Production Risk Guide

Phase 10B does not change risk calculations. The existing authoritative Risk Authorization service remains the only risk decision source.

Operational safety adds fail-closed controls around that source:

- Missing/corrupt kill-switch state blocks execution.
- Stale quotes block orders.
- Position mismatches stop strategies.
- Duplicate or UNKNOWN submissions are never retried blindly.
- Recovery requires exact position reconciliation.
- PAPER and LIVE ledgers remain isolated.

The kill switch is an emergency control, not a replacement for per-trade or daily risk authorization. Deactivation requires an identified incident cause, completed recovery, successful reconciliation and explicit operator approval.
