"""Fundamentals snapshot per stock: valuation, profitability, balance sheet, cash flow.

Data comes from yfinance (`Ticker.info` plus the annual statements). It is a
free, unofficial source: field coverage varies by company, and ratios are
exactly as yfinance reports them. Each stock is cached as one JSON file in
data/fundamentals/, so a run can stop and resume without refetching.

Snapshots carry no buyer or customer data. Shareholding percentages are the
aggregate figures yfinance provides, not named institutional holdings.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

FUNDAMENTALS_DIR = Path(__file__).resolve().parent.parent / "data" / "fundamentals"
MAX_AGE = timedelta(days=7)
YEARS_KEPT = 4

# yfinance row labels for the annual statements -> our short names
INCOME_ROWS = {"Total Revenue": "revenue", "Net Income": "net_income", "EBITDA": "ebitda"}
BALANCE_ROWS = {"Total Debt": "total_debt", "Stockholders Equity": "equity", "Cash And Cash Equivalents": "cash"}
CASHFLOW_ROWS = {"Operating Cash Flow": "operating_cash_flow", "Free Cash Flow": "free_cash_flow"}

# yfinance Ticker.info keys -> our short names
INFO_FIELDS = {
    "shortName": "name",
    "sector": "sector",
    "industry": "industry",
    "marketCap": "market_cap",
    "currentPrice": "price",
    "trailingPE": "pe_trailing",
    "forwardPE": "pe_forward",
    "priceToBook": "pb",
    "dividendYield": "dividend_yield_pct",
    "returnOnEquity": "roe",
    "debtToEquity": "debt_to_equity",
    "profitMargins": "profit_margin",
    "revenueGrowth": "revenue_growth",
    "trailingEps": "eps",
    "fiftyTwoWeekHigh": "high_52w",
    "fiftyTwoWeekLow": "low_52w",
    "heldPercentInsiders": "insider_pct",
    "heldPercentInstitutions": "institution_pct",
    "financialCurrency": "financial_currency",
}


@dataclass(frozen=True)
class FetchFailure:
    ticker: str
    reason: str


def _clean(value: Any) -> Any:
    """Turn NaN/inf/numpy scalars into JSON-safe values; None when missing."""
    if value is None:
        return None
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _series_rows(frame: Any, rows: dict[str, str]) -> dict[str, list[list[Any]]]:
    """Pick known rows from a statement frame (rows = labels, columns = fiscal years).

    Returns {short_name: [[year, value], ...]} newest first, at most YEARS_KEPT years.
    Missing rows are left out instead of guessed.
    """
    out: dict[str, list[list[Any]]] = {}
    if frame is None or getattr(frame, "empty", True):
        return out
    for label, short in rows.items():
        if label not in frame.index:
            continue
        series = []
        for column in list(frame.columns)[:YEARS_KEPT]:
            value = _clean(frame.at[label, column])
            year = column.date().isoformat() if hasattr(column, "date") else str(column)
            series.append([year, value])
        if any(v is not None for _, v in series):
            out[short] = series
    return out


def build_snapshot(ticker: str, info: dict[str, Any], financials: Any = None,
                   balance: Any = None, cashflow: Any = None,
                   fetched_at: datetime | None = None) -> dict[str, Any]:
    """Assemble one stock's snapshot from yfinance pieces. Pure: no network."""
    snap: dict[str, Any] = {"ticker": ticker,
                            "fetched_at": (fetched_at or datetime.now()).isoformat(timespec="seconds")}
    for key, short in INFO_FIELDS.items():
        snap[short] = _clean(info.get(key))
    snap["annual"] = {
        **_series_rows(financials, INCOME_ROWS),
        **_series_rows(balance, BALANCE_ROWS),
        **_series_rows(cashflow, CASHFLOW_ROWS),
    }
    return snap


def snapshot_path(ticker: str, directory: Path = FUNDAMENTALS_DIR) -> Path:
    return directory / f"{ticker.removesuffix('.NS')}.json"


