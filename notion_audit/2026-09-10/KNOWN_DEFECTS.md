# Known Defects For 2026-09-10 Audit

1. `same_receipt_mismatch`: soak telemetry repeatedly recorded Gemini and Sol stale outputs bound to different receipt ids. Trace BrainPacket receipt creation, stale rejection, and frontend projection before calling this only a UI issue.
2. `sol_input_hardening_required`: Sol readiness was incomplete; required option-economic inputs such as expiry, time-to-expiry, bid/ask, IV baseline, straddle change, theta/fair value, and flow evidence were missing.
3. `challenger_unavailable_state`: current cognitive status reports no challenger read while Luna is current. Audit whether this is intentional pause display, EvidenceGate behavior, or projection/freshness bug.
4. `large_fast_lane_payload_tail_latency`: Fast Lane payloads were roughly 1.1MB with high P95/P99 latency. Audit payload trimming, serialization, and downstream consumers.
5. `vob_zero_active_zones_during_soak`: VOB zone count remained zero during the 30-minute soak. Verify whether backend truly had no VOB zones or whether a projection/data-contract mismatch hid them.

No repairs were applied in this snapshot; these are audit findings requiring source-backed confirmation before code changes.
