import json
import logging
import os
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from src.argus.tactical_config import HISTORY_LIMIT, SCHEMA_VERSION

logger = logging.getLogger(__name__)


class ArgusTacticalStoreError(RuntimeError):
    """Raised when Tactical Edge state cannot be loaded or saved safely."""


class ArgusTacticalStore:
    """Persist the latest projection and a bounded exactly-once evidence timeline."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = Lock()
        self._in_memory_payload: dict[str, Any] | None = None
        self.is_degraded: bool = False
        self.last_persistence_error: str | None = None
        self.last_successful_persist_at: str | None = None
        self._last_log_time: float = 0.0

    def load(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._load_unlocked())

    def latest(self) -> dict[str, Any] | None:
        return self.load().get("latest")

    def history(self) -> list[dict[str, Any]]:
        return list(self.load().get("history") or [])

    def publish(
        self,
        calculation_id: str,
        projection: Mapping[str, Any],
        evidence_record: Mapping[str, Any],
    ) -> bool:
        with self._lock:
            payload = self._load_unlocked()
            history = list(payload.get("history") or [])
            duplicate = any(
                str(item.get("calculation_id")) == str(calculation_id)
                for item in history
            )
            if not duplicate:
                history.append(deepcopy(dict(evidence_record)))
                history = history[-HISTORY_LIMIT:]
            payload.update(
                {
                    "schema_version": SCHEMA_VERSION,
                    "latest_calculation_id": calculation_id,
                    "latest": deepcopy(dict(projection)),
                    "history": history,
                }
            )
            # Maintain canonical current state in-memory first (unconditional)
            self._in_memory_payload = deepcopy(payload)
            # Best-effort disk persistence (firewalled against disk full / OS errors)
            self._atomic_write(payload)
            return not duplicate

    def _load_unlocked(self) -> dict[str, Any]:
        if self._in_memory_payload is not None:
            return deepcopy(self._in_memory_payload)

        if not self.path.exists():
            default_payload = {
                "schema_version": SCHEMA_VERSION,
                "latest_calculation_id": None,
                "latest": None,
                "history": [],
            }
            self._in_memory_payload = deepcopy(default_payload)
            return default_payload
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning(f"ARGUS Tactical state file corrupt or unreadable, initializing default: {error}")
            payload = {
                "schema_version": SCHEMA_VERSION,
                "latest_calculation_id": None,
                "latest": None,
                "history": [],
            }
        if not isinstance(payload, dict) or not isinstance(
            payload.get("history", []), list
        ):
            payload = {
                "schema_version": SCHEMA_VERSION,
                "latest_calculation_id": None,
                "latest": None,
                "history": [],
            }
        self._in_memory_payload = deepcopy(payload)
        return payload

    def _atomic_write(self, payload: Mapping[str, Any]) -> None:
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.is_degraded = False
            self.last_persistence_error = None
            self.last_successful_persist_at = datetime.now(timezone.utc).isoformat()
        except OSError as error:
            self.is_degraded = True
            self.last_persistence_error = f"{type(error).__name__}:{error}"
            now = time.time()
            if now - self._last_log_time >= 10.0:
                logger.warning(
                    f"ARGUS Tactical state persistence degraded (in-memory state active): {error}"
                )
                self._last_log_time = now
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


