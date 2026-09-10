"""Model-Independent Local Reasoning Adapter Interface and Ollama Implementation.

Provides a unified interface for local open-weights LLMs:
- LocalModelAdapter (Abstract Base Class)
- OllamaQwenAdapter (Concrete Ollama HTTP Implementation for Qwen 3.5 9B)
- Extensible for future MLXLMAdapter without modifying Brain architecture.

Strictly adheres to:
- ONE loaded model maximum.
- ONE inference maximum at a time (protected by re-entrant mutex).
- Compact context (e.g. num_ctx=4096, NOT 256k).
- Full telemetry: TTFT, eval_count, prompt_eval_count, durations, schema_status.
- ZERO trading logic inside adapter.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.request
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class LocalModelAdapter(ABC):
    """Abstract base class for local LLM inference engines."""

    def __init__(self, model_identifier: str) -> None:
        self.model_identifier = model_identifier
        self._inference_lock = threading.Lock()

    @abstractmethod
    def invoke_reasoning(
        self,
        request_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        context_window: int = 4096,
        timeout_seconds: float = 60.0,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Invoke local reasoning engine.

        Returns: (parsed_json_output, telemetry_dict)
        """
        pass

    @abstractmethod
    def unload_model(self) -> bool:
        """Explicitly release model from VRAM/RAM to relieve memory pressure."""
        pass


class OllamaQwenAdapter(LocalModelAdapter):
    """Concrete adapter connecting to local Ollama instance for Qwen 3.5 9B."""

    def __init__(
        self,
        model_name: str = "qwen3.5:9b",
        ollama_host: str = "http://127.0.0.1:11434",
    ) -> None:
        super().__init__(model_identifier=model_name)
        self.ollama_host = os.getenv("OLLAMA_HOST_HTTP", ollama_host).rstrip("/")
        self.model_name = model_name

    def unload_model(self) -> bool:
        """Immediately unloads model from memory via keep_alive: 0."""
        try:
            url = f"{self.ollama_host}/api/generate"
            payload = {
                "model": self.model_name,
                "keep_alive": 0,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.debug("Failed unloading Ollama model: %s", exc)
            return False

    def invoke_reasoning(
        self,
        request_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        context_window: int = 4096,
        timeout_seconds: float = 60.0,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        started_at = datetime.now(timezone.utc).isoformat()
        t_start = time.perf_counter()

        telemetry: Dict[str, Any] = {
            "model": self.model_name,
            "request_id": request_id,
            "started_at": started_at,
            "ended_at": None,
            "prompt_eval_count": 0,
            "eval_count": 0,
            "prompt_eval_duration_ms": 0.0,
            "eval_duration_ms": 0.0,
            "total_duration_ms": 0.0,
            "load_duration_ms": 0.0,
            "ttft_ms": 0.0,
            "tokens_per_second": 0.0,
            "thinking_mode": "structured_synthesis",
            "schema_status": "PENDING",
            "error": None,
        }

        # Enforce ONE inference maximum at a time
        acquired = self._inference_lock.acquire(blocking=False)
        if not acquired:
            telemetry["schema_status"] = "INFERENCE_CONCURRENCY_LOCKED"
            telemetry["error"] = "Another inference is currently active. Dropping concurrent request."
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry

        try:
            url = f"{self.ollama_host}/api/generate"
            # Strict JSON structured generation
            request_body: Dict[str, Any] = {
                "model": self.model_name,
                "prompt": user_prompt,
                "system": system_prompt,
                "stream": False,
                "format": "json" if schema is not None else "",
                "options": {
                    "num_ctx": context_window,
                    "temperature": 0.1,  # Low temperature for factual consistency
                    "num_predict": 900,
                },
                "keep_alive": "5m",
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(request_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                raw_bytes = resp.read()
                raw_json = json.loads(raw_bytes.decode("utf-8"))

            t_end = time.perf_counter()
            ended_at = datetime.now(timezone.utc).isoformat()
            total_duration_ms = (t_end - t_start) * 1000.0

            prompt_eval_count = raw_json.get("prompt_eval_count", 0)
            eval_count = raw_json.get("eval_count", 0)
            prompt_eval_dur_ns = raw_json.get("prompt_eval_duration", 0)
            eval_dur_ns = raw_json.get("eval_duration", 0)
            load_dur_ns = raw_json.get("load_duration", 0)

            eval_dur_s = eval_dur_ns / 1e9
            tokens_per_sec = (eval_count / eval_dur_s) if eval_dur_s > 0 else 0.0

            telemetry.update({
                "ended_at": ended_at,
                "prompt_eval_count": prompt_eval_count,
                "eval_count": eval_count,
                "prompt_eval_duration_ms": prompt_eval_dur_ns / 1e6,
                "eval_duration_ms": eval_dur_ns / 1e6,
                "load_duration_ms": load_dur_ns / 1e6,
                "total_duration_ms": total_duration_ms,
                "ttft_ms": (load_dur_ns + prompt_eval_dur_ns) / 1e6,
                "tokens_per_second": round(tokens_per_sec, 2),
            })

            response_text = raw_json.get("response", "").strip()
            thinking_text = raw_json.get("thinking", "").strip()
            if thinking_text:
                telemetry["thinking_length"] = len(thinking_text)

            # In Ollama with thinking models, structured output can appear in response or thinking
            source_text = response_text if response_text else thinking_text
            if not source_text:
                telemetry["schema_status"] = "EMPTY_MODEL_RESPONSE"
                return None, telemetry

            # Parse and validate JSON (robust to markdown fences ```json ... ```)
            clean_text = source_text
            if "```" in clean_text:
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(1).strip()
                else:
                    match_any = re.search(r"(\{.*\})", clean_text, re.DOTALL)
                    if match_any:
                        clean_text = match_any.group(1).strip()
            elif not clean_text.startswith("{") and "{" in clean_text:
                match = re.search(r"(\{.*\})", clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(1).strip()

            try:
                parsed_output = json.loads(clean_text)
                telemetry["schema_status"] = "SCHEMA_VALID_JSON"
                return parsed_output, telemetry
            except json.JSONDecodeError as err:
                telemetry["schema_status"] = "INVALID_JSON"
                telemetry["error"] = f"JSON decode error: {err}"
                return None, telemetry

        except Exception as exc:
            telemetry["schema_status"] = "TRANSPORT_ERROR"
            telemetry["error"] = str(exc)
            telemetry["ended_at"] = datetime.now(timezone.utc).isoformat()
            return None, telemetry
        finally:
            self._inference_lock.release()
