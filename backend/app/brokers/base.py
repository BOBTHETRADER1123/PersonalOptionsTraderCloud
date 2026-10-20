from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class NormalizedQuote:
    instrument_id: str
    underlying: str
    exchange: str
    segment: str
    symbol: str
    expiry: str
    strike: float
    option_type: str
    broker: str
    ltp: float
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    exchange_time: str | None = None
    sequence: str | None = None
    received_at: str = ""
    status: str = "LIVE"

    def __post_init__(self):
        if not self.received_at:
            self.received_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
