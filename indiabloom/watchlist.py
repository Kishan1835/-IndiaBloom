"""Watchlist and positions: stocks you follow, with optional buy price and quantity.

Stored in data/watchlist.json. This file holds your holdings, so it is git-ignored.
A position with no buy price or quantity is just a watched stock. P&L appears
only when both are set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WATCHLIST_FILE = Path(__file__).resolve().parent.parent / "data" / "watchlist.json"


@dataclass(frozen=True)
class Position:
    ticker: str  # yfinance ticker, e.g. INFY.NS
    buy_price: float | None = None  # per share
    quantity: float | None = None


def load_watchlist(path: Path = WATCHLIST_FILE) -> list[Position]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Position(ticker=item["ticker"], buy_price=item.get("buy_price"), quantity=item.get("quantity"))
            for item in data.get("items", [])]


def save_watchlist(positions: list[Position], path: Path = WATCHLIST_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = [
        {"ticker": p.ticker, "buy_price": p.buy_price, "quantity": p.quantity}
        for p in sorted(positions, key=lambda p: p.ticker)
    ]
    path.write_text(json.dumps({"items": items}, indent=1), encoding="utf-8")


def add_position(positions: list[Position], ticker: str, buy_price: float | None = None,
                 quantity: float | None = None) -> list[Position]:
    """Add a stock, or replace its entry if it is already there."""
    rest = [p for p in positions if p.ticker != ticker]
    return [*rest, Position(ticker, buy_price, quantity)]


def remove_position(positions: list[Position], ticker: str) -> list[Position]:
    return [p for p in positions if p.ticker != ticker]


def find_position(positions: list[Position], ticker: str) -> Position | None:
    return next((p for p in positions if p.ticker == ticker), None)


def position_rows(position: Position, last: float | None) -> list[tuple[str, str]]:
    """Display rows (metric, value) for one position at the last price."""
    def money(value: float | None) -> str:
        return "-" if value is None else f"{value:,.2f}"

    cost = None
    value = None
    pnl = None
    pnl_pct = None
    if position.buy_price is not None and position.quantity is not None:
        cost = position.buy_price * position.quantity
        if last is not None:
            value = last * position.quantity
            pnl = value - cost
            pnl_pct = pnl / cost * 100 if cost else None
    return [
        ("Buy price (Rs)", money(position.buy_price)),
        ("Quantity", "-" if position.quantity is None else f"{position.quantity:,g}"),
        ("Cost (Rs)", money(cost)),
        ("Last price (Rs)", money(last)),
        ("Market value (Rs)", money(value)),
        ("P&L (Rs)", "-" if pnl is None else f"{pnl:+,.2f}"),
        ("P&L %", "-" if pnl_pct is None else f"{pnl_pct:+.2f}%"),
    ]
