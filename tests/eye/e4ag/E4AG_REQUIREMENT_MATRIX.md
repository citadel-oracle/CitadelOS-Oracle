# Phase E4A-G Requirement & Verification Matrix

| Requirement ID | Description | Status | Test File | Test Function | Evidence / Artifact |
|---|---|---|---|---|---|
| **E4AG-REQ-001** | Extended Pilot Session Classification | PROVEN_BY_TEST | `test_extended_pilot_session_truth.py` | `test_session_classification_hierarchy` | `EXTENDED_PILOT_SESSION` classification, complete sessions = 0 |
| **E4AG-REQ-002** | Continuous Timestamped Underlying Feed | PROVEN_BY_TEST | `test_continuous_underlying_feed.py` | `test_continuous_underlying_observations` | Continuous `underlying_observations.jsonl` |
| **E4AG-REQ-003** | Controlled Reconnect & Epoch Isolation | PROVEN_BY_TEST | `test_reconnect_epoch_isolation.py` | `test_reconnect_epoch_precedence_and_older_data_rejection` | Connection Epoch 2 precedence over Epoch 1 |
| **E4AG-REQ-004** | Checkpoint & Recovery Truncation | PROVEN_BY_TEST | `test_checkpoint_and_recovery_during_pilot.py` | `test_checkpoint_and_recovery_truncation` | Periodic `CaptureCheckpoint` recovery |
| **E4AG-REQ-005** | Offline Raw-to-Canonical Replay Parity | PROVEN_BY_TEST | `test_30_minute_replay_parity.py` | `test_offline_raw_to_canonical_replay_parity` | `REPLAY_PARITY_PASS` |
| **E4AG-REQ-006** | Zero Order Endpoint Safety | PROVEN_BY_TEST | `test_no_order_endpoint.py` | `test_no_order_endpoints_in_capture_module` | 0 order endpoints called |
