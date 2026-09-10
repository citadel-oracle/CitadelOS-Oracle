"""Per-strategy immutable and mutable stores for Strategy Lab."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, perf_counter_ns
from typing import Any, Dict, Iterable, List, Mapping, Optional

import fcntl


_PROHIBITED_KEYS = (
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "cookie",
    "api_key",
    "access_key",
)

_RUNTIME_METRICS_LOCK = threading.RLock()
_RUNTIME_METRICS = {
    "pid": os.getpid(),
    "atomic_writes": 0,
    "atomic_writes_by_thread": {},
}


def reset_storage_runtime_metrics() -> None:
    with _RUNTIME_METRICS_LOCK:
        _RUNTIME_METRICS["pid"] = os.getpid()
        _RUNTIME_METRICS["atomic_writes"] = 0
        _RUNTIME_METRICS["atomic_writes_by_thread"] = {}


def storage_runtime_metrics() -> dict[str, Any]:
    with _RUNTIME_METRICS_LOCK:
        return {
            "pid": int(_RUNTIME_METRICS["pid"]),
            "atomic_writes": int(_RUNTIME_METRICS["atomic_writes"]),
            "atomic_writes_by_thread": dict(_RUNTIME_METRICS["atomic_writes_by_thread"]),
        }


def _record_atomic_write() -> None:
    with _RUNTIME_METRICS_LOCK:
        if _RUNTIME_METRICS["pid"] != os.getpid():
            reset_storage_runtime_metrics()
        thread_name = threading.current_thread().name
        by_thread = _RUNTIME_METRICS["atomic_writes_by_thread"]
        _RUNTIME_METRICS["atomic_writes"] = int(_RUNTIME_METRICS["atomic_writes"]) + 1
        by_thread[thread_name] = int(by_thread.get(thread_name, 0)) + 1


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            safe_key = str(key)[:96]
            if any(token in safe_key.lower() for token in _PROHIBITED_KEYS):
                continue
            result[safe_key] = _safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:4000]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return deepcopy(default)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise RuntimeError("STRATEGY_LAB_STORE_UNAVAILABLE")


def _atomic_write(path: Path, value: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(_safe(value), handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _record_atomic_write()
        finally:
            if os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
    except OSError:
        pass


class ImmutableStream:
    """Append-only JSONL stream with an internal hash chain."""

    CHECKPOINT_VERSION = 1
    # A WAL checkpoint connection normally owns the database, WAL, and SHM
    # descriptors. Oracle creates many session/research streams lazily, so an
    # unbounded per-instance connection cache eventually exhausts the parent
    # process descriptor limit. Keep the active set bounded while retaining a
    # useful cache for the recorder's hot streams.
    CHECKPOINT_CONNECTION_CACHE_LIMIT = 16
    _checkpoint_registry_lock = threading.Lock()
    _checkpoint_registry_pid = os.getpid()
    _checkpoint_registry: OrderedDict[
        int, weakref.ReferenceType["ImmutableStream"]
    ] = OrderedDict()

    def __init__(self, path: Path, max_bytes: int = 10 * 1024 * 1024, max_files: int = 3):
        self.path = path
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self.checkpoint_path = self.path.with_name(f"{self.path.name}.checkpoint.sqlite3")
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self._lock = threading.RLock()
        self._state_cache: Optional[Dict[str, Any]] = None
        self._checkpoint: sqlite3.Connection | None = None
        self._resume_mode = "NOT_LOADED"
        self._resume_ms = 0.0
        self._resume_scanned_bytes = 0
        self._last_append_metrics: Dict[str, Any] = {
            "batch_size": 0, "serialization_ms": 0.0, "write_ms": 0.0,
            "fsync_count": 0, "durable_complete_ns": None,
        }

    def _rotate_if_needed(self) -> None:
        if not self.path.exists():
            return
        if self.path.stat().st_size >= self.max_bytes:
            prune_target = self.path.with_name(f"{self.path.name}.{self.max_files}")
            if prune_target.exists():
                prune_target.unlink()
            for i in range(self.max_files, 0, -1):
                src = self.path.with_name(f"{self.path.name}.{i-1}") if i > 1 else self.path
                dst = self.path.with_name(f"{self.path.name}.{i}")
                if src.exists():
                    src.rename(dst)
            self.path.touch(exist_ok=True)
            self._state_cache = None

    @contextmanager
    def _exclusive_file_lock(self):
        """Serialize independent process writers before reading chain state.

        ``threading.RLock`` only protects one ``ImmutableStream`` instance.  A
        stale second runtime can otherwise read the same predecessor and create
        two individually valid branches.  The sidecar carries no market data and
        exists only to coordinate the single-writer boundary across processes.
        """

        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def quarantine_corrupted_segment(self, *, suffix: str) -> Path:
        """Preserve an invalid segment byte-for-byte and start a fresh chain.

        This is intentionally explicit and is used only after a caller has
        observed a hash-chain failure.  It never edits or deletes the damaged
        evidence.  The new active file begins at ``GENESIS`` while the original
        inode is retained under a visible quarantine suffix.
        """

        safe_suffix = "".join(char for char in str(suffix) if char.isalnum() or char in "-_")
        if not safe_suffix:
            raise ValueError("immutable stream quarantine suffix is required")
        with self._lock:
            with self._exclusive_file_lock():
                # Do not roll a healthy stream because of a stale caller error.
                try:
                    self._scan_from(0, "GENESIS")
                except RuntimeError as error:
                    if "HASH_CHAIN_INVALID" not in str(error):
                        raise
                else:
                    raise RuntimeError("STRATEGY_LAB_IMMUTABLE_STREAM_QUARANTINE_NOT_REQUIRED")

                quarantine_path = self.path.with_name(f"{self.path.name}.quarantined-{safe_suffix}")
                if quarantine_path.exists():
                    raise RuntimeError("STRATEGY_LAB_IMMUTABLE_STREAM_QUARANTINE_COLLISION")
                self._discard_checkpoint()
                os.replace(self.path, quarantine_path)
                self.path.touch(exist_ok=False)
                directory_descriptor = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
                self._state_cache = None
                return quarantine_path

    def _connection(self) -> sqlite3.Connection:
        if self._checkpoint is None:
            connection = sqlite3.connect(
                self.checkpoint_path,
                timeout=5.0,
                check_same_thread=False,
            )
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS idempotency_index (
                        idempotency_key TEXT PRIMARY KEY,
                        byte_offset INTEGER NOT NULL,
                        byte_length INTEGER NOT NULL,
                        record_hash TEXT NOT NULL
                    )"""
                )
                connection.commit()
            except BaseException:
                connection.close()
                raise
            self._checkpoint = connection
        self._touch_checkpoint_connection()
        return self._checkpoint

    @classmethod
    def _registry(cls) -> OrderedDict[int, weakref.ReferenceType["ImmutableStream"]]:
        """Return the process-local connection registry.

        A multiprocessing fork inherits class memory. The registry is only an
        ownership index, so a child starts a new index instead of attempting to
        manage the parent's entries.
        """

        pid = os.getpid()
        if cls._checkpoint_registry_pid != pid:
            cls._checkpoint_registry_pid = pid
            cls._checkpoint_registry = OrderedDict()
        return cls._checkpoint_registry

    def _touch_checkpoint_connection(self) -> None:
        victims: list[ImmutableStream] = []
        identity = id(self)
        with self._checkpoint_registry_lock:
            registry = self._registry()
            for key, reference in tuple(registry.items()):
                if reference() is None:
                    registry.pop(key, None)
            registry.pop(identity, None)
            registry[identity] = weakref.ref(self)
            while len(registry) > self.CHECKPOINT_CONNECTION_CACHE_LIMIT:
                _, reference = registry.popitem(last=False)
                victim = reference()
                if victim is not None and victim is not self:
                    victims.append(victim)

        # Never wait for a different stream while holding this stream's lock:
        # concurrent appenders may touch the registry in the opposite order.
        for victim in victims:
            if not victim._lock.acquire(blocking=False):
                with self._checkpoint_registry_lock:
                    registry = self._registry()
                    if victim._checkpoint is not None:
                        registry[id(victim)] = weakref.ref(victim)
                continue
            try:
                victim._close_checkpoint_connection(unregister=False)
            finally:
                victim._lock.release()

    def _close_checkpoint_connection(self, *, unregister: bool = True) -> None:
        connection = self._checkpoint
        self._checkpoint = None
        if unregister:
            with self._checkpoint_registry_lock:
                registry = self._registry()
                reference = registry.get(id(self))
                if reference is None or reference() is self:
                    registry.pop(id(self), None)
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        """Release this stream's cached checkpoint handle deterministically."""

        with self._lock:
            self._close_checkpoint_connection()

    def _discard_checkpoint(self) -> None:
        self._close_checkpoint_connection()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(f"{self.checkpoint_path}{suffix}").unlink()
            except FileNotFoundError:
                pass

    def _stream_identity(self) -> str:
        return hashlib.sha256(str(self.path.resolve()).encode("utf-8")).hexdigest()

    @staticmethod
    def _record_is_valid(row: Mapping[str, Any], previous_hash: str) -> bool:
        body = {
            "event_type": row.get("event_type"),
            "recorded_at": row.get("recorded_at"),
            "payload": row.get("payload"),
            "idempotency_key": row.get("idempotency_key"),
            "previous_hash": row.get("previous_hash"),
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return row.get("previous_hash") == previous_hash and row.get("record_hash") == expected

    def _scan_from(
        self,
        byte_offset: int,
        previous_hash: str,
    ) -> tuple[int, str, list[tuple[str, int, int, str]]]:
        entries: list[tuple[str, int, int, str]] = []
        offset = byte_offset
        with self.path.open("rb") as handle:
            handle.seek(byte_offset)
            for line_num, line in enumerate(handle, start=1):
                if not line.strip():
                    offset += len(line)
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        f"STRATEGY_LAB_IMMUTABLE_STREAM_CORRUPTED: tail line {line_num}"
                    ) from error
                if not self._record_is_valid(row, previous_hash):
                    raise RuntimeError("STRATEGY_LAB_IMMUTABLE_STREAM_HASH_CHAIN_INVALID")
                record_hash = str(row["record_hash"])
                key = row.get("idempotency_key")
                if key is not None:
                    entries.append((str(key), offset, len(line), record_hash))
                previous_hash = record_hash
                offset += len(line)
        return offset, previous_hash, entries

    def _boundary_is_valid(self, byte_offset: int, last_hash: str) -> bool:
        if byte_offset == 0:
            return last_hash == "GENESIS"
        if byte_offset > self.path.stat().st_size:
            return False
        with self.path.open("rb") as handle:
            handle.seek(byte_offset - 1)
            if handle.read(1) != b"\n":
                return False
            end = byte_offset - 1
            cursor = end
            while cursor > 0:
                start = max(0, cursor - 64 * 1024)
                handle.seek(start)
                chunk = handle.read(cursor - start)
                newline = chunk.rfind(b"\n")
                if newline >= 0:
                    cursor = start + newline + 1
                    break
                cursor = start
            handle.seek(cursor)
            try:
                row = json.loads(handle.read(byte_offset - cursor))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
        return (
            row.get("record_hash") == last_hash
            and self._record_is_valid(row, str(row.get("previous_hash") or ""))
        )

    def _save_checkpoint(
        self,
        *,
        byte_offset: int,
        previous_hash: str,
        entries: Iterable[tuple[str, int, int, str]],
        replace_index: bool = False,
    ) -> None:
        stat = self.path.stat()
        metadata = {
            "version": str(self.CHECKPOINT_VERSION),
            "stream_identity": self._stream_identity(),
            "inode": str(stat.st_ino),
            "mtime_ns": str(stat.st_mtime_ns),
            "byte_offset": str(byte_offset),
            "previous_hash": previous_hash,
        }
        connection = self._connection()
        with connection:
            if replace_index:
                connection.execute("DELETE FROM idempotency_index")
            connection.executemany(
                """INSERT OR REPLACE INTO idempotency_index
                   (idempotency_key, byte_offset, byte_length, record_hash)
                   VALUES (?, ?, ?, ?)""",
                entries,
            )
            connection.executemany(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                metadata.items(),
            )

    def _full_rebuild(self, *, mode: str) -> Dict[str, Any]:
        offset, previous_hash, entries = self._scan_from(0, "GENESIS")
        self._save_checkpoint(
            byte_offset=offset,
            previous_hash=previous_hash,
            entries=entries,
            replace_index=True,
        )
        self._resume_mode = mode
        self._resume_scanned_bytes = offset
        return {
            "signature": self._file_signature(),
            "previous_hash": previous_hash,
            "byte_offset": offset,
        }

    def _file_signature(self) -> tuple[int, int, int]:
        stat = self.path.stat()
        return stat.st_ino, stat.st_mtime_ns, stat.st_size

    def _bootstrap(self) -> Dict[str, Any]:
        started = perf_counter()
        try:
            connection = self._connection()
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            stat = self.path.stat()
            valid_identity = (
                metadata.get("version") == str(self.CHECKPOINT_VERSION)
                and metadata.get("stream_identity") == self._stream_identity()
                and metadata.get("inode") == str(stat.st_ino)
            )
            byte_offset = int(metadata.get("byte_offset", "-1"))
            previous_hash = metadata.get("previous_hash", "")
            exact_checkpoint_mtime = metadata.get("mtime_ns") == str(stat.st_mtime_ns)
            if (
                valid_identity
                and 0 <= byte_offset <= stat.st_size
                and (byte_offset < stat.st_size or exact_checkpoint_mtime)
                and self._boundary_is_valid(byte_offset, previous_hash)
            ):
                if byte_offset == stat.st_size:
                    self._resume_mode = "CHECKPOINT"
                    self._resume_scanned_bytes = 0
                    return {
                        "signature": self._file_signature(),
                        "previous_hash": previous_hash,
                        "byte_offset": byte_offset,
                    }
                if byte_offset < stat.st_size:
                    end, last_hash, entries = self._scan_from(byte_offset, previous_hash)
                    self._save_checkpoint(
                        byte_offset=end,
                        previous_hash=last_hash,
                        entries=entries,
                    )
                    self._resume_mode = "TAIL_RECOVERY"
                    self._resume_scanned_bytes = end - byte_offset
                    return {
                        "signature": self._file_signature(),
                        "previous_hash": last_hash,
                        "byte_offset": end,
                    }
            self._discard_checkpoint()
            return self._full_rebuild(mode="FULL_REBUILD")
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self._discard_checkpoint()
            return self._full_rebuild(mode="SAFE_FALLBACK_REBUILD")
        finally:
            self._resume_ms = (perf_counter() - started) * 1000.0

    def _get_state(self) -> Dict[str, Any]:
        current_sig = self._file_signature()
        if self._state_cache is None or self._state_cache["signature"] != current_sig:
            self._state_cache = self._bootstrap()
        return self._state_cache

    def _indexed_rows(self, keys: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        unique = tuple(dict.fromkeys(str(key) for key in keys if key))
        if not unique:
            return {}
        connection = self._connection()
        found: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(unique), 400):
            part = unique[start : start + 400]
            placeholders = ",".join("?" for _ in part)
            query = (
                "SELECT idempotency_key, byte_offset, byte_length, record_hash "
                f"FROM idempotency_index WHERE idempotency_key IN ({placeholders})"
            )
            for key, offset, length, record_hash in connection.execute(query, part):
                with self.path.open("rb") as handle:
                    handle.seek(int(offset))
                    encoded = handle.read(int(length))
                try:
                    row = json.loads(encoded)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise RuntimeError("STRATEGY_LAB_CHECKPOINT_INDEX_INVALID") from error
                if row.get("idempotency_key") != key or row.get("record_hash") != record_hash:
                    raise RuntimeError("STRATEGY_LAB_CHECKPOINT_INDEX_INVALID")
                found[str(key)] = row
        return found

    def resume_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mode": self._resume_mode,
                "latency_ms": round(self._resume_ms, 3),
                "scanned_bytes": self._resume_scanned_bytes,
                "checkpoint_path": str(self.checkpoint_path),
            }

    def append_metrics(self) -> Dict[str, Any]:
        """Return the last durable append boundary measured inside the stream."""
        with self._lock:
            return dict(self._last_append_metrics)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self.append_batch(
            ((event_type, payload, recorded_at, idempotency_key),),
            return_rows=True,
        )
        return rows[0]

    def append_batch(
        self,
        records: Iterable[tuple[str, Mapping[str, Any], Optional[str], Optional[str]]],
        *,
        return_rows: bool = True,
    ) -> List[Dict[str, Any]]:
        """Append an ordered batch with one durable flush/fsync boundary.

        Hash-chain and idempotency semantics are identical to ``append``.  The
        method exists for high-rate evidence recorders so packet ingestion is
        not serialized behind one fsync per packet.
        """

        items = list(records)
        if not items:
            return []
        with self._lock:
            with self._exclusive_file_lock():
                return self._append_batch_locked(items, return_rows=return_rows)

    def _append_batch_locked(
        self,
        items: list[tuple[str, Mapping[str, Any], Optional[str], Optional[str]]],
        *,
        return_rows: bool,
    ) -> List[Dict[str, Any]]:
            self._rotate_if_needed()
            state = self._get_state()
            previous_hash = state["previous_hash"]
            rows: List[Dict[str, Any]] = []
            new_rows: List[Dict[str, Any]] = []
            pending_rows: Dict[str, Dict[str, Any]] = {}
            existing_rows = self._indexed_rows(
                key for _, _, _, key in items if key is not None
            )
            for event_type, payload, recorded_at, idempotency_key in items:
                if idempotency_key:
                    existing = pending_rows.get(idempotency_key)
                    if existing is None:
                        existing = existing_rows.get(idempotency_key)
                    if existing is not None:
                        if return_rows:
                            rows.append(deepcopy(existing))
                        continue
                timestamp = recorded_at or datetime.now(timezone.utc).isoformat()
                body = {
                    "event_type": str(event_type),
                    "recorded_at": timestamp,
                    "payload": _safe(payload),
                    "idempotency_key": idempotency_key,
                    "previous_hash": previous_hash,
                }
                canonical = json.dumps(
                    body, sort_keys=True, separators=(",", ":"), default=str
                )
                record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                row = {
                    "record_id": f"lab_{record_hash[:24]}",
                    **body,
                    "record_hash": record_hash,
                }
                if return_rows:
                    rows.append(row)
                new_rows.append(row)
                previous_hash = record_hash
                if idempotency_key:
                    pending_rows[idempotency_key] = row
            if new_rows:
                start_offset = self.path.stat().st_size
                serialization_started = perf_counter_ns()
                encoded_rows = [
                    (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                    for row in new_rows
                ]
                serialization_done = perf_counter_ns()
                write_started = serialization_done
                with self.path.open("ab") as handle:
                    handle.writelines(encoded_rows)
                    handle.flush()
                    os.fsync(handle.fileno())
                durable_done = perf_counter_ns()
                self._last_append_metrics = {
                    "batch_size": len(new_rows),
                    "serialization_ms": round((serialization_done - serialization_started) / 1_000_000.0, 6),
                    "write_ms": round((durable_done - write_started) / 1_000_000.0, 6),
                    "fsync_count": 1,
                    "durable_complete_ns": durable_done,
                }
                offset = start_offset
                index_entries: list[tuple[str, int, int, str]] = []
                for row, encoded in zip(new_rows, encoded_rows):
                    key = row.get("idempotency_key")
                    if key:
                        index_entries.append(
                            (str(key), offset, len(encoded), str(row["record_hash"]))
                        )
                    offset += len(encoded)
                try:
                    self._save_checkpoint(
                        byte_offset=offset,
                        previous_hash=previous_hash,
                        entries=index_entries,
                    )
                except Exception:
                    self._state_cache = None
                    raise
                state["signature"] = self._file_signature()
                state["previous_hash"] = previous_hash
                state["byte_offset"] = offset
            return deepcopy(rows) if return_rows else []

    def read(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            rows = []
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            rows.append(json.loads(line))
            except (OSError, ValueError, json.JSONDecodeError):
                raise RuntimeError("STRATEGY_LAB_IMMUTABLE_STREAM_UNAVAILABLE")
            return rows[-limit:] if limit else rows

    def verify(self) -> Dict[str, Any]:
        previous_hash = "GENESIS"
        rows = self.read()
        for index, row in enumerate(rows):
            body = {
                "event_type": row.get("event_type"),
                "recorded_at": row.get("recorded_at"),
                "payload": row.get("payload"),
                "idempotency_key": row.get("idempotency_key"),
                "previous_hash": row.get("previous_hash"),
            }
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if row.get("previous_hash") != previous_hash or row.get("record_hash") != expected:
                return {"valid": False, "records": len(rows), "failure_index": index}
            previous_hash = expected
        return {"valid": True, "records": len(rows), "failure_index": None}


class StrategyWorkspace:
    """One strategy owns every path exposed here; no path is shared."""

    FILES = {
        "metadata": "metadata.json",
        "runtime": "runtime.json",
        "scheduler_state": "scheduler_state.json",
        "strategy_state": "strategy_state.json",
        "evaluation_checkpoint": "evaluation_checkpoint.json",
        "readiness_state": "readiness_state.json",
        "paper_state": "paper_state.json",
        "paper_engine_state": "paper_engine_state.json",
        "risk_state": "risk_state.json",
        "statistics": "statistics.json",
        "order_ledger": "order_ledger.jsonl",
        "fill_ledger": "fill_ledger.jsonl",
        "transactions": "paper_transactions.jsonl",
        "journal": "journal.jsonl",
        "replay": "replay.jsonl",
        "evidence": "evidence.jsonl",
        "logs": "logs.jsonl",
    }

    def __init__(self, root: Path, strategy_id: str):
        self.strategy_id = strategy_id
        self.root = Path(root).resolve() / strategy_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {name: self.root / relative for name, relative in self.FILES.items()}
        self._lock = threading.RLock()
        self._field_cache: Dict[
            tuple[str, tuple[str, ...]],
            tuple[tuple[int, int, int], Dict[str, Any]],
        ] = {}
        self.order_ledger = ImmutableStream(self.paths["order_ledger"])
        self.fill_ledger = ImmutableStream(self.paths["fill_ledger"])
        self.transactions = ImmutableStream(self.paths["transactions"])
        self.journal = ImmutableStream(self.paths["journal"])
        self.replay = ImmutableStream(self.paths["replay"])
        self.evidence = ImmutableStream(self.paths["evidence"])
        self.logs = ImmutableStream(self.paths["logs"])
        self._initialize()

    def _initialize(self) -> None:
        defaults = {
            "runtime": {"state": "STOPPED", "health": "HEALTHY", "readiness": "READY", "updated_at": None},
            "scheduler_state": {"state": "STOPPED", "last_tick_at": None, "tick_count": 0, "skipped_count": 0},
            "strategy_state": {
                "current_decision": None,
                "last_evaluated_at": None,
                "last_processed_candle_id": None,
                "processed_candles": {},
                "adapter_state": None,
                "evaluation_cursor": None,
                "evaluation_interruption": None,
            },
            "evaluation_checkpoint": {
                "deployment_id": self.strategy_id,
                "cursor": None,
                "processed_candles": {},
                "interruption": None,
                "historical_audit_backlog": None,
                "updated_at": None,
            },
            "readiness_state": {"DATA_READY": False, "not_ready_reason": "HISTORY_LOADING", "updated_at": None},
            "paper_state": {"open_position": None, "open_positions": [], "closed_trades": [], "realized_pnl": 0.0, "unrealized_pnl": 0.0},
            "paper_engine_state": {},
            "risk_state": {"paper_only": True, "live_trading_enabled": False, "broker_submission": False, "last_decision": None},
            "statistics": {"completed_trades": 0, "updated_at": None},
        }
        for name, value in defaults.items():
            if not self.paths[name].exists():
                _atomic_write(self.paths[name], value)

    def write(self, name: str, value: Mapping[str, Any]) -> None:
        if name not in self.paths or name in {"order_ledger", "fill_ledger", "journal", "replay", "evidence", "logs"}:
            raise KeyError(name)
        with self._lock:
            _atomic_write(self.paths[name], value)
            signature = self._file_signature(self.paths[name])
            for cache_key in [key for key in self._field_cache if key[0] == name]:
                fields = cache_key[1]
                self._field_cache[cache_key] = (
                    signature,
                    {field: deepcopy(value.get(field)) for field in fields},
                )

    def read(self, name: str) -> Dict[str, Any]:
        if name not in self.paths:
            raise KeyError(name)
        with self._lock:
            value = _read_json(self.paths[name], {})
            if not isinstance(value, dict):
                raise RuntimeError("STRATEGY_LAB_DOCUMENT_INVALID")
            return value

    def read_fields(self, name: str, fields: Iterable[str]) -> Dict[str, Any]:
        if name not in self.paths:
            raise KeyError(name)
        selected = tuple(fields)
        cache_key = (name, selected)
        with self._lock:
            signature = self._file_signature(self.paths[name])
            cached = self._field_cache.get(cache_key)
            if cached is not None and cached[0] == signature:
                return deepcopy(cached[1])
            value = _read_json(self.paths[name], {})
            if not isinstance(value, dict):
                raise RuntimeError("STRATEGY_LAB_DOCUMENT_INVALID")
            projection = {field: value.get(field) for field in selected}
            self._field_cache[cache_key] = (signature, deepcopy(projection))
            return projection

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int, int]:
        stat = path.stat()
        return stat.st_ino, stat.st_mtime_ns, stat.st_size

    def record_completed_trade(self, trade: Mapping[str, Any]) -> Dict[str, Any]:
        payload = dict(_safe(trade))
        payload["status"] = "CLOSED"
        if payload.get("realized_pnl") is None:
            raise ValueError("completed trade requires realized_pnl")
        row = self.journal.append(
            "TRADE_CLOSED",
            payload,
            idempotency_key=str(payload.get("trade_id") or payload.get("replay_id") or ""),
        )
        paper = self.read("paper_state")
        closed = list(paper.get("closed_trades") or [])
        if not any(item.get("record_id") == row["record_id"] for item in closed):
            closed.append({"record_id": row["record_id"], **payload})
            paper["closed_trades"] = closed
            paper["realized_pnl"] = round(sum(float(item["realized_pnl"]) for item in closed), 8)
            self.write("paper_state", paper)
        return row

    def integrity(self) -> Dict[str, Any]:
        streams = {
            name: getattr(self, name).verify()
            for name in ("order_ledger", "fill_ledger", "transactions", "journal", "replay", "evidence", "logs")
        }
        return {
            "valid": all(item["valid"] for item in streams.values()),
            "streams": streams,
            "workspace": str(self.root),
        }


class StrategyRegistryStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.json"
        self._lock = threading.RLock()
        self._cache: Optional[tuple[tuple[int, int, int], Dict[str, Any]]] = None
        if not self.path.exists():
            _atomic_write(self.path, {"schema_version": 1, "deployments": []})

    def load(self) -> Dict[str, Any]:
        with self._lock:
            stat = self.path.stat()
            signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if self._cache is not None and self._cache[0] == signature:
                return deepcopy(self._cache[1])
            value = _read_json(self.path, {"schema_version": 1, "deployments": []})
            if not isinstance(value, dict) or not isinstance(value.get("deployments"), list):
                raise RuntimeError("STRATEGY_LAB_REGISTRY_INVALID")
            self._cache = (signature, deepcopy(value))
            return deepcopy(value)

    def register(self, metadata: Mapping[str, Any]) -> Dict[str, Any]:
        with self._lock:
            document = self.load()
            rows = list(document["deployments"])
            existing = next((row for row in rows if row.get("strategy_id") == metadata.get("strategy_id")), None)
            safe_metadata = dict(_safe(metadata))
            if existing is not None and existing != safe_metadata:
                raise ValueError("strategy deployment identity conflict")
            if existing is None:
                rows.append(safe_metadata)
                document["deployments"] = rows
                _atomic_write(self.path, document)
                stat = self.path.stat()
                self._cache = (
                    (stat.st_ino, stat.st_mtime_ns, stat.st_size),
                    deepcopy(document),
                )
            return safe_metadata
