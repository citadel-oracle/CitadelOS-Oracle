"""Base Adapter Interface for External Context Providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from src.external_context.contracts import ExternalEvent, ExternalQuote


class BaseExternalAdapter(ABC):
    """Abstract base adapter for external context providers."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.last_poll_time: Optional[float] = None
        self.last_status: str = "INITIALIZED"
        self.last_error: Optional[str] = None
        self.is_configured: bool = True

    @abstractmethod
    def poll_events(self) -> List[ExternalEvent]:
        """Poll and return newly discovered verified external events."""
        pass

    @abstractmethod
    def poll_quotes(self) -> List[ExternalQuote]:
        """Poll and return latest external market quotes."""
        pass

    def get_health(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "configured": self.is_configured,
            "status": self.last_status,
            "last_poll_time": self.last_poll_time,
            "last_error": self.last_error,
        }
