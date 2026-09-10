# E3-E Requirement & Verification Matrix

| Requirement ID | Claim Description | Invariant Property | Target Test File | Primary Fixture | Failure Mode Caught |
|---|---|---|---|---|---|
| **E3E-REQ-001** | True Multi-Event Definitions | Every research setup family requires >= 2 mandatory atomic steps | `test_multistep_definition_truth.py` | `MultiStepRegistryFixture` | Single-step multi-event setup confirmation |
| **E3E-REQ-002** | Two-Identity Model | Stable `setup_key` separate from immutable `record_id` | `test_setup_revision_identity.py` | `FourStageLifecycleFixture` | `record_id = hash(setup_key only)` violation |
| **E3E-REQ-003** | Atomic Revision Ingestion | Process `event_revision` updates without duplicate rejection | `test_atomic_revision_ingestion.py` | `AtomicEventRevisionFixture` | Dropped event state updates |
| **E3E-REQ-004** | Parent Invalidation Propagation | Emits `INVALIDATED` candidate revision when parent invalidates | `test_parent_invalidation_propagation.py` | `ParentInvalidationFixture` | Zombie candidate active post atomic parent invalidation |
| **E3E-REQ-005** | Complete Contiguity Policies | Distinct execution semantics for `STRICT_NEXT` vs `RELAXED_NEXT` | `test_contiguity_complete.py` | `ContiguityFixture` | Contiguity enum no-op |
| **E3E-REQ-006** | Complete Skip Policies | Distinct state transitions for `SKIP_PAST_LAST_EVENT` | `test_skip_policies_complete.py` | `SkipPolicyFixture` | Skip policy no-op |
| **E3E-REQ-007** | Complete Event Reuse Policies | `FORBID_ACROSS_MATCHES` tracks consumed event keys | `test_event_reuse_complete.py` | `EventReuseFixture` | Illegal event double-counting |
| **E3E-REQ-008** | Complete Overlap Policies | Overlap filtering suppresses duplicate candidate keys | `test_overlap_policies_complete.py` | `OverlapFixture` | Duplicate setup key emissions |
| **E3E-REQ-009** | Negative Cancellation & Expiry | Expired partial matches transition cleanly to `EXPIRED` | `test_negative_cancellation_expiry.py` | `ExpiryFixture` | Stale partial match retention |
| **E3E-REQ-010** | Immutable Audit Archive | Working state bounded without silent historical `deque` drop | `test_archive_integrity.py` | `ArchiveIntegrityFixture` | Silent deletion of 1,001st historical record |
| **E3E-REQ-011** | Historical Eligible Families | 4 eligible families with 2+ mandatory steps and E2B producers | `test_historical_eligible_families.py` | `EligibleFamilyFixture` | Ineligible setup execution on real historical data |
| **E3E-REQ-012** | Historical Candidate Correction | Synthetic-only families excluded from confirmed historical scan | `test_historical_candidate_correction.py` | `HistoricalCorrectionFixture` | Inflated setup candidate count |
| **E3E-REQ-013** | Real MTF Composition Binding | Knowledge-time ordering enforced across multi-timeframe events | `test_mtf_real_binding.py` | `MTFBindingFixture` | Lookahead bias in MTF context |
| **E3E-REQ-014** | Complete Trace Classification | 13 explicit trace states without default-to-valid | `test_trace_classifier_complete.py` | `TraceClassifierFixture` | Default-to-valid classifier trickery |
| **E3E-REQ-015** | Replay & Revision Parity | Incremental vs Full Reconstruction produces `100% IDENTICAL` result | `test_replay_revision_parity.py` | `ReplayParityFixture` | Streaming state accumulation drift |
| **E3E-REQ-016** | Non-Trivial Benchmark | Credible benchmarks across 5 scenarios and 3 sizes | `test_benchmark_nontrivial_work.py` | `BenchmarkWorkFixture` | Trivial 0-candidate benchmark |
| **E3E-REQ-017** | Phase E4 Eligibility Gate | Only `HISTORICALLY_SUPPORTED_RESEARCH` & `ACTIVE` enter E4 | `test_e4_eligibility.py` | `E4EligibilityFixture` | Premature E4 entry for synthetic/option setups |
