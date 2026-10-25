import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
from textual.widgets import DataTable

from indiabloom.companies import load_companies
from indiabloom.events import build_events, is_fresh, load_events, run_events, save_events, upcoming
from indiabloom.graph import Graph, parse_relations
from indiabloom.holdings import HoldingPoint, append_holdings, change, load_holdings
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp

NOW = datetime(2026, 10, 25, 10, 0, 0)


def _earnings():
    idx = pd.to_datetime(["2027-01-13 05:00", "2026-10-23 11:00", "2026-07-23 06:00"]).tz_localize(None)
    return pd.DataFrame({
        "EPS Estimate": [18.5, 19.6, 19.1],
        "Reported EPS": [float("nan"), 19.3, 19.2],
        "Surprise(%)": [float("nan"), -1.45, 0.27],
    }, index=idx)


def test_build_events_maps_calendar_results_and_dividends():
    dividends = pd.Series([22.0, 25.0], index=pd.to_datetime(["2025-05-30", "2026-06-10"]))
    events = build_events("INFY.NS", {"Earnings Date": [date(2027, 1, 13)],
                                      "Ex-Dividend Date": date(2026, 11, 3)},
                          _earnings(), dividends, None, fetched_at=NOW)
    assert events["next_results"] == "2027-01-13"
    assert events["ex_dividend"] == "2026-11-03"
    # the future results row has no reported EPS yet, so it is not a past result
    assert [r["date"] for r in events["past_results"]] == ["2026-10-23", "2026-07-23"]
    assert events["past_results"][0]["reported_eps"] == 19.3
    assert events["dividends"][0] == {"date": "2026-06-10", "amount": 25.0}  # newest first
    assert events["splits"] == []


def test_missing_pieces_are_none_not_guessed():
    events = build_events("X.NS", {}, None, None, None, fetched_at=NOW)
    assert events["next_results"] is None and events["ex_dividend"] is None
    assert events["past_results"] == [] and events["dividends"] == []


def test_upcoming_window_sorted_and_bounded():
    today = date(2026, 10, 25)
    events = [
        {"ticker": "A.NS", "next_results": "2026-10-30", "ex_dividend": None},
        {"ticker": "B.NS", "next_results": None, "ex_dividend": "2026-10-27"},
        {"ticker": "C.NS", "next_results": "2027-01-13", "ex_dividend": None},  # outside 30 days
        {"ticker": "D.NS", "next_results": "2026-10-20", "ex_dividend": None},  # already past
    ]
    rows = upcoming(events, today, 30)
    assert rows == [(date(2026, 10, 27), "B.NS", "Ex-dividend"), (date(2026, 10, 30), "A.NS", "Results")]


def test_run_events_is_resumable_and_records_failures(tmp_path):
    calls = []

    def fake(ticker):
        calls.append(ticker)
        if ticker == "BAD.NS":
            raise RuntimeError("no data")
        return build_events(ticker, {}, None, None, None, fetched_at=NOW)

    fetched, skipped, failures = run_events(["A.NS", "BAD.NS"], tmp_path, fetch=fake, sleep_s=0, now=NOW)
    assert (fetched, skipped, [f.ticker for f in failures]) == (1, 0, ["BAD.NS"])
    fetched, skipped, _ = run_events(["A.NS", "BAD.NS"], tmp_path, fetch=fake, sleep_s=0, now=NOW)
    assert skipped == 1  # A is fresh; BAD was never cached so it is retried
    assert calls == ["A.NS", "BAD.NS", "BAD.NS"]


def test_events_freshness_is_one_day(tmp_path):
    events = build_events("A.NS", {}, None, None, None, fetched_at=NOW)
    save_events(events, tmp_path)
    assert load_events("A.NS", tmp_path) == events
    assert is_fresh(events, NOW + timedelta(hours=23))
    assert not is_fresh(events, NOW + timedelta(days=2))


def test_holdings_append_dedupes_and_reports_change(tmp_path):
    path = tmp_path / "holdings.csv"
    first = [HoldingPoint("2026-10-01", "INFY.NS", 16.0, 50.0)]
    assert append_holdings(first, path) == 1
    assert append_holdings(first, path) == 0  # same date and ticker: not repeated
    assert append_holdings([HoldingPoint("2026-10-25", "INFY.NS", 15.5, 51.2),
                            HoldingPoint("2026-10-25", "TCS.NS", None, None)], path) == 2
    points = load_holdings(path)
    pair = change(points, "INFY.NS")
    assert pair is not None and pair[0].date == "2026-10-01" and pair[1].institution_pct == 51.2
    assert change(points, "TCS.NS") is None  # one point is not a change


def _app(tmp_path):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none",
                         watchlist_path=tmp_path / "watchlist.json")


def test_events_view_shows_cached_dates(monkeypatch, tmp_path):
    events = build_events("INFY.NS", {"Earnings Date": [date(2027, 1, 13)]}, _earnings(), None, None,
                          fetched_at=NOW)
    monkeypatch.setattr("indiabloom.events.load_events", lambda ticker, directory=None: events)

    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            app.select_stock("INFY.NS")
            await pilot.press("k")
            await pilot.pause()
            assert app.view == "events"
            table = app.query_one("#links", DataTable)
            rows = {str(table.get_row_at(r)[0]): str(table.get_row_at(r)[1]) for r in range(table.row_count)}
            assert rows["Next results"] == "2027-01-13"
            assert any(k.startswith("Results 2026-10-23") for k in rows)

    asyncio.run(run())
