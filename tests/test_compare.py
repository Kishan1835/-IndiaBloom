import asyncio

import numpy as np
import pandas as pd
from textual.widgets import DataTable

from indiabloom.chart import compare_lines, rebase_common
from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def _closes():
    index = pd.bdate_range("2025-01-01", periods=100)
    return pd.DataFrame({
        "A.NS": np.linspace(50, 100, 100),    # doubles: +100%
        "B.NS": np.linspace(5000, 4000, 100),  # falls 20%
    }, index=index)


def test_rebase_starts_at_100_and_keeps_common_dates():
    closes = _closes()
    closes.iloc[0, closes.columns.get_loc("B.NS")] = np.nan  # B has no first-day price
    series, missing = rebase_common(closes, ["A.NS", "B.NS"])
    assert missing == []
    assert len(series["A.NS"]) == len(series["B.NS"]) == 99  # first common date is day 2
    assert series["A.NS"][0] == 100.0 and series["B.NS"][0] == 100.0


def test_missing_ticker_is_reported_and_comparison_uses_the_rest():
    series, missing = rebase_common(_closes(), ["A.NS", "B.NS", "NOPE.NS"])
    assert missing == ["NOPE.NS"]
    assert set(series) == {"A.NS", "B.NS"}


def test_compare_lines_has_legend_with_returns():
    lines = compare_lines(_closes(), ["A.NS", "B.NS"], width=30, height=6)
    text = "\n".join(lines)
    assert "A.NS" in text and "B.NS" in text
    assert "(+0.0%)" not in text
    assert any("A.NS" in line and "(+" in line and "%)" in line for line in lines)
    assert any("B.NS" in line and "(-" in line for line in lines)


def test_compare_needs_two_stocks_with_data():
    lines = compare_lines(_closes(), ["A.NS", "NOPE.NS"])
    assert any("Need at least two" in line for line in lines)


def _app(tmp_path, prices):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        from indiabloom.market import MarketDataError
        raise MarketDataError("offline in test")

    services = Services(prices=prices, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none",
                         watchlist_path=tmp_path / "watchlist.json")


def test_compare_view_runs_from_input(tmp_path):
    closes = _closes()

    def prices(tickers, period):
        return closes[[t for t in tickers if t in closes.columns]]

    async def run():
        app = _app(tmp_path, prices)
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            box = app.query_one("#compare-input")
            assert box.display and box.has_focus
            box.value = "a.ns, b.ns"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "compare"
            table = app.query_one("#links", DataTable)
            text = "\n".join(str(table.get_row_at(r)[0]) for r in range(table.row_count))
            assert "A.NS" in text and "B.NS" in text
            assert "COMPARE" not in text  # column header is not a row

    asyncio.run(run())


def test_compare_needs_two_tickers(tmp_path):
    closes = _closes()

    async def run():
        app = _app(tmp_path, lambda t, p: closes)
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            app.query_one("#compare-input").value = "A.NS"
            await pilot.press("enter")
            await pilot.pause()
            assert app.view != "compare"

    asyncio.run(run())
