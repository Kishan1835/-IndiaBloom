import asyncio
from datetime import datetime

import pytest
from textual.widgets import DataTable, Input

from indiabloom.alerts import (
    Alert,
    AlertError,
    Rule,
    append_log,
    apply_alert_text,
    load_rules,
    parse_remove,
    parse_rule_text,
    save_rules,
)
from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


def test_parse_each_rule_form():
    assert parse_rule_text("infy.ns above 1700").__dict__ == {"ticker": "INFY.NS", "kind": "price_above",
                                                              "threshold": 1700.0}
    assert parse_rule_text("MU move_down -3").kind == "move_below"
    assert parse_rule_text("INFY.NS deals").threshold is None
    assert parse_rule_text("TCS.NS news").kind == "news"


@pytest.mark.parametrize("text", ["", "INFY.NS", "INFY.NS sideways 3", "INFY.NS above", "INFY.NS above abc",
                                  "INFY.NS deals 5"])
def test_bad_rule_text_is_rejected(text):
    with pytest.raises(AlertError):
        parse_rule_text(text)


def test_parse_remove():
    assert parse_remove("remove 3") == 3
    assert parse_remove("rm 7") == 7
    assert parse_remove("INFY.NS above 1700") is None
    with pytest.raises(AlertError):
        parse_remove("remove three")


def test_apply_adds_and_removes_rules(tmp_path):
    path = tmp_path / "alerts.json"
    assert apply_alert_text("INFY.NS above 1700", path) == "added rule 1: INFY.NS price_above 1700"
    assert apply_alert_text("MU move_down -3", path).startswith("added rule 2")
    rules, next_id = load_rules(path)
    assert [r.id for r in rules] == [1, 2] and next_id == 3
    assert apply_alert_text("remove 1", path) == "removed rule 1"
    assert [r.id for r in load_rules(path)[0]] == [2]
    with pytest.raises(AlertError):
        apply_alert_text("remove 1", path)


def test_deal_rule_marks_existing_history_as_seen(tmp_path):
    path = tmp_path / "alerts.json"
    apply_alert_text("INFY.NS deals", path)
    rules, _ = load_rules(path)
    assert rules[0].kind == "deal" and isinstance(rules[0].seen, list)


def _app(tmp_path):
    graph = Graph(parse_relations([
        {"source": "TCS.NS", "target": "INFY.NS", "relation": "peer",
         "confidence": "high", "rationale": "IT peers", "sources": []},
    ]))

    def offline(*args):
        raise MarketDataError("offline in test")

    services = Services(prices=offline, bulk=offline, news=lambda q: [])
    return IndiaBloomApp(graph, load_companies(), services, index_name="none",
                         watchlist_path=tmp_path / "watchlist.json",
                         alerts_path=tmp_path / "alerts.json",
                         alert_log_path=tmp_path / "log.csv")


def test_alerts_view_shows_rules_and_fired_log(tmp_path):
    save_rules([Rule(1, "INFY.NS", "price_above", 1700.0)], 2, tmp_path / "alerts.json")
    append_log([Alert(1, "INFY.NS", "INFY.NS at 1,750.00, at or above 1700")], datetime(2026, 10, 26, 9, 0),
               tmp_path / "log.csv")

    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            assert app.view == "alerts"
            table = app.query_one("#links", DataTable)
            rows = [[str(c) for c in table.get_row_at(r)] for r in range(table.row_count)]
            assert rows[0][0] == "rule" and rows[0][2] == "INFY.NS" and "price_above 1700" in rows[0][3]
            assert rows[1][3].startswith("INFY.NS at 1,750.00")

    asyncio.run(run())


def test_ctrl_l_adds_and_removes_rules_from_the_tui(tmp_path):
    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            await pilot.press("ctrl+l")
            await pilot.pause()
            box = app.query_one("#alert-input", Input)
            assert box.display and box.has_focus
            box.value = "INFY.NS below 1200"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            rules, _ = load_rules(tmp_path / "alerts.json")
            assert [(r.ticker, r.kind, r.threshold) for r in rules] == [("INFY.NS", "price_below", 1200.0)]
            table = app.query_one("#links", DataTable)
            assert table.row_count == 1  # the view refreshed with the new rule

            await pilot.press("ctrl+l")
            await pilot.pause()
            app.query_one("#alert-input", Input).value = "remove 1"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert load_rules(tmp_path / "alerts.json")[0] == []

    asyncio.run(run())


def test_bad_alert_text_reports_error_in_status(tmp_path):
    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+l")
            await pilot.pause()
            app.query_one("#alert-input", Input).value = "INFY.NS sideways 3"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            status = str(app.query_one("#status").render())
            assert "alert not saved" in status
            assert not (tmp_path / "alerts.json").exists()

    asyncio.run(run())
