from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable

BROKERS = ("Dhan", "Kotak Neo", "5paisa")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def leg_pnl(direction: int, avg_entry: float, current: float, lots: int, lot_size: int) -> float:
    """Weighted-average accounting: direction=+1 long, -1 short."""
    return direction * (current - avg_entry) * lots * lot_size


def validate_leg(leg: dict) -> None:
    required = ("underlying", "expiry", "strike", "option_type", "side", "lots", "lot_size", "entry_price")
    missing = [name for name in required if name not in leg]
    if missing:
        raise ValueError(f"Missing leg fields: {', '.join(missing)}")
    if leg["option_type"] not in {"CE", "PE"}:
        raise ValueError("Option type must be CE or PE")
    if leg["side"] not in {"BUY", "SELL"}:
        raise ValueError("Side must be BUY or SELL")
    for field in ("strike", "entry_price"):
        if not isfinite(float(leg[field])) or float(leg[field]) < 0:
            raise ValueError(f"{field} must be a finite non-negative number")
    if int(leg["lots"]) < 1 or int(leg["lot_size"]) < 1:
        raise ValueError("Lots and lot size must be positive integers")


def option_payoff(legs: Iterable[dict], underlying_price: float) -> float:
    total = 0.0
    for leg in legs:
        sign = 1 if leg["side"] in ("BUY", 1) else -1
        intrinsic = max(underlying_price - float(leg["strike"]), 0) if leg["option_type"] == "CE" else max(float(leg["strike"]) - underlying_price, 0)
        premium = float(leg.get("entry_price", leg.get("avg_entry", 0)))
        total += sign * (intrinsic - premium) * int(leg["lots"]) * int(leg["lot_size"])
    return total


def payoff_summary(legs: list[dict]) -> dict:
    if not legs:
        return {"net_premium": 0, "max_profit": 0, "max_loss": 0, "breakevens": [], "curve": []}
    strikes = [float(x["strike"]) for x in legs]
    span = max(max(strikes) * 0.15, 1000)
    low, high = max(0, min(strikes) - span), max(strikes) + span
    points = 81
    curve = [{"underlying": round(low + (high - low) * i / (points - 1), 2), "pnl": round(option_payoff(legs, low + (high - low) * i / (points - 1)), 2)} for i in range(points)]
    premium = sum((1 if x["side"] == "SELL" else -1) * float(x.get("entry_price", x.get("avg_entry", 0))) * int(x["lots"]) * int(x["lot_size"]) for x in legs)
    ys = [v["pnl"] for v in curve]
    call_exposure = sum((1 if x["side"] == "BUY" else -1) * int(x["lots"]) * int(x["lot_size"]) for x in legs if x["option_type"] == "CE")
    breakevens = []
    for left, right in zip(curve, curve[1:]):
        if left["pnl"] == 0:
            breakevens.append(left["underlying"])
        elif left["pnl"] * right["pnl"] < 0:
            x = left["underlying"] + abs(left["pnl"]) / (abs(left["pnl"]) + abs(right["pnl"])) * (right["underlying"] - left["underlying"])
            breakevens.append(round(x, 2))
    return {"net_premium": round(premium, 2), "max_profit": None if call_exposure > 0 else round(max(ys), 2), "max_loss": None if call_exposure < 0 else round(min(ys), 2), "breakevens": breakevens, "curve": curve}
