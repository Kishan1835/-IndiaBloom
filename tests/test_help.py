import asyncio

from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.tui import HelpScreen, IndiaBloomApp, help_lines


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


def test_help_lists_every_binding_key():
    lines = help_lines(IndiaBloomApp.BINDINGS)
    for key, _action, _desc in IndiaBloomApp.BINDINGS:
        assert any(line.strip().startswith(key + " ") or line.strip() == key for line in lines), \
            f"key {key} missing from help"


def test_question_mark_opens_help_and_escape_closes(tmp_path):
    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(run())
