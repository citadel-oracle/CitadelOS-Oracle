"""Upstox Market Data Feed V3 Protobuf Decoder and Normalizer.

Decodes official binary Protobuf packets from Upstox WebSocket Feed V3 and
normalizes them into structured CITADEL ticks with full field-level provenance.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.broker.proto import MarketDataFeedV3_pb2 as pb2


class UpstoxPacketError(ValueError):
    """Raised when an Upstox binary packet cannot be parsed or is malformed."""


@dataclass(frozen=True, slots=True)
class DecodedUpstoxFeed:
    """Represents a decoded Upstox FeedResponse containing normalized ticks."""
    feed_type: int  # 0: initial_feed, 1: live_feed, 2: market_info
    current_ts: int  # ms timestamp from Upstox
    ticks: List[Dict[str, Any]]
    market_info: Optional[Dict[str, Any]]
    raw_fingerprint: str


class UpstoxProtoDecoder:
    """Zero-side-effect Protobuf decoder for Upstox V3 live feeds."""

    @classmethod
    def decode_packet(cls, packet: bytes | bytearray | memoryview) -> DecodedUpstoxFeed:
        if not isinstance(packet, (bytes, bytearray, memoryview)):
            raise UpstoxPacketError("UPSTOX_PACKET_TYPE_INVALID")
        raw = bytes(packet)
        if len(raw) == 0:
            raise UpstoxPacketError("UPSTOX_PACKET_EMPTY")

        fingerprint = hashlib.sha256(raw).hexdigest()
        feed_response = pb2.FeedResponse()
        try:
            feed_response.ParseFromString(raw)
        except Exception as exc:
            raise UpstoxPacketError(f"UPSTOX_PROTOBUF_PARSE_FAILED: {exc}") from exc

        ticks: List[Dict[str, Any]] = []
        now_ns = time.perf_counter_ns()
        now_utc = datetime.now(timezone.utc).isoformat()
        current_ts = feed_response.currentTs

        for instrument_key, feed in feed_response.feeds.items():
            tick = cls._normalize_feed_item(
                instrument_key=instrument_key,
                feed=feed,
                current_ts=current_ts,
                fingerprint=fingerprint,
                decode_done_ns=now_ns,
                received_iso=now_utc,
            )
            if tick is not None:
                ticks.append(tick)

        # Parse market info if present
        market_info_dict = None
        if feed_response.HasField("marketInfo"):
            info = feed_response.marketInfo
            market_info_dict = {
                "segment_status": {k: v for k, v in info.segmentStatus.items()},
                "cas_status": {k: {"status": v.status, "updated": v.updatedTime} for k, v in info.casMarketStatus.items()},
                "pre_open_status": {k: {"status": v.status, "updated": v.updatedTime} for k, v in info.preOpenSessionStatus.items()},
            }

        return DecodedUpstoxFeed(
            feed_type=feed_response.type,
            current_ts=current_ts,
            ticks=ticks,
            market_info=market_info_dict,
            raw_fingerprint=fingerprint,
        )

    @classmethod
    def _normalize_feed_item(
        cls,
        instrument_key: str,
        feed: pb2.Feed,
        current_ts: int,
        fingerprint: str,
        decode_done_ns: int,
        received_iso: str,
    ) -> Optional[Dict[str, Any]]:
        union_case = feed.WhichOneof("FeedUnion")
        if not union_case:
            return None

        # Base tick metadata
        tick: Dict[str, Any] = {
            "provider": "UPSTOX",
            "instrument_key": instrument_key,
            "packet_fingerprint": fingerprint,
            "decode_done_ns": decode_done_ns,
            "received_timestamp": received_iso,
            "request_mode": feed.requestMode,
            "feed_union": union_case,
        }

        # Format source timestamp
        source_ts_ms = current_ts

        if union_case == "ltpc":
            ltpc = feed.ltpc
            if ltpc.ltt > 0:
                source_ts_ms = ltpc.ltt
            tick.update({
                "response_code": 2,  # ticker equivalent
                "ltp": float(ltpc.ltp),
                "ltt": int(ltpc.ltt),
                "ltq": int(ltpc.ltq),
                "close": float(ltpc.cp),
                "previous_close": float(ltpc.cp),
            })

        elif union_case == "fullFeed":
            ff = feed.fullFeed
            ff_case = ff.WhichOneof("FullFeedUnion")
            tick["response_code"] = 8  # Full packet equivalent

            if ff_case == "indexFF":
                idx = ff.indexFF
                ltpc = idx.ltpc
                if ltpc.ltt > 0:
                    source_ts_ms = ltpc.ltt
                raw_ltt = int(ltpc.ltt)
                ltt_sec = int(raw_ltt // 1000) if raw_ltt > 10_000_000_000 else raw_ltt
                vol = 0
                open_p = float(ltpc.cp)
                high_p = float(ltpc.ltp)
                low_p = float(ltpc.ltp)
                if idx.marketOHLC and idx.marketOHLC.ohlc:
                    latest_ohlc = idx.marketOHLC.ohlc[-1]
                    open_p = float(latest_ohlc.open)
                    high_p = float(latest_ohlc.high)
                    low_p = float(latest_ohlc.low)
                    vol = int(latest_ohlc.vol)

                depth_5 = [
                    {
                        "level": i + 1,
                        "bid_quantity": 0,
                        "bid_price": 0.0,
                        "bid_orders": 0,
                        "ask_quantity": 0,
                        "ask_price": 0.0,
                        "ask_orders": 0,
                    }
                    for i in range(5)
                ]
                tick.update({
                    "is_index": True,
                    "ltp": float(ltpc.ltp),
                    "ltt": ltt_sec,
                    "ltt_ms": raw_ltt,
                    "ltq": int(ltpc.ltq),
                    "close": float(ltpc.cp),
                    "previous_close": float(ltpc.cp),
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "atp": float(ltpc.ltp),
                    "volume": vol,
                    "cumulative_volume": vol,
                    "oi": 0,
                    "open_interest": 0,
                    "high_open_interest": 0,
                    "low_open_interest": 0,
                    "total_buy_quantity": 0,
                    "total_sell_quantity": 0,
                    "depth": [],
                    "depth_5": depth_5,
                    "depth_levels_count": 0,
                })

            elif ff_case == "marketFF":
                mff = ff.marketFF
                ltpc = mff.ltpc
                if ltpc.ltt > 0:
                    source_ts_ms = ltpc.ltt
                raw_ltt = int(ltpc.ltt)
                ltt_sec = int(raw_ltt // 1000) if raw_ltt > 10_000_000_000 else raw_ltt

                # Depth levels (up to 30 or 5)
                depth: List[Dict[str, Any]] = []
                depth_5: List[Dict[str, Any]] = []
                for idx_q, q in enumerate(mff.marketLevel.bidAskQuote):
                    entry = {
                        "level": idx_q + 1,
                        "bid_quantity": int(q.bidQ),
                        "bid_price": float(q.bidP),
                        "ask_quantity": int(q.askQ),
                        "ask_price": float(q.askP),
                        "bid_orders": 0,  # Upstox V3 depth does not publish order count per level
                        "ask_orders": 0,
                    }
                    depth.append(entry)
                    if idx_q < 5:
                        depth_5.append(entry)

                while len(depth_5) < 5:
                    depth_5.append({
                        "level": len(depth_5) + 1,
                        "bid_quantity": 0,
                        "bid_price": 0.0,
                        "bid_orders": 0,
                        "ask_quantity": 0,
                        "ask_price": 0.0,
                        "ask_orders": 0,
                    })

                greeks: Optional[Dict[str, float]] = None
                if mff.HasField("optionGreeks"):
                    og = mff.optionGreeks
                    greeks = {
                        "delta": float(og.delta),
                        "theta": float(og.theta),
                        "gamma": float(og.gamma),
                        "vega": float(og.vega),
                        "rho": float(og.rho),
                    }

                open_p = float(ltpc.cp)
                high_p = float(ltpc.ltp)
                low_p = float(ltpc.ltp)
                if mff.marketOHLC and mff.marketOHLC.ohlc:
                    latest_ohlc = mff.marketOHLC.ohlc[-1]
                    open_p = float(latest_ohlc.open)
                    high_p = float(latest_ohlc.high)
                    low_p = float(latest_ohlc.low)

                atp_val = float(mff.atp) if float(mff.atp) > 0 else float(ltpc.ltp)
                vol_val = int(mff.vtt)
                tick.update({
                    "is_index": False,
                    "ltp": float(ltpc.ltp),
                    "ltt": ltt_sec,
                    "ltt_ms": raw_ltt,
                    "ltq": int(ltpc.ltq),
                    "close": float(ltpc.cp),
                    "previous_close": float(ltpc.cp),
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "atp": atp_val,
                    "volume": vol_val,
                    "cumulative_volume": vol_val,
                    "oi": int(mff.oi),
                    "open_interest": int(mff.oi),
                    "high_open_interest": 0,
                    "low_open_interest": 0,
                    "implied_volatility": float(mff.iv) if mff.iv > 0 else None,
                    "total_buy_quantity": int(mff.tbq),
                    "total_sell_quantity": int(mff.tsq),
                    "depth": depth,
                    "depth_5": depth_5,
                    "depth_levels_count": len(depth),
                    "option_greeks": greeks,
                })

        elif union_case == "firstLevelWithGreeks":
            flg = feed.firstLevelWithGreeks
            ltpc = flg.ltpc
            if ltpc.ltt > 0:
                source_ts_ms = ltpc.ltt
            raw_ltt = int(ltpc.ltt)
            ltt_sec = int(raw_ltt // 1000) if raw_ltt > 10_000_000_000 else raw_ltt
            greeks = None
            if flg.HasField("optionGreeks"):
                og = flg.optionGreeks
                greeks = {
                    "delta": float(og.delta),
                    "theta": float(og.theta),
                    "gamma": float(og.gamma),
                    "vega": float(og.vega),
                    "rho": float(og.rho),
                }
            depth = []
            depth_5 = []
            if flg.firstDepth:
                q = flg.firstDepth
                entry = {
                    "level": 1,
                    "bid_quantity": int(q.bidQ),
                    "bid_price": float(q.bidP),
                    "ask_quantity": int(q.askQ),
                    "ask_price": float(q.askP),
                    "bid_orders": 0,
                    "ask_orders": 0,
                }
                depth.append(entry)
                depth_5.append(entry)
            while len(depth_5) < 5:
                depth_5.append({
                    "level": len(depth_5) + 1,
                    "bid_quantity": 0,
                    "bid_price": 0.0,
                    "bid_orders": 0,
                    "ask_quantity": 0,
                    "ask_price": 0.0,
                    "ask_orders": 0,
                })
            vol_val = int(flg.vtt)
            tick.update({
                "response_code": 8,
                "ltp": float(ltpc.ltp),
                "ltt": ltt_sec,
                "ltt_ms": raw_ltt,
                "ltq": int(ltpc.ltq),
                "close": float(ltpc.cp),
                "previous_close": float(ltpc.cp),
                "atp": float(ltpc.ltp),
                "volume": vol_val,
                "cumulative_volume": vol_val,
                "oi": int(flg.oi),
                "open_interest": int(flg.oi),
                "implied_volatility": float(flg.iv) if flg.iv > 0 else None,
                "depth": depth,
                "depth_5": depth_5,
                "depth_levels_count": len(depth),
                "option_greeks": greeks,
            })

        # Attach standard ISO timestamp and provenance
        try:
            source_dt = datetime.fromtimestamp(source_ts_ms / 1000.0, tz=timezone.utc)
            tick["source_timestamp"] = source_dt.isoformat()
        except (ValueError, OSError):
            tick["source_timestamp"] = received_iso

        return tick
