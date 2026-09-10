# Phase E4A-E Requirement & Verification Matrix

| Requirement ID | Description | Status | Test File | Test Function | Evidence / Artifact |
|---|---|---|---|---|---|
| **E4AE-REQ-001** | Read-Only Endpoint Guard | PROVEN_BY_TEST | `test_endpoint_guard.py` | `test_forbidden_order_endpoint_blocked` | `EndpointSafetyError` on non-allowlisted routes |
| **E4AE-REQ-002** | Token & Header Redaction | PROVEN_BY_TEST | `test_secret_redaction.py` | `test_secret_redaction_in_text` | `[REDACTED_SECRET]` token masking |
| **E4AE-REQ-003** | Capture Configuration Policy | PROVEN_BY_TEST | `test_capture_config.py` | `test_capture_config_validation` | `execution_authority=False` enforcement |
| **E4AE-REQ-004** | Instrument Master Snapshot Parsing | PROVEN_BY_TEST | `test_instrument_snapshot.py` | `test_instrument_snapshot_parsing` | Exact metadata identity resolution |
| **E4AE-REQ-005** | Expiry List Snapshot Parsing | PROVEN_BY_TEST | `test_expiry_snapshot.py` | `test_expiry_snapshot_parsing` | Sorted expiry list validation |
| **E4AE-REQ-006** | Dynamic Research Universe Policy | PROVEN_BY_TEST | `test_universe_policy.py` | `test_universe_manager_filters_around_spot` | `CAPTURED_FOR_RESEARCH_COVERAGE` |
| **E4AE-REQ-007** | Contract Identity Mapping | PROVEN_BY_TEST | `test_contract_identity_mapping.py` | `test_contract_identity_key_generation` | `OPTCONTRACT:...` contract key generation |
| **E4AE-REQ-008** | Option Chain Collector Parsing | PROVEN_BY_TEST | `test_chain_capture.py` | `test_chain_collector_parsing` | Dynamic option chain matrix extraction |
| **E4AE-REQ-009** | WebSocket Binary Packet Decoder | PROVEN_BY_TEST | `test_websocket_packet_decode.py` | `test_dhan_full_packet_decoder` | 82-byte Little-Endian packet unpacking |
| **E4AE-REQ-010** | Append-Only Raw Packet Journal Writer | PROVEN_BY_TEST | `test_raw_journal.py` | `test_raw_journal_writer_appends` | Raw journal offset tracking & secret scrubbing |
| **E4AE-REQ-011** | Canonical Writer JSONL | PROVEN_BY_TEST | `test_canonical_writer.py` | `test_canonical_writer_writes_jsonl` | Deterministic JSONL observation serialization |
| **E4AE-REQ-012** | Dual-Lane Field Provenance Precedence | PROVEN_BY_TEST | `test_field_provenance.py` | `test_older_chain_cannot_overwrite_newer_websocket_quote` | Older chain snapshot overwrite rejection |
| **E4AE-REQ-013** | Explicit Timestamp Model | PROVEN_BY_TEST | `test_timestamp_model.py` | `test_timestamp_fields_preserved` | Exchange vs Receive vs Monotonic timestamps |
| **E4AE-REQ-014** | Duplicate Packet Idempotency | PROVEN_BY_TEST | `test_duplicate_packets.py` | `test_duplicate_packet_writing` | Identical SHA256 payload handling |
| **E4AE-REQ-015** | Out-of-Order Packet Diagnostics | PROVEN_BY_TEST | `test_out_of_order_packets.py` | `test_out_of_order_packet_logging` | Sequence gap diagnostic logging |
| **E4AE-REQ-016** | Reconnect Epoch Management | PROVEN_BY_TEST | `test_reconnect.py` | `test_reconnect_increments_epoch` | Incrementing connection epoch counter |
| **E4AE-REQ-017** | Contract Roll Identity Isolation | PROVEN_BY_TEST | `test_contract_roll.py` | `test_contract_roll_creates_distinct_keys` | Distinct contract_keys per expiry roll |
| **E4AE-REQ-018** | Dynamic Universe Refresh | PROVEN_BY_TEST | `test_universe_refresh.py` | `test_universe_refreshes_when_spot_moves` | Universe revisioning on spot moves |
| **E4AE-REQ-019** | Checkpoint & Tail Byte Recovery | PROVEN_BY_TEST | `test_checkpoint_recovery.py` | `test_checkpoint_and_tail_recovery` | WAL truncation of partial corrupt tail bytes |
| **E4AE-REQ-020** | Session Finalization & State Transitions | PROVEN_BY_TEST | `test_session_finalization.py` | `test_session_state_transitions` | `CaptureSessionState` state machine |
| **E4AE-REQ-021** | Manifest & Checksums Generation | PROVEN_BY_TEST | `test_manifest_checksums.py` | `test_manifest_and_checksum_generation` | `checksums.sha256` generation |
| **E4AE-REQ-022** | Deterministic Offline Replay Parity | PROVEN_BY_TEST | `test_raw_canonical_replay.py` | `test_offline_replay_engine` | `REPLAY_PARITY_PASS` without network |
| **E4AE-REQ-023** | Synchronized Underlying & Option Observations | PROVEN_BY_TEST | `test_underlying_option_sync.py` | `test_underlying_option_synchronization` | Lag-bound synchronization check |
| **E4AE-REQ-024** | Offline Setup Binding Availability | PROVEN_BY_TEST | `test_setup_binding_availability.py` | `test_setup_binding_no_future_data` | Setup candidate binding classification |
| **E4AE-REQ-025** | Zero Order Endpoint Safety | PROVEN_BY_TEST | `test_no_order_endpoint.py` | `test_no_order_endpoints_in_capture_module` | Zero broker order endpoints called |
| **E4AE-REQ-026** | Secret Redaction Engine | PROVEN_BY_TEST | `test_secret_redaction.py` | `test_secret_redaction_in_text` | Sensitive key scrubbing |
| **E4AE-REQ-027** | Decoder Performance | PROVEN_BY_TEST | `test_performance.py` | `test_packet_decoder_throughput` | High throughput decoder execution |
