"""Bulk and block deals from NSE: who bought and sold large blocks of a stock.

NSE publishes two daily files:
  bulk.csv   a client trades more than 0.5% of a company's shares in one day
  block.csv  negotiated block trades (at least 5 lakh shares or Rs 10 crore)

These cover only large trades. They do not show all FII or DII flows, and they
do not show who the company sells to. The published file is one day only, so
`update_deals` appends new rows to data/deals/deals.csv to build a history.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

DEALS_DIR = Path(__file__).resolve().parent.parent / "data" / "deals"
DEALS_FILE = DEALS_DIR / "deals.csv"
SOURCES = {
    "bulk": "https://archives.nseindia.com/content/equities/bulk.csv",
    "block": "https://archives.nseindia.com/content/equities/block.csv",
}
USER_AGENT = "Mozilla/5.0 (IndiaBloom research tool)"
REQUIRED_HEADERS = ("Date", "Symbol", "Client Name", "Buy/Sell", "Quantity Traded")
PRICE_HEADER = "Trade Price / Wght. Avg. Price"
FIELDS = ("date", "symbol", "kind", "client", "side", "quantity", "price", "value_cr")


class DealsError(RuntimeError):
    """Raised when a deals file cannot be fetched or does not match the expected format."""


@dataclass(frozen=True)
class Deal:
    date: str  # ISO date, e.g. 2026-10-23
    symbol: str  # NSE code, e.g. INFY
    kind: str  # "bulk" or "block"
    client: str  # buyer or seller name as NSE publishes it
    side: str  # "BUY" or "SELL"
    quantity: int
    price: float
    value_cr: float  # quantity * price, in rupees crore

    def key(self) -> tuple:
        return (self.date, self.symbol, self.kind, self.client, self.side, self.quantity, self.price)


def parse_deals(text: str, kind: str) -> list[Deal]:
    """Parse one NSE deals file. 'NO RECORDS' (a day with no deals) gives an empty list."""
    if kind not in SOURCES:
        raise DealsError(f"unknown deal kind '{kind}'")
    if text.lstrip().upper().startswith("NO RECORDS"):
        return []
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    missing = [h for h in (*REQUIRED_HEADERS, PRICE_HEADER) if h not in fields]
    if missing:
        raise DealsError(f"{kind} file is missing columns: {', '.join(missing)}")

    out: list[Deal] = []
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            when = datetime.strptime((row["Date"] or "").strip(), "%d-%b-%Y").date().isoformat()
            quantity = int(float((row["Quantity Traded"] or "0").replace(",", "")))
            price = float((row[PRICE_HEADER] or "0").replace(",", ""))
        except (ValueError, TypeError):
            continue  # skip malformed rows instead of failing the whole file
        side = (row.get("Buy/Sell") or "").strip().upper()
        if side not in ("BUY", "SELL"):
            continue
        out.append(Deal(
            date=when, symbol=symbol, kind=kind,
            client=" ".join((row.get("Client Name") or "").split()),
            side=side, quantity=quantity, price=price,
            value_cr=quantity * price / 1e7,
        ))
    return out


def fetch_deals(kind: str, timeout: float = 20.0) -> list[Deal]:
    request = urllib.request.Request(SOURCES[kind], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8-sig")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DealsError(f"could not fetch NSE {kind} deals: {exc}") from exc
    return parse_deals(text, kind)


def load_history(path: Path = DEALS_FILE) -> list[Deal]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            Deal(date=r["date"], symbol=r["symbol"], kind=r["kind"], client=r["client"],
                 side=r["side"], quantity=int(r["quantity"]), price=float(r["price"]),
                 value_cr=float(r["value_cr"]))
            for r in csv.DictReader(handle)
        ]


def merge_history(existing: list[Deal], new: list[Deal]) -> tuple[list[Deal], int]:
    """Union of both lists without duplicates. Returns (merged, number added)."""
    seen = {d.key() for d in existing}
    added = []
    for deal in new:
        if deal.key() not in seen:
            seen.add(deal.key())
            added.append(deal)
    return [*existing, *added], len(added)


def save_history(deals: list[Deal], path: Path = DEALS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(deals, key=lambda d: (d.date, d.symbol, d.kind, d.side, d.client))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for deal in ordered:
            writer.writerow(asdict(deal))


def update_deals(path: Path = DEALS_FILE, fetch=fetch_deals) -> tuple[int, int]:
    """Fetch today's bulk and block files and merge them into the history. Returns (fetched, added)."""
    new: list[Deal] = []
    for kind in SOURCES:
        new.extend(fetch(kind))
    merged, added = merge_history(load_history(path), new)
    save_history(merged, path)
    return len(new), added


def deals_for(symbol: str, deals: list[Deal]) -> list[Deal]:
    """Deals for one NSE symbol (no .NS suffix), newest first."""
    code = symbol.removesuffix(".NS").upper()
    return sorted((d for d in deals if d.symbol == code),
                  key=lambda d: (d.date, d.value_cr), reverse=True)
