"""Bounded persistent JSON-line model workers."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


class WorkerError(RuntimeError):
    pass


class LatestWinsQueue:
    """A single-slot queue that drops superseded work deterministically."""

    def __init__(self):
        self._condition = threading.Condition()
        self._pending: tuple[str, Any] | None = None
        self._closed = False
        self._last_key: str | None = None
        self.dropped = 0
        self.duplicates = 0

    def submit(self, key: str, value: Any) -> bool:
        with self._condition:
            if key == self._last_key or self._pending and self._pending[0] == key:
                self.duplicates += 1
                return False
            if self._pending is not None:
                self.dropped += 1
            self._pending = (key, deepcopy(value))
            self._condition.notify()
            return True

    def get(self, timeout: float | None = None) -> tuple[str, Any] | None:
        with self._condition:
            if self._pending is None and not self._closed:
                self._condition.wait(timeout)
            if self._pending is None:
                return None
            item, self._pending = self._pending, None
            self._last_key = item[0]
            return item

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    @property
    def depth(self) -> int:
        with self._condition:
            return int(self._pending is not None)


class PersistentJsonWorker:
    """One lazy subprocess; one model load; sequential bounded requests."""

    PREFIX = "CITADEL_RESULT\t"

    def __init__(self, command: list[str], *, cwd: Path, environment: dict[str, str] | None = None, timeout_seconds: float = 120.0):
        self.command = command
        self.cwd = cwd
        self.environment = environment or {}
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self.model_load_count = 0
        self.inference_latencies: list[float] = []
        self.failures = 0
        self.rss_mb: float | None = None

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            assert self._process and self._process.stdin and self._process.stdout
            started = time.perf_counter()
            try:
                self._process.stdin.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
                self._process.stdin.flush()
                deadline = time.monotonic() + self.timeout_seconds
                result: dict[str, Any] | None = None
                while time.monotonic() < deadline:
                    try:
                        line = self._lines.get(timeout=min(.5, max(0.0, deadline - time.monotonic())))
                    except queue.Empty:
                        if self._process.poll() is not None:
                            raise WorkerError(f"MODEL_WORKER_EXITED:{self._process.returncode}")
                        continue
                    if line is None:
                        raise WorkerError(f"MODEL_WORKER_EXITED:{self._process.returncode}")
                    if line.startswith(self.PREFIX):
                        result = json.loads(line[len(self.PREFIX):])
                        break
                if result is None:
                    raise WorkerError("MODEL_WORKER_TIMEOUT")
                if result.get("status") == "ERROR":
                    raise WorkerError(str(result.get("reason") or "MODEL_WORKER_FAILED"))
                self.inference_latencies.append((time.perf_counter() - started) * 1000)
                self.inference_latencies = self.inference_latencies[-200:]
                try:
                    rss_kb = int(subprocess.check_output(
                        ["ps", "-o", "rss=", "-p", str(self._process.pid)], text=True, timeout=1,
                    ).strip())
                    self.rss_mb = round(rss_kb / 1024, 1)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                return result
            except Exception:
                self.failures += 1
                raise

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            if process is None:
                return
            try:
                if process.stdin:
                    process.stdin.write('{"command":"STOP"}\n')
                    process.stdin.flush()
                process.wait(timeout=3)
            except Exception:
                process.terminate()

    def status(self) -> dict[str, Any]:
        process = self._process
        return {
            "pid": process.pid if process and process.poll() is None else None,
            "model_load_count": self.model_load_count,
            "failure_count": self.failures,
            "latency_samples": len(self.inference_latencies),
            "rss_mb": self.rss_mb,
        }

    def _ensure_started(self) -> None:
        if self._process and self._process.poll() is None:
            return
        environment = {**os.environ, **self.environment}
        self._process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._lines = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True)
        self._reader.start()
        self.model_load_count += 1

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout
        for line in process.stdout:
            self._lines.put(line)
        self._lines.put(None)


def function_worker(callback: Callable[[dict[str, Any]], dict[str, Any]]):
    class FunctionWorker:
        model_load_count = 1
        failures = 0

        def request(self, payload):
            return callback(deepcopy(payload))

        def stop(self):
            return None

        def status(self):
            return {"pid": None, "model_load_count": 1, "failure_count": self.failures, "latency_samples": 0}

    return FunctionWorker()
