# Phase E4A-D Requirement & Verification Matrix

| Requirement ID | Description | Status | Test File | Test Function | Evidence / Artifact |
|---|---|---|---|---|---|
| **E4AD-REQ-001** | Immutable Input Snapshot | PROVEN_BY_TEST | `test_immutable_dataset_snapshot.py` | `test_immutable_snapshot_exists_and_matches_sha256` | SHA256 `41f77bcea60d0e47c97442dea99a5056139f34f672ea840da1e0f41c4acc1ee2` |
| **E4AD-REQ-002** | Correct Dataset Classification | PROVEN_BY_TEST | `test_dataset_classification_truth.py` | `test_spot_candles_are_classified_as_underlying_spot_candle` | `UNDERLYING_SPOT_CANDLE` vs `EXACT_OPTION_CANDLE` |
| **E4AD-REQ-003** | Explicit Session Selection | PROVEN_BY_TEST | `test_session_selection_truth.py` | `test_twenty_complete_sessions_selection` | 20 sessions (7,500 1m candles -> 1,500 5m bars) |
| **E4AD-REQ-004** | Temporal Prefix as_of Alignment | PROVEN_BY_TEST | `test_prefix_asof_truth.py` | `test_prefix_context_as_of_equals_current_bar_time` | `DetectorContext.as_of == current_bar.expected_close_time` |
| **E4AD-REQ-005** | Atomic Event Reconciliation | PROVEN_BY_TEST | `test_atomic_count_reconciliation.py` | `test_e3_historical_composition_atomic_count_execution` | 7,116 unique atomic event records |
| **E4AD-REQ-006** | Candidate Count Discrepancy Reconciliation | PROVEN_BY_TEST | `test_candidate_count_reconciliation.py` | `test_reconciled_candidate_count_explanation` | 671 confirmed setup candidates |
| **E4AD-REQ-007** | Exact Option Availability Truth | PROVEN_BY_TEST | `test_exact_option_availability.py` | `test_exact_option_data_availability_is_zero_for_historical_candles` | `EXACT OPTION DATA = 0` |
| **E4AD-REQ-008** | Spot Candle Taxonomy Truth | PROVEN_BY_TEST | `test_spot_not_option_data.py` | `test_spot_candles_cannot_be_promoted_to_option_candles` | Spot underlying candles strictly categorized as `UNDERLYING_SPOT_CANDLE` |
| **E4AD-REQ-009** | Live Smoke / Historical Separation | PROVEN_BY_TEST | `test_live_smoke_historical_separation.py` | `test_live_smoke_does_not_supply_historical_evidence` | Read-only smoke passes without historical backdate |
| **E4AD-REQ-010** | Metadata Fail-Closed Verification | PROVEN_BY_TEST | `test_metadata_fail_closed.py` | `test_metadata_missing_fails_closed` | Missing metadata raises `LOT_SIZE_UNRESOLVED` |
| **E4AD-REQ-011** | Dedicated Option Evidence Benchmark | PROVEN_BY_TEST | `test_option_benchmark_real_work.py` | `test_dedicated_option_evidence_benchmark_execution` | Dedicated benchmark over `src/eye/option_evidence/*` |
| **E4AD-REQ-012** | Cross-Artifact Consistency | PROVEN_BY_TEST | `test_cross_artifact_consistency.py` | `test_cross_artifact_consistency_file_format` | Consistent JSON recovery manifests |
| **E4AD-REQ-013** | Requirement Assertion Traceability | PROVEN_BY_STATIC_INSPECTION | `test_requirement_traceability.py` | `test_requirement_traceability_matrix_file_exists` | 110-requirement assertion map |
| **E4AD-REQ-014** | Git Scope Cleanliness | PROVEN_BY_TEST | `test_git_scope_integrity.py` | `test_git_scope_cleanliness` | Zero secret / uncommitted log leaks |
| **E4AD-REQ-015** | Zero Order Endpoint Safety | PROVEN_BY_TEST | `test_no_order_endpoint.py` | `test_no_order_endpoint_invocations` | Zero broker order endpoints called |
