"""Corporate events per stock: next results date, ex-dividend date, past results, dividends, splits.

Source: yfinance (unofficial). Each stock is cached as JSON in data/events/ and
refreshed after a day. Dates are stored as ISO strings. A value yfinance does not
publish is stored as null rather than guessed.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

EVENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "events"
MAX_AGE = timedelta(days=1)
PAST_RESULTS = 4
PAST_DIVIDENDS = 4


def _to_iso(value: Any) -> str | None:
    """A date-like value as YYYY-MM-DD, or None when it is missing or not a date."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _to_iso(value[0]) if value else None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return pd.Timestamp(value).date().isoformat()
    except (ValueError, TypeError):
        return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def build_events(ticker: str, calendar: dict[str, Any], earnings: pd.DataFrame | None,
                 dividends: pd.Series | None, splits: pd.Series | None,
                 fetched_at: datetime | None = None) -> dict[str, Any]:
    """Assemble one stock's events from yfinance pieces. Pure: no network."""
    past_results: list[dict[str, Any]] = []
    if earnings is not None and not earnings.empty:
        for index, row in earnings.iterrows():  # newest first
            reported = _num(row.get("Reported EPS"))
            if reported is None:
                continue  # results not out yet
            past_results.append({
                "date": _to_iso(index),
                "eps_estimate": _num(row.get("EPS Estimate")),
                "reported_eps": reported,
                "surprise_pct": _num(row.get("Surprise(%)")),
            })
            if len(past_results) == PAST_RESULTS:
                break

    past_dividends: list[dict[str, Any]] = []
    if dividends is not None and len(dividends):
        for index, amount in dividends.sort_index(ascending=False).items():
            past_dividends.append({"date": _to_iso(index), "amount": _num(amount)})
            if len(past_dividends) == PAST_DIVIDENDS:
                break

    split_rows: list[dict[str, Any]] = []
    if splits is not None and len(splits):
        for index, ratio in splits.sort_index(ascending=False).items():
            split_rows.append({"date": _to_iso(index), "ratio": _num(ratio)})
            if len(split_rows) == 2:
                break

    return {
        "ticker": ticker,
        "fetched_at": (fetched_at or datetime.now()).isoformat(timespec="seconds"),
        "next_results": _to_iso(calendar.get("Earnings Date")),
        "ex_dividend": _to_iso(calendar.get("Ex-Dividend Date")),
        "past_results": past_results,
        "dividends": past_dividends,
        "splits": split_rows,
    }


def events_path(ticker: str, directory: Path = EVENTS_DIR) -> Path:
    return directory / f"{ticker.removesuffix('.NS')}.json"


def load_events(ticker: str, directory: Path = EVENTS_DIR) -> dict[str, Any] | None:
    path = events_path(ticker, directory)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_events(events: dict[str, Any], directory: Path = EVENTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = events_path(events["ticker"], directory)
    path.write_text(json.dumps(events, indent=1), encoding="utf-8")
    return path


def is_fresh(events: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not events or "fetched_at" not in events:
        return False
    return (now or datetime.now()) - datetime.fromisoformat(events["fetched_at"]) <= MAX_AGE


def fetch_events(ticker: str) -> dict[str, Any]:
    """Fetch one stock from yfinance. Each part is independent: a missing part is left empty."""
    import yfinance as yf

    handle = yf.Ticker(ticker)

    def part(getter: Callable[[], Any], default: Any = None) -> Any:
        try:
            return getter()
        except Exception:  # one missing piece should not lose the rest
            return default

    calendar = part(lambda: handle.calendar, {}) or {}
    earnings = part(lambda: handle.earnings_dates)
    dividends = part(lambda: handle.dividends)
    splits = part(lambda: handle.splits)
    if not calendar and earnings is None and dividends is None and splits is None:
        raise ValueError("yfinance returned no event data")
    return build_events(ticker, calendar, earnings, dividends, splits)


@dataclass(frozen=True)
class EventFailure:
    ticker: str
    reason: str


def run_events(tickers: Iterable[str], directory: Path = EVENTS_DIR,
               fetch: Callable[[str], dict[str, Any]] = fetch_events, sleep_s: float = 0.5,
               refresh: bool = False, progress: Callable[[int, int, str], None] | None = None,
               now: datetime | None = None) -> tuple[int, int, list[EventFailure]]:
    """Fetch events for tickers without a fresh cache. Returns (fetched, skipped, failures)."""
    todo = list(dict.fromkeys(tickers))
    fetched = skipped = 0
    failures: list[EventFailure] = []
    for index, ticker in enumerate(todo, start=1):
        if not refresh and is_fresh(load_events(ticker, directory), now):
            skipped += 1
            continue
        try:
            save_events(fetch(ticker), directory)
            fetched += 1
        except Exception as exc:
            failures.append(EventFailure(ticker, f"{type(exc).__name__}: {exc}"))
        if progress:
            progress(index, len(todo), ticker)
        if sleep_s and index < len(todo):
            time.sleep(sleep_s)
    return fetched, skipped, failures


def upcoming(events: Iterable[dict[str, Any]], today: date, days: int) -> list[tuple[date, str, str]]:
    """(date, ticker, what) for results and ex-dividend dates from today to today + days, soonest first."""
    end = today + timedelta(days=days)
    rows: list[tuple[date, str, str]] = []
    for e in events:
        for key, label in (("next_results", "Results"), ("ex_dividend", "Ex-dividend")):
            iso = e.get(key)
            if not iso:
                continue
            when = date.fromisoformat(iso)
            if today <= when <= end:
                rows.append((when, e["ticker"], label))
    return sorted(rows)
