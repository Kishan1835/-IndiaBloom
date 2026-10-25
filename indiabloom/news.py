"""News headlines from Google News RSS, plus a crude sentiment score.

The sentiment is a word count against a small list. It is a rough signal for
scanning headlines, not a model. Read the headline before acting.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
USER_AGENT = "IndiaBloom/0.2 (personal research tool)"

POSITIVE = frozenset({
    "beat", "beats", "surge", "surges", "rally", "rallies", "record", "gain", "gains",
    "upgrade", "upgrades", "growth", "strong", "profit", "profits", "wins", "win", "deal",
    "expands", "expansion", "raises", "boost", "boosts", "approval", "approved", "rise",
    "rises", "jumps", "soars",
})
NEGATIVE = frozenset({
    "plunge", "plunges", "fall", "falls", "miss", "misses", "cut", "cuts", "downgrade",
    "downgrades", "loss", "losses", "probe", "lawsuit", "ban", "banned", "slump", "weak",
    "drop", "drops", "fraud", "warns", "warning", "delay", "delays", "tumble", "tumbles",
    "sell-off", "selloff",
})


class NewsError(RuntimeError):
    """Raised when the news feed cannot be fetched or parsed."""


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    published: datetime | None
    source: str


def parse_rss(data: bytes, limit: int = 20) -> list[NewsItem]:
    """Parse an RSS 2.0 document into news items, newest first, de-duplicated by title."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError(f"feed is not valid XML: {exc}") from exc

    items: list[NewsItem] = []
    seen: set[str] = set()
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        source = (node.findtext("source") or "").strip()
        # Google appends " - Publisher" to every headline. Strip it so the same
        # story from several outlets is recognised as one headline.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(f" - {source}")].rstrip()
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        published: datetime | None = None
        raw_date = node.findtext("pubDate")
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                published = None
        items.append(NewsItem(
            title=title,
            link=(node.findtext("link") or "").strip(),
            published=published,
            source=source,
        ))

    items.sort(key=lambda i: (i.published is None, -(i.published.timestamp() if i.published else 0)))
    return items[:limit]


def fetch_news(query: str, limit: int = 20, timeout: float = 15.0) -> list[NewsItem]:
    """Fetch headlines for a search query. Network call."""
    url = GOOGLE_NEWS_URL.format(query=urllib.parse.quote_plus(query))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NewsError(f"could not fetch news for '{query}': {exc}") from exc
    return parse_rss(data, limit=limit)


def sentiment(title: str) -> int:
    """Positive word count minus negative word count. Crude by design."""
    words = re.findall(r"[a-z\-]+", title.lower())
    return sum(w in POSITIVE for w in words) - sum(w in NEGATIVE for w in words)


def sentiment_label(score: int) -> str:
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"
