"""Read-only adapter over verified TradingView MCP chart-reading capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from src.oracle.contracts.perception import (
    Availability, CompletionStatus, FreshnessState, VisualClaimCandidate,
    VisualObservation, record_from_dict, seal,
)
from src.strategy_lab.storage import _atomic_write


MCP_NAME = "tradingview"
MCP_VERSION = "2.0.0"
ADAPTER_VERSION = "1.0.1"
VERIFIED_READ_TOOLS = (
    "tv_health_check", "chart_get_state", "pane_list", "draw_list",
    "data_get_pine_lines", "data_get_pine_labels", "data_get_pine_boxes",
    "data_get_study_values", "capture_screenshot",
)


class TradingViewMCPAdapter:
    """The caller is injected so CITADEL never embeds MCP transport or UI control."""

    def __init__(self, caller: Callable[[str, Mapping[str, Any]], Mapping[str, Any]], *, clock=None):
        self.caller = caller
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def capture(self, *, correlation_id: str, instrument_id: str, symbol: str, timeframe: str) -> VisualObservation:
        now = self.clock()
        common = dict(
            correlation_id=correlation_id, instrument_id=instrument_id, symbol=symbol, timeframe=timeframe,
            source_timestamp=now.isoformat(), generated_at=now.isoformat(), as_of=now.isoformat(),
            freshness_state=FreshnessState.FRESH, source_ids={"mcp": MCP_NAME},
            dependency_versions={"mcp": MCP_VERSION, "adapter": ADAPTER_VERSION}, completion_status=CompletionStatus.COMPLETE,
            provenance={"mcp": MCP_NAME, "mcp_version": MCP_VERSION, "tools": VERIFIED_READ_TOOLS,
                        "visual_authority_only": True, "execution_influence": "ZERO"},
        )
        try:
            health = dict(self.caller("tv_health_check", {}))
            state = dict(self.caller("chart_get_state", {}))
        except Exception as error:
            return self._failure(common, "VISUAL_UNAVAILABLE", type(error).__name__)
        detected = self._symbol(state) or self._symbol(health)
        visible_tf = self._timeframe(state) or self._timeframe(health)
        if not detected or not visible_tf:
            return self._failure(common, "VISUAL_AMBIGUOUS", "SYMBOL_OR_TIMEFRAME_UNREADABLE")
        if detected.upper().split(":")[-1] != symbol.upper().split(":")[-1] or self._normalize_tf(visible_tf) != timeframe:
            return self._failure(common, "VISUAL_AMBIGUOUS", "SYMBOL_OR_TIMEFRAME_MISMATCH", detected, visible_tf)
        observation_id = "tvobs_" + hashlib.sha256(f"{correlation_id}:{detected}:{visible_tf}:{now.isoformat()}".encode()).hexdigest()[:20]
        drawings, indicators, artifact, metadata = [], [], None, {"health": health, "chart_state": state}
        for tool, key in (("pane_list", "panes"), ("draw_list", "drawings"), ("data_get_pine_lines", "pine_lines"),
                          ("data_get_pine_labels", "pine_labels"), ("data_get_pine_boxes", "pine_boxes")):
            try:
                value = self.caller(tool, {})
                metadata[key] = value
                if key in {"drawings", "pine_lines", "pine_labels", "pine_boxes"}:
                    drawings.append({"tool": tool, "response": value})
            except Exception as error:
                metadata[key] = {"status": "UNAVAILABLE", "error": type(error).__name__}
        for item in state.get("indicators") or state.get("studies") or ():
            if isinstance(item, Mapping) and item.get("name"):
                indicators.append(str(item["name"]))
            elif isinstance(item, str):
                indicators.append(item)
        try:
            screenshot = self.caller("capture_screenshot", {"region": "chart"})
            artifact = str(screenshot.get("path") or screenshot.get("artifact") or "") or None
            metadata["screenshot"] = screenshot
        except Exception as error:
            metadata["screenshot"] = {"status": "UNAVAILABLE", "error": type(error).__name__}
        candidates = self._claim_candidates(
            state.get("visual_claim_candidates") or state.get("claim_candidates") or (),
            common=common, observation_id=observation_id,
        )
        return seal(VisualObservation(
            **common, availability=Availability.AVAILABLE, observation_id=observation_id,
            detected_symbol=detected, visible_timeframe=timeframe, chart_metadata=metadata,
            artifact_reference=artifact, visible_drawings=tuple(drawings), visible_indicators=tuple(indicators),
            claim_candidates=candidates, failure_reason=None,
        ))

    @staticmethod
    def _claim_candidates(raw_candidates, *, common, observation_id):
        """Preserve explicit visual assertions; never infer values from pixels or names."""
        result = []
        if not isinstance(raw_candidates, (list, tuple)):
            return ()
        for index, raw in enumerate(raw_candidates):
            if not isinstance(raw, Mapping):
                continue
            predicates = raw.get("predicates")
            if not isinstance(predicates, Mapping) or not predicates:
                continue
            seed = json.dumps(raw, sort_keys=True, default=str)
            claim_id = str(raw.get("claim_id") or "tvclaim_" + hashlib.sha256(seed.encode()).hexdigest()[:20])
            try:
                result.append(seal(VisualClaimCandidate(
                    correlation_id=common["correlation_id"], instrument_id=common["instrument_id"],
                    symbol=common["symbol"], timeframe=common["timeframe"],
                    source_timestamp=common["source_timestamp"], generated_at=common["generated_at"],
                    as_of=common["as_of"], availability=Availability.AVAILABLE,
                    freshness_state=common["freshness_state"],
                    source_ids={"observation": observation_id, "raw_candidate_index": str(index)},
                    dependency_versions={"mcp": MCP_VERSION, "adapter": ADAPTER_VERSION},
                    completion_status=CompletionStatus.COMPLETE,
                    provenance={"source": "EXPLICIT_TRADINGVIEW_VISUAL_CANDIDATE", "numerical_authority": False,
                                "requires_citadel_verification": True, "execution_influence": "ZERO"},
                    claim_id=claim_id, claim_type=str(raw.get("claim_type") or "").upper(),
                    direction=str(raw.get("direction") or "").upper(), predicates=dict(predicates),
                    declared_tolerance=float(raw.get("declared_tolerance") or 0.0),
                    observation_id=observation_id,
                )))
            except (TypeError, ValueError):
                continue
        return tuple(result)

    def _failure(self, common, availability, reason, detected=None, visible_tf=None):
        value = Availability.UNAVAILABLE if availability == "VISUAL_UNAVAILABLE" else Availability.AMBIGUOUS
        observation_id = "tvobs_" + hashlib.sha256(f"{common['correlation_id']}:{availability}:{reason}".encode()).hexdigest()[:20]
        failure_common = dict(common)
        failure_common["freshness_state"] = FreshnessState.UNKNOWN
        return seal(VisualObservation(
            **failure_common, availability=value, observation_id=observation_id,
            detected_symbol=detected, visible_timeframe=self._normalize_tf(visible_tf) if visible_tf else None,
            chart_metadata={"status": availability}, artifact_reference=None, visible_drawings=(),
            visible_indicators=(), claim_candidates=(), failure_reason=f"{availability}:{reason}",
        ))

    @staticmethod
    def _symbol(value):
        result = value.get("symbol") or value.get("ticker")
        if not result and isinstance(value.get("chart"), Mapping):
            result = value["chart"].get("symbol")
        return str(result) if result else None

    @staticmethod
    def _timeframe(value):
        result = value.get("timeframe") or value.get("interval")
        if not result and isinstance(value.get("chart"), Mapping):
            result = value["chart"].get("timeframe")
        return str(result) if result else None

    @staticmethod
    def _normalize_tf(value):
        return {"1": "1m", "3": "3m", "5": "5m", "15": "15m", "60": "1H", "240": "4H", "D": "1D", "1D": "1D"}.get(str(value), str(value))


class VisualObservationStore:
    """Side-effect-free reads over explicitly captured observations/claims."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save_observation(self, value: VisualObservation) -> None:
        _atomic_write(self.root / "observations" / f"{value.observation_id}.json", value.to_dict())

    def observation(self, observation_id: str) -> VisualObservation | None:
        try:
            return record_from_dict(VisualObservation, json.loads((self.root / "observations" / f"{observation_id}.json").read_text(encoding="utf-8")))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save_claim(self, value) -> None:
        _atomic_write(self.root / "claims" / f"{value.claim_id}.json", value.to_dict())

    def claim(self, claim_id: str):
        from src.oracle.contracts.perception import VerifiedVisualClaim
        try:
            return record_from_dict(VerifiedVisualClaim, json.loads((self.root / "claims" / f"{claim_id}.json").read_text(encoding="utf-8")))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
