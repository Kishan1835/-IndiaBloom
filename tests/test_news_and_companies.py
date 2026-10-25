import pytest

from indiabloom.companies import CompanyFileError, find_mentions, load_companies
from indiabloom.news import NewsError, parse_rss, sentiment, sentiment_label
from indiabloom.watch import build_watch
from indiabloom.graph import Graph, parse_relations
from indiabloom.news import NewsItem

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Micron posts record profit, shares rally</title>
    <link>https://example.test/a</link>
    <pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate>
    <source url="https://x.test">Reuters</source>
  </item>
  <item>
    <title>Micron posts record profit, shares rally</title>
    <link>https://example.test/dup</link>
    <pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate>
    <source url="https://y.test">Other</source>
  </item>
  <item>
    <title>Older story about Micron plant delay</title>
    <link>https://example.test/b</link>
    <pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>
    <source url="https://z.test">Mint</source>
  </item>
  <item>
    <title>Undated story</title>
    <link>https://example.test/c</link>
    <source url="https://w.test">Blog</source>
  </item>
</channel></rss>
"""


def test_parse_rss_dedupes_sorts_newest_first_and_keeps_undated():
    items = parse_rss(FEED)
    assert [i.title for i in items] == [
        "Micron posts record profit, shares rally",
        "Older story about Micron plant delay",
        "Undated story",
    ]
    assert items[0].published is not None
    assert items[-1].published is None
    assert items[0].source == "Reuters"


def test_parse_rss_rejects_non_xml():
    with pytest.raises(NewsError):
        parse_rss(b"<html><not closed")


def test_sentiment_counts_positive_and_negative_words():
    assert sentiment("Micron posts record profit, shares rally") == 3
    assert sentiment("Micron plant delay and loss") == -2
    assert sentiment("Micron opens office") == 0
    assert sentiment_label(0) == "neutral"


NAMES = {
    "MU": ("Micron",),
    "INFY.NS": ("Infosys",),
    "TCS.NS": ("TCS", "Tata Consultancy Services"),
}


def test_find_mentions_whole_word_only():
    assert find_mentions("Micron beats estimates", NAMES) == {"MU"}
    assert find_mentions("Micronesia tourism grows", NAMES) == set()


def test_find_mentions_matches_aliases_and_cashtags():
    assert find_mentions("Tata Consultancy Services wins deal", NAMES) == {"TCS.NS"}
    assert find_mentions("$MU up 3%", NAMES) == {"MU"}
    assert find_mentions("Infosys and TCS report", NAMES) == {"INFY.NS", "TCS.NS"}


def test_load_companies_rejects_bad_shape(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"MU": []}', encoding="utf-8")
    with pytest.raises(CompanyFileError):
        load_companies(path)


def test_load_companies_reads_bundled_file():
    names = load_companies()
    assert names["MU"][0] == "Micron"
    assert "INFY.NS" in names


def test_build_watch_keeps_only_headlines_naming_the_company():
    graph = Graph(parse_relations([{
        "source": "MU", "target": "CGPOWER.NS", "relation": "thematic",
        "confidence": "low", "rationale": "theme", "sources": [],
    }]))
    feed = [
        NewsItem("Micron profit jumps", "u1", None, "R"),
        NewsItem("Chip stocks drift lower", "u2", None, "R"),  # loose match, not about Micron
    ]
    rows = build_watch(graph, NAMES | {"MU": ("Micron",)}, lambda q: feed)
    assert len(rows) == 1
    row = rows[0]
    assert row.global_ticker == "MU"
    assert row.indian_links == ("CGPOWER.NS (thematic, low)",)
    assert row.sentiment == "positive"


def test_build_watch_groups_all_indian_links_per_headline():
    graph = Graph(parse_relations([
        {"source": "ACN", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "peer", "sources": []},
        {"source": "ACN", "target": "TCS.NS", "relation": "peer",
         "confidence": "high", "rationale": "peer", "sources": []},
    ]))
    feed = [NewsItem("Accenture shares fall on downgrade", "u", None, "R"),
            NewsItem("Accenture shares fall on downgrade", "v", None, "S")]
    rows = build_watch(graph, {"ACN": ("Accenture",)}, lambda q: feed)
    assert len(rows) == 1
    assert rows[0].indian_links == ("INFY.NS (peer, high)", "TCS.NS (peer, high)")
    assert rows[0].sentiment == "negative"


def test_parse_rss_strips_publisher_suffix_so_copies_collapse():
    feed = b"""<rss version="2.0"><channel>
      <item><title>Micron beats estimates - Reuters</title><source url="u">Reuters</source></item>
      <item><title>Micron beats estimates - Mint</title><source url="v">Mint</source></item>
    </channel></rss>"""
    items = parse_rss(feed)
    assert len(items) == 1
    assert items[0].title == "Micron beats estimates"


def test_build_watch_skips_companies_with_no_indian_links():
    graph = Graph(parse_relations([{
        "source": "MU", "target": "CGPOWER.NS", "relation": "thematic",
        "confidence": "low", "rationale": "theme", "sources": [],
    }]))
    calls = []
    build_watch(graph, {"ACN": ("Accenture",), "MU": ("Micron",)},
                lambda q: calls.append(q) or [])
    assert calls == ["Micron stock"]
