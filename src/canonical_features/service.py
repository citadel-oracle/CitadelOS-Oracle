"""
Canonical Feature Production Shadow Publisher Service.
Single singleton service mounted in application lifecycle to publish immutable feature snapshots,
evaluate consumer shadow parity, and manage schema-aware bounded restart persistence and runtime bootstrap.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Mapping, Optional

from src.canonical_features.engine import CanonicalFeatureEngine
from src.canonical_features.models import CanonicalFeatureSnapshot
from src.canonical_features.formula_registry import FormulaProfileRegistry
from src.canonical_features.adapters.ose_adapter import OseShadowAdapter
from src.canonical_features.adapters.vob_adapter import VobShadowAdapter
from src.canonical_features.adapters.tactical_edge_adapter import TacticalEdgeShadowAdapter
from src.canonical_features.adapters.edge_lab_adapter import EdgeLabShadowAdapter
from src.canonical_features.migration import MigrationRegistry, MigrationReadResult

logger = logging.getLogger("citadel.canonical_features")

DEFAULT_PRODUCTION_STATE_PATH = "/Users/ayushmudgal/Developer/CitadelOS/logs/canonical_features_state.json"
DEFAULT_BOOTSTRAP_CANDLES_PATH = "logs/kronos_alpha_candles.json"


class CanonicalFeatureService:
    _instance: Optional[CanonicalFeatureService] = None

    def __init__(
        self,
        persistence_path: Optional[str] = None,
        bootstrap_path: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        self._override_enabled = enabled
        if persistence_path is None:
            self.persistence_path = Path(
                os.getenv("CITADEL_CANONICAL_STATE_PATH", DEFAULT_PRODUCTION_STATE_PATH)
            )
        else:
            self.persistence_path = Path(persistence_path)

        self.bootstrap_path = Path(
            bootstrap_path
            or os.getenv("CITADEL_CANONICAL_BOOTSTRAP_PATH", DEFAULT_BOOTSTRAP_CANDLES_PATH)
        )

        self.engine = CanonicalFeatureEngine(instrument="NIFTY", timeframe="5m", max_history=500)
        self.migration_registry = MigrationRegistry()

        self.ose_adapter = OseShadowAdapter()
        self.vob_adapter = VobShadowAdapter()
        self.tactical_adapter = TacticalEdgeShadowAdapter()
        self.edge_lab_adapter = EdgeLabShadowAdapter()

        self._last_snapshot: Optional[CanonicalFeatureSnapshot] = None
        self._shadow_reports: dict[str, dict[str, Any]] = {}

        # Telemetry & Runtime Status Accounting
        self.runtime_status: str = "INITIALIZING"
        self.bootstrap_source: Optional[str] = None
        self.bootstrap_started_at: Optional[str] = None
        self.bootstrap_completed_at: Optional[str] = None
        self.bars_loaded: int = 0
        self.valid_bars: int = 0
        self.rejected_bars: int = 0
        self.bars_finalized: int = 0
        self.warmup_bars: int = 50
        self.restored_from_state: bool = False

        # Persistence Telemetry
        self.last_checkpoint_at: Optional[str] = None
        self.checkpoint_count: int = 0
        self.checkpoint_reason: Optional[str] = None
        self.checkpoint_duration_ms: float = 0.0
        self.checkpoint_error: Optional[str] = None

        # Execute Startup Priority Chain if enabled
        if self.enabled:
            self._startup_initialize()

    @property
    def enabled(self) -> bool:
        if self._override_enabled is not None:
            return self._override_enabled
        env_val = os.getenv("CITADEL_CANONICAL_SHADOW_ENABLED", "0").lower()
        return env_val in ("1", "true", "yes", "enabled")

    @classmethod
    def get_instance(
        cls,
        persistence_path: Optional[str] = None,
        bootstrap_path: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> CanonicalFeatureService:
        if cls._instance is None:
            cls._instance = cls(
                persistence_path=persistence_path,
                bootstrap_path=bootstrap_path,
                enabled=enabled,
            )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance for testing isolation."""
        cls._instance = None

    def publish_candle(
        self, candle: Mapping[str, Any], is_complete: bool = False
    ) -> Optional[CanonicalFeatureSnapshot]:
        if not self.enabled:
            return None

        # Authoritative OHLCV Validation: Reject LTP-only payloads marked as complete
        if is_complete and not self._is_valid_ohlcv(candle):
            logger.warning("Rejected incomplete OHLCV payload marked as completed bar.")
            self.rejected_bars += 1
            return None

        snapshot = self.engine.update_bar(candle, is_complete=is_complete)
        self._last_snapshot = snapshot

        if is_complete:
            self.bars_finalized = len(self.engine._candles)
            self.checkpoint(reason="COMPLETED_BAR")

        return snapshot

    def get_latest_snapshot(self) -> Optional[CanonicalFeatureSnapshot]:
        if not self.enabled:
            return None
        return self._last_snapshot or self.engine._last_snapshot

    def evaluate_shadow_parity(
        self,
        consumer_name: str,
        legacy_output: Mapping[str, Any],
        feature_name: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "status": "SHADOW_DISABLED",
                "consumer": consumer_name,
                "feature": feature_name,
                "execution_influence": "ZERO",
            }

        snapshot = self.get_latest_snapshot()
        if snapshot is None:
            return {
                "status": "NO_SNAPSHOT",
                "consumer": consumer_name,
                "feature": feature_name,
                "execution_influence": "ZERO",
            }

        c_upper = consumer_name.upper()
        if c_upper == "OSE":
            res = self.ose_adapter.evaluate_shadow_parity(legacy_output, snapshot, feature_name)
        elif c_upper == "VOB":
            res = self.vob_adapter.evaluate_shadow_parity(legacy_output, snapshot, feature_name)
        elif c_upper in ("TACTICAL_EDGE", "TACTICAL EDGE"):
            res = self.tactical_adapter.evaluate_shadow_parity(legacy_output, snapshot, feature_name)
        elif c_upper in ("EDGE_LAB", "EDGE LAB"):
            res = self.edge_lab_adapter.evaluate_shadow_parity(legacy_output, snapshot, feature_name)
        else:
            res = {
                "consumer": consumer_name,
                "feature": feature_name,
                "parity_status": "UNKNOWN_CONSUMER",
                "execution_influence": "ZERO",
            }

        drift = res.get("drift")
        if drift is None:
            res["classification"] = "WARMUP_MISSING"
        elif drift == 0.0:
            res["classification"] = "EXACT"
        elif drift <= 0.02:
            res["classification"] = "TOLERANCE"
        else:
            res["classification"] = "MISMATCH"

        self._shadow_reports[f"{consumer_name}:{feature_name}"] = res
        return res

    def get_shadow_status(self) -> dict[str, Any]:
        snap = self.get_latest_snapshot() if self.enabled else None
        return {
            "enabled": self.enabled,
            "runtime_status": self.runtime_status if self.enabled else "SHADOW_DISABLED",
            "bootstrap_source": self.bootstrap_source if self.enabled else None,
            "bootstrap_started_at": self.bootstrap_started_at,
            "bootstrap_completed_at": self.bootstrap_completed_at,
            "bars_loaded": self.bars_loaded,
            "valid_bars": self.valid_bars,
            "rejected_bars": self.rejected_bars,
            "bars_finalized": self.bars_finalized or (len(self.engine._candles) if self.enabled else 0),
            "warmup_bars": self.warmup_bars,
            "latest_snapshot_id": snap.feature_snapshot_id if snap else None,
            "source_revision": snap.source_revision if snap else 0,
            "feature_revision": snap.feature_revision if snap else 0,
            "latest_completed_bar_end": snap.bar_end if snap else None,
            "restored_from_state": self.restored_from_state,
            "publisher_instance": id(self),
            "persistence_path": str(self.persistence_path),
            "telemetry": {
                "last_checkpoint_at": self.last_checkpoint_at,
                "checkpoint_count": self.checkpoint_count,
                "checkpoint_reason": self.checkpoint_reason,
                "checkpoint_duration_ms": round(self.checkpoint_duration_ms, 3),
                "checkpoint_error": self.checkpoint_error,
            },
            "active_reports": dict(self._shadow_reports) if self.enabled else {},
            "migration_status": self.migration_registry.get_migration_status() if self.enabled else {},
            "execution_influence": "ZERO",
        }

    def get_migration_status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "SHADOW_DISABLED", "execution_influence": "ZERO"}
        return self.migration_registry.get_migration_status()

    # ------------------------------------------------------------------
    # Startup Priority Chain
    # ------------------------------------------------------------------

    def _startup_initialize(self) -> None:
        self.bootstrap_started_at = datetime.now(timezone.utc).isoformat()

        # Priority 1: Restore valid canonical state file
        if self._restore_on_startup():
            self.runtime_status = "RESTORED"
            self.restored_from_state = True
            self.bootstrap_source = str(self.persistence_path)
            self.bootstrap_completed_at = datetime.now(timezone.utc).isoformat()
            self._populate_initial_consumer_reports()
            return

        # Priority 2: Bootstrap from approved persisted completed bars
        if self._bootstrap_from_persisted_candles():
            self.runtime_status = "BOOTSTRAPPED"
            self.restored_from_state = False
            self.bootstrap_source = str(self.bootstrap_path)
            self.bootstrap_completed_at = datetime.now(timezone.utc).isoformat()
            self._populate_initial_consumer_reports()
            return

        # Priority 3: Start empty with explicit status NO_BOOTSTRAP_DATA
        self.runtime_status = "NO_BOOTSTRAP_DATA"
        self.restored_from_state = False
        self.bootstrap_source = None
        self.bootstrap_completed_at = datetime.now(timezone.utc).isoformat()

    def _bootstrap_from_persisted_candles(self) -> bool:
        if not self.bootstrap_path.exists():
            logger.info(f"Bootstrap candle path not found at {self.bootstrap_path}.")
            return False

        try:
            with open(self.bootstrap_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            candles = data.get("candles", [])
            if not candles:
                return False

            self.bars_loaded = len(candles)
            valid_candles = []
            for c in candles:
                if self._is_valid_ohlcv(c):
                    valid_candles.append(c)
                else:
                    self.rejected_bars += 1

            self.valid_bars = len(valid_candles)
            if not valid_candles:
                return False

            # Ingest valid candles into canonical feature engine
            self.engine.ingest_candles(valid_candles)
            self._last_snapshot = self.engine._last_snapshot
            self.bars_finalized = len(self.engine._candles)
            logger.info(f"Canonical feature engine bootstrapped {self.bars_finalized} bars from {self.bootstrap_path}.")

            # Write initial checkpoint
            self.checkpoint(reason="BOOTSTRAP")
            return True
        except Exception as err:
            logger.warning(f"Failed to bootstrap canonical features from {self.bootstrap_path}: {err}")
            return False

    def _restore_on_startup(self) -> bool:
        if not self.persistence_path.exists():
            return False

        try:
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return False

            if data.get("schema_version") != 1:
                logger.warning("Incompatible schema_version in persistence. Safe fallback.")
                return False

            engine_state = data.get("engine_state")
            if not isinstance(engine_state, dict):
                return False

            self.engine.import_state(engine_state)
            self._last_snapshot = self.engine._last_snapshot
            self.bars_finalized = len(self.engine._candles)
            logger.info(f"Canonical feature engine state restored from {self.persistence_path}.")
            return True
        except Exception as err:
            logger.warning(f"Could not restore state from {self.persistence_path}: {err}")
            return False

    def _populate_initial_consumer_reports(self) -> None:
        """Populate initial read-only shadow parity reports on startup."""
        snapshot = self.get_latest_snapshot()
        if snapshot is None:
            return

        # Legacy active profiles parity reports
        ose_ema = FormulaProfileRegistry.compute_profile("EMA_OSE_V1", self.engine._candles, period=50)
        if ose_ema is not None:
            self.evaluate_shadow_parity("OSE", {"ema_50": ose_ema}, "ema_50")

        vob_atr = FormulaProfileRegistry.compute_profile("ATR_OSE_V1", self.engine._candles, period=14)
        if vob_atr is not None:
            self.evaluate_shadow_parity("VOB", {"atr_value": vob_atr}, "atr_value")

        st_tuple = FormulaProfileRegistry.compute_profile("SUPERTREND_OSE_V1", self.engine._candles, period=10)
        if st_tuple is not None and isinstance(st_tuple, tuple):
            self.evaluate_shadow_parity("TACTICAL_EDGE", {"supertrend": st_tuple[0]}, "supertrend")

        vwap_val = FormulaProfileRegistry.compute_profile("VWAP_CUMULATIVE_V1", self.engine._candles)
        if vwap_val is not None:
            self.evaluate_shadow_parity("EDGE_LAB", {"vwap_value": vwap_val}, "vwap_value")

    @staticmethod
    def _is_valid_ohlcv(c: Mapping[str, Any]) -> bool:
        """Check whether a candle object contains complete, non-zero OHLCV fields."""
        required = ["open", "high", "low", "close"]
        for field in required:
            if field not in c or c[field] is None:
                return False
            try:
                val = float(c[field])
                if val <= 0.0:
                    return False
            except (ValueError, TypeError):
                return False
        return True

    def checkpoint(self, reason: str = "EXPLICIT") -> bool:
        """Perform synchronous schema-aware persistence write.

        Atomic write via temporary file (.tmp) and os.replace.
        """
        if not self.enabled:
            return False

        t0 = time.perf_counter()
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 1,
                "formula_version": "1.0.0",
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "engine_state": self.engine.export_state(),
            }
            tmp_path = self.persistence_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, self.persistence_path)

            t1 = time.perf_counter()
            self.last_checkpoint_at = datetime.now(timezone.utc).isoformat()
            self.checkpoint_count += 1
            self.checkpoint_reason = reason
            self.checkpoint_duration_ms = (t1 - t0) * 1000.0
            self.checkpoint_error = None
            return True
        except Exception as err:
            t1 = time.perf_counter()
            self.checkpoint_duration_ms = (t1 - t0) * 1000.0
            self.checkpoint_error = str(err)
            logger.warning(f"Failed to write canonical feature checkpoint: {err}")
            return False
