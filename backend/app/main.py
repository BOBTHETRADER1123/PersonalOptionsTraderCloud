from __future__ import annotations
import asyncio
import csv
import hashlib
import hmac
import io
import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, joinedload
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .domain import BROKERS, leg_pnl, payoff_summary, utc_iso, validate_leg
from .exporter import write_trade_workbook, write_async
from .journal import append_journal
from .models import AuditLog, IdempotencyRecord, Instrument, Leg, PendingPaperOrder, PnLSnapshot, QuoteEvent, Trade, TradeEvent
from .brokers.status import broker_status
from .brokers.feeds import feed_manager

Base.metadata.create_all(bind=engine)


def ensure_trade_extrema_columns():
    existing = {column["name"] for column in inspect(engine).get_columns("trades")}
    columns = ("max_profit_pnl", "max_profit_at", "max_loss_pnl", "max_loss_at")
    with engine.begin() as connection:
        for name in columns:
            if name not in existing:
                sql_type = Trade.__table__.c[name].type.compile(dialect=engine.dialect)
                connection.exec_driver_sql(f"ALTER TABLE trades ADD COLUMN {name} {sql_type}")


ensure_trade_extrema_columns()


@asynccontextmanager
async def lifespan(_app):
    settings.data_path.mkdir(parents=True, exist_ok=True)
    backfill_trade_extrema()
    replay_quote_journal()
    feed_manager.start()
    yield
    tasks = list(feed_manager.tasks.values())
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Personal Options Trader", version="0.1.0", description="Paper trading and read-only market data; no live order submission.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"])

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
SESSION_COOKIE = "pot_session"
CSRF_COOKIE = "pot_csrf"
websocket_clients: set[WebSocket] = set()
login_failures: dict[str, list[float]] = {}


class LoginBody(BaseModel):
    password: str


class LegInput(BaseModel):
    underlying: str = "NIFTY"
    expiry: str
    strike: float = Field(gt=0)
    option_type: str
    side: str
    lots: int = Field(ge=1)
    lot_size: int = Field(ge=1)
    entry_price: float = Field(ge=0)
    symbol: str | None = None


class ActionBody(BaseModel):
    action: str = "NEW_TRADE"
    action_id: str | None = None
    order_type: str = "MARKET"
    trade_id: str | None = None
    leg_id: str | None = None
    brokers: list[str] = Field(default_factory=lambda: ["Dhan"])
    strategy: str = Field(default="Custom", max_length=80)
    underlying: str = "NIFTY"
    legs: list[LegInput] = Field(default_factory=list)
    lots: int | None = None
    exit_price: float | None = None
    assumed_entry_price: float | None = None
    note: str = ""


class QuoteInput(BaseModel):
    instrument_id: str
    underlying: str
    exchange: str = "NSE"
    segment: str = "NFO"
    symbol: str
    expiry: str = ""
    strike: float = 0
    option_type: str = ""
    broker: str
    ltp: float = Field(ge=0)
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    exchange_time: str | None = None
    sequence: str | None = None
    status: str = "LIVE"


class InstrumentRow(BaseModel):
    broker: str = "Manual"
    underlying: str
    exchange: str
    segment: str
    symbol: str
    expiry: str
    strike: float
    option_type: str
    lot_size: int
    token: str


