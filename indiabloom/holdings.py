"""Shareholding history: how the insider and institutional percentages change over time.

yfinance publishes only aggregate percentages (insiders, institutions), not who
holds the shares. Each fundamentals refresh appends one row per stock to
data/holdings.csv, so changes show up as the history grows. Quarterly FII/DII
figures from NSE are a separate source and are not included here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

HOLDINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "holdings.csv"
FIELDS = ("date", "ticker", "insider_pct", "institution_pct")


@dataclass(frozen=True)
class HoldingPoint:
    date: str
    ticker: str
    insider_pct: float | None
    institution_pct: float | None


def load_holdings(path: Path = HOLDINGS_FILE) -> list[HoldingPoint]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            HoldingPoint(
                date=r["date"], ticker=r["ticker"],
                insider_pct=None if r["insider_pct"] == "" else float(r["insider_pct"]),
                institution_pct=None if r["institution_pct"] == "" else float(r["institution_pct"]),
            )
            for r in csv.DictReader(handle)
        ]


def append_holdings(points: list[HoldingPoint], path: Path = HOLDINGS_FILE) -> int:
    """Append points not already recorded for the same date and ticker. Returns how many were added."""
    existing = {(p.date, p.ticker) for p in load_holdings(path)}
    new = [p for p in points if (p.date, p.ticker) not in existing]
    if not new:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(FIELDS)
        for p in new:
            writer.writerow([p.date, p.ticker, "" if p.insider_pct is None else p.insider_pct,
                             "" if p.institution_pct is None else p.institution_pct])
    return len(new)


def change(points: list[HoldingPoint], ticker: str) -> tuple[HoldingPoint, HoldingPoint] | None:
    """Earliest and latest point for a ticker, or None when there are fewer than two."""
    own = sorted((p for p in points if p.ticker == ticker), key=lambda p: p.date)
    if len(own) < 2:
        return None
    return own[0], own[-1]
