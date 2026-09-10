# E3-D Requirement & Verification Matrix

| Requirement ID | Claim Description | Invariant Property | Target Test File | Primary Fixture | Failure Mode Caught |
|---|---|---|---|---|---|
| **E3D-REQ-001** | Full Causal Lineage | Causal DAG acyclic & hash-linked to raw events | `test_claim_traceability.py` | `CausalEventChainFixture` | Orphaned setup claims, broken parent hash |
| **E3D-REQ-002** | Renderer Independence | State truth independent of UI / string representation | `test_renderer_evidence_integrity.py` | `StructuralEvidenceFixture` | UI decoy text match with invalid struct state |
| **E3D-REQ-003** | Atomic Prerequisite Resolution | Topological condition eval without side-effects | `test_atomic_prerequisite_matrix.py` | `PrerequisiteGraphFixture` | Evaluation order inversion, state mutation during eval |
| **E3D-REQ-004** | Setup Schema & Semantics | Strict parameter boundary & structural definition | `test_setup_definition_semantics.py` | `BoundaryValueFixture` | Invalid window lookbacks, out-of-bound parameters |
| **E3D-REQ-005** | Bar Stream Contiguity | Monotonic index sequence without unhandled gaps | `test_contiguity_truth.py` | `GappedBarSeriesFixture` | Backward timestamp jump, unlogged bar gaps |
| **E3D-REQ-006** | Explicit Gap & Skip Policy | Zero false setups across non-trading gaps | `test_skip_policy_truth.py` | `WeekendGapFixture` | Pattern bridging across weekend/halt gaps |
| **E3D-REQ-007** | Primitive Event Reuse Defense | Event resource allocation limits enforced | `test_event_reuse_truth.py` | `EventResourcePoolFixture` | Double-counting same pivot across mutually exclusive setups |
| **E3D-REQ-008** | Deterministic Overlap Resolution | Strict priority tie-breaking for concurrent windows | `test_overlap_policy_truth.py` | `OverlappingWindowFixture` | Non-deterministic setup selection |
| **E3D-REQ-009** | Negative Cancellation & TTL Expiry | Immediate state invalidation on stop/boundary breach | `test_negative_cancellation_expiry.py` | `ActiveSetupWithTTLFixture` | Post-expiry signal execution, delayed stop cancellation |
| **E3D-REQ-010** | Immutable Identity Revisions | Versioned setup UUID & ancestor hash linkage | `test_setup_identity_revisions.py` | `MutatedSetupStateFixture` | In-place identity overwrites, detached mutation logs |
| **E3D-REQ-011** | Leak-Free Family Statistics | Atomic counter aggregation per pattern family | `test_historical_family_counts.py` | `FamilyCountAggregatorFixture` | Counter drift during parallel streaming aggregation |
| **E3D-REQ-012** | Candidate Density & Backpressure | Strict rate-limiting per bar/window boundary | `test_candidate_density.py` | `HighDensityBurstFixture` | Candidate explosion, memory unbounding under noise |
| **E3D-REQ-013** | Strict Trace Classification | Deterministic 4-state classification | `test_trace_classifier.py` | `LabeledTraceDatasetFixture` | Ambiguous trace misclassified as True Positive |
| **E3D-REQ-014** | Streaming vs Batch Equivalence | `Eval(Streaming[0..N]) == Eval(Batch[0..N])` | `test_incremental_full_independence.py` | `BatchVsIncrementalStreamFixture` | State accumulation drift, lookahead bias in batch |
| **E3D-REQ-015** | Multi-Timeframe Alignment | Zero lookahead bias across HTF unclosed bars | `test_mtf_composition_truth.py` | `MTFStreamFixture` | Unclosed higher-tf bar leaks high/low to lower-tf |
| **E3D-REQ-016** | Real Computational Work | No stubbed pass-throughs; budget latency enforced | `test_benchmark_real_work.py` | `ComputeHeavyStreamFixture` | Stubbed mock pass-throughs, execution timeouts |
| **E3D-REQ-017** | Memory Cleanup & Lifecycle | Zero retained references post session termination | `test_state_cleanup.py` | `MemoryTrackerFixture` | Retained event DAG nodes, memory leaks |
| **E3D-REQ-018** | Registry Lifecycle Status | State machine (Active -> Deprecated -> Disabled) | `test_registry_status_truth.py` | `RegistryStateMachineFixture` | Deprecated setup execution without override flag |
| **E3D-REQ-019** | Phase E4 Readiness Handshake | Payload cryptographic signature & schema validation | `test_e4_readiness_contract.py` | `E4PreconditionContractFixture` | Missing E3-D proof signature in payload to Phase E4 |