def _cookie_signature(token: str) -> str:
    return hmac.new(settings.app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def _valid_session(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE, "")
    sig = request.cookies.get(CSRF_COOKIE, "")
    return bool(token and sig and hmac.compare_digest(sig, _cookie_signature(token)))


def _verify_password(candidate: str) -> bool:
    encoded = settings.app_password_hash
    if not encoded:
        return hmac.compare_digest(candidate, settings.app_password)
    try:
        algorithm, salt, expected = encoded.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", candidate.encode(), salt.encode(), 310000).hex()
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


async def require_session(request: Request):
    if not _valid_session(request):
        raise HTTPException(status_code=401, detail="Please sign in")


async def require_csrf(request: Request):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not csrf or not cookie or not hmac.compare_digest(csrf, cookie):
            raise HTTPException(status_code=403, detail="CSRF validation failed")


def now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def event_record(db: Session, trade: Trade, leg: Leg | None, event_type: str, action_id: str, details: dict):
    event = TradeEvent(event_id=str(uuid.uuid4()), action_id=action_id, trade_id=trade.id, leg_id=leg.id if leg else None, event_type=event_type, occurred_at=now(), details=details)
    db.add(event)
    append_journal({"kind": "trade_event", "event_id": event.event_id, "action_id": action_id, "trade_id": trade.id, "leg_id": event.leg_id, "event_type": event_type, "occurred_at": event.occurred_at.isoformat(), "details": details})
    return event


def leg_symbol(data: LegInput) -> str:
    return data.symbol or f"{data.underlying} {data.expiry} {data.strike:g} {data.option_type}"


def broker_instrument(db: Session, broker: str, data: LegInput) -> Instrument | None:
    return db.query(Instrument).filter_by(
        broker=broker,
        underlying=data.underlying,
        expiry=data.expiry,
        strike=data.strike,
        option_type=data.option_type,
    ).first()


def create_leg(db: Session, trade: Trade, data: LegInput, action_id: str) -> Leg:
    payload = data.model_dump()
    validate_leg(payload)
    contract = broker_instrument(db, trade.broker, data)
    direction = 1 if data.side == "BUY" else -1
    fill_price = max(0.0, data.entry_price + direction * settings.slippage_points)
    symbol = contract.symbol if contract else leg_symbol(data)
    lot_size = contract.lot_size if contract else data.lot_size
    payload["symbol"] = symbol
    payload["lot_size"] = lot_size
    leg = Leg(id=str(uuid.uuid4()), trade_id=trade.id, underlying=data.underlying, expiry=data.expiry, strike=data.strike, option_type=data.option_type, symbol=symbol, direction=direction, lot_size=lot_size, open_lots=data.lots, avg_entry=fill_price, mark=fill_price, charges=settings.charge_per_order, broker=trade.broker)
    db.add(leg)
    event_record(db, trade, leg, "ENTRY", action_id, {**payload, "requested_price": data.entry_price, "fill_price": fill_price, "slippage_points": settings.slippage_points, "charges": settings.charge_per_order, "fill_model": "user-entered paper price", "mode": "PAPER"})
    return leg


def serialize_leg(leg: Leg) -> dict:
    gross_unrealized = leg_pnl(leg.direction, leg.avg_entry, leg.mark, leg.open_lots, leg.lot_size)
    return {"id": leg.id, "trade_id": leg.trade_id, "broker": leg.broker, "underlying": leg.underlying, "expiry": leg.expiry, "strike": leg.strike, "option_type": leg.option_type, "symbol": leg.symbol, "side": "BUY" if leg.direction == 1 else "SELL", "lot_size": leg.lot_size, "open_lots": leg.open_lots, "avg_entry": leg.avg_entry, "mark": leg.mark, "realized_pnl": leg.realized_pnl, "unrealized_pnl": gross_unrealized, "charges": leg.charges, "net_pnl": leg.realized_pnl + gross_unrealized - leg.charges}


def serialize_trade(trade: Trade) -> dict:
    legs = [serialize_leg(leg) for leg in trade.legs]
    created = as_utc(trade.created_at)
    closed = as_utc(trade.closed_at)
    best_at = as_utc(trade.max_profit_at)
    worst_at = as_utc(trade.max_loss_at)
    return {"id": trade.id, "action_id": trade.action_id, "strategy": trade.strategy, "broker": trade.broker, "underlying": trade.underlying, "status": trade.status, "created_at": created.isoformat(), "closed_at": closed.isoformat() if closed else None, "legs": legs, "realized_pnl": sum(x["realized_pnl"] for x in legs), "unrealized_pnl": sum(x["unrealized_pnl"] for x in legs), "charges": sum(x["charges"] for x in legs), "net_pnl": sum(x["net_pnl"] for x in legs), "max_profit_pnl": trade.max_profit_pnl, "max_profit_at": best_at.isoformat() if best_at else None, "max_loss_pnl": trade.max_loss_pnl, "max_loss_at": worst_at.isoformat() if worst_at else None}


def trade_net_pnl(legs: list[Leg]) -> float:
    return round(sum(leg.realized_pnl + leg_pnl(leg.direction, leg.avg_entry, leg.mark, leg.open_lots, leg.lot_size) - leg.charges for leg in legs), 2)


def update_trade_extrema(db: Session, trade: Trade, occurred_at: datetime):
    value = trade_net_pnl(db.query(Leg).filter_by(trade_id=trade.id).all())
    stamp = as_utc(occurred_at) or now()
    if trade.max_profit_pnl is None or value > trade.max_profit_pnl:
        trade.max_profit_pnl, trade.max_profit_at = value, stamp
    if trade.max_loss_pnl is None or value < trade.max_loss_pnl:
        trade.max_loss_pnl, trade.max_loss_at = value, stamp


def backfill_trade_extrema():
    db = SessionLocal()
    try:
        trades = db.query(Trade).filter((Trade.max_profit_pnl.is_(None)) | (Trade.max_loss_pnl.is_(None))).all()
        for trade in trades:
            has_profit = trade.max_profit_pnl is not None
            has_loss = trade.max_loss_pnl is not None
            per_leg: dict[str, float] = {}
            snapshots = db.query(PnLSnapshot).filter_by(trade_id=trade.id).order_by(PnLSnapshot.event_at, PnLSnapshot.id).all()
            for snapshot in snapshots:
                per_leg[snapshot.leg_id] = snapshot.net_pnl
                value = round(sum(per_leg.values()), 2)
                stamp = as_utc(snapshot.event_at)
                if not has_profit and (trade.max_profit_pnl is None or value > trade.max_profit_pnl):
                    trade.max_profit_pnl, trade.max_profit_at = value, stamp
                if not has_loss and (trade.max_loss_pnl is None or value < trade.max_loss_pnl):
                    trade.max_loss_pnl, trade.max_loss_at = value, stamp
            if trade.status == "CLOSED" and trade.closed_at:
                value = trade_net_pnl(db.query(Leg).filter_by(trade_id=trade.id).all())
                stamp = as_utc(trade.closed_at)
                if not has_profit and (trade.max_profit_pnl is None or value > trade.max_profit_pnl):
                    trade.max_profit_pnl, trade.max_profit_at = value, stamp
                if not has_loss and (trade.max_loss_pnl is None or value < trade.max_loss_pnl):
                    trade.max_loss_pnl, trade.max_loss_at = value, stamp
        db.commit()
    finally:
        db.close()


def snapshot_leg(db: Session, quote: QuoteEvent, leg: Leg):
    if leg.open_lots < 1 or leg.broker != quote.broker or leg.symbol != quote.symbol:
        return
    quote_time, entered = as_utc(quote.received_at), as_utc(leg.entered_at)
    if quote_time and entered and quote_time < entered:
        return
    leg.mark = quote.ltp
    unrealized = leg_pnl(leg.direction, leg.avg_entry, quote.ltp, leg.open_lots, leg.lot_size)
    db.add(PnLSnapshot(quote_event_id=quote.id, trade_id=leg.trade_id, leg_id=leg.id, event_at=quote.received_at,
        instrument=quote.symbol, source_broker=quote.broker, ltp=quote.ltp, bid=quote.bid, ask=quote.ask,
        open_lots=leg.open_lots, avg_entry=leg.avg_entry, unrealized_pnl=unrealized,
        realized_pnl=leg.realized_pnl, charges=leg.charges, net_pnl=leg.realized_pnl+unrealized-leg.charges,
        feed_age_ms=None, sequence=quote.sequence))
    trade = db.get(Trade, leg.trade_id)
    if trade:
        update_trade_extrema(db, trade, quote.received_at)


def apply_quote_to_positions(db: Session, quote: QuoteEvent):
    for leg in db.query(Leg).filter(Leg.symbol == quote.symbol, Leg.broker == quote.broker, Leg.open_lots > 0).all():
        snapshot_leg(db, quote, leg)


def match_pending_orders(db: Session, quote: QuoteEvent):
    for order in db.query(PendingPaperOrder).filter_by(broker=quote.broker, status="PENDING").all():
        leg, trade = db.get(Leg, order.leg_id), db.get(Trade, order.trade_id)
        if not leg or not trade or leg.symbol != quote.symbol or trade.status != "PENDING":
            continue
        order_time, quote_time = as_utc(order.created_at), as_utc(quote.received_at)
        if order_time and quote_time and quote_time < order_time:
            continue
        crossed = quote.ltp <= order.limit_price if order.side == "BUY" else quote.ltp >= order.limit_price
        if not crossed:
            continue
        direction = leg.direction
        fill_price = quote.ltp + direction * settings.slippage_points
        fill_price = min(fill_price, order.limit_price) if direction == 1 else max(fill_price, order.limit_price)
        leg.open_lots = order.lots; leg.avg_entry = fill_price; leg.mark = quote.ltp
        leg.entered_at = quote.received_at; leg.charges = settings.charge_per_order
        trade.status = "OPEN"
        order.status = "FILLED"; order.updated_at = quote.received_at
        event_record(db, trade, leg, "LIMIT_FILLED", order.action_id, {"limit_price": order.limit_price, "quote_price": quote.ltp, "fill_price": fill_price, "lots": order.lots, "slippage_points": settings.slippage_points, "charges": settings.charge_per_order, "mode": "PAPER"})
        snapshot_leg(db, quote, leg)


def _calculate_dashboard(db: Session) -> dict:
    trades = db.query(Trade).options(joinedload(Trade.legs)).order_by(Trade.created_at.desc()).all()
    serialized = [serialize_trade(t) for t in trades]
    open_trades = [t for t in serialized if t["status"] == "OPEN"]
    closed = [t for t in serialized if t["status"] == "CLOSED"]
    by_broker = {broker: {"realized": 0.0, "unrealized": 0.0, "net": 0.0, "open_trades": 0} for broker in BROKERS}
    for trade in serialized:
        slot = by_broker.setdefault(trade["broker"], {"realized": 0.0, "unrealized": 0.0, "net": 0.0, "open_trades": 0})
        slot["realized"] += trade["realized_pnl"]
        slot["unrealized"] += trade["unrealized_pnl"]
        slot["net"] += trade["net_pnl"]
        slot["open_trades"] += trade["status"] == "OPEN"
    q = db.query(QuoteEvent).order_by(QuoteEvent.received_at.desc()).all()
    latest = {}
    for quote in q:
        if quote.event_key not in latest:
            age = (now() - quote.received_at.replace(tzinfo=timezone.utc) if quote.received_at.tzinfo is None else now() - quote.received_at).total_seconds()
            latest[quote.event_key] = {"instrument_id": quote.instrument_id, "underlying": quote.underlying, "symbol": quote.symbol, "expiry": quote.expiry, "strike": quote.strike, "option_type": quote.option_type, "broker": quote.broker, "ltp": quote.ltp, "bid": quote.bid, "ask": quote.ask, "volume": quote.volume, "open_interest": quote.open_interest, "exchange_time": quote.exchange_time, "received_at": quote.received_at.isoformat(), "sequence": quote.sequence, "status": quote.source_status, "age_seconds": round(max(0, age), 3), "stale": age > settings.quote_stale_seconds}
    today = now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    todays = [t for t in serialized if datetime.fromisoformat(t["created_at"]).astimezone(ZoneInfo("Asia/Kolkata")).date() == today]
    runtime_status = {x["broker"]: x for x in feed_manager.status()}
    brokers = [{**x, "feed": runtime_status.get(x["broker"], {})} for x in broker_status()]
    return {"mode": "PAPER", "live_trading_enabled": False, "summary": {"realized_pnl": round(sum(t["realized_pnl"] for t in serialized), 2), "unrealized_pnl": round(sum(t["unrealized_pnl"] for t in open_trades), 2), "net_pnl": round(sum(t["net_pnl"] for t in serialized), 2), "today_pnl": round(sum(t["net_pnl"] for t in todays), 2), "open_trades": len(open_trades), "closed_trades": len(closed)}, "broker_pnl": by_broker, "trades": serialized, "quotes": list(latest.values()), "brokers": brokers, "server_time": utc_iso()}


async def _broadcast(payload: dict):
    dead = []
    for ws in list(websocket_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        websocket_clients.discard(ws)


def replay_quote_journal():
    path = settings.data_path / "journal" / "events.jsonl"
    if not path.exists():
        return
    db = SessionLocal()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") != "quote":
                continue
            if db.query(QuoteEvent.id).filter_by(event_key=record["event_key"]).first():
                continue
            data = dict(record["quote"])
            data.pop("event_key", None)
            data["received_at"] = datetime.fromisoformat(data["received_at"])
            quote = QuoteEvent(event_key=record["event_key"], **data)
            db.add(quote)
            db.flush()
            apply_quote_to_positions(db, quote)
            match_pending_orders(db, quote)
        db.commit()
    finally:
        db.close()


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {"authenticated": _valid_session(request), "csrf_token": request.cookies.get(CSRF_COOKIE) if _valid_session(request) else None}


@app.post("/api/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    peer_key = request.client.host if request.client else "unknown"
    attempts = [x for x in login_failures.get(peer_key, []) if time.time() - x < 300]
    if len(attempts) >= 8:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Wait five minutes and try again.")
    if not _verify_password(body.password):
        attempts.append(time.time())
        login_failures[peer_key] = attempts
        raise HTTPException(status_code=401, detail="Password did not match")
    login_failures.pop(peer_key, None)
    token = secrets.token_urlsafe(40)
    csrf = _cookie_signature(token)
    secure = settings.cookie_secure
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="strict", max_age=43200)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="strict", max_age=43200)
    return {"authenticated": True, "csrf_token": csrf}


@app.post("/api/auth/logout", dependencies=[Depends(require_session), Depends(require_csrf)])
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"authenticated": False}


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "PAPER", "orders_enabled": False, "time": utc_iso()}


