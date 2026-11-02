import asyncio

from textual.widgets import DataTable

from indiabloom.jev import HeadlineClassification, headline_key
from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.news import NewsItem
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def _app():
    graph = Graph(parse_relations([
        {"source": "MU", "target": "INFY.NS", "relation": "thematic",
         "confidence": "low", "rationale": "test", "sources": []},
    ]))
    def offline(*args):
        raise MarketDataError("offline")
    item = NewsItem("Micron wins a major contract", "https://example.test/news", None, "Test")
    def news(_query):
        return [item]
    def classify(items):
        return [HeadlineClassification(headline_key(items[0]), "positive", "high", 0.91,
                                       "accepted", "test", "jev", "jev-latest")]
    return IndiaBloomApp(graph, load_companies(),
                         Services(prices=offline, bulk=offline, news=news, classifier=classify),
                         index_name="none")


def test_jev_results_render_in_news_view():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("MU")
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#links", DataTable)
            assert table.get_cell_at((0, 2)) == "positive/high"
            assert table.get_cell_at((0, 3)) == "0.91"
            assert table.get_cell_at((0, 4)) == "Micron wins a major contract"

    asyncio.run(run())
