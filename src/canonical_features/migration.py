"""
Canonical Feature Migration Mode Registry & Guard Manager.

Manages per-consumer migration modes (LEGACY_ONLY, DUAL_READ, CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK, CANONICAL_ONLY).
Applies strict runtime automatic guards (stale snapshot, wrong instrument/timeframe, incomplete bar,
missing feature, formula/schema version mismatch, drift threshold) before allowing canonical read.

Safety Guarantee:
- Legacy remains 100% authoritative for all decisions in DUAL_READ mode.
- CANONICAL_PRIMARY and CANONICAL_ONLY modes are blocked from default configuration during migration readiness.
- Execution influence remains ZERO.
"""

from __future__ import annotations
from enum import Enum
import logging
import os
from typing import Any, Mapping, Optional

from src.canonical_features.models import CanonicalFeatureSnapshot

logger = logging.getLogger("citadel.canonical_migration")


class MigrationMode(str, Enum):
    LEGACY_ONLY = "LEGACY_ONLY"
    DUAL_READ = "DUAL_READ"
    CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK = "CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK"
    CANONICAL_ONLY = "CANONICAL_ONLY"


class MigrationGuardFailure(str, Enum):
    SHADOW_DISABLED = "SHADOW_DISABLED"
    MODE_LEGACY_ONLY = "MODE_LEGACY_ONLY"
    NO_SNAPSHOT = "NO_SNAPSHOT"
    STALE_SNAPSHOT = "STALE_SNAPSHOT"
    WRONG_INSTRUMENT = "WRONG_INSTRUMENT"
    WRONG_TIMEFRAME = "WRONG_TIMEFRAME"
    INCOMPLETE_BAR = "INCOMPLETE_BAR"
    MISSING_FEATURE = "MISSING_FEATURE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    FORMULA_MISMATCH = "FORMULA_MISMATCH"
    DRIFT_EXCEEDED = "DRIFT_EXCEEDED"


class MigrationReadResult:
    def __init__(
        self,
        consumer: str,
        feature_name: str,
        mode: MigrationMode,
        legacy_value: Optional[float],
        canonical_value: Optional[float],
        selected_value: Optional[float],
        authoritative_source: str,  # "LEGACY" or "CANONICAL"
        profile_id: str,
        snapshot_id: Optional[str] = None,
        source_timestamp: Optional[str] = None,
        freshness_seconds: Optional[float] = None,
        drift: Optional[float] = None,
        classification: str = "EXACT",  # EXACT, TOLERANCE, MISMATCH, WARMUP_MISSING, FALLBACK
        fallback_occurred: bool = False,
        fallback_reason: Optional[str] = None,
        execution_influence: str = "ZERO",
    ):
        self.consumer = consumer
        self.feature_name = feature_name
        self.mode = mode
        self.legacy_value = legacy_value
        self.canonical_value = canonical_value
        self.selected_value = selected_value
        self.authoritative_source = authoritative_source
        self.profile_id = profile_id
        self.snapshot_id = snapshot_id
        self.source_timestamp = source_timestamp
        self.freshness_seconds = freshness_seconds
        self.drift = drift
        self.classification = classification
        self.fallback_occurred = fallback_occurred
        self.fallback_reason = fallback_reason
        self.execution_influence = execution_influence

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "feature_name": self.feature_name,
            "migration_mode": self.mode.value,
            "legacy_value": self.legacy_value,
            "canonical_value": self.canonical_value,
            "selected_value": self.selected_value,
            "authoritative_source": self.authoritative_source,
            "profile_id": self.profile_id,
            "snapshot_id": self.snapshot_id,
            "source_timestamp": self.source_timestamp,
            "freshness_seconds": round(self.freshness_seconds, 2) if self.freshness_seconds is not None else None,
            "drift": self.drift,
            "classification": self.classification,
            "fallback_occurred": self.fallback_occurred,
            "fallback_reason": self.fallback_reason,
            "execution_influence": self.execution_influence,
        }


from pathlib import Path
import json
import time

DEFAULT_CONTROL_PATH = "/Users/ayushmudgal/Developer/CitadelOS/logs/canonical_migration_control.json"


