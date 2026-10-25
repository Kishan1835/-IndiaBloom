import asyncio
from datetime import datetime

from textual.widgets import DataTable, Static

from indiabloom.companies import load_companies
from indiabloom.deals import Deal
from indiabloom.fundamentals import build_snapshot
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def _app():
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none")


def _snapshot():
    return build_snapshot("INFY.NS", {"shortName": "INFOSYS", "sector": "Technology",
                                      "marketCap": 4.6e12, "trailingPE": 15.4},
                          fetched_at=datetime(2026, 10, 25, 9, 0, 0))


def test_fundamentals_view_shows_cached_snapshot(monkeypatch):
    monkeypatch.setattr("indiabloom.tui.load_snapshot", lambda ticker: _snapshot())

    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("f")
            await pilot.pause()
            assert app.view == "fundamentals"
            table = app.query_one("#links", DataTable)
            metrics = {table.get_row_at(r)[0] for r in range(table.row_count)}
            assert "P/E trailing" in metrics
            assert "Market cap (Rs cr)" in metrics

    asyncio.run(run())


def test_fundamentals_view_hints_when_not_cached(monkeypatch):
    monkeypatch.setattr("indiabloom.tui.load_snapshot", lambda ticker: None)

    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("f")
            await pilot.pause()
            assert "python -m indiabloom fundamentals" in str(app.query_one("#hint", Static).render())

    asyncio.run(run())


def test_deals_view_lists_buyers_and_sellers(monkeypatch):
    deals = [
        Deal("2026-10-23", "INFY", "bulk", "BIG BUYER LLP", "BUY", 1000, 1500.0, 0.15),
        Deal("2026-10-23", "INFY", "block", "BIG SELLER FUND", "SELL", 500, 1490.0, 0.0745),
    ]
    monkeypatch.setattr("indiabloom.tui.load_deals", lambda: deals)

    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("d")
            await pilot.pause()
            assert app.view == "deals"
            table = app.query_one("#links", DataTable)
            assert table.row_count == 2
            clients = {table.get_row_at(r)[3] for r in range(table.row_count)}
            assert clients == {"BIG BUYER LLP", "BIG SELLER FUND"}

    asyncio.run(run())