@app.get("/api/state", dependencies=[Depends(require_session)])
def get_state(db: Session = Depends(get_db)):
    return _calculate_dashboard(db)


@app.get("/api/instruments", dependencies=[Depends(require_session)])
def search_instruments(underlying: str | None = None, q: str | None = None, broker: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(Instrument)
    if broker:
        query = query.filter(Instrument.broker == broker)
    if underlying:
        query = query.filter(Instrument.underlying == underlying)
    if q:
        query = query.filter(Instrument.symbol.ilike(f"%{q}%"))
    rows = query.filter(Instrument.option_type.in_(("CE", "PE"))).order_by(Instrument.expiry, Instrument.strike, Instrument.option_type).limit(min(max(limit, 1), 10000)).all()
    return [dict(id=x.id, broker=x.broker, underlying=x.underlying, exchange=x.exchange, segment=x.segment, symbol=x.symbol, expiry=x.expiry, strike=x.strike, option_type=x.option_type, lot_size=x.lot_size, token=x.token) for x in rows]


@app.get("/api/instrument-roots", dependencies=[Depends(require_session)])
def instrument_roots(broker: str = "Dhan", db: Session = Depends(get_db)):
    rows = db.query(Instrument.underlying).filter(
        Instrument.broker == broker,
        Instrument.option_type.in_(("CE", "PE")),
        Instrument.expiry >= datetime.now().date().isoformat(),
    ).distinct().order_by(Instrument.underlying).all()
    return [row[0] for row in rows]


@app.post("/api/instruments/import", dependencies=[Depends(require_session), Depends(require_csrf)])
async def import_instruments(file: UploadFile = File(...), broker: str = Form("Dhan"), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a broker instrument-master CSV")
    if broker not in BROKERS:
        raise HTTPException(422, "Select Dhan, Kotak Neo, or 5paisa as the instrument-master source")
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    aliases = {"underlying": ["underlying", "root", "root_symbol", "underlying_symbol", "sem_underlying_symbol", "name", "scrip_name", "symbol", "trading_symbol"], "exchange": ["exchange", "exch", "sem_exchange_code", "sem_exm_exch_id"], "segment": ["segment", "exchange_segment", "exchtype", "sem_segment", "sem_exm_segment"], "symbol": ["trading_symbol", "tradingsymbol", "sem_custom_symbol", "scrip_name", "name", "symbol"], "expiry": ["expiry", "expiry_date", "expirydate", "sem_expiry_date"], "strike": ["strike", "strike_price", "strikerate", "sem_strike_price"], "option_type": ["option_type", "optiontype", "right", "cptype", "sem_option_type"], "lot_size": ["lot_size", "lotsize", "lot_units", "sem_lot_units"], "token": ["token", "security_id", "scrip_code", "scripcode", "instrument_token"]}
    normalize_header = lambda name: name.lower().strip().replace(" ", "_").replace("-", "_")
    headers = {normalize_header(name): name for name in reader.fieldnames or []}
    cols = {k: next((headers[name] for name in v if name in headers), None) for k, v in aliases.items()}
    needed = ["underlying", "expiry", "strike", "option_type", "lot_size", "token"]
    missing = [x for x in needed if not cols[x]]
    if missing:
        raise HTTPException(422, f"Could not find required columns: {', '.join(missing)}. Rename CSV columns to recognizable broker master fields.")
    count = 0
    for row in reader:
        try:
            val = lambda key, fallback="": str(row.get(cols[key], fallback) or fallback).strip()
            otype = val("option_type").upper()
            if otype in {"CALL", "CE"}: otype = "CE"
            elif otype in {"PUT", "PE"}: otype = "PE"
            else: continue
            token = val("token")
            underlying_name = val("underlying").upper()
            if "BANK" in underlying_name: underlying_name = "BANKNIFTY"
            elif "SENSEX" in underlying_name: underlying_name = "SENSEX"
            elif "NIFTY" in underlying_name: underlying_name = "NIFTY"
            symbol = val("symbol", underlying_name)
            expiry_raw = val("expiry").strip()
            expiry = ""
            for fmt in ("%Y-%m-%d", "%Y%m%d", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y"):
                try:
                    expiry = datetime.strptime(expiry_raw, fmt).date().isoformat()
                    break
                except ValueError:
                    pass
                try:
                    expiry = datetime.strptime(expiry_raw[:10], fmt).date().isoformat()
                    break
                except ValueError:
                    pass
            if not expiry:
                try: expiry = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00")).date().isoformat()
                except ValueError: continue
            exchange = val("exchange", "NSE").upper()
            segment = val("segment", "NFO").upper()
            if broker == "Dhan":
                if exchange in {"MCX", "M"} or segment in {"MCX", "MCX_COMM", "MCX_FO"}: segment = "MCX_COMM"
                elif segment in {"NFO", "D", "NSE_FNO", "BFO", "BSE_FNO"}: segment = "BSE_FNO" if exchange in {"BSE", "B"} or segment in {"BFO", "BSE_FNO"} else "NSE_FNO"
            elif broker == "Kotak Neo":
                if exchange in {"MCX", "M"} or segment.lower() in {"mcx", "mcx_fo", "mcx_comm"}: segment = "mcx_fo"
                elif segment in {"NFO", "D", "NSE_FNO", "BFO", "BSE_FNO"}: segment = "bse_fo" if exchange in {"BSE", "B"} or segment in {"BFO", "BSE_FNO"} else "nse_fo"
            elif broker == "5paisa":
                exchange = {"NSE": "N", "BSE": "B", "MCX": "M"}.get(exchange, exchange)
                segment = {"NFO": "D", "BFO": "D", "NSE_FNO": "D", "BSE_FNO": "D", "MCX": "D", "MCX_FO": "D", "MCX_COMM": "D", "CASH": "C"}.get(segment, segment)
            strike = float(val("strike").replace(",", ""))
            lot_size = int(float(val("lot_size")))
            if not underlying_name or not token or strike <= 0 or lot_size <= 0: continue
            rec = Instrument(id=f"{broker}:{exchange}:{segment}:{token}", broker=broker, underlying=underlying_name, exchange=exchange, segment=segment, symbol=symbol, expiry=expiry, strike=strike, option_type=otype, lot_size=lot_size, token=token)
            db.merge(rec); count += 1
        except (TypeError, ValueError):
            continue
    db.commit()
    return {"imported": count, "source_file": file.filename, "note": "Imported master records are only as current as the supplied file. Refresh from the broker before use."}


@app.post("/api/actions", dependencies=[Depends(require_session), Depends(require_csrf)])
def paper_action(body: ActionBody, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    action = body.action.upper()
    action_id = body.action_id or str(uuid.uuid4())
    key = idempotency_key or action_id
    duplicate = db.get(IdempotencyRecord, key)
    if duplicate:
        return duplicate.response
    export_trade_id = None
    if action == "NEW_TRADE":
        if not body.legs:
            raise HTTPException(422, "Add at least one option leg")
        if any(b not in BROKERS for b in body.brokers) or not body.brokers:
            raise HTTPException(422, "Select one or more supported brokers")
        if body.order_type not in {"MARKET", "LIMIT"}:
            raise HTTPException(422, "Order type must be MARKET or LIMIT")
        if body.order_type == "LIMIT" and len(body.legs) != 1:
            raise HTTPException(422, "Limit-order simulation currently supports one option leg at a time")
        for leg_data in body.legs:
            try: validate_leg(leg_data.model_dump())
            except ValueError as exc: raise HTTPException(422, str(exc))
        created = []
        for broker in dict.fromkeys(body.brokers):
            trade = Trade(id=str(uuid.uuid4()), action_id=action_id, strategy=body.strategy, broker=broker, underlying=body.underlying, status="PENDING" if body.order_type == "LIMIT" else "OPEN", created_at=now())
            db.add(trade)
            for leg_data in body.legs:
                if body.order_type == "LIMIT":
                    direction = 1 if leg_data.side == "BUY" else -1
                    contract = broker_instrument(db, broker, leg_data)
                    pending_leg = Leg(id=str(uuid.uuid4()), trade_id=trade.id, underlying=leg_data.underlying, expiry=leg_data.expiry, strike=leg_data.strike, option_type=leg_data.option_type, symbol=contract.symbol if contract else leg_symbol(leg_data), direction=direction, lot_size=contract.lot_size if contract else leg_data.lot_size, open_lots=0, avg_entry=leg_data.entry_price, mark=leg_data.entry_price, broker=broker)
                    db.add(pending_leg)
                    db.add(PendingPaperOrder(id=str(uuid.uuid4()), trade_id=trade.id, leg_id=pending_leg.id, action_id=action_id, broker=broker, order_type="LIMIT", side=leg_data.side, limit_price=leg_data.entry_price, lots=leg_data.lots, status="PENDING", created_at=now()))
                    event_record(db, trade, pending_leg, "PENDING_SIMULATION", action_id, {"side": leg_data.side, "lots": leg_data.lots, "limit_price": leg_data.entry_price, "mode": "PAPER"})
                else:
                    create_leg(db, trade, leg_data, action_id)
            db.flush()
            update_trade_extrema(db, trade, trade.created_at)
            created.append(trade)
        db.add(AuditLog(action=action, occurred_at=now(), details={"action_id": action_id, "brokers": body.brokers, "mode": "PAPER"}))
        db.flush()
        response = {"action_id": action_id, "mode": "PAPER", "results": [serialize_trade(t) for t in created], "message": "Limit simulation is pending a qualifying quote." if body.order_type == "LIMIT" else "Simulated in paper mode. No broker order was sent."}
    else:
        if not body.trade_id:
            raise HTTPException(422, "trade_id is required for this action")
        trade = db.query(Trade).options(joinedload(Trade.legs)).filter_by(id=body.trade_id).first()
        if not trade:
            raise HTTPException(404, "Trade not found")
        if action == "CANCEL_PENDING":
            if trade.status != "PENDING":
                raise HTTPException(409, "There is no pending simulation to cancel")
            for pending in db.query(PendingPaperOrder).filter_by(trade_id=trade.id, status="PENDING").all():
                pending.status = "CANCELLED"; pending.updated_at = now()
            trade.status = "CANCELLED"; trade.closed_at = now()
            event_record(db, trade, None, "SIMULATION_CANCELLED", action_id, {"note": body.note, "mode": "PAPER"})
        elif trade.status != "OPEN":
            raise HTTPException(409, "Trade is not open")
        elif action == "ADD_LEG":
            if len(body.legs) != 1: raise HTTPException(422, "Add exactly one leg")
            leg = create_leg(db, trade, body.legs[0], action_id)
        elif action == "ADD_LOTS":
            leg = next((x for x in trade.legs if x.id == body.leg_id), None)
            if not leg or not body.lots or body.lots < 1: raise HTTPException(422, "Choose an open leg and positive lots")
            requested_price = float(body.exit_price if body.exit_price is not None else leg.mark)
            price = max(0.0, requested_price + leg.direction * settings.slippage_points)
            total = leg.open_lots + body.lots
            leg.avg_entry = (leg.avg_entry * leg.open_lots + price * body.lots) / total
            leg.open_lots = total; leg.mark = price; leg.charges += settings.charge_per_order
            event_record(db, trade, leg, "ADDED_LOTS", action_id, {"lots": body.lots, "requested_price": requested_price, "fill_price": price, "slippage_points": settings.slippage_points, "charges": settings.charge_per_order, "mode": "PAPER"})
        elif action in {"PARTIAL_EXIT", "EXIT_LEG", "EXIT_STRATEGY"}:
            selected = [x for x in trade.legs if (action == "EXIT_STRATEGY" or x.id == body.leg_id) and x.open_lots > 0]
            if action != "EXIT_STRATEGY" and not selected: raise HTTPException(422, "Choose an open leg")
            for leg in selected:
                lots_to_close = leg.open_lots if action != "PARTIAL_EXIT" else int(body.lots or 0)
                if lots_to_close < 1 or lots_to_close > leg.open_lots: raise HTTPException(422, "Exit lots must be between one and the open lots")
                requested_price = float(body.exit_price if body.exit_price is not None else leg.mark)
                price = max(0.0, requested_price - leg.direction * settings.slippage_points)
                gross = leg_pnl(leg.direction, leg.avg_entry, price, lots_to_close, leg.lot_size)
                leg.realized_pnl += gross; leg.open_lots -= lots_to_close; leg.mark = price; leg.charges += settings.charge_per_order
                event_record(db, trade, leg, "PARTIAL_EXIT" if leg.open_lots else "EXIT", action_id, {"lots": lots_to_close, "requested_price": requested_price, "fill_price": price, "slippage_points": settings.slippage_points, "gross_realized_pnl": gross, "charges": settings.charge_per_order, "mode": "PAPER"})
            if all(x.open_lots == 0 for x in trade.legs):
                trade.status = "CLOSED"; trade.closed_at = now()
        elif action == "EDIT_TRADE":
            leg = next((x for x in trade.legs if x.id == body.leg_id), None) if body.leg_id else None
            if body.assumed_entry_price is not None:
                if not leg or leg.open_lots < 1 or body.assumed_entry_price < 0:
                    raise HTTPException(422, "Choose an open leg and a non-negative revised entry assumption")
                before = leg.avg_entry
                leg.avg_entry = float(body.assumed_entry_price)
                event_record(db, trade, leg, "CONFIGURATION_CHANGE", action_id, {"field": "avg_entry", "before": before, "after": leg.avg_entry, "note": body.note, "mode": "PAPER"})
            else:
                event_record(db, trade, None, "CONFIGURATION_CHANGE", action_id, {"note": body.note, "mode": "PAPER"})
        elif action == "DUPLICATE_STRATEGY":
            # Duplicate the strategy as a new trade, preserving each leg's original assumptions.
            new = Trade(id=str(uuid.uuid4()), action_id=action_id, strategy=trade.strategy, broker=trade.broker, underlying=trade.underlying, status="OPEN", created_at=now())
            db.add(new)
            for leg in trade.legs:
                if leg.open_lots:
                    copy_input = LegInput(underlying=leg.underlying, expiry=leg.expiry, strike=leg.strike, option_type=leg.option_type, side="BUY" if leg.direction == 1 else "SELL", lots=leg.open_lots, lot_size=leg.lot_size, entry_price=leg.mark, symbol=leg.symbol)
                    create_leg(db, new, copy_input, action_id)
            trade = new
        else:
            raise HTTPException(422, f"Unknown paper action: {action}")
        if trade.status in {"OPEN", "CLOSED"}:
            update_trade_extrema(db, trade, now())
        db.add(AuditLog(action=action, occurred_at=now(), details={"action_id": action_id, "trade_id": trade.id, "mode": "PAPER"}))
        db.flush()
        response = {"action_id": action_id, "mode": "PAPER", "results": [serialize_trade(trade)], "message": "Paper simulation updated."}
        if trade.status == "CLOSED":
            export_trade_id = trade.id
    db.add(IdempotencyRecord(key=key, response=response, created_at=now()))
    db.commit()
    if export_trade_id:
        write_async(export_trade_id, SessionLocal)
    return response


async def save_quote(body: QuoteInput):
    data = body.model_dump()
    received = now()
    fallback_id = f"{body.exchange_time}:{body.ltp}:{body.bid}:{body.ask}:{body.volume}:{body.open_interest}" if body.exchange_time else received.isoformat()
    event_key = f"{body.broker}:{body.instrument_id}:{body.sequence or fallback_id}"
    source_status = data.pop("status")
    quote_row = {**data, "source_status": source_status, "event_key": event_key, "received_at": received.isoformat()}
    db = SessionLocal()
    try:
        existing = db.query(QuoteEvent).filter_by(event_key=event_key).first()
        if not existing:
            append_journal({"kind": "quote", "event_key": event_key, "quote": quote_row})
            fields = {k: v for k, v in data.items() if k != "status"}
            quote = QuoteEvent(event_key=event_key, received_at=received, **fields, source_status=source_status)
            db.add(quote)
            db.flush()
            apply_quote_to_positions(db, quote)
            match_pending_orders(db, quote)
            db.commit()
        accepted = not bool(existing)
    finally:
        db.close()
    payload = {"type": "quote", "quote": {**data, "received_at": received.isoformat(), "status": source_status}}
    await _broadcast(payload)
    return {"accepted": accepted, "event_key": event_key, "received_at": received.isoformat()}


@app.post("/api/quotes", dependencies=[Depends(require_session), Depends(require_csrf)])
async def ingest_quote(body: QuoteInput, db: Session = Depends(get_db)):
    return await save_quote(body)


@app.get("/api/trades/{trade_id}/export", dependencies=[Depends(require_session)])
def export_trade(trade_id: str, db: Session = Depends(get_db)):
    try:
        path = write_trade_workbook(db, trade_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/payoff", dependencies=[Depends(require_session), Depends(require_csrf)])
def payoff(legs: list[dict]):
    try:
        return payoff_summary(legs)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/live-trading")
def live_status():
    return {"enabled": False, "available": False, "reason": "This release has no real-order submission endpoints. All order actions are paper-only."}


@app.websocket("/api/ws")
async def quote_socket(websocket: WebSocket):
    token, csrf = websocket.cookies.get(SESSION_COOKIE, ""), websocket.cookies.get(CSRF_COOKIE, "")
    if not token or not csrf or not hmac.compare_digest(csrf, _cookie_signature(token)):
        await websocket.close(code=4401); return
    await websocket.accept(); websocket_clients.add(websocket)
    try:
        db = SessionLocal()
        try:
            await websocket.send_json({"type": "state", "data": _calculate_dashboard(db)})
        finally:
            db.close()
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        websocket_clients.discard(websocket)


@app.get("/api/recovery")
def recovery_status(request: Request):
    if not _valid_session(request): raise HTTPException(401, "Please sign in")
    journal = settings.data_path / "journal" / "events.jsonl"
    return {"journal_exists": journal.exists(), "journal_path": str(journal), "journal_bytes": journal.stat().st_size if journal.exists() else 0, "replay": "Quote records are reinserted on startup if missing from SQLite. Trade actions are also persisted in SQLite and the journal."}


@app.get("/api/broker-status", dependencies=[Depends(require_session)])
def get_broker_status():
    return feed_manager.status()


if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    index = FRONTEND / "index.html"
    if index.exists(): return FileResponse(index)
    return {"message": "Frontend build is missing. Run npm install and npm run build in frontend/ or use the Vite dev server on port 5173."}