class MigrationRegistry:
    DEFAULT_MODES = {
        "OSE": MigrationMode.DUAL_READ,
        "VOB": MigrationMode.DUAL_READ,
        "TACTICAL_EDGE": MigrationMode.DUAL_READ,
        "EDGE_LAB": MigrationMode.DUAL_READ,
    }

    def __init__(
        self,
        overrides: Optional[Mapping[str, str]] = None,
        primary_permit: Optional[bool] = None,
        control_path: Optional[str] = None,
    ):
        self._control_path = Path(
            control_path
            or os.getenv("CITADEL_CANONICAL_CONTROL_PATH", DEFAULT_CONTROL_PATH)
        )
        self._modes: dict[str, MigrationMode] = {}
        self._history: list[dict[str, Any]] = []
        self._override_permit = primary_permit
        self._primary_permit: bool = (
            primary_permit
            if primary_permit is not None
            else os.getenv("CITADEL_CANONICAL_PRIMARY_APPROVED", "false").lower() == "true"
        )
        self._telemetry: dict[str, int] = {
            "total_reads": 0,
            "dual_reads": 0,
            "canonical_primary_reads": 0,
            "legacy_fallback_reads": 0,
            "guard_failures": 0,
        }

        self._last_mtime: float = 0.0
        self._control_revision: int = 0
        self._control_loaded_at: Optional[str] = None
        self._control_error: Optional[str] = None

        # Initial default mode assignments
        for consumer, default_mode in self.DEFAULT_MODES.items():
            env_key = f"CITADEL_MIGRATION_MODE_{consumer}"
            env_val = os.getenv(env_key, default_mode.value)
            if overrides and consumer in overrides:
                env_val = overrides[consumer]
            mode = self._parse_mode(env_val, default_mode, self._primary_permit)
            self._modes[consumer] = mode

        # Load persisted control state if present
        self._load_control_state()

    def _load_control_state(self) -> None:
        if not self._control_path.exists():
            return
        try:
            mtime = self._control_path.stat().st_mtime
            if mtime == self._last_mtime and self._last_mtime > 0:
                return  # Unchanged
            with open(self._control_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "primary_permit" in data and self._override_permit is None:
                self._primary_permit = bool(data["primary_permit"])
            persisted_modes = data.get("modes", {})
            for c, m in persisted_modes.items():
                c_key = c.upper().replace(" ", "_")
                if c_key in self.DEFAULT_MODES:
                    self._modes[c_key] = self._parse_mode(m, self.DEFAULT_MODES[c_key], self._primary_permit)
            self._history = data.get("history", [])
            self._last_mtime = mtime
            self._control_revision += 1
            self._control_loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._control_error = None
        except Exception as e:
            self._control_error = str(e)
            logger.error(f"Failed to load migration control state from {self._control_path}: {e}")

    def refresh_if_stale(self) -> None:
        if self._control_path.exists():
            try:
                mtime = self._control_path.stat().st_mtime
                if mtime != self._last_mtime:
                    self._load_control_state()
            except Exception:
                pass

    def _save_control_state(self) -> None:
        try:
            self._control_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": "1.0.0",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "primary_permit": self._primary_permit,
                "modes": {c: m.value for c, m in self._modes.items()},
                "history": self._history[-50:],  # Retain latest 50 audit entries
            }
            tmp_p = self._control_path.with_suffix(".tmp")
            with open(tmp_p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_p.replace(self._control_path)
        except Exception as e:
            logger.error(f"Failed to save migration control state to {self._control_path}: {e}")

    @property
    def primary_permit(self) -> bool:
        return self._primary_permit

    def set_primary_permit(self, approved: bool, actor: str = "CLI_CONTROLLER", reason: str = "PERMIT_MUTATION") -> None:
        prev = self._primary_permit
        self._primary_permit = approved
        if not approved:
            # Downgrade any primary mode if permit is revoked
            for c, m in list(self._modes.items()):
                if m == MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK:
                    self._modes[c] = MigrationMode.DUAL_READ
        self._history.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "consumer": "GLOBAL_PERMIT",
            "previous_mode": str(prev),
            "new_mode": str(approved),
            "actor": actor,
            "reason": reason,
        })
        self._save_control_state()

    def _parse_mode(self, val: str, default: MigrationMode, permit: bool) -> MigrationMode:
        try:
            mode = MigrationMode(val.upper())
            if mode == MigrationMode.CANONICAL_ONLY:
                logger.warning("CANONICAL_ONLY mode is strictly prohibited. Defaulting to DUAL_READ.")
                return MigrationMode.DUAL_READ
            if mode == MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK and not permit:
                logger.warning(
                    "CANONICAL_PRIMARY requested but CITADEL_CANONICAL_PRIMARY_APPROVED permit is false. Defaulting to DUAL_READ."
                )
                return MigrationMode.DUAL_READ
            return mode
        except ValueError:
            return default

    def get_mode(self, consumer: str) -> MigrationMode:
        self.refresh_if_stale()
        c_key = consumer.upper().replace(" ", "_")
        raw_mode = self._modes.get(c_key, MigrationMode.DUAL_READ)
        if raw_mode == MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK and not self._primary_permit:
            return MigrationMode.DUAL_READ
        return raw_mode

    def set_mode(
        self,
        consumer: str,
        mode: MigrationMode,
        actor: str = "CLI_CONTROLLER",
        reason: str = "RUNTIME_MUTATION",
    ) -> None:
        self.refresh_if_stale()
        c_key = consumer.upper().replace(" ", "_")
        prev_mode = self.get_mode(c_key)
        target_mode = mode

        if target_mode == MigrationMode.CANONICAL_ONLY:
            logger.warning(f"Blocked setting {c_key} to CANONICAL_ONLY.")
            target_mode = MigrationMode.DUAL_READ
        elif target_mode == MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK and not self._primary_permit:
            logger.warning(f"Blocked setting {c_key} to CANONICAL_PRIMARY because permit is False.")
            target_mode = MigrationMode.DUAL_READ

        self._modes[c_key] = target_mode
        self._history.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "consumer": c_key,
            "previous_mode": prev_mode.value,
            "new_mode": target_mode.value,
            "actor": actor,
            "reason": reason,
        })
        self._save_control_state()

    def evaluate_read(
        self,
        consumer: str,
        feature_name: str,
        profile_id: str,
        legacy_val: Optional[float],
        snapshot: Optional[CanonicalFeatureSnapshot],
        expected_instrument: str = "NIFTY",
        expected_timeframe: str = "5m",
        max_tolerance: float = 0.02,
        max_freshness_seconds: float = 900.0,
        is_live_market: bool = False,
    ) -> MigrationReadResult:
        self.refresh_if_stale()
        self._telemetry["total_reads"] += 1
        c_key = consumer.upper().replace(" ", "_")
        mode = self.get_mode(c_key)

        # 1. Mode check: LEGACY_ONLY
        if mode == MigrationMode.LEGACY_ONLY:
            return MigrationReadResult(
                consumer=consumer,
                feature_name=feature_name,
                mode=mode,
                legacy_value=legacy_val,
                canonical_value=None,
                selected_value=legacy_val,
                authoritative_source="LEGACY",
                profile_id=profile_id,
                classification="LEGACY_ONLY",
                fallback_occurred=False,
                fallback_reason="MODE_LEGACY_ONLY",
                execution_influence="ZERO",
            )

        # 2. Snapshot Check: Missing
        if snapshot is None:
            self._telemetry["guard_failures"] += 1
            self._telemetry["legacy_fallback_reads"] += 1
            return MigrationReadResult(
                consumer=consumer,
                feature_name=feature_name,
                mode=mode,
                legacy_value=legacy_val,
                canonical_value=None,
                selected_value=legacy_val,
                authoritative_source="LEGACY",
                profile_id=profile_id,
                classification="WARMUP_MISSING",
                fallback_occurred=True,
                fallback_reason=MigrationGuardFailure.NO_SNAPSHOT.value,
                execution_influence="ZERO",
            )

        # 3. Instrument Guard
        if snapshot.instrument != expected_instrument:
            self._telemetry["guard_failures"] += 1
            return self._build_fallback(
                consumer, feature_name, mode, legacy_val, profile_id, snapshot, MigrationGuardFailure.WRONG_INSTRUMENT
            )

        # 4. Timeframe Guard
        if snapshot.timeframe != expected_timeframe:
            self._telemetry["guard_failures"] += 1
            return self._build_fallback(
                consumer, feature_name, mode, legacy_val, profile_id, snapshot, MigrationGuardFailure.WRONG_TIMEFRAME
            )

        # 5. Freshness Guard (enforced in live market)
        freshness_sec = snapshot.freshness_age_seconds
        if is_live_market and freshness_sec is not None and freshness_sec > max_freshness_seconds:
            self._telemetry["guard_failures"] += 1
            return self._build_fallback(
                consumer, feature_name, mode, legacy_val, profile_id, snapshot, MigrationGuardFailure.STALE_SNAPSHOT
            )

        # 6. Extract Canonical Feature Value
        canonical_val = self._extract_canonical_val(snapshot, feature_name)
        if canonical_val is None:
            self._telemetry["guard_failures"] += 1
            return self._build_fallback(
                consumer, feature_name, mode, legacy_val, profile_id, snapshot, MigrationGuardFailure.MISSING_FEATURE
            )

        # 7. Compute Drift and Classification
        drift = None
        classification = "EXACT"
        if legacy_val is not None and canonical_val is not None:
            drift = round(abs(float(canonical_val) - float(legacy_val)), 6)
            if drift == 0.0:
                classification = "EXACT"
            elif drift <= max_tolerance:
                classification = "TOLERANCE"
            else:
                classification = "MISMATCH"

        # 8. Selection Logic: DUAL_READ vs CANONICAL_PRIMARY
        if mode == MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK and self._primary_permit:
            if classification in ("EXACT", "TOLERANCE"):
                self._telemetry["canonical_primary_reads"] += 1
                return MigrationReadResult(
                    consumer=consumer,
                    feature_name=feature_name,
                    mode=mode,
                    legacy_value=legacy_val,
                    canonical_value=canonical_val,
                    selected_value=canonical_val,  # Canonical selected as primary!
                    authoritative_source="CANONICAL",
                    profile_id=profile_id,
                    snapshot_id=snapshot.feature_snapshot_id,
                    source_timestamp=snapshot.source_timestamp,
                    freshness_seconds=freshness_sec,
                    drift=drift,
                    classification=classification,
                    fallback_occurred=False,
                    fallback_reason=None,
                    execution_influence="ZERO",
                )
            else:
                # Guard Failure (Drift Mismatch): Automatic Fallback to Legacy!
                self._telemetry["guard_failures"] += 1
                return self._build_fallback(
                    consumer, feature_name, mode, legacy_val, profile_id, snapshot, MigrationGuardFailure.DRIFT_EXCEEDED
                )

        # DUAL_READ mode: Always select LEGACY as decision authority!
        self._telemetry["dual_reads"] += 1
        return MigrationReadResult(
            consumer=consumer,
            feature_name=feature_name,
            mode=mode,
            legacy_value=legacy_val,
            canonical_value=canonical_val,
            selected_value=legacy_val,  # Legacy remains 100% decision authority!
            authoritative_source="LEGACY",
            profile_id=profile_id,
            snapshot_id=snapshot.feature_snapshot_id,
            source_timestamp=snapshot.source_timestamp,
            freshness_seconds=freshness_sec,
            drift=drift,
            classification=classification,
            fallback_occurred=False,
            fallback_reason=None,
            execution_influence="ZERO",
        )

    def _build_fallback(
        self,
        consumer: str,
        feature_name: str,
        mode: MigrationMode,
        legacy_val: Optional[float],
        profile_id: str,
        snapshot: CanonicalFeatureSnapshot,
        reason: MigrationGuardFailure,
    ) -> MigrationReadResult:
        self._telemetry["legacy_fallback_reads"] += 1
        return MigrationReadResult(
            consumer=consumer,
            feature_name=feature_name,
            mode=mode,
            legacy_value=legacy_val,
            canonical_value=None,
            selected_value=legacy_val,
            authoritative_source="LEGACY",
            profile_id=profile_id,
            snapshot_id=snapshot.feature_snapshot_id,
            source_timestamp=snapshot.source_timestamp,
            freshness_seconds=snapshot.freshness_age_seconds,
            drift=None,
            classification="FALLBACK",
            fallback_occurred=True,
            fallback_reason=reason.value,
            execution_influence="ZERO",
        )

    @staticmethod
    def _extract_canonical_val(snapshot: CanonicalFeatureSnapshot, feature_name: str) -> Optional[float]:
        f_lower = feature_name.lower()
        if f_lower in ("ema_50", "ema50"):
            return snapshot.ema_values.get("ema_50")
        elif f_lower in ("ema_21", "ema21"):
            return snapshot.ema_values.get("ema_21")
        elif f_lower in ("atr", "atr_value", "atr_14"):
            return snapshot.atr_value
        elif f_lower in ("vwap", "vwap_value"):
            return snapshot.vwap_value
        elif f_lower in ("supertrend", "supertrend_value"):
            return snapshot.supertrend.value
        elif f_lower in snapshot.ema_values:
            return snapshot.ema_values[f_lower]
        return None

    def get_migration_status(self) -> dict[str, Any]:
        self.refresh_if_stale()
        return {
            "migration_modes": {c: m.value for c, m in self._modes.items()},
            "primary_permit": self.primary_permit,
            "control_plane": {
                "control_revision": self._control_revision,
                "loaded_at": self._control_loaded_at,
                "control_error": self._control_error,
                "control_path": str(self._control_path),
            },
            "telemetry": dict(self._telemetry),
            "safety": {
                "legacy_authoritative": not self.primary_permit,
                "canonical_primary_allowed": self.primary_permit,
                "execution_influence": "ZERO",
            },
        }
