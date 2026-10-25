"""CSV export for the terminal's tables: screens, movers, watchlist P&L and stock lists.

Files go to data/exports/ by default. Exports are your own working files, so the
folder is git-ignored. Numbers in the watchlist export are plain (no thousands
separators) so spreadsheets can sum them. The file is UTF-8 with a BOM so Excel
reads company names correctly.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from indiabloom.watchlist import Position

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"
_UNSAFE = str.maketrans({c: "-" for c in '<>:"/\\|?* ^'})


def export_path(view: str, ticker: str = "", now: datetime | None = None,
                directory: Path = EXPORTS_DIR) -> Path:
    """data/exports/<view>[-<ticker>]-<timestamp>.csv, with characters unsafe in file names replaced."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    name = f"{view}-{ticker}" if ticker else view
    return directory / f"{name.translate(_UNSAFE)}-{stamp}.csv"


def write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return path


WATCHLIST_HEADERS = ["TICKER", "BUY", "QTY", "LAST", "COST", "VALUE", "PNL", "PNL_PCT"]


def watchlist_rows(positions: list[Position], last_prices: dict[str, float]) -> list[list[object]]:
    """One row per watched stock. Cost, value and P&L are blank unless buy price and quantity are set."""
    rows: list[list[object]] = []
    for p in sorted(positions, key=lambda p: p.ticker):
        last = last_prices.get(p.ticker)
        cost = p.buy_price * p.quantity if p.buy_price is not None and p.quantity is not None else None
        value = last * p.quantity if last is not None and p.quantity is not None else None
        pnl = value - cost if cost is not None and value is not None else None
        pnl_pct = pnl / cost * 100 if pnl is not None and cost else None
        rows.append([
            p.ticker,
            "" if p.buy_price is None else round(p.buy_price, 4),
            "" if p.quantity is None else p.quantity,
            "" if last is None else round(last, 4),
            "" if cost is None else round(cost, 2),
            "" if value is None else round(value, 2),
            "" if pnl is None else round(pnl, 2),
            "" if pnl_pct is None else round(pnl_pct, 2),
        ])
    return rows
