import asyncio
from types import SimpleNamespace

from textual.widgets import DataTable, Input

from indiabloom.companies import load_companies
from indiabloom.fundamentals import build_snapshot
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def _snapshots():
    infy = build_snapshot("INFY.NS", {"shortName": "INFOSYS", "sector": "Technology",
                                      "trailingPE": 15.4, "returnOnEquity": 0.30, "marketCap": 4.6e12})
    slow = build_snapshot("SLOW.NS", {"shortName": "SLOW CO", "sector": "Technology",
                                      "trailingPE": 60.0, "returnOnEquity": 0.30, "marketCap": 1e12})
    return {"INFY.NS": infy, "SLOW.NS": slow}


def _app(tmp_path):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="nifty500",
                         watchlist_path=tmp_path / "watchlist.json")


def _patch_data(monkeypatch):
    snaps = _snapshots()
    monkeypatch.setattr("indiabloom.fundamentals.load_snapshot", lambda t: snaps.get(t))
    monkeypatch.setattr("indiabloom.universe.load_index",
                        lambda name, *a, **k: [SimpleNamespace(ticker=t) for t in snaps])


def test_screen_view_lists_matches_and_opens_a_stock(monkeypatch, tmp_path):
    _patch_data(monkeypatch)

    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("x")
            await pilot.pause()
            box = app.query_one("#screen-input", Input)
            assert box.display and box.has_focus
            box.value = "pe_trailing<20, roe>=15"
            await pilot.press("enter")
            await pilot.pause()
            assert app.view == "screen"
            table = app.query_one("#links", DataTable)
            assert table.row_count == 1  # SLOW.NS fails the P/E condition
            assert table.get_row_at(0)[0] == "INFY.NS"
            app.on_data_table_row_selected(_selected("INFY.NS", table))
            await pilot.pause()
            assert app.view == "competitors"
            assert app.selected == "INFY.NS"

    asyncio.run(run())


def test_bad_screen_condition_shows_message(monkeypatch, tmp_path):
    _patch_data(monkeypatch)

    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("x")
            await pilot.pause()
            app.query_one("#screen-input", Input).value = "pe_trailing"
            await pilot.press("enter")
            await pilot.pause()
            table = app.query_one("#links", DataTable)
            assert "cannot read condition" in str(table.get_row_at(0)[0])

    asyncio.run(run())


def _selected(key, table):
    from textual.widgets import DataTable as DT
    row_key = table.rows and list(table.rows.keys())[0]
    return DT.RowSelected(table, 0, row_key)
