import asyncio

from textual.command import CommandPalette

from indiabloom.companies import load_companies
from indiabloom.graph import Graph, parse_relations
from indiabloom.market import MarketDataError
from indiabloom.services import Services
from indiabloom.tui import IndiaBloomApp


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


def _commands(app):
    from textual.screen import Screen
    return list(app.get_system_commands(Screen(id="test")))


def test_palette_lists_every_view_tab_and_action(tmp_path):
    app = _app(tmp_path)
    titles = [c.title for c in _commands(app)]
    assert "View: Fundamentals" in titles
    assert "View: Chart" in titles and "View: Movers" in titles
    assert "Stock list: Watch" in titles and "Stock list: IT" in titles
    for action in ("Search a stock", "Screen the index", "Compare stocks", "Toggle watchlist", "Show all keys"):
        assert action in titles
    assert "Quit" in titles and "Theme" in titles  # Textual's own commands are still there


def test_ctrl_p_opens_palette(tmp_path):
    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert isinstance(app.screen, CommandPalette)

    asyncio.run(run())


def test_palette_command_switches_view(tmp_path):
    async def run():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            command = next(c for c in _commands(app) if c.title == "View: Movers")
            command.callback()
            await pilot.pause()
            assert app.view == "movers"

    asyncio.run(run())
