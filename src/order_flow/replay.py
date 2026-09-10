"""Deterministic sanitized Full-packet replay harness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from src.broker.dhan_full_packet import DhanFullPacketDecoder

from .contracts import InstrumentIdentity, canonical_hash
from .service import OrderFlowService


class DeterministicClock:
    def __init__(self, start_ns: int = 1_000_000_000, step_ns: int = 50_000):
        self.value = start_ns - step_ns
        self.step_ns = step_ns

    def __call__(self) -> int:
        self.value += self.step_ns
        return self.value


class OrderFlowReplayHarness:
    def __init__(self, instruments: tuple[InstrumentIdentity, ...]):
        self.instruments = instruments

    def run(self, packets: Iterable[bytes]) -> dict:
        monotonic = DeterministicClock()
        wall_start = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
        wall_index = 0
        def wall() -> datetime:
            nonlocal wall_index
            value = wall_start + timedelta(milliseconds=wall_index)
            wall_index += 1
            return value
        service = OrderFlowService(clock_ns=monotonic, wall_clock=wall)
        service.register_instruments(self.instruments)
        hashes = []
        episodes = []
        generation = 1
        for raw in packets:
            receive_ns = monotonic()
            decoded = DhanFullPacketDecoder.decode_packet(raw).to_dict()
            decoded.update(
                {
                    "feed_generation": generation,
                    "feed_receive_ns": receive_ns,
                    "decode_done_ns": monotonic(),
                    "receive_wall_utc": wall().isoformat(),
                    "transport_gap_count": 0,
                }
            )
            projection = service.ingest_tick(decoded)
            if projection is not None:
                hashes.append(projection.content_hash)
                if service.episodes.active is not None:
                    episodes.append(service.episodes.active.episode_id)
        result = {
            "projection_hashes": hashes,
            "episode_ids": episodes,
            "latest": service.latest_projection(),
            "telemetry": service.telemetry(),
        }
        result["replay_hash"] = canonical_hash(result)
        return result
