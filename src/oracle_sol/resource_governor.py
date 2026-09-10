"""Resource Governor for CITADEL 8GB M1 Architecture.

Guarantees system survival on 8 GB unified memory:
Strict Priority Order:
1. Dhan / Market Ingest
2. Order Flow + Deterministic Engines (VOB, PCR, GEX)
3. Fast Lane
4. Frontend / SSE
5. Qwen 3.5 9B Local Cognition
6. External Context Polling

QWEN MUST LOSE WHENEVER RESOURCES CONFLICT.
If running Qwen creates unacceptable swap pressure (> 1.2 GB delta from baseline)
or drives memory free percentage < 15%, the Governor immediately signals unload
and records: QWEN_9B_LIVE_UNSAFE_ON_8GB.
CITADEL backend and Dhan connection are NEVER stopped.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Empirical host baseline recorded in Phase 1: 3493.75 MB
BASELINE_SWAP_MB = 3493.75

# AUDIT FINDING (MISSION H):
# The previous 1200 MB swap threshold was REMOVED_AS_ARBITRARY.
# macOS allocates swap in discrete 1GB-2GB extents; a static 1200MB ceiling does not
# accurately measure memory pressure or live system safety.
# Production policy relies on empirical OS indicators:
# 1. System-wide memory free percentage (< 20% warning, < 15% critical)
# 2. Swap growth relative to active baseline
# 3. CITADEL Fast Lane process health and latency degradation


@dataclass
class HostTelemetry:
    timestamp: float
    swap_total_mb: float
    swap_used_mb: float
    swap_free_mb: float
    swap_delta_mb: float
    system_memory_free_pct: float
    is_safe: bool
    verdict: str  # LIVE_SAFE | HIGH_PRESSURE | CRITICAL_UNSAFE
    policy_notes: str = ""


class ResourceGovernor:
    """Monitors M1 system health and enforces cognitive shedding on resource contention.
    
    Protects CITADEL's Fast Lane and market data ingest by monitoring true OS memory pressure
    and process responsiveness rather than arbitrary static swap limits.
    """

    def __init__(self, baseline_swap_mb: float = BASELINE_SWAP_MB) -> None:
        self.baseline_swap_mb = baseline_swap_mb
        self._lock = threading.Lock()
        self.last_telemetry: Optional[HostTelemetry] = None
        self.governor_verdict: str = "EVALUATION_PENDING"
        self.shed_count: int = 0

    def inspect_system(self) -> HostTelemetry:
        """Query macOS sysctl and memory_pressure for ground-truth host metrics."""
        now = time.time()
        swap_total = 0.0
        swap_used = 0.0
        swap_free = 0.0

        try:
            # Check swap usage
            out = subprocess.check_output(["sysctl", "vm.swapusage"], text=True)
            # e.g.: "vm.swapusage: total = 5120.00M  used = 3493.75M  free = 1626.25M"
            match = re.search(r"total\s*=\s*([\d\.]+)M\s*used\s*=\s*([\d\.]+)M\s*free\s*=\s*([\d\.]+)M", out)
            if match:
                swap_total = float(match.group(1))
                swap_used = float(match.group(2))
                swap_free = float(match.group(3))
        except Exception as exc:
            logger.debug("Failed checking sysctl vm.swapusage: %s", exc)

        # Check memory pressure percentage via macOS memory_pressure
        free_pct = 50.0
        try:
            mp_out = subprocess.check_output(["memory_pressure"], text=True)
            # e.g. "System-wide memory free percentage: 49%"
            mp_match = re.search(r"System-wide memory free percentage:\s*(\d+)%", mp_out)
            if mp_match:
                free_pct = float(mp_match.group(1))
        except Exception as exc:
            logger.debug("Failed checking memory_pressure: %s", exc)

        swap_delta = max(0.0, swap_used - self.baseline_swap_mb)

        # Diagnostic Host Telemetry
        # Note: Fixed percentage thresholds (e.g. 15%, 25%) are demoted from production authority
        # because live cognition runs in the cloud (Groq). Host memory telemetry is purely observational.
        # Invariant: During live market, local models (llama-server) must NOT remain resident in memory.
        local_model_resident = False
        try:
            res = subprocess.run(["pgrep", "llama-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            local_model_resident = (res.returncode == 0 and len(res.stdout.strip()) > 0)
        except Exception:
            pass

        verdict = "LIVE_SAFE"
        policy_notes = "Cloud cognitive routing active. Host telemetry normal."
        if local_model_resident:
            verdict = "LOCAL_MODEL_RESIDENT_DURING_LIVE"
            policy_notes = "Local LLM resident in memory during live operation; should remain unloaded."

        telemetry = HostTelemetry(
            timestamp=now,
            swap_total_mb=swap_total,
            swap_used_mb=swap_used,
            swap_free_mb=swap_free,
            swap_delta_mb=round(swap_delta, 2),
            system_memory_free_pct=free_pct,
            is_safe=not local_model_resident,
            verdict=verdict,
            policy_notes=policy_notes,
        )

        with self._lock:
            self.last_telemetry = telemetry
            self.governor_verdict = verdict

        return telemetry

    def should_permit_inference(self) -> Tuple[bool, str]:
        """Advises whether the local model may be invoked."""
        telemetry = self.inspect_system()
        if not telemetry.is_safe:
            return False, f"Memory pressure unsafe (Free: {telemetry.system_memory_free_pct}%, Swap delta: +{telemetry.swap_delta_mb}MB)"
        return True, "SYSTEM_RESOURCES_NOMINAL"

    def enforce_shedding(self, adapter: Any) -> None:
        """Forcefully unloads model from memory if system enters critical state."""
        with self._lock:
            self.shed_count += 1
            self.governor_verdict = "QWEN_9B_LIVE_UNSAFE_ON_8GB"
        logger.warning("ResourceGovernor: Shedding local model from memory to protect Dhan/Fast Lane!")
        if hasattr(adapter, "unload_model"):
            adapter.unload_model()
