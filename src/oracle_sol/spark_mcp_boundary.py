"""Future Read-Only Spark MCP Tool Boundary for CITADEL (Phase 1 Specification).

Defines the strictly sandboxed read-only tools and authenticated external-context ingest
interface for future Gemini Spark MCP integrations.

ABSOLUTE SECURITY MANDATES:
1. READ-ONLY by default for all market data, event history, thesis records, and expectations.
2. ZERO broker execution tools: place_order, modify_order, cancel_order are STRICTLY FORBIDDEN.
3. ZERO credential exposure: Dhan tokens, client IDs, account balances, and secrets are NEVER exposed.
4. ZERO automated trading authority: Spark cannot directly execute trades or set Beacon state.
5. Disabled/local-only in Phase 1.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from src.oracle_sol.external_context import validate_external_context_payload


SPARK_RUNTIME: str = "RETIRED_PENDING_FINAL_REMOVAL"


class SparkMcpBoundary:
    """Safe read-only interface exposing CITADEL state to external agents/MCP.
    
    STATUS: RETIRED_PENDING_FINAL_REMOVAL.
    Replaced by deterministic ExternalContextCore.
    """

    def __init__(self, service: Optional[Any] = None) -> None:
        self._service = service
        self.enabled = False  # Disabled permanently - Spark retired
        self.spark_runtime_status = SPARK_RUNTIME

    def _get_service(self):
        if self._service is not None:
            return self._service
        from src.oracle_sol.service import SolMarketBrainService
        return SolMarketBrainService.get_instance()

    # ── 1. Read-Only Context Tools ──

    def get_session_summary(self, session_date: Optional[str] = None) -> Dict[str, Any]:
        """Return high-level factual session status, date, and active story summary."""
        srv = self._get_service()
        state = srv.get_latest_state()
        return {
            "service": "CitadelMarketBrain",
            "session_date": session_date or srv.memory._session_date,
            "data_stream": state["health_strip"]["data_stream"],
            "brain_worker": state["health_strip"]["brain_worker"],
            "active_market_story": state["active_market_story"],
        }

    def get_oracle_events(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Return recent factual chronological microstructural market events."""
        srv = self._get_service()
        clean_limit = max(1, min(limit, 50))
        return [e.to_dict() for e in srv.memory.get_recent_raw_events(limit=clean_limit)]

    def get_gemini_thesis_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Return previous thesis records and narrative evolutions."""
        srv = self._get_service()
        active_thesis = srv.thesis_memory.get_active_thesis()
        return [active_thesis.to_dict()]

    def get_expectation_outcomes(self) -> List[Dict[str, Any]]:
        """Return pre-registered forward expectations and their factual evaluations."""
        srv = self._get_service()
        active_thesis = srv.thesis_memory.get_active_thesis()
        return [e.to_dict() for e in active_thesis.evaluation_history]

    def get_external_context_health(self) -> Dict[str, Any]:
        """Return external context store health and ingested item counts."""
        srv = self._get_service()
        return srv.external_context_store.get_health_summary(srv.memory._session_date)

    # ── 2. Authenticated Validated Ingest ──

    def submit_external_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit and validate a structured Spark external context payload."""
        srv = self._get_service()
        ok, errors, context_obj = srv.ingest_external_context(payload)
        if not ok or not context_obj:
            return {
                "status": "REJECTED",
                "validation_errors": errors,
            }
        return {
            "status": "ACCEPTED",
            "external_context_id": context_obj.external_context_id,
            "market_session_date": context_obj.market_session_date,
            "total_items": context_obj.total_items_count(),
            "provenance_hash": context_obj.provenance_hash,
        }

    # ── 3. Prohibited Tool Guard ──

    def __getattr__(self, name: str) -> Any:
        if name in {
            "place_order",
            "modify_order",
            "cancel_order",
            "get_positions",
            "get_holdings",
            "get_funds",
            "get_dhan_token",
            "get_credentials",
        }:
            raise PermissionError(
                f"Tool '{name}' is strictly prohibited. Spark MCP boundary has zero broker trading authority."
            )
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
