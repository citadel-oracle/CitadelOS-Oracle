"""Immutable episode identities around existing authoritative VOB zones.

This module deliberately contains no VOB geometry, ranking, or trading logic.
It adapts the already-computed OSE option-premium VOB projection into stable
research identities and freezes the selected contracts for each active timeframe episode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping


SOURCE_ENGINE = "OPTIONS_STRUCTURE_ENGINE_V1"
SUPPORTED_TIMEFRAMES = ("1m", "3m", "5m")


@dataclass(frozen=True, slots=True)
class FrozenContractIdentity:
    security_id: str
    trading_symbol: str | None
    expiry: str | None
    strike: float | None
    option_type: str
    lot_size: int | None
    source: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FrozenContractIdentity":
        security_id = str(value.get("security_id") or "").strip()
        option_type = str(value.get("option_type") or value.get("side") or "").upper()
        if not security_id or option_type not in {"CE", "PE"}:
            raise ValueError("authoritative option contract identity unavailable")
        return cls(
            security_id=security_id,
            trading_symbol=_text(value.get("trading_symbol") or value.get("symbol")),
            expiry=_text(value.get("expiry")),
            strike=_number(value.get("strike")),
            option_type=option_type,
            lot_size=_integer(value.get("lot_size")),
            source=_text(value.get("instrument_source") or value.get("source")),
        )


@dataclass(frozen=True, slots=True)
class VobEpisode:
    episode_id: str
    vob_revision: str
    source_engine: str
    source_zone_id: str
    symbol: str
    direction: str
    timeframe: str
    zone_top: float
    zone_bottom: float
    created_at: str
    approach_at: str | None
    touch_at: str | None
    primary_role: str
    primary_reason: str
    vob_state: str
    contract_identity: FrozenContractIdentity
    contract_frozen_at: str
    session_date: str | None = None
    expiry_day: bool | None = None
    evidence_revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_authoritative_update(
        self,
        *,
        vob_revision: str,
        vob_state: str,
        approach_at: str | None,
        touch_at: str | None,
    ) -> "VobEpisode":
        """Advance metadata without ever replacing the frozen contract/zone."""

        return replace(
            self,
            vob_revision=str(vob_revision),
            vob_state=str(vob_state),
            approach_at=self.approach_at or approach_at,
            touch_at=self.touch_at or touch_at,
            evidence_revision=self.evidence_revision + 1,
        )


def select_ose_vobs_by_timeframe(projection: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract valid non-broken VOB zones for all supported timeframes (1m, 3m, 5m)."""
    duel = _mapping(projection.get("duel"))
    duel_state = str(duel.get("state") or "").upper()
    if "CALL" in duel_state:
        direction, side = "CALL", "CE"
    elif "PUT" in duel_state:
        direction, side = "PUT", "PE"
    else:
        return {}

    contract_state = _mapping(_mapping(projection.get("contracts")).get(side))
    contract = _mapping(contract_state.get("contract"))
    structures = _mapping(contract_state.get("structures"))

    result = {}
    for timeframe in SUPPORTED_TIMEFRAMES:
        zone = _mapping(_mapping(structures.get(timeframe)).get("demand"))
        if zone and str(zone.get("status") or "").upper() != "BROKEN":
            result[timeframe] = {
                "direction": direction,
                "side": side,
                "timeframe": timeframe,
                "zone": dict(zone),
                "contract": dict(contract),
                "primary_role": "SUPPORT",
                "primary_reason": "NEAREST_SUPPORT",
            }
    return result


def select_primary_ose_vob(projection: Mapping[str, Any]) -> dict[str, Any] | None:
    """Reference OSE's existing directional and nearest-zone decisions with 5m/3m/1m precedence."""
    vobs_by_tf = select_ose_vobs_by_timeframe(projection)
    for timeframe in ("5m", "3m", "1m"):
        if timeframe in vobs_by_tf:
            return vobs_by_tf[timeframe]
    return None


def episodes_from_ose(projection: Mapping[str, Any]) -> dict[str, VobEpisode]:
    """Construct deterministic VobEpisode instances for all active timeframe candidates."""
    vobs_by_tf = select_ose_vobs_by_timeframe(projection)
    episodes = {}
    for tf, selected in vobs_by_tf.items():
        ep = _build_episode_from_selected(selected, projection)
        if ep is not None:
            episodes[tf] = ep
    return episodes


def episode_from_ose(projection: Mapping[str, Any]) -> VobEpisode | None:
    """Construct primary VobEpisode instance (for backward compatibility)."""
    selected = select_primary_ose_vob(projection)
    if selected is None:
        return None
    return _build_episode_from_selected(selected, projection)


def _build_episode_from_selected(selected: Mapping[str, Any], projection: Mapping[str, Any]) -> VobEpisode | None:
    zone = _mapping(selected["zone"])
    contract = FrozenContractIdentity.from_mapping(_mapping(selected["contract"]))
    zone_id = str(zone.get("zone_id") or "").strip()
    if not zone_id:
        return None
    zone_top = _number(zone.get("zone_high"))
    zone_bottom = _number(zone.get("zone_low"))
    if zone_top is None or zone_bottom is None:
        return None
    revision = str(
        projection.get("calculation_revision")
        or _mapping(projection.get("performance")).get("calculation_count")
        or projection.get("calculated_at")
        or "UNKNOWN"
    )
    source_time = str(
        zone.get("source_candle_timestamp")
        or projection.get("source_timestamp")
        or projection.get("calculated_at")
        or "UNKNOWN"
    )
    session_date = _iso_date(source_time)
    expiry_date = _iso_date(contract.expiry)
    tf = str(selected["timeframe"]).lower()
    episode_id = _episode_id(
        source_engine=SOURCE_ENGINE,
        zone_id=zone_id,
        security_id=contract.security_id,
        direction=str(selected["direction"]),
        timeframe=tf,
    )
    state = str(zone.get("status") or "UNKNOWN").upper()
    touch_at = source_time if state == "TESTED" else None
    approach_at = source_time if state in {"ACTIVE", "TESTED", "WEAKENING"} else None
    return VobEpisode(
        episode_id=episode_id,
        vob_revision=revision,
        source_engine=SOURCE_ENGINE,
        source_zone_id=zone_id,
        symbol=str(zone.get("symbol") or contract.trading_symbol or "NIFTY"),
        direction=str(selected["direction"]),
        timeframe=tf,
        zone_top=zone_top,
        zone_bottom=zone_bottom,
        created_at=source_time,
        approach_at=approach_at,
        touch_at=touch_at,
        primary_role=str(selected["primary_role"]),
        primary_reason=str(selected["primary_reason"]),
        vob_state=state,
        contract_identity=contract,
        contract_frozen_at=source_time,
        session_date=session_date,
        expiry_day=(session_date == expiry_date) if session_date and expiry_date else None,
    )


def _episode_id(**identity: str) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return "vobep_" + sha256(encoded).hexdigest()[:24]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    result = str(value).strip() if value is not None else ""
    return result or None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iso_date(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(text[:10]).date().isoformat()
        except (TypeError, ValueError):
            return None
