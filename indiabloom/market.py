"""Prices and quotes via yfinance, with an on-disk cache. The only network module for prices."""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
MAX_CACHE_AGE = timedelta(hours=12)


class MarketDataError(RuntimeError):
    """Raised when price data cannot be fetched at all."""


@dataclass(frozen=True)
class Quote:
    ticker: str
    last: float | None
    previous_close: float | None
    market_cap: float | None

    @property
    def change_pct(self) -> float | None:
        if self.last is None or not self.previous_close:
            return None
        return (self.last / self.previous_close - 1.0) * 100.0


def _cache_path(ticker: str, period: str, cache_dir: Path) -> Path:
    return cache_dir / f"{ticker.replace('.', '_')}_{period}.csv"


def _read_cache(path: Path, now: datetime) -> pd.Series | None:
    if not path.exists():
        return None
    age = now - datetime.fromtimestamp(path.stat().st_mtime)
    if age > MAX_CACHE_AGE:
        return None
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if frame.empty:
        return None
    series = frame.iloc[:, 0].astype(float)
    series.index = pd.DatetimeIndex(series.index)
    return series


def _download(ticker: str, period: str) -> pd.Series | None:
    import yfinance as yf  # imported lazily so offline tests never need it

    try:
        # yfinance emits pandas deprecation warnings from its own code on every call.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            history = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception as exc:  # yfinance raises a variety of exception types
        raise MarketDataError(f"failed to fetch {ticker}: {exc}") from exc
    if history is None or history.empty or "Close" not in history:
        return None
    close = history["Close"].astype(float).copy()
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    return close[~close.index.duplicated(keep="last")]


def fetch_closes(
    tickers: list[str],
    period: str = "1y",
    cache_dir: Path = CACHE_DIR,
    use_cache: bool = True,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Daily closing prices, one column per ticker, indexed by date.

    Fresh cache files (under MAX_CACHE_AGE old) are used without a download.
    Tickers with no data are skipped with a warning on stderr. Raises
    MarketDataError if no ticker returns data.
    """
    current = now or datetime.now()
    columns: dict[str, pd.Series] = {}
    cache_dir.mkdir(parents=True, exist_ok=True)

    for ticker in dict.fromkeys(t.strip().upper() for t in tickers):
        path = _cache_path(ticker, period, cache_dir)
        series = _read_cache(path, current) if use_cache else None
        if series is None:
            series = _download(ticker, period)
            if series is None or series.empty:
                print(f"warning: no price data for {ticker}", file=sys.stderr)
                continue
            series.to_frame("Close").to_csv(path, index_label="date")
        columns[ticker] = series

    if not columns:
        raise MarketDataError("no price data returned for any ticker")
    return pd.DataFrame(columns).sort_index()


def fetch_quote(ticker: str) -> Quote | None:
    """Last price, previous close, and market cap. Returns None if unavailable."""
    import yfinance as yf

    key = ticker.strip().upper()
    try:
        info = yf.Ticker(key).fast_info
        last = float(info.last_price)
        previous = float(info.previous_close)
        cap = info.market_cap
        return Quote(key, last, previous, float(cap) if cap is not None else None)
    except Exception:  # fast_info raises assorted errors when a quote is missing
        return None


def download_bulk(
    tickers: list[str],
    period: str = "2y",
    chunk_size: int = 100,
    cache_dir: Path = CACHE_DIR,
    use_cache: bool = True,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Closing prices for many tickers in few requests, cached as one CSV.

    Tickers are downloaded in chunks so one bad symbol cannot fail the batch.
    Columns that come back empty are dropped with a warning on stderr.
    """
    import hashlib

    import yfinance as yf

    wanted = sorted(dict.fromkeys(t.strip().upper() for t in tickers))
    if not wanted:
        raise MarketDataError("no tickers requested")
    key = hashlib.sha1(",".join(wanted).encode()).hexdigest()[:12]
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"bulk_{period}_{key}.csv"
    current = now or datetime.now()

    if use_cache and path.exists() and current - datetime.fromtimestamp(path.stat().st_mtime) <= MAX_CACHE_AGE:
        return pd.read_csv(path, index_col=0, parse_dates=True)

    frames: list[pd.DataFrame] = []
    for start in range(0, len(wanted), chunk_size):
        batch = wanted[start:start + chunk_size]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = yf.download(batch, period=period, auto_adjust=True,
                                  progress=False, threads=True)
        except Exception as exc:
            print(f"warning: batch starting {batch[0]} failed: {exc}", file=sys.stderr)
            continue
        if raw is None or raw.empty or "Close" not in raw:
            print(f"warning: empty batch starting {batch[0]}", file=sys.stderr)
            continue
        close = raw["Close"].copy()
        close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
        frames.append(close[~close.index.duplicated(keep="last")])

    if not frames:
        raise MarketDataError("bulk download returned no data")
    closes = pd.concat(frames, axis=1).sort_index()
    closes = closes.loc[:, ~closes.columns.duplicated()].dropna(axis=1, how="all")
    missing = sorted(set(wanted) - set(closes.columns))
    if missing:
        print(f"warning: {len(missing)} ticker(s) returned no data (e.g. {missing[0]})", file=sys.stderr)
    closes.to_csv(path, index_label="date")
    return closes
