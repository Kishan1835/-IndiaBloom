import asyncio
import csv
from datetime import datetime
from pathlib import Path

from indiabloom.companies import load_companies
from indiabloom.export import export_path, watchlist_rows, write_csv
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.stock_list import StockRow
from indiabloom.tui import IndiaBloomApp
from indiabloom.watchlist import Position, add_position, save_watchlist


def _read(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.reader(handle))


def test_write_csv_round_trips_with_bom_and_headers(tmp_path):
    path = write_csv(tmp_path / "out.csv", ["NAME", "VALUE"], [["Infosys, Ltd", 1.5], ["Tata", "-"]])
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    assert _read(path) == [["NAME", "VALUE"], ["Infosys, Ltd", "1.5"], ["Tata", "-"]]


def test_export_path_is_named_by_view_ticker_and_time(tmp_path):
    when = datetime(2026, 10, 25, 9, 30, 5)
    path = export_path("screen", "INFY.NS", now=when, directory=tmp_path)
    assert path.name == "screen-INFY.NS-20261025-093005.csv"
    assert export_path("stocks-watch", "", now=when, directory=tmp_path).name == "stocks-watch-20261025-093005.csv"


def test_watchlist_rows_compute_cost_value_and_pnl():
    positions = add_position([], "INFY.NS", 1500.0, 10)
    positions = add_position(positions, "MU")  # watched without a cost
    rows = {r[0]: r for r in watchlist_rows(positions, {"INFY.NS": 1650.0, "MU": 100.0})}
    infy = rows["INFY.NS"]
    assert infy[4:] == [15000.0, 16500.0, 1500.0, 10.0]  # cost, value, pnl, pnl %
    assert rows["MU"][4:] == ["", "", "", ""]  # no cost basis, so no P&L


def test_watchlist_rows_blank_when_price_missing():
    rows = watchlist_rows([Position("INFY.NS", 1500.0, 10)], {})
    assert rows[0][3] == "" and rows[0][5] == "" and rows[0][6] == ""


def _app(tmp_path):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none",
                         watchlist_path=tmp_path / "watchlist.json", exports_dir=tmp_path / "exports")


def test_e_exports_the_movers_table(tmp_path):
    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.stocks = [StockRow("UP.NS", "UP", "IT", 10.0, 2.5, None),
                          StockRow("DOWN.NS", "DOWN", "IT", 9.0, -1.5, None)]
            await pilot.press("m")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            files = list((tmp_path / "exports").glob("movers-*.csv"))
            assert len(files) == 1
            rows = _read(files[0])
            assert rows[0] == ["SIDE", "TICKER", "CHG%", "PRICE", "SECTOR"]
            assert [r[1] for r in rows[1:]] == ["UP.NS", "DOWN.NS"]

    asyncio.run(run())


def test_ctrl_e_on_watch_tab_exports_pnl(tmp_path):
    save_watchlist(add_position([], "INFY.NS", 1500.0, 10), tmp_path / "watchlist.json")

    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.stocks = [StockRow("INFY.NS", "INFOSYS", "IT", 1650.0, 1.0, None)]
            await pilot.press("7")
            await pilot.pause()
            await pilot.press("ctrl+e")
            await pilot.pause()
            files = list((tmp_path / "exports").glob("watchlist-*.csv"))
            assert len(files) == 1
            rows = _read(files[0])
            assert rows[0][0] == "TICKER"
            assert rows[1][0] == "INFY.NS" and rows[1][6] == "1500.0"  # P&L

    asyncio.run(run())
