"""One-shot run ownership, immutable finalization, and canonical journal taps."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def create_run_directory(root: Path, *, prefix: str, run_id: str | None = None) -> tuple[str, Path]:
    identity = run_id or f"{prefix}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S.%fZ}_{uuid.uuid4().hex[:8]}"
    output = root / identity
    output.mkdir(parents=True, exist_ok=False)
    return identity, output


def write_once(path: Path, value: Mapping[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x"
    with path.open(mode, encoding="utf-8") as handle:
        if isinstance(value, str):
            handle.write(value)
        else:
            json.dump(dict(value), handle, indent=2, sort_keys=True)
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def finalize_run(
    output: Path, *, run_id: str, started_at: str, ended_at: str,
    pid: int, exit_code: int, browser_evidence: Path | None = None,
) -> dict[str, Any]:
    if (output / "MANIFEST.json").exists():
        raise FileExistsError("FINALIZED_RUN_DIRECTORY_IMMUTABLE")
    finalized_at = datetime.now(timezone.utc).isoformat()
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            files.append({
                "path": str(path.relative_to(output)), "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
    manifest = {
        "schema_version": 2, "run_id": run_id, "start": started_at, "end": ended_at,
        "pid": pid, "exit_code": exit_code, "finalized_at": finalized_at,
        "browser_evidence": str(browser_evidence) if browser_evidence else None,
        "files": files,
    }
    write_once(output / "MANIFEST.json", manifest)
    return manifest


def launch_one_shot(command: Sequence[str], *, cwd: Path, stdout: Path) -> subprocess.Popen[str]:
    """Launch exactly once without launchd's inferred keepalive semantics."""
    stdout.parent.mkdir(parents=True, exist_ok=True)
    handle = stdout.open("x", encoding="utf-8")
    try:
        return subprocess.Popen(
            list(command), cwd=cwd, stdout=handle, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
    finally:
        handle.close()


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    role: str
    pid: int
    cwd: str
    command: str
    port: int | None


def listener_pid(port: int) -> int | None:
    try:
        rows = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], text=True,
        ).splitlines()
        return int(rows[0]) if rows else None
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def resolve_process(role: str, *, port: int | None = None, pid: int | None = None) -> ProcessIdentity:
    resolved = pid if pid is not None else listener_pid(int(port)) if port is not None else None
    if resolved is None:
        raise RuntimeError(f"{role.upper()}_PID_NOT_FOUND")
    command = subprocess.check_output(["ps", "-p", str(resolved), "-o", "command="], text=True).strip()
    cwd_rows = subprocess.check_output(["lsof", "-a", "-p", str(resolved), "-d", "cwd", "-Fn"], text=True).splitlines()
    cwd = next((row[1:] for row in cwd_rows if row.startswith("n")), "")
    if not command or not cwd:
        raise RuntimeError(f"{role.upper()}_IDENTITY_UNVERIFIED")
    return ProcessIdentity(role, resolved, cwd, command, port)


class DynamicProcessMonitor:
    def __init__(
        self, resolvers: Mapping[str, Callable[[], ProcessIdentity]], *,
        expected_pid_changes: set[str] | None = None,
    ) -> None:
        self.resolvers = dict(resolvers)
        self.expected_pid_changes = set(expected_pid_changes or ())
        self.current: dict[str, ProcessIdentity] = {}
        self.transitions: list[dict[str, Any]] = []

    def sample(self) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        result: dict[str, Any] = {"timestamp": timestamp, "processes": {}}
        for role, resolver in self.resolvers.items():
            try:
                identity = resolver()
                prior = self.current.get(role)
                if prior and prior.pid != identity.pid:
                    self.transitions.append({
                        "timestamp": timestamp, "role": role, "old_pid": prior.pid,
                        "new_pid": identity.pid,
                        "classification": (
                            "EXPECTED_PID_CHANGE" if role in self.expected_pid_changes
                            else "UNEXPECTED_PID_CHANGE"
                        ),
                    })
                self.current[role] = identity
                result["processes"][role] = asdict(identity)
            except Exception as error:
                prior = self.current.get(role)
                result["processes"][role] = {
                    "pid": prior.pid if prior else None,
                    "status": "DEAD_OR_UNRESOLVED", "error": f"{type(error).__name__}:{error}",
                }
        result["transitions"] = list(self.transitions)
        return result


class RotatingJsonlFollower:
    """Follow the canonical file identity across rename-based rotation."""

    def __init__(self, path: Path, *, required_projection_fields: bool = False) -> None:
        self.path = path
        self.required_projection_fields = required_projection_fields
        self.rows: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.attached_at_ns: int | None = None
        self.first_row_at_ns: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handle: Any = None
        self._inode: int | None = None

    def start(self, *, from_end: bool = True) -> None:
        self._attach(from_end=from_end)
        self.attached_at_ns = time.perf_counter_ns()
        self._thread = threading.Thread(target=self._run, name="canonical-projection-follower", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._drain()
        if self._handle:
            self._handle.close()

    def _attach(self, *, from_end: bool) -> None:
        self._handle = self.path.open("rb")
        self._inode = os.fstat(self._handle.fileno()).st_ino
        if from_end:
            self._handle.seek(0, os.SEEK_END)

    def _run(self) -> None:
        while not self._stop.wait(0.02):
            self._drain()
            try:
                inode = self.path.stat().st_ino
            except FileNotFoundError:
                continue
            if inode != self._inode:
                self._drain()
                if self._handle:
                    self._handle.close()
                self._attach(from_end=False)

    def _drain(self) -> None:
        if not self._handle:
            return
        for raw in self._handle:
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.errors.append("INVALID_JSONL_ROW")
                continue
            if self.required_projection_fields:
                payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else row
                required = (row.get("recorded_at"),)
                if row.get("event_type") == "FLOW_PROJECTION":
                    required += (
                        payload.get("revision"), payload.get("generated_at"), payload.get("snapshot_id"),
                        payload.get("source_security_id")
                        or any(item.get("security_id") for item in payload.get("instruments") or () if isinstance(item, Mapping)),
                    )
                if any(value is None for value in required):
                    self.errors.append("PROJECTION_IDENTITY_INCOMPLETE")
                    continue
            if self.first_row_at_ns is None:
                self.first_row_at_ns = time.perf_counter_ns()
            self.rows.append(row)


HARD_GATE_KEYS = (
    "DHAN_WS_CONNECTED", "FUTURES_PACKETS_ADVANCING", "OPTION_PACKETS_ADVANCING",
    "BACKEND_HEALTHY", "FAST_LANE_HTTP_200", "FAST_LANE_REVISION_ADVANCING",
    "BROWSER_FAST_LANE_FETCH", "EVENTSOURCE_CONNECTED", "BROWSER_SSE_REVISION_ADVANCING",
    "ORACLE_DOM_POPULATED", "FUTURES_LTP_DOM_ADVANCING", "FLOW_PULSE_PRESENT", "CE_PE_HUD_PRESENT",
)


def evaluate_pre_soak_gate(evidence: Mapping[str, Any]) -> dict[str, Any]:
    failures = [key for key in HARD_GATE_KEYS if evidence.get(key) is not True]
    return {
        "schema_version": 1, "oracle_ready": not failures,
        "certified_clock_armed": not failures, "failures": failures,
    }
