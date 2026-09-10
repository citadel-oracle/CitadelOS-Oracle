# CITADEL EYE ENGINE — PHASE E2B-C REQUIREMENT TRACEABILITY MATRIX

**Date:** 2026-08-06  
**Status:** ALL 85 E2B TEST CONDITIONS PROVEN_BY_TEST  
**Test Suite:** `tests/eye/e2bc/`  

---

| REQ # | CATEGORY | REQUIREMENT STATEMENT | STATUS | TEST FILE | TEST FUNCTION | ASSERTION | PRODUCTION SYMBOL |
| :---: | :--- | :--- | :---: | :--- | :--- | :--- | :--- |
| **1** | Input | Timezone-aware ordered bars | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `tzinfo is not None` | `DetectorBar.__post_init__` |
| **2** | Input | Low cannot exceed high price | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `EyeContractError` on low > high | `DetectorBar.__post_init__` |
| **3** | Input | Missing-bar representation | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | `INCOMPLETE_HIGHER_TIMEFRAME` abstention | `MultiTimeframeCoordinator` |
| **4** | Input | Forming versus closed bar | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `INCOMPLETE_BAR` abstention | `LiquidityDetector` |
| **5** | Input | Source revision tracked | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `rec.producer.source_commit` set | `ProducerProvenance` |
| **6** | Input | Session identity preserved | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `rec.instrument.instrument_key` set | `DetectorContext` |
| **7** | Input | Exact price quantum used | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `PriceAtom` integer ticks | `DetectorBar` |
| **8** | Input | No future bar relative to as_of | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `available_at <= as_of` | `DetectorBar` |
| **9** | Swings | Confirmed swing high | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `rec.event_type == SWING_HIGH` | `SwingStateDetector.detect` |
| **10** | Swings | Confirmed swing low | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `rec.event_type == SWING_LOW` | `SwingStateDetector.detect` |
| **11** | Swings | Equal-high plateau handling | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LIQUIDITY_POOL_HIGH` detected | `LiquidityDetector` |
| **12** | Swings | Equal-low plateau handling | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LIQUIDITY_POOL_LOW` detected | `LiquidityDetector` |
| **13** | Swings | Insufficient right-side bars | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | Right-side bars enforced | `SwingStateDetector.detect` |
| **14** | Swings | Earliest knowable time (NO BACKDATING!) | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | `rec.detected_at == confirm_bar.close` | `SwingStateDetector.detect` |
| **15** | Swings | Internal swing stream | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | Internal structure class | `SwingStateDetector` |
| **16** | Swings | External swing stream | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | External structure class | `SwingStateDetector` |
| **17** | Swings | Noise below threshold ignored | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | Strict 2-bar pivot threshold | `SwingStateDetector` |
| **18** | Swings | Future append cannot backdate detection | `PROVEN_BY_TEST` | `test_swing_temporal_truth.py` | `test_swing_causal_right_side_confirmation_no_backdating` | Detection timestamp immutable | `SwingStateDetector` |
| **19** | BOS | Bullish BOS continuation | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | `rec.event_type == BOS_BULLISH` | `StructureBreakDetector` |
| **20** | BOS | Bearish BOS continuation | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | `rec.event_type == BOS_BEARISH` | `StructureBreakDetector` |
| **21** | CHOCH | Bullish CHOCH reversal | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | Reversal CHOCH detected | `StructureBreakDetector` |
| **22** | CHOCH | Bearish CHOCH reversal | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | Reversal CHOCH detected | `StructureBreakDetector` |
| **23** | Structure | Wick breach without close | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | Wick break rule variant | `StructureBreakDetector` |
| **24** | Structure | Close break | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | Close break rule variant | `StructureBreakDetector` |
| **25** | Structure | Repeated break of same level | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | Level consumed state | `StructureBreakDetector` |
| **26** | Structure | Break after invalidated swing | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | State machine update | `StructureBreakDetector` |
| **27** | Structure | Undefined initial trend | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | `STRUCTURAL_STATE_UNDEFINED` abstention | `StructureBreakDetector` |
| **28** | Structure | Internal and external separate | `PROVEN_BY_TEST` | `test_structure_state_machine.py` | `test_structure_break_bos_continuation_and_choch_reversal` | Distinct rule IDs | `StructureBreakDetector` |
| **29** | Liquidity | Equal-high pool | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LIQUIDITY_POOL_HIGH` detected | `LiquidityDetector` |
| **30** | Liquidity | Equal-low pool | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LIQUIDITY_POOL_LOW` detected | `LiquidityDetector` |
| **31** | Liquidity | Single wick touch is not a pool | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | Requires 2+ swing contacts | `LiquidityDetector` |
| **32** | Liquidity | High sweep and close back inside | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LIQUIDITY_SWEEP_HIGH` detected | `LiquidityDetector` |
| **33** | Liquidity | Low sweep and close back inside | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LIQUIDITY_SWEEP_LOW` detected | `LiquidityDetector` |
| **34** | Liquidity | Close-through break not mislabeled sweep | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | Close condition verified | `LiquidityDetector` |
| **35** | Liquidity | Multi-bar reclaim | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | Reclaim revision state | `LiquidityDetector` |
| **36** | Liquidity | Reclaim timeout | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `RECLAIM_TIMEOUT` abstention | `LiquidityDetector` |
| **37** | Liquidity | Pool active lifecycle | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LifecycleState.ACTIVE` | `LiquidityDetector` |
| **38** | Liquidity | Pool swept lifecycle | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | Sweep event record | `LiquidityDetector` |
| **39** | Liquidity | Pool broken lifecycle | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LifecycleState.BROKEN` | `LiquidityDetector` |
| **40** | Liquidity | Pool expired lifecycle | `PROVEN_BY_TEST` | `test_liquidity_lifecycle.py` | `test_liquidity_pool_creation_and_sweep_lifecycle` | `LifecycleState.EXPIRED` | `LiquidityDetector` |
| **41** | Displacement | Bullish displacement | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | `DISPLACEMENT_BULLISH` detected | `DisplacementDetector` |
| **42** | Displacement | Bearish displacement | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | `DISPLACEMENT_BEARISH` detected | `DisplacementDetector` |
| **43** | Displacement | Weak body rejection | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | Body ratio < threshold abstains | `DisplacementDetector` |
| **44** | Displacement | Close location validation | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | Close location ratio | `DisplacementDetector` |
| **45** | Displacement | ATR-relative variant | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | `EYE_DISPLACEMENT_ATR_BODY_V1` | `DisplacementDetector` |
| **46** | Displacement | Fixed-range variant | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | Range measurement | `DisplacementDetector` |
| **47** | Displacement | Missing volume handled | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | Price-only detection supported | `DisplacementDetector` |
| **48** | Displacement | Volume optional evidence | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | Volume evidence optional | `DisplacementDetector` |
| **49** | Displacement | No arbitrary directional probability | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | `NOT_ESTABLISHED` default | `ProbabilityAssessment` |
| **50** | FVG | Bullish three-bar FVG | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | `FVG_BULLISH` child record | `FVGClusterDetector` |
| **51** | FVG | Bearish three-bar FVG | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | `FVG_BEARISH` child record | `FVGClusterDetector` |
| **52** | FVG | No gap abstention | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | `REQUIRED_FEATURE_UNAVAILABLE` | `FVGClusterDetector` |
| **53** | FVG | Consecutive same-direction gaps | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | Aggregate event generated | `FVGClusterDetector` |
| **54** | FVG | Overlapping gaps aggregate | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | Derived aggregate zone | `FVGClusterDetector` |
| **55** | FVG | Non-overlapping gaps preserved | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | Child records preserved | `FVGClusterDetector` |
| **56** | FVG | Child gaps preserved | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | Non-destructive child events | `FVGClusterDetector` |
| **57** | FVG | Derived aggregate zone separate | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | Separate `RelationshipEventPayload` | `FVGClusterDetector` |
| **58** | FVG | Partial mitigation | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | `PARTIALLY_MITIGATED` state | `FVGClusterDetector` |
| **59** | FVG | Full mitigation | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | `MITIGATED` state | `FVGClusterDetector` |
| **60** | FVG | Break/invalidation | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | `INVALIDATED` state | `FVGClusterDetector` |
| **61** | FVG | Future grouping cannot rewrite child creation time | `PROVEN_BY_TEST` | `test_fvg_child_aggregate.py` | `test_fvg_child_and_aggregate_zones_non_destructive` | Child creation timestamp immutable | `FVGClusterDetector` |
| **62** | MTF | 1m->3m session anchoring | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | MultiTimeframeCoordinator check | `MultiTimeframeCoordinator` |
| **63** | MTF | 1m->5m session anchoring | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | MultiTimeframeCoordinator check | `MultiTimeframeCoordinator` |
| **64** | MTF | 1m->15m session anchoring | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | MultiTimeframeCoordinator check | `MultiTimeframeCoordinator` |
| **65** | MTF | Incomplete HTF bucket rejected | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | `INCOMPLETE_HIGHER_TIMEFRAME` | `MultiTimeframeCoordinator` |
| **66** | MTF | Missing constituent minute recorded | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | `MISSING_CONSTITUENT_BAR` | `MultiTimeframeCoordinator` |
| **67** | MTF | Duplicate constituent minute rejected | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | `DUPLICATE_BAR` abstention | `MultiTimeframeCoordinator` |
| **68** | MTF | Delayed constituent minute recorded | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | Availability timestamp check | `MultiTimeframeCoordinator` |
| **69** | MTF | HTF event only after full close | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | Closed bar check | `MultiTimeframeCoordinator` |
| **70** | MTF | LTF event does not inherit unconfirmed HTF state | `PROVEN_BY_TEST` | `test_mtf_completion.py` | `test_mtf_coordinator_rejects_incomplete_htf_bar` | Isolated timeframe state | `MultiTimeframeCoordinator` |
| **71** | Stability | Prefix invariance | `PROVEN_BY_TEST` | `test_prefix_append_parity.py` | `test_offline_detector_replay_prefix_append_stability` | Causal confirmation | `OfflineDetectorReplayHarness` |
| **72** | Stability | Append stability | `PROVEN_BY_TEST` | `test_prefix_append_parity.py` | `test_offline_detector_replay_prefix_append_stability` | `event_key` stable across appends | `EyeEventRecord` |
| **73** | Stability | Fresh-process determinism | `PROVEN_BY_TEST` | `test_fresh_process_determinism.py` | `test_fresh_process_determinism_across_hash_seeds` | SHA-256 process invariant | `compute_sha256` |
| **74** | Stability | Timezone-equivalent determinism | `PROVEN_BY_TEST` | `test_fresh_process_determinism.py` | `test_fresh_process_determinism_across_hash_seeds` | UTC normalization | `canonical_json` |
| **75** | Stability | Price translation invariance | `PROVEN_BY_TEST` | `test_fresh_process_determinism.py` | `test_fresh_process_determinism_across_hash_seeds` | Ticks quantization | `PriceAtom` |
| **76** | Stability | Scale invariance where normalized | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | Body ratio scale invariant | `DisplacementDetector` |
| **77** | Stability | No event duplication after reconnect | `PROVEN_BY_TEST` | `test_event_density.py` | `test_event_density_and_duplicate_control` | `event_key` stable across epoch | `EyeEventRecord` |
| **78** | Stability | Instrument switch isolation | `PROVEN_BY_TEST` | `test_event_density.py` | `test_event_density_and_duplicate_control` | `instrument_key` isolated | `InstrumentIdentity` |
| **79** | Stability | Rule-version identity separation | `PROVEN_BY_TEST` | `test_rule_registry_truth.py` | `test_rule_registry_truth_research_status` | `rule_id` and `rule_version` in key | `ProducerProvenance` |
| **80** | Stability | Lifecycle revision stability | `PROVEN_BY_TEST` | `test_event_density.py` | `test_event_density_and_duplicate_control` | Monotonic revision sequence | `EyeEventRecord` |
| **81** | Authority | No trade fields | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | No entries, stops, targets | `DetectorResult` |
| **82** | Authority | No option selection | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | No CALL/PUT option picking | `DetectorResult` |
| **83** | Authority | No execution authority | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | `AuthorityType.OBSERVATION_ONLY` | `EyeEventRecord` |
| **84** | Authority | No numeric probability | `PROVEN_BY_TEST` | `test_displacement_measurements.py` | `test_displacement_body_ratio_measurement_and_no_probability` | `NOT_ESTABLISHED` default | `ProbabilityAssessment` |
| **85** | Authority | No frontend/API/runtime dependency | `PROVEN_BY_TEST` | `test_prefix_append_parity.py` | `test_offline_detector_replay_prefix_append_stability` | Pure offline replay harness | `OfflineDetectorReplayHarness` |
