"""Rows for the UI's stock list: Nifty constituents plus graph-only stocks.

Each row has a last price and day change from the last two closes, a sector
group, and (for Indian stocks) the t-statistic from the most recent S&P 500
universe scan, if a report exists.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from indiabloom.graph import Graph
from indiabloom.models import is_indian
from indiabloom.sectors import OTHER, SectorRule, classify

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
US_GROUP = "US"


@dataclass(frozen=True)
class StockRow:
    ticker: str
    company: str
    group: str
    last: float | None
    change_pct: float | None
    us_t: float | None


def latest_us_t(reports_dir: Path = REPORTS_DIR) -> dict[str, float]:
    """t-stats from the newest S&P 500 universe report, keyed by ticker. Empty if none."""
    reports = sorted(reports_dir.glob("*_GSPC_*.csv"))
    if not reports:
        return {}
    out: dict[str, float] = {}
    with reports[-1].open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["ticker"]] = float(row["t_stat"])
            except (KeyError, ValueError):
                continue
    return out


def price_change(closes: pd.DataFrame, ticker: str) -> tuple[float | None, float | None]:
    """Last close and day change in percent, or (None, None) if there is too little data."""
    if ticker not in closes.columns:
        return None, None
    series = closes[ticker].dropna()
    if series.empty:
        return None, None
    last = float(series.iloc[-1])
    if len(series) < 2 or series.iloc[-2] == 0:
        return last, None
    return last, (last / float(series.iloc[-2]) - 1.0) * 100.0


def build_stock_list(
    constituents: list,  # universe.Constituent objects
    closes: pd.DataFrame,
    graph: Graph,
    rules: list[SectorRule],
    us_t: dict[str, float],
) -> list[StockRow]:
    rows: dict[str, StockRow] = {}
    for c in constituents:
        last, change = price_change(closes, c.ticker)
        rows[c.ticker] = StockRow(
            c.ticker, c.company, classify(c.company, c.industry, rules),
            last, change, us_t.get(c.ticker),
        )

    for ticker in graph.nodes():
        if ticker in rows:
            continue
        last, change = price_change(closes, ticker)
        group = OTHER if is_indian(ticker) else US_GROUP
        rows[ticker] = StockRow(ticker, ticker, group, last, change, us_t.get(ticker))

    return sorted(rows.values(), key=lambda r: r.ticker)


def filter_group(rows: list[StockRow], group: str | None) -> list[StockRow]:
    """All rows when group is None, otherwise the rows in that group."""
    if group is None:
        return rows
    return [r for r in rows if r.group == group]
