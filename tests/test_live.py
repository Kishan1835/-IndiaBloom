import asyncio
from datetime import datetime

import pandas as pd
from textual.widgets import DataTable

from indiabloom.chart import IST, is_market_open, live_lines
from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import IntradayData, MarketDataError
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def test_market_hours_on_weekdays_only():
    assert is_market_open(datetime(2026, 10, 26, 9, 15, tzinfo=IST))
    assert is_market_open(datetime(2026, 10, 26, 15, 30, tzinfo=IST))
    assert not is_market_open(datetime(2026, 10, 26, 9, 14, tzinfo=IST))
    assert not is_market_open(datetime(2026, 10, 26, 15, 31, tzinfo=IST))
    assert not is_market_open(datetime(2026, 10, 25, 11, 0, tzinfo=IST))  # Sunday


def test_live_lines_header_and_change():
    lines = live_lines([("09:15", 100.0), ("09:20", 102.0)], previous_close=100.0, width=20, height=4)
    assert "102.00" in lines[0] and "+2.00%" in lines[0]
    assert "vs previous close 100.00" in lines[0]
    assert "last bar 09:20 IST" in lines[1]
    assert lines[-1].strip().startswith("09:15") and lines[-1].strip().endswith("09:20")


def test_live_text_colours_the_move():
    from indiabloom.chart import live_text
    up = live_text([("09:15", 100.0), ("09:20", 102.0)], 100.0, width=20, height=4)
    down = live_text([("09:15", 100.0), ("09:20", 98.0)], 100.0, width=20, height=4)
    assert "green" in str(up[0].spans[0].style)
    assert "red" in str(down[0].spans[0].style)


def test_live_chart_columns_are_coloured():
    from indiabloom.chart import live_text
    lines = live_text([("09:15", 99.0), ("09:20", 101.0)], 100.0, width=10, height=4)
    styles = {str(span.style) for line in lines for span in line.spans}
    assert "bold green" in styles and "bold red" in styles


def test_live_lines_before_open():
    assert live_lines([], None) == ["No intraday bars yet. The chart fills in after the 09:15 IST open."]


def _app(tmp_path, intraday):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [], intraday=intraday)
    return IndiaBloomApp(graph, load_companies(), services, index_name="none",
                         watchlist_path=tmp_path / "watchlist.json")


def test_live_view_shows_todays_bars(tmp_path):
    stamps = pd.to_datetime(["2026-10-26 09:15", "2026-10-26 09:20", "2026-10-26 09:25"]).tz_localize(IST)

    def intraday(ticker):
        return IntradayData(bars=pd.Series([100.0, 103.0, 101.0], index=stamps), previous_close=100.0)

    async def run():
        app = _app(tmp_path, intraday)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.select_stock("INFY.NS")
            await pilot.press("v")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "live"
            table = app.query_one("#links", DataTable)
            text = "\n".join(str(table.get_row_at(r)[0]) for r in range(table.row_count))
            assert "101.00" in text and "09:25 IST" in text

    asyncio.run(run())


def test_live_view_reports_fetch_failure(tmp_path):
    def broken(ticker):
        raise RuntimeError("yahoo unreachable")

    async def run():
        app = _app(tmp_path, broken)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.select_stock("INFY.NS")
            await pilot.press("v")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#links", DataTable)
            assert "live data failed: yahoo unreachable" in str(table.get_row_at(0)[0])

    asyncio.run(run())
