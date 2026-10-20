"""5paisa Xstream authenticated WebSocket subscription helpers."""
import json
from .base import NormalizedQuote


def subscribe_payload(client_code: str, instruments: list[dict]) -> str:
    return json.dumps({"Method": "MarketFeedV3", "Operation": "Subscribe", "ClientCode": client_code,
                       "MarketFeedData": [{"Exch": x["exchange"], "ExchType": x["exchange_type"], "ScripCode": int(x["scrip_code"])} for x in instruments]})


def to_normalized_feed(message: dict, instrument_map: dict[int, dict]) -> NormalizedQuote | None:
    code = int(message.get("Token", message.get("ScripCode", 0)))
    meta = instrument_map.get(code)
    if not meta or message.get("LastRate") is None:
        return None
    return NormalizedQuote(instrument_id=str(code), broker="5paisa", ltp=float(message["LastRate"]),
        bid=float(message["BidRate"]) if message.get("BidRate") else None,
        ask=float(message["OffRate"]) if message.get("OffRate") else None,
        volume=int(message["TotalQty"]) if message.get("TotalQty") is not None else None,
        exchange_time=str(message.get("TickDt") or "") or None, **meta)