def load_snapshot(ticker: str, directory: Path = FUNDAMENTALS_DIR) -> dict[str, Any] | None:
    path = snapshot_path(ticker, directory)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_snapshot(snap: dict[str, Any], directory: Path = FUNDAMENTALS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(snap["ticker"], directory)
    path.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    return path


def is_fresh(snap: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not snap or "fetched_at" not in snap:
        return False
    fetched = datetime.fromisoformat(snap["fetched_at"])
    return (now or datetime.now()) - fetched <= MAX_AGE


def fetch_snapshot(ticker: str) -> dict[str, Any]:
    """Fetch one stock from yfinance. Raises on network failure or an empty response."""
    import yfinance as yf

    handle = yf.Ticker(ticker)
    info = handle.info or {}
    if not info or ("shortName" not in info and "marketCap" not in info):
        raise ValueError("yfinance returned no company data")
    return build_snapshot(
        ticker, info,
        financials=handle.financials,
        balance=handle.balance_sheet,
        cashflow=handle.cashflow,
    )


@dataclass(frozen=True)
class RunReport:
    fetched: int
    skipped_fresh: int
    failed: list[FetchFailure]


def run_fundamentals(
    tickers: Iterable[str],
    directory: Path = FUNDAMENTALS_DIR,
    fetch: Callable[[str], dict[str, Any]] = fetch_snapshot,
    sleep_s: float = 0.5,
    progress: Callable[[int, int, str], None] | None = None,
    now: datetime | None = None,
    refresh: bool = False,
) -> RunReport:
    """Fetch snapshots for every ticker that lacks a fresh cache. Resumable.

    Failures are reported and not cached, so the next run retries them.
    With refresh=True every ticker is fetched again.
    """
    todo = list(dict.fromkeys(tickers))
    fetched = 0
    skipped = 0
    failed: list[FetchFailure] = []
    for index, ticker in enumerate(todo, start=1):
        if not refresh and is_fresh(load_snapshot(ticker, directory), now):
            skipped += 1
            continue
        try:
            snap = fetch(ticker)
            save_snapshot(snap, directory)
            fetched += 1
        except Exception as exc:  # one bad ticker must not stop the run
            failed.append(FetchFailure(ticker, f"{type(exc).__name__}: {exc}"))
        if progress:
            progress(index, len(todo), ticker)
        if sleep_s and index < len(todo):
            time.sleep(sleep_s)
    return RunReport(fetched=fetched, skipped_fresh=skipped, failed=failed)


def _num(value: Any, digits: int = 2) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def _crore(value: Any) -> str:
    """Rupees to crore (1 crore = 10 million), the usual Indian unit."""
    return "-" if value is None else f"{value / 1e7:,.0f}"


def _statement_amount(value: Any, currency: str | None) -> str:
    """Statement amounts in the reporting currency: crore for INR, millions otherwise.

    Some NSE stocks (e.g. Infosys) report their statements in USD even though the
    share price is in INR, so the currency has to come from the snapshot.
    """
    if value is None:
        return "-"
    if currency in (None, "INR"):
        return _crore(value)
    return f"{value / 1e6:,.0f} {currency} mn"


def _pct(value: Any) -> str:
    """Ratio (0.15) to percent text. yfinance reports these as fractions."""
    return "-" if value is None else f"{value * 100:.1f}%"


def _computed_roe(annual: dict[str, list[list[Any]]]) -> tuple[str, Any]:
    """ROE from the latest net income and equity, used when yfinance omits it."""
    ni = (annual.get("net_income") or [[None, None]])[0][1]
    eq = (annual.get("equity") or [[None, None]])[0][1]
    if ni is not None and eq:
        return "ROE (computed: net income / equity)", ni / eq
    return "ROE", None


def fundamentals_rows(snap: dict[str, Any]) -> list[tuple[str, str]]:
    """Display rows (metric, value) for one snapshot. Units are in the labels."""
    annual = snap.get("annual") or {}
    roe_label, roe_value = ("ROE", snap.get("roe"))
    if roe_value is None:
        roe_label, roe_value = _computed_roe(annual)

    rows: list[tuple[str, str]] = [
        ("Sector", snap.get("sector") or "-"),
        ("Industry", snap.get("industry") or "-"),
        ("Price (Rs)", _num(snap.get("price"))),
        ("Market cap (Rs cr)", _crore(snap.get("market_cap"))),
        ("P/E trailing", _num(snap.get("pe_trailing"))),
        ("P/E forward", _num(snap.get("pe_forward"))),
        ("P/B", _num(snap.get("pb"))),
        ("EPS (Rs)", _num(snap.get("eps"))),
        ("Dividend yield (as reported)", _num(snap.get("dividend_yield_pct"))),
        (roe_label, _pct(roe_value)),
        ("Profit margin", _pct(snap.get("profit_margin"))),
        ("Revenue growth (latest)", _pct(snap.get("revenue_growth"))),
        ("Debt to equity (as reported)", _num(snap.get("debt_to_equity"))),
        ("52-week high / low (Rs)", f"{_num(snap.get('high_52w'))} / {_num(snap.get('low_52w'))}"),
        ("Insiders held", _pct(snap.get("insider_pct"))),
        ("Institutions held (aggregate)", _pct(snap.get("institution_pct"))),
    ]
    labels = {
        "revenue": "Revenue",
        "net_income": "Net income",
        "operating_cash_flow": "Operating cash flow",
        "free_cash_flow": "Free cash flow",
        "total_debt": "Total debt",
        "equity": "Equity",
    }
    currency = snap.get("financial_currency") or "INR"
    unit = "Rs cr" if currency == "INR" else f"{currency} mn"
    for key, label in labels.items():
        for year, value in annual.get(key, []):
            rows.append((f"{label} FY ending {year} ({unit})", _statement_amount(value, currency)))
    return rows


def effective_roe(snap: dict[str, Any]) -> float | None:
    """Reported ROE if yfinance has it, otherwise net income / equity from the statements."""
    if snap.get("roe") is not None:
        return snap["roe"]
    return _computed_roe(snap.get("annual") or {})[1]
