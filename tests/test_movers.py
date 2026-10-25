import asyncio

from textual.widgets import DataTable

from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.stock_list import StockRow, top_movers
from indiabloom.tui import IndiaBloomApp


def _row(ticker, change):
    return StockRow(ticker, ticker, "IT", 100.0, change, None)


def test_top_movers_splits_and_ranks():
    rows = [_row("A", 3.0), _row("B", -1.0), _row("C", 5.0), _row("D", -4.0), _row("E", None), _row("F", 0.0)]
    gainers, losers = top_movers(rows, n=2)
    assert [r.ticker for r in gainers] == ["C", "A"]
    assert [r.ticker for r in losers] == ["D", "B"]  # zero and missing changes are in neither list


def test_movers_view_lists_gainers_and_losers(tmp_path):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    app = IndiaBloomApp(graph, load_companies(), services, index_name="none",
                        watchlist_path=tmp_path / "watchlist.json")

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.stocks = [_row("UP.NS", 2.5), _row("DOWN.NS", -1.5)]
            await pilot.press("m")
            await pilot.pause()
            assert app.view == "movers"
            table = app.query_one("#links", DataTable)
            tickers = [table.get_row_at(r)[1] for r in range(table.row_count)]
            assert tickers == ["UP.NS", "DOWN.NS"]

    asyncio.run(run())
