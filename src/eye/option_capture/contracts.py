"""Capture Data Models and Enums for Eye Engine Option Capture."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, Dict, List


class CaptureSessionState(str, Enum):
    PLANNED = "PLANNED"
    CONNECTING = "CONNECTING"
    CAPTURING = "CAPTURING"
    DEGRADED = "DEGRADED"
    FINALIZING = "FINALIZING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    RECOVERED = "RECOVERED"


class SessionClassification(str, Enum):
    SHORT_LIVE_PILOT = "SHORT_LIVE_PILOT"
    EXTENDED_PILOT_SESSION = "EXTENDED_PILOT_SESSION"
    COMPLETE_SESSION = "COMPLETE_SESSION"
    REPLAY_SESSION = "REPLAY_SESSION"



class RawPacketType(str, Enum):
    REST_RESPONSE = "REST_RESPONSE"
    WEBSOCKET_BINARY = "WEBSOCKET_BINARY"
    WEBSOCKET_TEXT = "WEBSOCKET_TEXT"


class FeedLane(str, Enum):
    FAST_LANE_WEBSOCKET = "FAST_LANE_WEBSOCKET"
    SLOW_LANE_OPTION_CHAIN = "SLOW_LANE_OPTION_CHAIN"


@dataclass
class RawPacketRecord:
    packet_id: str
    session_id: str
    packet_type: RawPacketType
    endpoint_or_feed: str
    received_at_utc: str
    received_monotonic_ns: int
    payload_size_bytes: int
    payload_sha256: str
    raw_journal_file: str
    byte_offset: int
    sequence_number: Optional[int] = None
    security_id: Optional[str] = None
    response_code: Optional[int] = None
    declared_length: Optional[int] = None
    actual_length: Optional[int] = None
    exchange_segment: Optional[int] = None
    decode_status: str = "SUCCESS"



@dataclass
class FieldRevisionRecord:
    contract_key: str
    field_name: str
    field_value: Any
    source_lane: FeedLane
    exchange_timestamp: Optional[str]
    received_at_utc: str
    available_at_utc: str
    revision_number: int
    connection_epoch: int = 1
    validity_status: str = "VALID"

