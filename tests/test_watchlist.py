import asyncio

from textual.widgets import DataTable, Static

from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.stock_list import StockRow
from indiabloom.tui import IndiaBloomApp
from indiabloom.watchlist import (
    Position,
    add_position,
    find_position,
    load_watchlist,
    position_rows,
    remove_position,
    save_watchlist,
)


def test_add_replaces_existing_entry_and_remove_drops_it():
    positions = add_position([], "INFY.NS")
    positions = add_position(positions, "INFY.NS", buy_price=1500.0, quantity=10)
    assert len(positions) == 1
    assert find_position(positions, "INFY.NS") == Position("INFY.NS", 1500.0, 10)
    assert remove_position(positions, "INFY.NS") == []


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "watchlist.json"
    positions = add_position([], "TCS.NS", 3500.0, 5)
    positions = add_position(positions, "MU")  # watched only, no cost
    save_watchlist(positions, path)
    assert load_watchlist(path) == sorted(positions, key=lambda p: p.ticker)
    assert load_watchlist(tmp_path / "missing.json") == []


def test_pnl_rows_with_cost_and_price():
    rows = dict(position_rows(Position("INFY.NS", 1500.0, 10), last=1650.0))
    assert rows["Cost (Rs)"] == "15,000.00"
    assert rows["Market value (Rs)"] == "16,500.00"
    assert rows["P&L (Rs)"] == "+1,500.00"
    assert rows["P&L %"] == "+10.00%"


def test_watched_without_cost_shows_dashes():
    rows = dict(position_rows(Position("MU"), last=100.0))
    assert rows["Cost (Rs)"] == "-"
    assert rows["P&L (Rs)"] == "-"
    assert rows["Last price (Rs)"] == "100.00"


def test_missing_price_shows_dashes_for_value():
    rows = dict(position_rows(Position("INFY.NS", 1500.0, 10), last=None))
    assert rows["Market value (Rs)"] == "-"
    assert rows["P&L %"] == "-"


def _app(path):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none", watchlist_path=path)


def test_a_key_toggles_watchlist_and_saves(tmp_path):
    path = tmp_path / "watchlist.json"

    async def run():
        app = _app(path)
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("a")
            await pilot.pause()
            assert [p.ticker for p in load_watchlist(path)] == ["INFY.NS"]
            await pilot.press("a")
            await pilot.pause()
            assert load_watchlist(path) == []

    asyncio.run(run())


def test_position_view_shows_hint_when_not_watched(tmp_path):
    async def run():
        app = _app(tmp_path / "watchlist.json")
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("p")
            await pilot.pause()
            assert app.view == "position"
            assert "is not in the watchlist" in str(app.query_one("#hint", Static).render())

    asyncio.run(run())


def test_watch_tab_lists_only_watched_stocks(tmp_path):
    path = tmp_path / "watchlist.json"
    save_watchlist(add_position([], "INFY.NS", 1500.0, 10), path)

    async def run():
        app = _app(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.stocks = [
                StockRow("INFY.NS", "INFOSYS", "IT", 1650.0, 1.2, None),
                StockRow("TCS.NS", "TCS", "IT", 3500.0, -0.4, None),
            ]
            await pilot.press("7")
            await pilot.pause()
            assert app.tab == "watch"
            assert [r.ticker for r in app._visible_stocks()] == ["INFY.NS"]
            await pilot.press("1")
            await pilot.pause()
            assert len(app._visible_stocks()) == 2

    asyncio.run(run())
