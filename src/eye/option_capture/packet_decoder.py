"""Official DhanHQ v2 Binary WebSocket Packet Decoder for Citadel Eye Engine Option Capture."""

import struct
from typing import Dict, Any, Optional, Tuple, List


class DhanPacketDecoder:
    """Decodes Little-Endian DhanHQ v2 WebSocket binary packets.

    Header (8 bytes):
    - Byte 0: Response Code (uint8)
    - Byte 1..2: Message Length (uint16)
    - Byte 3: Exchange Segment (uint8)
    - Byte 4..7: Security ID (int32)
    """

    @staticmethod
    def decode_packet(payload: bytes) -> Optional[Dict[str, Any]]:
        if not payload or len(payload) < 8:
            return None

        res_code = payload[0]
        msg_len = struct.unpack_from("<H", payload, 1)[0]
        exchange_seg = payload[3]
        sec_id = struct.unpack_from("<i", payload, 4)[0]

        if len(payload) < msg_len:
            # Truncated packet
            return None

        # Exact packet slice according to declared message length
        pkt_data = payload[:msg_len]

        # Code 8: Full Market Depth Quote Packet (162 bytes)
        if res_code == 8:
            if msg_len != 162:
                # Length mismatch (e.g. truncated 82-byte legacy packet rejected!)
                return None

            try:
                ltp = struct.unpack_from("<f", pkt_data, 8)[0]
                ltq = struct.unpack_from("<I", pkt_data, 12)[0]
                ltt = struct.unpack_from("<I", pkt_data, 16)[0]
                atp = struct.unpack_from("<f", pkt_data, 20)[0]
                vol = struct.unpack_from("<I", pkt_data, 24)[0]
                tot_sell = struct.unpack_from("<I", pkt_data, 28)[0]
                tot_buy = struct.unpack_from("<I", pkt_data, 32)[0]
                oi = struct.unpack_from("<I", pkt_data, 36)[0]
                high_oi = struct.unpack_from("<I", pkt_data, 40)[0]
                low_oi = struct.unpack_from("<I", pkt_data, 44)[0]
                open_px = struct.unpack_from("<f", pkt_data, 48)[0]
                close_px = struct.unpack_from("<f", pkt_data, 52)[0]
                high_px = struct.unpack_from("<f", pkt_data, 56)[0]
                low_px = struct.unpack_from("<f", pkt_data, 60)[0]

                # 5 Depth Levels (bytes 62..161)
                depth_levels = []
                offset = 62
                for i in range(5):
                    bid_q = struct.unpack_from("<I", pkt_data, offset)[0]
                    ask_q = struct.unpack_from("<I", pkt_data, offset + 4)[0]
                    bid_orders = struct.unpack_from("<H", pkt_data, offset + 8)[0]
                    ask_orders = struct.unpack_from("<H", pkt_data, offset + 10)[0]
                    bid_p = struct.unpack_from("<f", pkt_data, offset + 12)[0]
                    ask_p = struct.unpack_from("<f", pkt_data, offset + 16)[0]
                    depth_levels.append({
                        "level": i + 1,
                        "bid_quantity": int(bid_q),
                        "ask_quantity": int(ask_q),
                        "bid_orders": int(bid_orders),
                        "ask_orders": int(ask_orders),
                        "bid_price": float(round(bid_p, 4)),
                        "ask_price": float(round(ask_p, 4)),
                    })
                    offset += 20

                top_book = depth_levels[0]

                return {
                    "response_code": 8,
                    "message_length": msg_len,
                    "exchange_segment": int(exchange_seg),
                    "security_id": str(sec_id),
                    "last_price": float(round(ltp, 4)),
                    "last_quantity": int(ltq),
                    "last_trade_time": int(ltt),
                    "avg_traded_price": float(round(atp, 4)),
                    "volume": int(vol),
                    "total_sell_quantity": int(tot_sell),
                    "total_buy_quantity": int(tot_buy),
                    "open_interest": int(oi),
                    "highest_open_interest": int(high_oi),
                    "lowest_open_interest": int(low_oi),
                    "open": float(round(open_px, 4)),
                    "close": float(round(close_px, 4)),
                    "high": float(round(high_px, 4)),
                    "low": float(round(low_px, 4)),
                    "depth": depth_levels,
                    "best_bid": top_book["bid_price"],
                    "best_ask": top_book["ask_price"],
                    "bid_quantity": top_book["bid_quantity"],
                    "ask_quantity": top_book["ask_quantity"],
                }
            except Exception:
                return None

        # Code 4: Quote Packet (50 bytes)
        elif res_code == 4:
            if msg_len != 50:
                return None
            try:
                ltp = struct.unpack_from("<f", pkt_data, 8)[0]
                ltq = struct.unpack_from("<I", pkt_data, 12)[0]
                ltt = struct.unpack_from("<I", pkt_data, 16)[0]
                atp = struct.unpack_from("<f", pkt_data, 20)[0]
                vol = struct.unpack_from("<I", pkt_data, 24)[0]
                tot_sell = struct.unpack_from("<I", pkt_data, 28)[0]
                tot_buy = struct.unpack_from("<I", pkt_data, 32)[0]
                open_px = struct.unpack_from("<f", pkt_data, 36)[0]
                close_px = struct.unpack_from("<f", pkt_data, 40)[0]
                high_px = struct.unpack_from("<f", pkt_data, 44)[0]
                low_px = struct.unpack_from("<f", pkt_data, 48)[0]

                return {
                    "response_code": 4,
                    "message_length": msg_len,
                    "exchange_segment": int(exchange_seg),
                    "security_id": str(sec_id),
                    "last_price": float(round(ltp, 4)),
                    "last_quantity": int(ltq),
                    "last_trade_time": int(ltt),
                    "avg_traded_price": float(round(atp, 4)),
                    "volume": int(vol),
                    "total_sell_quantity": int(tot_sell),
                    "total_buy_quantity": int(tot_buy),
                    "open": float(round(open_px, 4)),
                    "close": float(round(close_px, 4)),
                    "high": float(round(high_px, 4)),
                    "low": float(round(low_px, 4)),
                }
            except Exception:
                return None

        # Code 2: Ticker Packet (16 bytes)
        elif res_code == 2:
            if msg_len != 16:
                return None
            try:
                ltp = struct.unpack_from("<f", pkt_data, 8)[0]
                ltt = struct.unpack_from("<I", pkt_data, 12)[0]

                return {
                    "response_code": 2,
                    "message_length": msg_len,
                    "exchange_segment": int(exchange_seg),
                    "security_id": str(sec_id),
                    "last_price": float(round(ltp, 4)),
                    "last_trade_time": int(ltt),
                }
            except Exception:
                return None

        # Code 6: OI Packet (20 bytes)
        elif res_code == 6:
            if msg_len != 20:
                return None
            try:
                oi = struct.unpack_from("<I", pkt_data, 8)[0]
                high_oi = struct.unpack_from("<I", pkt_data, 12)[0]
                low_oi = struct.unpack_from("<I", pkt_data, 16)[0]

                return {
                    "response_code": 6,
                    "message_length": msg_len,
                    "exchange_segment": int(exchange_seg),
                    "security_id": str(sec_id),
                    "open_interest": int(oi),
                    "highest_open_interest": int(high_oi),
                    "lowest_open_interest": int(low_oi),
                }
            except Exception:
                return None

        # Code 5: Previous Close Packet (20 bytes)
        elif res_code == 5:
            if msg_len != 20:
                return None
            try:
                prev_close = struct.unpack_from("<f", pkt_data, 8)[0]
                prev_oi = struct.unpack_from("<I", pkt_data, 12)[0]

                return {
                    "response_code": 5,
                    "message_length": msg_len,
                    "exchange_segment": int(exchange_seg),
                    "security_id": str(sec_id),
                    "previous_close": float(round(prev_close, 4)),
                    "previous_open_interest": int(prev_oi),
                }
            except Exception:
                return None

        # Code 50: Disconnect / Ack Packet (12 bytes)
        elif res_code == 50:
            if msg_len != 12:
                return None
            try:
                reason_code = struct.unpack_from("<I", pkt_data, 8)[0]
                return {
                    "response_code": 50,
                    "message_length": msg_len,
                    "exchange_segment": int(exchange_seg),
                    "security_id": str(sec_id),
                    "disconnect_reason_code": int(reason_code),
                }
            except Exception:
                return None

        return None

    @classmethod
    def decode_stream(cls, buffer: bytes) -> Tuple[List[Dict[str, Any]], bytes]:
        """Decodes concatenated sequential binary packets from a streaming buffer."""
        packets = []
        while len(buffer) >= 8:
            msg_len = struct.unpack_from("<H", buffer, 1)[0]
            if msg_len < 8 or len(buffer) < msg_len:
                break
            pkt = cls.decode_packet(buffer[:msg_len])
            if pkt:
                packets.append(pkt)
            buffer = buffer[msg_len:]
        return packets, buffer
