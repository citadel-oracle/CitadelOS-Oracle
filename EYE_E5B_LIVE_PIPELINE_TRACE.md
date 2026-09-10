# EYE E5B LIVE PIPELINE TRACE

## Pipeline Architecture & Lineage

```
CANONICAL LIVE MARKET DATA (Dhan WebSocket / REST or Canonical Bar Resampler)
        ↓
EYE ATOMIC DETECTORS (SwingStateDetector, StructureBreakDetector, LiquidityDetector, DisplacementDetector, FVGClusterDetector)
        ↓
E3 SETUP COMPOSER (SetupComposer with DEFAULT_SETUP_DEFINITIONS)
        ↓
EYE RUNTIME STATE (EyeRuntimeState Service)
        ↓
EYE ORACLE PROJECTION (EyeOracleProjectionService)
        ↓
V2 DASHBOARD (/v2/dashboard endpoint)
        ↓
ORACLE FRONTEND (OracleWorkspacePanel.tsx)
```

## Detailed Component Trace Matrix

| Stage | Module Path | Class / Function | Input Data | Output Data | Timestamp Semantics |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Canonical Bars** | `src/eye/detectors/input_model.py` | `DetectorBar` | Raw OHLCV tick data / candles | Sequence of `DetectorBar` objects | `expected_close_time` (Bar close UTC) |
| **2. Atomic Detectors** | `src/eye/detectors/` | `SwingStateDetector.detect()`, `StructureBreakDetector.detect()`, `LiquidityDetector.detect()`, `FVGClusterDetector.detect()` | `Sequence[DetectorBar]`, `DetectorContext` | `DetectorResult` emitting `EyeEventRecord` events | `knowledge_time` (Confirmed bar close UTC) |
| **3. Setup Composer** | `src/eye/composer/matcher.py` | `SetupComposer.process_event()` | `EyeEventRecord` atomic event | `List[SetupCandidateRecord]` candidate setups | `confirmed_at` (Knowledge time of triggering event) |
| **4. Runtime State** | `src/eye/oracle_projection/runtime_state.py` | `EyeRuntimeState` | Live bar ingestion, TradingView context | Current structure, active setups, liquidity state | `source_event_timestamp` & `source_received_timestamp` |
| **5. Pure Projection** | `src/eye/oracle_projection/projection_service.py` | `EyeOracleProjectionService.get_projection()` | `EyeRuntimeState` snapshot | `EyeOracleProjection` | `projection_computed_at` (now) |
| **6. V2 Dashboard** | `src/api/v2_integration.py` | `V2DashboardIntegration._build_dashboard()` | `EyeOracleProjection.to_dict()` | `feeds.eye_oracle_projection` in `/v2/dashboard` JSON | `generated_at` (Dashboard response ISO) |
| **7. Oracle UI** | `citadel-dashboard/src/components/institutional/OracleWorkspacePanel.tsx` | `OracleWorkspacePanel` React component | `feeds.eye_oracle_projection.data` | Visual render of Structure, Setup, Entry, SL, Targets, R:R, Thesis | Frontend render timestamp |

---

## Production Rule Invariance
- **No Active Setup:** Returns `setup_family = "NO_ACTIVE_SETUP"`, `lifecycle = "NO_ACTIVE_SETUP"`.
- **No Entry Geometry:** Returns `entry_status = "ENTRY_BAND_NOT_ESTABLISHED"`.
- **No Structural Stop:** Returns `status = "STRUCTURAL_SL_NOT_ESTABLISHED"`.
- **No Natural Targets:** Returns `targets = []`.
- **No R:R:** Returns `status = "RR_NOT_ESTABLISHED"`.
- **No Structure:** Returns `directional_structure = "UNKNOWN"`.
- **Zero Fake Fixtures:** Absolutely no default prices (24600, 24575, etc.) in production runtime code.
