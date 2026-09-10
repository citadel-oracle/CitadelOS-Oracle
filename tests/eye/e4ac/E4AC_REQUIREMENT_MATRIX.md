# E4A-C Requirement & Verification Matrix

| Req ID | Description | Status | Test File | Test Function | Evidence Provenance |
|---|---|---|---|---|---|
| **E4AC-REQ-001** | E3 Dataset Loader Truth | PROVEN_BY_TEST | `test_e3_dataset_loader_truth.py` | `test_vob_dataset_loader_reads_candle_rows_not_dict_keys` | `vob_1m_candles.json` 19,125 candles |
| **E4AC-REQ-002** | Real E2B Detection & E3 Matcher Pipeline | PROVEN_BY_DIRECT_EXECUTION | `run_eye_e3e_historical_composition.py` | `run_e3e_historical_composition()` | 7,500 1m candles -> 1,500 5m bars -> 17,590 atomic events -> 65 setup candidates |
| **E4AC-REQ-003** | Distinct Benchmark Scenarios | PROVEN_BY_TEST | `test_e3_benchmark_scenario_truth.py` | `test_no_match_control_produces_zero_candidates` | 5 distinct scenarios with non-zero metrics & distinct checksums |
| **E4AC-REQ-004** | Metadata Enforcement Without Defaults | PROVEN_BY_TEST | `test_contract_metadata_no_defaults.py` | `test_missing_metadata_raises_explicit_unresolved_error` | `LOT_SIZE_UNRESOLVED`, `SECURITY_ID_MISMATCH` |
| **E4AC-REQ-005** | Local Dataset Classification Integrity | PROVEN_BY_TEST | `test_local_dataset_classification.py` | `test_local_dataset_classifications` | `EXACT_CONTRACT_CANDLE` vs `ROLLING_MONEYNESS_PROXY` |
| **E4AC-REQ-006** | Exact vs Proxy Boundary Isolation | PROVEN_BY_TEST | `test_exact_proxy_boundary.py` | `test_proxy_series_key_format_isolation` | `ROLLING:` prefix strictly isolated |
| **E4AC-REQ-007** | FutEq Regulatory Classification | PROVEN_BY_TEST | `test_futeq_semantics.py` | `test_futeq_classification_is_regulatory_delta_input_only` | `REGULATORY_DELTA_INPUT_ONLY` without false compliance claim |
| **E4AC-REQ-008** | Independent Greeks Model Provenance | PROVEN_BY_TEST | `test_greeks_model_provenance.py` | `test_black_scholes_greeks_provenance_and_ranges` | Analytical BS Delta, Gamma, Theta, Vega |
| **E4AC-REQ-009** | Independent IV Solver & Arbitrage Bounds | PROVEN_BY_TEST | `test_iv_model_provenance.py` | `test_iv_solver_provenance_and_arbitrage_bounds` | Newton-Raphson + Bisection fallback with no-arbitrage lower bound |
| **E4AC-REQ-010** | Read-Only Smoke Reporting | PROVEN_BY_TEST | `test_readonly_smoke_reporting.py` | `test_readonly_smoke_execution` | Read-only smoke passes without live trade authority |
| **E4AC-REQ-011** | Historical Option Availability | PROVEN_BY_TEST | `test_historical_availability_truth.py` | `test_historical_option_candle_availability` | Contemporaneous historical evidence binding |
| **E4AC-REQ-012** | Requirement Assertion Traceability | PROVEN_BY_STATIC_INSPECTION | `test_requirement_traceability.py` | `test_requirement_traceability_matrix_file_exists` | 110-requirement assertion map |
| **E4AC-REQ-013** | Benchmark Execution Real Work | PROVEN_BY_TEST | `test_benchmark_real_work.py` | `test_benchmark_execution_real_work` | Non-trivial composer work across 500, 5,000, 50,000 records |
| **E4AC-REQ-014** | Renderer Integrity | PROVEN_BY_TEST | `test_renderer_integrity.py` | `test_renderer_artifacts_dynamic_provenance` | Renderer outputs generated from executed JSON results |
| **E4AC-REQ-015** | Zero Order Endpoint Safety | PROVEN_BY_TEST | `test_no_order_endpoint.py` | `test_no_order_endpoint_calls_in_eye` | Zero order placement / modification calls |
