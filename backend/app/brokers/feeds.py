from __future__ import annotations
import asyncio
import json
import os
import random
from urllib.parse import quote
import websockets
from datetime import date
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Instrument
from .base import NormalizedQuote
from .dhan import DhanSegments, parse_ticker_packet, subscribe_message
from .fivepaisa import subscribe_payload, to_normalized_feed
from .kotak_neo import iter_sfeed, to_normalized_sfeed


class FeedManager:
    """Independent read-only streams. Each reconnect rebuilds subscriptions from the latest imported master."""
    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}
        self.runtime = {broker: {"state": "Disconnected", "last_quote": None, "error": None, "reconnects": 0} for broker in ("Dhan", "Kotak Neo", "5paisa")}
        self.sink = None

    def status(self):
        return [{"broker": k, **v} for k, v in self.runtime.items()]

    def start(self):
        configured = {
            "Dhan": all(os.getenv(x) for x in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN")),
            "Kotak Neo": all(os.getenv(x) for x in ("KOTAK_CONSUMER_KEY", "KOTAK_MOBILE_NUMBER", "KOTAK_UCC", "KOTAK_MPIN")) and bool(os.getenv("KOTAK_TOTP") or os.getenv("KOTAK_TOTP_SECRET")),
            "5paisa": all(os.getenv(x) for x in ("FIVEPAISA_CLIENT_CODE", "FIVEPAISA_ACCESS_TOKEN")),
        }
        runners = {"Dhan": self._dhan_loop, "Kotak Neo": self._kotak_loop, "5paisa": self._fivepaisa_loop}
        for broker, is_configured in configured.items():
            if is_configured and broker not in self.tasks:
                self.tasks[broker] = asyncio.create_task(runners[broker](), name=f"feed-{broker}")
            elif not is_configured:
                self.runtime[broker]["state"] = "Needs credentials"

    async def _emit(self, quote: NormalizedQuote):
        if self.sink:
            await self.sink({
                "instrument_id": quote.instrument_id, "underlying": quote.underlying,
                "exchange": quote.exchange, "segment": quote.segment, "symbol": quote.symbol,
                "expiry": quote.expiry, "strike": quote.strike, "option_type": quote.option_type,
                "broker": quote.broker, "ltp": quote.ltp, "bid": quote.bid, "ask": quote.ask,
                "volume": quote.volume, "open_interest": quote.open_interest,
                "exchange_time": quote.exchange_time, "sequence": quote.sequence, "status": quote.status,
            })
        self.runtime[quote.broker]["last_quote"] = quote.received_at
        self.runtime[quote.broker]["state"] = "Connected"
        self.runtime[quote.broker]["error"] = None

    def _master(self, broker: str):
        db: Session = SessionLocal()
        try:
            rows = [dict(id=x.id, broker=x.broker, underlying=x.underlying, exchange=x.exchange, segment=x.segment, symbol=x.symbol, expiry=x.expiry, strike=x.strike, option_type=x.option_type, lot_size=x.lot_size, token=x.token) for x in db.query(Instrument).filter_by(broker=broker).all()]
            roots = {x.strip().upper() for x in os.getenv("FEED_UNDERLYINGS", "NIFTY,BANKNIFTY,SENSEX,GOLD,GOLDM,GOLDPETAL,SILVER,SILVERM,SILVERMIC,CRUDEOIL,CRUDEOILM,NATURALGAS,NATGASMINI,COPPER,ZINC,ALUMINIUM,LEAD,NICKEL").split(",") if x.strip()}
            valid = [x for x in rows if x["underlying"].upper() in roots and x["option_type"] in {"CE", "PE"} and x["expiry"] >= date.today().isoformat()]
            by_root = {}
            for row in sorted(valid, key=lambda x: (x["underlying"], x["expiry"])):
                by_root.setdefault(row["underlying"], set()).add(row["expiry"])
            allowed = {root: set(sorted(expiries)[:4]) for root, expiries in by_root.items()}
            return [x for x in valid if x["expiry"] in allowed.get(x["underlying"], set())]
        finally:
            db.close()

    async def _reconnect(self, broker, runner):
        delay = 1
        while True:
            try:
                self.runtime[broker]["state"] = "Connecting"
                self.runtime[broker]["error"] = None
                await runner()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.runtime[broker]["state"] = "Disconnected"
                # Exception strings can contain broker response data; trim and never expose request URLs or credentials.
                self.runtime[broker]["error"] = type(exc).__name__
                self.runtime[broker]["reconnects"] += 1
                await asyncio.sleep(delay + random.random() * 0.5)
                delay = min(delay * 2, 30)

    async def _dhan_loop(self):
        await self._reconnect("Dhan", self._dhan_once)

    async def _dhan_once(self):
        rows = self._master("Dhan")
        if not rows:
            self.runtime["Dhan"]["state"] = "Import Dhan instrument master"
            await asyncio.sleep(15)
            return
        by_key, items = {}, []
        for row in rows:
            segment = row["segment"].upper().replace(" ", "_")
            code = DhanSegments.get(segment)
            if code is None:
                continue
            by_key[f"{code}:{row['token']}"] = {"underlying": row["underlying"], "exchange": row["exchange"], "segment": segment, "symbol": row["symbol"], "expiry": row["expiry"], "strike": row["strike"], "option_type": row["option_type"]}
            items.append({"segment": segment, "security_id": row["token"]})
        if not items:
            self.runtime["Dhan"]["state"] = "No supported option rows in instrument master"
            await asyncio.sleep(15)
            return
        url = "wss://api-feed.dhan.co?version=2&token=" + quote(os.environ["DHAN_ACCESS_TOKEN"], safe="") + "&clientId=" + quote(os.environ["DHAN_CLIENT_ID"], safe="") + "&authType=2"
        async with websockets.connect(url, ping_interval=20, ping_timeout=40, max_size=2**20) as ws:
            for start in range(0, len(items), 100):
                await ws.send(json.dumps(subscribe_message(items[start:start+100])))
            self.runtime["Dhan"]["state"] = "Connected"
            async for packet in ws:
                if isinstance(packet, bytes):
                    quote_obj = parse_ticker_packet(packet, by_key)
                    if quote_obj:
                        await self._emit(quote_obj)

    async def _kotak_loop(self):
        await self._reconnect("Kotak Neo", self._kotak_once)

    async def _kotak_once(self):
        rows = self._master("Kotak Neo")
        if not rows:
            self.runtime["Kotak Neo"]["state"] = "Import Kotak Neo instrument master"
            await asyncio.sleep(15)
            return
        try:
            from neo_api_client import NeoAPI
        except ImportError as exc:
            raise RuntimeError("Install kotakneoapi SDK") from exc
        client = NeoAPI(consumer_key=os.environ["KOTAK_CONSUMER_KEY"], environment="prod")
        totp_code = os.getenv("KOTAK_TOTP")
        if os.getenv("KOTAK_TOTP_SECRET"):
            import pyotp
            totp_code = pyotp.TOTP(os.environ["KOTAK_TOTP_SECRET"]).now()
        if not totp_code:
            raise RuntimeError("Configure Kotak Neo TOTP")
        await asyncio.to_thread(client.totp_login, mobile_number=os.environ["KOTAK_MOBILE_NUMBER"], ucc=os.environ["KOTAK_UCC"], totp=totp_code)
        await asyncio.to_thread(client.totp_validate, mpin=os.environ["KOTAK_MPIN"])
        meta = {str(row["token"]): {"underlying": row["underlying"], "exchange": row["exchange"], "segment": row["segment"], "symbol": row["symbol"], "expiry": row["expiry"], "strike": row["strike"], "option_type": row["option_type"]} for row in rows}
        tokens = [(row["segment"], row["token"]) for row in rows]
        async for message in iter_sfeed(client, tokens):
            message_token = str(getattr(message, "instrument_token", ""))
            info = meta.get(message_token)
            if not info:
                continue
            quote_obj = to_normalized_sfeed(message, {"instrument_id": message_token, **info})
            if quote_obj:
                await self._emit(quote_obj)

    async def _fivepaisa_loop(self):
        await self._reconnect("5paisa", self._fivepaisa_once)

    async def _fivepaisa_once(self):
        rows = self._master("5paisa")
        if not rows:
            self.runtime["5paisa"]["state"] = "Import 5paisa instrument master"
            await asyncio.sleep(15)
            return
        url = "wss://openfeed.5paisa.com/feeds/api/chat?Value1=" + quote(os.environ["FIVEPAISA_ACCESS_TOKEN"], safe="") + "|" + quote(os.environ["FIVEPAISA_CLIENT_CODE"], safe="")
        instrument_map = {int(row["token"]): {"instrument_id": str(row["token"]), "underlying": row["underlying"], "exchange": row["exchange"], "segment": row["segment"], "symbol": row["symbol"], "expiry": row["expiry"], "strike": row["strike"], "option_type": row["option_type"]} for row in rows if str(row["token"]).isdigit()}
        instruments = [{"exchange": row["exchange"], "exchange_type": row["segment"], "scrip_code": row["token"]} for row in rows if str(row["token"]).isdigit()]
        async with websockets.connect(url, ping_interval=20, ping_timeout=40, max_size=2**20) as ws:
            for start in range(0, len(instruments), 100):
                await ws.send(subscribe_payload(os.environ["FIVEPAISA_CLIENT_CODE"], instruments[start:start+100]))
            self.runtime["5paisa"]["state"] = "Connected"
            async for raw in ws:
                payload = json.loads(raw)
                for event in payload if isinstance(payload, list) else [payload]:
                    quote_obj = to_normalized_feed(event, instrument_map)
                    if quote_obj:
                        await self._emit(quote_obj)


feed_manager = FeedManager()
