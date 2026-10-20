"""Read-only DhanHQ v2 market-data protocol helpers.

Order API methods are intentionally absent. Dhan sends little-endian binary packets;
the parser below handles the documented 8-byte header and ticker packet only.
"""
import struct
from .base import NormalizedQuote

DhanSegments = {"NSE_FNO": 2, "BSE_FNO": 8, "MCX_COMM": 5}


def subscribe_message(instruments: list[dict]) -> dict:
    if len(instruments) > 100:
        raise ValueError("Dhan subscription messages accept at most 100 instruments")
    return {"RequestCode": 15, "InstrumentCount": len(instruments), "InstrumentList": [{"ExchangeSegment": x["segment"], "SecurityId": str(x["security_id"])} for x in instruments]}


def parse_ticker_packet(packet: bytes, instrument_map: dict[str, dict]) -> NormalizedQuote | None:
    if len(packet) < 16:
        return None
    response_code, _length, segment, security_id = struct.unpack_from("<BHB I", packet, 0)
    if response_code != 2:
        return None
    meta = instrument_map.get(f"{segment}:{security_id}")
    if not meta:
        return None
    ltp = struct.unpack_from("<f", packet, 8)[0]
    ltt = struct.unpack_from("<I", packet, 12)[0]
    return NormalizedQuote(instrument_id=str(security_id), broker="Dhan", ltp=ltp, exchange_time=str(ltt), **meta)
