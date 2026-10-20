"""Kotak Neo current SDK bridge helpers (SFeed; never the retired callback feed)."""
from .base import NormalizedQuote


def to_normalized_sfeed(message, meta: dict) -> NormalizedQuote | None:
    # The official kotakneoapi SFeedScrip message exposes these typed fields.
    price = getattr(message, "last_traded_price", None)
    if price is None:
        return None
    return NormalizedQuote(
        instrument_id=str(getattr(message, "instrument_token", meta.get("instrument_id", ""))),
        broker="Kotak Neo", ltp=float(price), exchange_time=str(getattr(message, "exchange_timestamp", "") or "") or None,
        sequence=str(getattr(message, "sequence_number", "") or "") or None, **meta,
    )


async def iter_sfeed(neo_client, tokens):
    """Yield official SDK SFeed messages. Caller owns login and reconnect policy."""
    from neo_api_client.websocket.feed import WsToken
    async with neo_client.create_websocket() as ws:
        await ws.subscribe_scrips([WsToken(segment, token) for segment, token in tokens])
        async for message in ws:
            yield message
