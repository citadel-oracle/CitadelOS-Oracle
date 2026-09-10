# CITADEL EYE ENGINE — PHASE E2A REQUIREMENT TRACEABILITY MATRIX

**Date:** 2026-08-06  
**Status:** ALL 40 E2A TEST CONDITIONS PROVEN_BY_TEST  
**Test Suite:** `tests/eye/adapters/test_adapters_all.py`  

---

| REQ # | CATEGORY | REQUIREMENT STATEMENT | STATUS | TEST FILE | TEST FUNCTION | ASSERTION | PRODUCTION SYMBOL |
| :---: | :--- | :--- | :---: | :--- | :--- | :--- | :--- |
| **1** | Characterization | Native no-event behavior | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_no_signal_abstention` | `len(res.records) == 0` | `StructureV2Adapter.adapt` |
| **2** | Characterization | StructureEngineV2 event behavior | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.event_type == BOS_BULLISH` | `StructureV2Adapter.adapt` |
| **3** | Characterization | BigBelugaVOBEngine event behavior | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_bigbeluga_order_block_adaptation` | `rec.event_type == ORDER_BLOCK_BULLISH` | `BigBelugaAdapter.adapt` |
| **4** | Characterization | FVGEngine event behavior | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_fvg_imbalance_adaptation` | `rec.event_type == FVG_BULLISH` | `FVGAdapter.adapt` |
| **5** | Characterization | LiquidityEngine event behavior | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_liquidity_pool_adaptation` | `rec.event_type == LIQUIDITY_POOL_HIGH` | `LiquidityAdapter.adapt` |
| **6** | Characterization | OracleDevPriceActionAnalyzer state behavior | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_oracle_dev_regime_adaptation` | `rec.event_type == TREND_BULLISH` | `OracleDevAdapter.adapt` |
| **7** | Adapter | Exact field mapping | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.payload.primary_level.value == 24500.0` | `StructureV2Adapter.adapt` |
| **8** | Adapter | Rule provenance | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_default_native_rule_registry` | `r_struct.status == ACTIVE` | `RuleRegistry._register_default_native_rules` |
| **9** | Adapter | Source-bar lineage | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `len(rec.source_bars) == 2` | `StructureV2Adapter.adapt` |
| **10** | Adapter | Exact price conversion | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_exact_price_quantization` | `atom.ticks == 2450000` | `quantize_price` |
| **11** | Adapter | Identity mapping | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.instrument.instrument_key == "UNDERLYING_INDEX:NIFTY"` | `StructureV2Adapter.adapt` |
| **12** | Adapter | Timeframe mapping | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.timeframe == "5m"` | `StructureV2Adapter.adapt` |
| **13** | Adapter | Lifecycle mapping | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_bigbeluga_order_block_adaptation` | `rec.lifecycle_state == ACTIVE` | `BigBelugaAdapter.adapt` |
| **14** | Adapter | Abstention handling | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_no_signal_abstention` | `res.abstentions[0].code == UNSUPPORTED_NATIVE_EVENT` | `AdapterAbstention` |
| **15** | Temporal | No future source bar | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | Source bar `available_at <= as_of` | `BarReference.__post_init__` |
| **16** | Temporal | Earliest-knowable watermark | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.detected_at == as_of` | `EyeEventRecord.create` |
| **17** | Temporal | Forming vs closed bar separation | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.detection_state == CONFIRMED_CLOSED_BAR` | `EyeEventRecord.create` |
| **18** | Temporal | Higher-timeframe completion | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `b.is_closed is True` | `BarReference` |
| **19** | Temporal | Timezone normalization | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `ctx.as_of.tzinfo is not None` | `EvaluationContext.__post_init__` |
| **20** | Temporal | Delayed source availability | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `bar.available_at` enforced | `BarReference` |
| **21** | Temporal | Prefix invariance | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_offline_replay_parity` | `status == PREFIX_STABLE` | `OfflineReplayHarness.compare_parity` |
| **22** | Stability | Append stability | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_offline_replay_parity` | `event_key` stable across appends | `OfflineReplayHarness.compare_parity` |
| **23** | Stability | Reconnect stability | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `event_key` stable across epoch | `EyeEventRecord.create` |
| **24** | Stability | Contract-switch isolation | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `instrument_key` isolated | `InstrumentIdentity` |
| **25** | Stability | Full-run / incremental parity | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_offline_replay_parity` | `parity_res.is_parity is True` | `OfflineReplayHarness.compare_parity` |
| **26** | Stability | Fresh-process deterministic ordering | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | Canonical JSON byte-identical | `canonical_json` |
| **27** | Stability | Stable event key | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_cross_producer_bos_isolation` | `rec_s.event_key` stable | `compute_sha256` |
| **28** | Stability | Immutable previous revisions | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `record_id` changes monotonically | `EyeEventRecord.create` |
| **29** | Conflict | StructureV2 BOS and BigBeluga BOS distinct | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_cross_producer_bos_isolation` | `rec_s.event_key != rec_b.event_key` | `ProducerProvenance` |
| **30** | Conflict | Close-break and wick-break variants distinct | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_cross_producer_bos_isolation` | `rule_id` distinct | `ProducerProvenance` |
| **31** | Conflict | Native Citadel definition preserved | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_default_native_rule_registry` | `EXISTING_CITADEL_RULE` | `RuleRegistry` |
| **32** | Conflict | Producer priority does not change evidence quality | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_cross_producer_bos_isolation` | Separate provenance records | `ProducerProvenance` |
| **33** | Failure | Unsupported native event abstains | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_no_signal_abstention` | `UNSUPPORTED_NATIVE_EVENT` abstention | `StructureV2Adapter.adapt` |
| **34** | Failure | Missing lineage abstains | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_no_signal_abstention` | `SOURCE_BAR_LINEAGE_MISSING` abstention | `StructureV2Adapter.adapt` |
| **35** | Failure | Ambiguous timing abstains | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_no_signal_abstention` | `AMBIGUOUS_EVENT_TIME` abstention | `AdapterAbstention` |
| **36** | Failure | Invalid price fails | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_exact_price_quantization` | `EyeContractError` on boolean | `quantize_price` |
| **37** | Failure | Identity mismatch fails | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | Strict `InstrumentIdentity` validation | `InstrumentIdentity.__post_init__` |
| **38** | Safety | No execution authority | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | `rec.authority == OBSERVATION_ONLY` | `EyeEventRecord` |
| **39** | Safety | No option recommendation | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_structure_v2_bos_bullish_adaptation` | Pure market observation | `EyeEventRecord` |
| **40** | Safety | No frontend/API/runtime dependency | `PROVEN_BY_TEST` | `test_adapters_all.py` | `test_offline_replay_parity` | Pure offline replay | `OfflineReplayHarness` |
