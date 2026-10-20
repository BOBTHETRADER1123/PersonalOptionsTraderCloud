from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(String(36), index=True)
    strategy: Mapped[str] = mapped_column(String(80), default="Custom")
    broker: Mapped[str] = mapped_column(String(20), index=True)
    underlying: Mapped[str] = mapped_column(String(40), default="NIFTY")
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_profit_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_profit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_loss_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_loss_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legs: Mapped[list["Leg"]] = relationship(back_populates="trade", cascade="all, delete-orphan")
    events: Mapped[list["TradeEvent"]] = relationship(back_populates="trade", cascade="all, delete-orphan")


class Leg(Base):
    __tablename__ = "legs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    underlying: Mapped[str] = mapped_column(String(40))
    expiry: Mapped[str] = mapped_column(String(10))
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(2))
    symbol: Mapped[str] = mapped_column(String(120))
    direction: Mapped[int] = mapped_column(Integer)  # +1 long, -1 short
    lot_size: Mapped[int] = mapped_column(Integer)
    open_lots: Mapped[int] = mapped_column(Integer)
    avg_entry: Mapped[float] = mapped_column(Float)
    mark: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    charges: Mapped[float] = mapped_column(Float, default=0)
    broker: Mapped[str] = mapped_column(String(20))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trade: Mapped[Trade] = relationship(back_populates="legs")


class TradeEvent(Base):
    __tablename__ = "trade_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    action_id: Mapped[str] = mapped_column(String(36), index=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    leg_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    trade: Mapped[Trade] = relationship(back_populates="events")


class QuoteEvent(Base):
    __tablename__ = "quote_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(240), index=True)
    instrument_id: Mapped[str] = mapped_column(String(120), index=True)
    underlying: Mapped[str] = mapped_column(String(40))
    exchange: Mapped[str] = mapped_column(String(20), default="NSE")
    segment: Mapped[str] = mapped_column(String(20), default="NFO")
    symbol: Mapped[str] = mapped_column(String(120))
    expiry: Mapped[str] = mapped_column(String(10), default="")
    strike: Mapped[float] = mapped_column(Float, default=0)
    option_type: Mapped[str] = mapped_column(String(2), default="")
    broker: Mapped[str] = mapped_column(String(20), index=True)
    ltp: Mapped[float] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    sequence: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_status: Mapped[str] = mapped_column(String(20), default="LIVE")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    broker: Mapped[str] = mapped_column(String(20), index=True)
    underlying: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(20))
    segment: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(120), index=True)
    expiry: Mapped[str] = mapped_column(String(10), index=True)
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(2))
    lot_size: Mapped[int] = mapped_column(Integer)
    token: Mapped[str] = mapped_column(String(80))


class PendingPaperOrder(Base):
    __tablename__ = "pending_paper_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    leg_id: Mapped[str] = mapped_column(ForeignKey("legs.id"), index=True)
    action_id: Mapped[str] = mapped_column(String(36), index=True)
    broker: Mapped[str] = mapped_column(String(20), index=True)
    order_type: Mapped[str] = mapped_column(String(10), default="LIMIT")
    side: Mapped[str] = mapped_column(String(4))
    limit_price: Mapped[float] = mapped_column(Float)
    lots: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PnLSnapshot(Base):
    __tablename__ = "pnl_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_event_id: Mapped[int] = mapped_column(ForeignKey("quote_events.id"), index=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    leg_id: Mapped[str] = mapped_column(ForeignKey("legs.id"), index=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    instrument: Mapped[str] = mapped_column(String(120))
    source_broker: Mapped[str] = mapped_column(String(20))
    ltp: Mapped[float] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_lots: Mapped[int] = mapped_column(Integer)
    avg_entry: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float)
    net_pnl: Mapped[float] = mapped_column(Float)
    feed_age_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    sequence: Mapped[str | None] = mapped_column(String(120), nullable=True)
