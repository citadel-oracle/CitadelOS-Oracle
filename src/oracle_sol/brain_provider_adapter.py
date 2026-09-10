"""Abstract Base Interface for Cloud & Local Cognitive Brain Providers.

Defines the contract for:
- Request serialization (pure BrainPacket evidence, zero raw broker/hotpath data)
- Structured JSON Schema invocation
- Latency and token telemetry
- Rate limit telemetry and dynamic backoff
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class BrainProviderAdapter(ABC):
    """Abstract interface for all CITADEL cognitive engine providers."""

    @abstractmethod
    def invoke_reasoning(
        self,
        request_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Invoke model reasoning with strict schema enforcement.

        Returns: (parsed_json_dict_or_none, execution_telemetry_dict)
        """
        pass

    @abstractmethod
    def get_telemetry(self) -> Dict[str, Any]:
        """Return cumulative provider usage and rate limit status."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider credentials and network endpoints are configured."""
        pass
