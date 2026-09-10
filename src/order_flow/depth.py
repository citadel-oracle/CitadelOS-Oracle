"""Optional Level-3 seam; never authoritative in P2."""

from __future__ import annotations

from typing import Mapping, Protocol


AUTHORITY_20_DEPTH = "DISABLED"


class Depth20Enhancer(Protocol):
    def latest(self, exchange_segment: str, security_id: str) -> Mapping | None: ...
