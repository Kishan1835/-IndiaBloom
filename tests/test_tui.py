import asyncio
from datetime import datetime

from textual.widgets import DataTable, Static

from indiabloom.companies import load_companies
from indiabloom.demo import synthetic_closes
from indiabloom.graph import Graph, parse_relations
from indiabloom.news import NewsItem
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def _graph():
    return Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
        {"source": "KAYNES.NS", "target": "MU", "relation": "supplier",
         "confidence": "low", "rationale": "test supplier", "sources": []},
        {"source": "MU", "target": "CGPOWER.NS", "relation": "thematic",
         "confidence": "low", "rationale": "theme", "sources": []},
    ]))


def _closes(tickers, days=300, seed=4):
    base = synthetic_closes("MU", {"CGPOWER.NS": 0.5, "KAYNES.NS": 0.1,
                                   "INFY.NS": 0.0, "TCS.NS": 0.0}, days=days, seed=seed)
    return base[[t for t in tickers if t in base.columns]]


def _services():
    return Services(
        prices=lambda tickers, period: _closes(tickers),
        bulk=lambda tickers, period: _closes(tickers),
        news=lambda q: [NewsItem("Micron posts record profit", "u", datetime(2026, 10, 23), "R")],
    )


def _app():
    # index_name that does not exist makes the app use graph stocks only
    return IndiaBloomApp(_graph(), load_companies(), _services(), index_name="none")


def test_stock_list_shows_graph_stocks_with_prices():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            stocks = app.query_one("#stocks", DataTable)
            assert stocks.row_count == len(_graph().nodes())
            assert stocks.get_cell("MU", "price") != "-"
            assert stocks.get_cell("MU", "ust") == "-"  # no universe report in tests

    asyncio.run(run())


def test_sector_tab_filters_stock_list():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            stocks = app.query_one("#stocks", DataTable)
            await pilot.press("6")  # US tab
            await pilot.pause()
            assert {stocks.get_cell_at((r, 4)) for r in range(stocks.row_count)} == {"US"}
            await pilot.press("1")  # All tab
            await pilot.pause()
            assert stocks.row_count == len(_graph().nodes())

    asyncio.run(run())


def test_graph_views_switch_with_buttons():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("MU")
            await pilot.pause()
            assert app.query_one("#links", DataTable).row_count == 0  # MU has no peers
            await pilot.press("s")
            await pilot.pause()
            assert app.view == "suppliers"
            links = app.query_one("#links", DataTable)
            assert links.row_count == 1
            assert links.get_cell_at((0, 0)) == "KAYNES.NS"

    asyncio.run(run())


def test_empty_view_shows_hint():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("MU")
            await pilot.press("c")
            await pilot.pause()
            hint = str(app.query_one("#hint", Static).render())
            assert "Nothing recorded under competitors for MU" in hint

    asyncio.run(run())


def test_correlation_view_loads_in_background():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("MU")
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#links", DataTable)
            assert table.row_count == 2  # CGPOWER and KAYNES
            methods = {table.get_cell_at((r, 1)) for r in range(table.row_count)}
            assert methods == {"next-session"}

    asyncio.run(run())


def test_news_view_shows_headlines_with_mentions():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            app.select_stock("MU")
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#links", DataTable)
            assert table.row_count == 1
            assert table.get_cell_at((0, 1)) == "positive"
            assert table.get_cell_at((0, 3)) == "MU"

    asyncio.run(run())


def test_failed_news_is_reported_not_hung():
    def broken(query):
        raise RuntimeError("offline")

    async def run():
        services = Services(prices=_services().prices, bulk=_services().bulk, news=broken)
        app = IndiaBloomApp(_graph(), load_companies(), services, index_name="none")
        async with app.run_test() as pilot:
            app.select_stock("MU")
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#links", DataTable).get_cell_at((0, 0)).startswith("news failed")

    asyncio.run(run())



def test_status_line_reports_loading_and_result():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            status = str(app.query_one("#status", Static).render())
            assert status.startswith("Loaded ")
            assert "Latest prices:" in status

    asyncio.run(run())
