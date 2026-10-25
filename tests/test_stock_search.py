import asyncio

from textual.widgets import Input

from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.stock_list import find_stock
from indiabloom.tui import IndiaBloomApp

TICKERS = ["INFY.NS", "INFOBEAN.NS", "TCS.NS", "HDFCBANK.NS", "MU"]
NAMES = {"INFY.NS": "INFOSYS LIMITED", "TCS.NS": "TATA CONSULTANCY SERVICES"}


def test_exact_code_with_or_without_suffix():
    assert find_stock("INFY", TICKERS, NAMES) == "INFY.NS"
    assert find_stock("infy.ns", TICKERS, NAMES) == "INFY.NS"
    assert find_stock("mu", TICKERS, NAMES) == "MU"


def test_prefix_prefers_shortest_code():
    assert find_stock("INF", TICKERS, NAMES) == "INFY.NS"  # INFY is shorter than INFOBEAN


def test_company_name_substring():
    assert find_stock("consultancy", TICKERS, NAMES) == "TCS.NS"
    assert find_stock("  Infosys ", TICKERS, NAMES) == "INFY.NS"


def test_no_match_and_empty_query():
    assert find_stock("ZZZZ", TICKERS, NAMES) is None
    assert find_stock("   ", TICKERS, NAMES) is None


def _app():
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none")


def test_ctrl_f_search_selects_stock():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.press("ctrl+f")
            await pilot.pause()
            box = app.query_one("#search", Input)
            assert box.display and box.has_focus
            for ch in "infy":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            assert app.selected == "INFY.NS"
            assert not box.display

    asyncio.run(run())


def test_escape_closes_search_box():
    async def run():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.press("ctrl+f")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one("#search", Input).display

    asyncio.run(run())
