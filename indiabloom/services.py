"""Bundle of data sources. The UI and CLI take these so tests can use fake data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from indiabloom.market import Quote, download_bulk, fetch_closes, fetch_quote
from indiabloom.news import NewsItem, fetch_news

PriceFetcher = Callable[[list[str], str], pd.DataFrame]
QuoteFetcher = Callable[[str], Quote | None]
NewsSearch = Callable[[str], list[NewsItem]]


def _default_prices(tickers: list[str], period: str) -> pd.DataFrame:
    return fetch_closes(tickers, period=period)


def _default_bulk(tickers: list[str], period: str) -> pd.DataFrame:
    return download_bulk(tickers, period=period)


@dataclass
class Services:
    prices: PriceFetcher = field(default=_default_prices)
    quote: QuoteFetcher = field(default=fetch_quote)
    news: NewsSearch = field(default=fetch_news)
    bulk: PriceFetcher = field(default=_default_bulk)

