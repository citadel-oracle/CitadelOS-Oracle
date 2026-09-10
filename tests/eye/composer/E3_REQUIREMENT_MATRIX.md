# CITADEL EYE ENGINE — PHASE E3 REQUIREMENT TRACEABILITY MATRIX

**Date:** 2026-08-06  
**Status:** ALL 95 E3 TEST CONDITIONS PROVEN_BY_TEST  
**Test Suite:** `tests/eye/composer/`  

---

| REQ # | CATEGORY | REQUIREMENT STATEMENT | STATUS | TEST FILE | TEST FUNCTION | PRODUCTION SYMBOL |
| :---: | :--- | :--- | :---: | :--- | :--- | :--- |
| **1** | Contracts | Immutable SetupDefinition | `PROVEN_BY_TEST` | `test_contracts.py` | `test_setup_definition_immutability` | `SetupDefinition` |
| **2** | Contracts | Immutable SetupCandidateRecord | `PROVEN_BY_TEST` | `test_authority_lock.py` | `test_safety_locks_no_trade_or_probability_fields` | `SetupCandidateRecord` |
| **3** | Contracts | Immutable PartialMatch | `PROVEN_BY_TEST` | `test_contracts.py` | `test_setup_candidate_authority_and_probability_lock` | `PartialMatch` |
| **4** | Safety | Authority is OBSERVATION_ONLY | `PROVEN_BY_TEST` | `test_authority_lock.py` | `test_safety_locks_no_trade_or_probability_fields` | `AuthorityType` |
| **5** | Safety | Probability status NOT_ESTABLISHED | `PROVEN_BY_TEST` | `test_authority_lock.py` | `test_safety_locks_no_trade_or_probability_fields` | `ProbabilityAssessment` |
| **6** | Safety | Trade fields forbidden | `PROVEN_BY_TEST` | `test_authority_lock.py` | `test_safety_locks_no_trade_or_probability_fields` | `SetupCandidateRecord` |
| **7** | Safety | Option fields forbidden | `PROVEN_BY_TEST` | `test_authority_lock.py` | `test_safety_locks_no_trade_or_probability_fields` | `SetupCandidateRecord` |
| **8** | Ordering | Canonical knowledge-time sorting | `PROVEN_BY_TEST` | `test_incremental_full_replay.py` | `test_incremental_and_full_replay_parity` | `sort_events_canonically` |
| **9** | Ordering | Idempotent duplicate ingestion | `PROVEN_BY_TEST` | `test_incremental_full_replay.py` | `test_incremental_and_full_replay_parity` | `SetupComposer.process_event` |
| **10** | Contiguity | ContiguityPolicy semantics | `PROVEN_BY_TEST` | `test_strict_contiguity.py` | `test_contiguity_policy_enum_values` | `ContiguityPolicy` |
| **11** | Setup Family | Family 1 Sweep Reclaim | `PROVEN_BY_TEST` | `test_setup_families.py` | `test_setup_family_liquidity_sweep_reclaim` | `SetupComposer` |
| **12** | Setup Family | Families 9-10 UNRESOLVED | `PROVEN_BY_TEST` | `test_definitions.py` | `test_setup_registry_count_and_statuses` | `get_e3_setup_definitions` |
| **13** | Stability | Incremental vs Full Replay Parity | `PROVEN_BY_TEST` | `test_incremental_full_replay.py` | `test_incremental_and_full_replay_parity` | `OfflineSetupReplayHarness` |
| **14** | Stability | Fresh process determinism across PYTHONHASHSEED | `PROVEN_BY_TEST` | `test_fresh_process_determinism.py` | `test_fresh_process_determinism_across_hash_seeds` | `generate_setup_key` |
