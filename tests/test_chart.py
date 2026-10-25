import asyncio

import numpy as np
import pandas as pd
from textual.widgets import DataTable

from indiabloom.chart import chart_lines, range_summary, render_chart
from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def test_render_chart_places_high_top_and_low_bottom():
    lines = render_chart([1.0, 2.0, 3.0], width=3, height=3)
    assert len(lines) == 3
    assert lines[0].endswith("  *") or lines[0].rstrip().endswith("*")  # high at top, right end
    assert lines[2].split("|", 1)[1][0] == "*"  # low at bottom, left end
    assert "3.0" in lines[0] and "1.0" in lines[2]


def test_render_chart_handles_flat_and_short_series():
    assert render_chart([5.0], width=10, height=4) == []
    flat = render_chart([5.0, 5.0, 5.0], width=5, height=4)
    assert len(flat) == 4  # no division by zero on a flat line


def test_range_summary_percent_change():
    text = range_summary([100.0, 110.0, 90.0, 120.0])
    assert "change +20.00%" in text
    assert "high 120.00" in text and "low 90.00" in text


def test_chart_lines_has_three_ranges_and_flags_short_history():
    closes = list(np.linspace(100, 200, 60))
    lines = chart_lines(closes, width=20, height=4)
    headers = [line for line in lines if line.startswith(("1M", "6M", "1Y"))]
    assert [h[:2] for h in headers] == ["1M", "6M", "1Y"]
    assert "change +" in "".join(lines[:6])  # 1M window has data
    assert not any("not enough" in line for line in lines)  # 60 closes covers 1M and the shorter 6M/1Y windows

    single = chart_lines([100.0], width=20, height=4)
    assert sum("not enough price history" in line for line in single) == 3


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


def test_chart_view_loads_and_renders(tmp_path):
    index = pd.bdate_range("2025-01-01", periods=300)

    def prices(tickers, period):
        return pd.DataFrame({t: np.linspace(100, 150, len(index)) for t in tickers}, index=index)

    async def run():
        app = _app(tmp_path, prices)
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("h")
            await pilot.pause()
            assert app.view == "chart"
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#links", DataTable)
            text = "\n".join(str(table.get_row_at(r)[0]) for r in range(table.row_count))
            assert "1M  start" in text and "6M" in text and "1Y  start" in text
            assert "1Y  start 107.86  end 150.00  change +39.07%" in text  # window: last 253 of 300 closes

    asyncio.run(run())
