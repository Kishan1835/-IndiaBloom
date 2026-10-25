"""News-driven watch: which Indian stocks to look at because of today's US headlines.

For each US company in the graph that has a known name, search its recent
headlines. Keep only headlines that name the company itself, then list the
Indian stocks linked to it. One row per headline, with all its Indian links.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from indiabloom.companies import find_mentions
from indiabloom.graph import Graph
from indiabloom.models import is_indian
from indiabloom.news import NewsItem, sentiment, sentiment_label


@dataclass(frozen=True)
class WatchRow:
    global_ticker: str
    headline: str
    link: str
    published: datetime | None
    sentiment: str
    indian_links: tuple[str, ...] = field(default_factory=tuple)  # "TICKER (type, conf)"


NewsFetcher = Callable[[str], list[NewsItem]]


def build_watch(
    graph: Graph,
    names: dict[str, tuple[str, ...]],
    fetch: NewsFetcher,
    per_company: int = 10,
) -> list[WatchRow]:
    """Headlines about US companies in the graph, each with its Indian links."""
    grouped: dict[tuple[str, str], dict] = {}
    for ticker in graph.nodes():
        if is_indian(ticker) or ticker not in names:
            continue
        counterparts = graph.indian_counterparts(ticker)
        if not counterparts:
            continue
        for item in fetch(f"{names[ticker][0]} stock")[:per_company]:
            if ticker not in find_mentions(item.title, names):
                continue  # the feed matched loosely; keep only headlines that name the company
            key = (ticker, item.title.lower())
            entry = grouped.setdefault(key, {"item": item, "links": []})
            for rel in counterparts:
                label = f"{rel.other(ticker)} ({rel.relation}, {rel.confidence})"
                if label not in entry["links"]:
                    entry["links"].append(label)

    rows = [
        WatchRow(
            global_ticker=ticker,
            headline=entry["item"].title,
            link=entry["item"].link,
            published=entry["item"].published,
            sentiment=sentiment_label(sentiment(entry["item"].title)),
            indian_links=tuple(entry["links"]),
        )
        for (ticker, _), entry in grouped.items()
    ]
    rows.sort(key=lambda r: (r.published is None,
                             -(r.published.timestamp() if r.published else 0.0)))
    return rows
