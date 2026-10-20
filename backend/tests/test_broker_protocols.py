import struct
from app.brokers.dhan import parse_ticker_packet, subscribe_message
from app.brokers.fivepaisa import subscribe_payload


def test_dhan_subscribe_chunks_contracts_and_uses_v2_fields():
    msg = subscribe_message([{"segment": "NSE_FNO", "security_id": "123"}])
    assert msg == {"RequestCode": 15, "InstrumentCount": 1, "InstrumentList": [{"ExchangeSegment": "NSE_FNO", "SecurityId": "123"}]}


def test_dhan_ticker_packet_normalizes_header_and_ltp():
    packet = struct.pack("<BHBIfI", 2, 16, 2, 123, 101.25, 36000)
    quote = parse_ticker_packet(packet, {"2:123": {"underlying": "NIFTY", "exchange": "NSE", "segment": "NSE_FNO", "symbol": "NIFTY OPT", "expiry": "2030-01-01", "strike": 100, "option_type": "CE"}})
    assert quote is not None and quote.ltp == 101.25
    assert quote.broker == "Dhan" and quote.exchange_time == "36000"


def test_fivepaisa_market_feed_subscription_shape():
    import json
    data = json.loads(subscribe_payload("client", [{"exchange": "N", "exchange_type": "D", "scrip_code": "123"}]))
    assert data["Method"] == "MarketFeedV3"
    assert data["MarketFeedData"] == [{"Exch": "N", "ExchType": "D", "ScripCode": 123}]
