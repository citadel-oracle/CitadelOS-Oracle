# Phase E4A-F Requirement & Verification Matrix

| Requirement ID | Description | Status | Test File | Test Function | Evidence / Artifact |
|---|---|---|---|---|---|
| **E4AF-REQ-001** | Market Status Evaluation Truth | PROVEN_BY_TEST | `test_market_status_truth.py` | `test_august_7_2026_10am_is_open` | `MarketStatus.OPEN` on Aug 7, 2026 10:10 IST |
| **E4AF-REQ-002** | DhanHQ 162-Byte Full Market Depth Packet Decoder | PROVEN_BY_TEST | `test_dhan_full_packet_162.py` | `test_dhan_162_byte_full_packet` | 162-byte Little-Endian packet decode with 5 depth levels |
| **E4AF-REQ-003** | Rejection of Truncated 82-Byte and 161-Byte Packets | PROVEN_BY_TEST | `test_truncated_full_packet.py` | `test_legacy_82_byte_full_packet_rejected` | `PREVIOUS_82_BYTE_FULL_PACKET_CLAIM = INVALIDATED` |
| **E4AF-REQ-004** | Declared Message Length vs Schema Validation | PROVEN_BY_TEST | `test_message_length_validation.py` | `test_declared_message_length_mismatch` | Length mismatch rejection |
| **E4AF-REQ-005** | 5-Level Market Depth Unpacking | PROVEN_BY_TEST | `test_depth_decode.py` | `test_five_level_depth_decode` | 5 levels of bid/ask qty, orders, and prices |
| **E4AF-REQ-006** | Dynamic Live Metadata Discovery | PROVEN_BY_TEST | `test_live_metadata_universe.py` | `test_live_metadata_universe_discovery` | Metadata-resolved exact security IDs |
| **E4AF-REQ-007** | Non-Hardcoded Strike Step Discovery | PROVEN_BY_TEST | `test_no_hardcoded_strike_step.py` | `test_strikes_derived_from_metadata` | Dynamic metadata strike selection |
| **E4AF-REQ-008** | Live Capture Status Classification Enums | PROVEN_BY_TEST | `test_live_status_classification.py` | `test_status_classification_enums` | 12 explicit live outcome enums |
| **E4AF-REQ-009** | Non-Zero Live Pilot Acceptance | PROVEN_BY_TEST | `test_nonzero_pilot_acceptance.py` | `test_zero_packet_pilot_cannot_pass` | Non-zero packet requirement for `LIVE_CAPTURE_PILOT_PASS` |
| **E4AF-REQ-010** | Offline Raw-to-Canonical Replay Parity | PROVEN_BY_TEST | `test_raw_live_replay.py` | `test_raw_to_canonical_replay_parity` | `REPLAY_PARITY_PASS` |
| **E4AF-REQ-011** | Option Chain REST & WebSocket Cross-Check | PROVEN_BY_TEST | `test_chain_ws_crosscheck.py` | `test_chain_ws_reconciliation_crosscheck` | Field reconciler precedence |
| **E4AF-REQ-012** | Authoritative Pytest Count Truth | PROVEN_BY_TEST | `test_pytest_count_truth.py` | `test_pytest_collection_truth` | Raw `--collect-only` count report |
| **E4AF-REQ-013** | Zero Order Endpoint Safety | PROVEN_BY_TEST | `test_no_order_endpoint.py` | `test_no_order_endpoints_in_capture_module` | 0 order endpoints called |
