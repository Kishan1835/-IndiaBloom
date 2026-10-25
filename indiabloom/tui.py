"""Terminal UI: browse stocks by sector, then see links, correlations, and news.

Left pane: sector tabs, a status line, and the stock list (Nifty 500 plus the
stocks in the relationship graph). Columns: ticker, last price, day change,
S&P 500 t-stat from the latest universe scan, and sector group.

Right pane: one view at a time.

Keys
  1 All   2 IT   3 Banks   4 Manufacturing   5 Pharma   6 US
  c competitors   s suppliers   u customers   r correlation   n news   f fundamentals   d deals   q quit
  ctrl+f search a stock by ticker or company name (Enter jumps to it, Esc closes)
  7 Watch (your watchlist)   a add or remove the selected stock from the watchlist   p position (P&L)
  x screen the index on fundamentals (e.g. pe_trailing<20, roe>=15); Enter on a result opens it
  m top movers (largest day gainers and losers)
  ? full key list (this panel is generated from the same bindings)

The status line under the stock list shows loading progress: the index list,
the price download, and the result (with the date of the latest prices).
Slow data loads in background threads, so the screen stays responsive.
"""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from indiabloom.companies import find_mentions
from indiabloom.deals import deals_for, load_history as load_deals
from indiabloom.fundamentals import fundamentals_rows, load_snapshot
from indiabloom.graph import Graph
from indiabloom.news import sentiment, sentiment_label
from indiabloom.peers import load_peers
from indiabloom.scanner import pair_metrics
from indiabloom.sectors import SECTORS_FILE, load_rules
from indiabloom.services import Services
from indiabloom.stock_list import (
    StockRow,
    build_stock_list,
    filter_group,
    find_stock,
    latest_us_t,
    top_movers,
)
from indiabloom.watchlist import (
    WATCHLIST_FILE,
    add_position,
    find_position,
    load_watchlist,
    position_rows,
    remove_position,
    save_watchlist,
)

GRAPH_VIEWS = ("competitors", "suppliers", "customers")
DATA_VIEWS = ("correlation", "news")
VIEW_LABELS = {
    "competitors": "Competitors",
    "suppliers": "Suppliers",
    "customers": "Customers",
    "correlation": "Correlation",
    "news": "News",
    "fundamentals": "Fundamentals",
    "deals": "Deals",
    "position": "Position",
    "movers": "Movers",
}
VIEW_KEYS = {"c": "competitors", "s": "suppliers", "u": "customers", "r": "correlation", "n": "news",
             "f": "fundamentals", "d": "deals", "p": "position", "m": "movers"}
LIST_VIEWS = ("screen", "movers")  # right pane shows a list of stocks, not one stock's data
FUNDAMENTALS_HINT = (
    "No fundamentals cached for {ticker}. Run: python -m indiabloom fundamentals --index {index}"
)

# tab key -> (button label, sector group or None for all)
TABS = {
    "all": ("All", None),
    "it": ("IT", "IT"),
    "banks": ("Banks", "Banks"),
    "mfg": ("Mfg", "Manufacturing"),
    "pharma": ("Pharma", "Pharma"),
    "us": ("US", "US"),
    "watch": ("Watch", None),  # filtered by the watchlist, not by sector
}
TAB_NUMBER_KEYS = {"1": "all", "2": "it", "3": "banks", "4": "mfg", "5": "pharma", "6": "us", "7": "watch"}
EMPTY_HINT = (
    "Nothing recorded under {view} for {ticker}. Add links to data/relations.json "
    "(supplier links are directed: source supplies target)."
)
INDEX_NAME = "nifty500"


class HelpScreen(ModalScreen):
    """Full key list, generated from the app's bindings so it always matches what the keys do."""

    BINDINGS = [("escape", "dismiss", "Close"), ("question_mark", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.lines = lines

    def compose(self) -> ComposeResult:
        with Vertical(id="help"):
            yield Static("\n".join(self.lines))
            yield Static("Press Esc, ? or q to close.", id="help-footer")


def help_lines(bindings: list[tuple[str, str, str]]) -> list[str]:
    """One line per key: the key, then what it does. Duplicate keys are listed once."""
    seen: set[str] = set()
    lines = ["IndiaBloom keys", ""]
    for key, _action, description in bindings:
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  {key:<12} {description}")
    return lines


class IndiaBloomApp(App):
    """Sector-aware browser for Indian stocks and their US links."""

    TITLE = "IndiaBloom"
    SUB_TITLE = "Indian stocks by sector, with US links"
    CSS = """
    #left { width: 55%; min-width: 60; }
    #tabs { height: auto; }
    #tabs Button { margin-right: 0; min-width: 5; padding: 0 1; }
    #stocks { height: 1fr; }
    #status { height: auto; color: $accent; padding: 0 1; }
    #right { width: 1fr; padding: 0 1; }
    #summary { height: auto; padding: 1 0; text-style: bold; }
    #buttons { layout: grid; grid-size: 3; grid-gutter: 0 1; height: auto; }
    #buttons Button { width: 100%; min-width: 0; }
    #links { height: 1fr; }
    #hint { height: auto; color: $warning; }
    HelpScreen { align: center middle; }
    #help { width: 60; height: auto; max-height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    #help-footer { color: $text-muted; }
    """
    BINDINGS = (
        [(key, f"tab('{name}')", TABS[name][0]) for key, name in TAB_NUMBER_KEYS.items()]
        + [(key, f"show('{view}')", VIEW_LABELS[view]) for key, view in VIEW_KEYS.items()]
        + [("q", "quit", "Quit"), ("ctrl+f", "search", "Search"), ("escape", "close_search", "Close search"),
           ("a", "watch_toggle", "Watch +/-"), ("x", "open_screen", "Screen"), ("question_mark", "help", "Help")]
    )

    def __init__(self, graph: Graph, names: dict[str, tuple[str, ...]] | None = None,
                 services: Services | None = None, index_name: str = INDEX_NAME,
                 watchlist_path: Path = WATCHLIST_FILE) -> None:
        super().__init__()
        self.graph = graph
        self.names = names or {}
        self.services = services or Services()
        self.index_name = index_name
        self.watchlist_path = watchlist_path
        self.positions = load_watchlist(watchlist_path)
        self.screen_hits: list[dict] = []
        self.screen_text = ""
        self.screen_total = 0
        self.stocks: list[StockRow] = []
        self.company_names: dict[str, str] = {}  # ticker -> company name from the index list
        self.group: str | None = None
        self.tab = "all"
        self.selected: str | None = None
        self.view = "competitors"
        self._results: dict[tuple[str, str], object] = {}
        self.peers = load_peers()

    # ----- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield Input(placeholder="Search ticker or company name. Enter jumps, Esc closes.",
                            id="search")
                with Horizontal(id="tabs"):
                    for name, (label, _) in TABS.items():
                        variant = "primary" if name == self.tab else "default"
                        yield Button(label, id=f"tab-{name}", variant=variant)
                stocks = DataTable(id="stocks", cursor_type="row", zebra_stripes=True)
                stocks.add_column("TICKER", key="ticker", width=14)
                stocks.add_column("PRICE", key="price", width=11)
                stocks.add_column("CHG%", key="change", width=8)
                stocks.add_column("US-T", key="ust", width=6)
                stocks.add_column("SECTOR", key="group", width=14)
                yield stocks
                yield Static("Starting...", id="status")
            with Vertical(id="right"):
                yield Input(placeholder="Screen: conditions separated by commas, e.g. pe_trailing<20, roe>=15. Enter runs, Esc closes.",
                            id="screen-input")
                yield Static("Choose a stock on the left.", id="summary")
                with Horizontal(id="buttons"):
                    for view in (*GRAPH_VIEWS, *DATA_VIEWS, "fundamentals", "deals", "position", "movers"):
                        variant = "primary" if view == self.view else "default"
                        yield Button(VIEW_LABELS[view], id=f"btn-{view}", variant=variant)
                yield DataTable(id="links", cursor_type="row", zebra_stripes=True)
                yield Static("", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search", Input).display = False
        self.query_one("#screen-input", Input).display = False
        self.query_one("#stocks", DataTable).focus()  # keys must reach the view bindings, not the search box
        self._select_first_graph_node()
        self._load_market()

    def _select_first_graph_node(self) -> None:
        nodes = self.graph.nodes()
        if nodes:
            self.select_stock(nodes[0])

    # ----- events -------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is None:
            return
        if event.data_table.id == "stocks":
            self.select_stock(str(event.row_key.value))
        elif event.data_table.id == "links" and self.view in LIST_VIEWS:
            self.select_stock(str(event.row_key.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("tab-"):
            self.action_tab(button_id.removeprefix("tab-"))
        elif button_id.startswith("btn-"):
            self.action_show(button_id.removeprefix("btn-"))

    def action_tab(self, name: str) -> None:
        if name not in TABS:
            return
        self.tab = name
        self.group = TABS[name][1]
        for key in TABS:
            self.query_one(f"#tab-{key}", Button).variant = "primary" if key == name else "default"
        self._render_stock_table()

    def action_show(self, view: str) -> None:
        if view not in VIEW_LABELS:
            return
        self.view = view
        for name in VIEW_LABELS:
            self.query_one(f"#btn-{name}", Button).variant = "primary" if name == view else "default"
        self._render()

    def select_stock(self, ticker: str) -> None:
        self.selected = ticker
        if self.view in LIST_VIEWS:
            self.action_show("competitors")  # leaving the list for a single stock
        else:
            self._render()

    # ----- screen (x) ---------------------------------------------------------

    def action_open_screen(self) -> None:
        box = self.query_one("#screen-input", Input)
        box.display = True
        box.value = ""
        box.focus()

    def _run_screen(self, text: str) -> None:
        from indiabloom.fundamentals import load_snapshot
        from indiabloom.screener import ScreenError, parse_condition, screen
        from indiabloom.universe import UniverseError, load_index

        parts = [p for p in text.split(",") if p.strip()]
        try:
            conditions = [parse_condition(p) for p in parts]
        except ScreenError as exc:
            self._show_message(str(exc))
            return
        try:
            constituents = load_index(self.index_name)
        except UniverseError:
            constituents = []
        snapshots = [s for s in (load_snapshot(c.ticker) for c in constituents) if s is not None]
        self.screen_text = text
        self.screen_total = len(snapshots)
        self.screen_hits = screen(snapshots, conditions, top=100)
        self.view = "screen"
        for name in VIEW_LABELS:
            self.query_one(f"#btn-{name}", Button).variant = "default"
        self._show_screen_results()

    def _show_screen_results(self) -> None:
        from indiabloom.screener import metric

        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        for key, label in (("ticker", "TICKER"), ("name", "NAME"), ("sector", "SECTOR"),
                           ("mcap", "MCAP CR"), ("pe", "PE"), ("roe", "ROE %"), ("pb", "PB")):
            table.add_column(label, key=key)

        def fmt(value: object, digits: int = 1) -> str:
            return "-" if value is None or isinstance(value, str) else f"{value:,.{digits}f}"

        for s in self.screen_hits:
            table.add_row(
                s["ticker"], (s.get("name") or "")[:28], (s.get("sector") or "-")[:16],
                fmt(metric(s, "market_cap_cr"), 0), fmt(s.get("pe_trailing")),
                fmt(metric(s, "roe")), fmt(s.get("pb")), key=s["ticker"],
            )
        self.query_one("#summary", Static).update(
            f"Screen: {len(self.screen_hits)} of {self.screen_total} cached stocks  |  {self.screen_text}"
        )
        hint = self.query_one("#hint", Static)
        if self.screen_hits:
            hint.update("Enter on a row opens that stock. Press x to change the screen.")
        else:
            hint.update("No stock matches. Press x to change the screen. Run fundamentals first if the cache is empty.")

    def action_help(self) -> None:
        self.push_screen(HelpScreen(help_lines(self.BINDINGS)))

    def action_search(self) -> None:
        box = self.query_one("#search", Input)
        box.display = True
        box.value = ""
        box.focus()

    def _show_movers(self) -> None:
        gainers, losers = top_movers(self.stocks, n=10)
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        for key, label in (("side", "SIDE"), ("ticker", "TICKER"), ("chg", "CHG%"),
                           ("price", "PRICE"), ("sector", "SECTOR")):
            table.add_column(label, key=key)
        for side, rows in (("UP", gainers), ("DOWN", losers)):
            for r in rows:
                table.add_row(side, r.ticker, f"{r.change_pct:+.2f}",
                              "-" if r.last is None else f"{r.last:,.2f}", r.group, key=r.ticker)
        priced = sum(1 for r in self.stocks if r.change_pct is not None)
        self.query_one("#summary", Static).update(
            f"Top movers: {len(gainers)} gainers, {len(losers)} losers  |  {priced} stocks with a day change"
        )
        hint = self.query_one("#hint", Static)
        hint.update("Day change from the last two closes. Enter on a row opens that stock."
                    if priced else "No price data yet. Wait for the price download to finish.")

    def action_close_search(self) -> None:
        for box_id in ("#search", "#screen-input"):
            box = self.query_one(box_id, Input)
            if box.display:
                box.display = False
                self.query_one("#stocks", DataTable).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "screen-input":
            text = event.value.strip()
            event.input.display = False
            self.query_one("#links", DataTable).focus()
            if text:
                self._run_screen(text)
            return
        if event.input.id != "search":
            return
        query = event.value.strip()
        event.input.display = False
        self.query_one("#stocks", DataTable).focus()
        if not query:
            return
        tickers = list(dict.fromkeys([r.ticker for r in self.stocks] + self.graph.nodes()))
        found = find_stock(query, tickers, {**self.company_names, **{t: v[0] for t, v in self.names.items()}})
        if found is None:
            self._show_status(f"No stock matches '{query}'.")
            return
        if self.tab != "all":
            self.action_tab("all")  # the match must be visible in the list to be highlighted
        index = next((i for i, r in enumerate(self.stocks) if r.ticker == found), None)
        if index is not None:
            self.query_one("#stocks", DataTable).move_cursor(row=index)
        self.select_stock(found)

    # ----- stock list and loading status --------------------------------------

    def _show_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _visible_stocks(self) -> list[StockRow]:
        if self.tab == "watch":
            watched = {p.ticker for p in self.positions}
            return [r for r in self.stocks if r.ticker in watched]
        return filter_group(self.stocks, self.group)

    def action_watch_toggle(self) -> None:
        """Add or remove the selected stock from the watchlist and save it."""
        ticker = self.selected
        if ticker is None:
            return
        if find_position(self.positions, ticker) is not None:
            self.positions = remove_position(self.positions, ticker)
            message = f"Removed {ticker} from the watchlist."
        else:
            self.positions = add_position(self.positions, ticker)
            message = f"Added {ticker} to the watchlist. Set buy price with: python -m indiabloom watchlist add {ticker} --buy PRICE --qty N"
        save_watchlist(self.positions, self.watchlist_path)
        if self.tab == "watch":
            self._render_stock_table()
        self._show_status(message)

    def _render_stock_table(self) -> None:
        table = self.query_one("#stocks", DataTable)
        table.clear()
        shown = self._visible_stocks()
        for row in shown:
            table.add_row(
                row.ticker,
                "-" if row.last is None else f"{row.last:,.2f}",
                "-" if row.change_pct is None else f"{row.change_pct:+.2f}",
                "-" if row.us_t is None else f"{row.us_t:.2f}",
                row.group,
                key=row.ticker,
            )
        if self.stocks:
            self.query_one("#status", Static).update(
                f"showing {len(shown)} of {len(self.stocks)} stocks  |  "
                f"tab: {TABS[self.tab][0]}"
            )

    @work(thread=True, exclusive=True, group="market")
    def _load_market(self) -> None:
        from indiabloom.market import MarketDataError
        from indiabloom.universe import UniverseError, load_index

        self.call_from_thread(self._show_status, "Step 1/2: loading the Nifty 500 list...")
        constituents: list = []
        try:
            constituents = load_index(self.index_name)
        except UniverseError as exc:
            self.call_from_thread(self._show_status,
                                  f"Nifty list unavailable ({exc}). Showing graph stocks only.")
        tickers = sorted({c.ticker for c in constituents} | set(self.graph.nodes()))

        self.call_from_thread(
            self._show_status,
            f"Step 2/2: downloading 2 years of prices for {len(tickers)} stocks. "
            "The first run takes about a minute.",
        )
        try:
            closes = self.services.bulk(tickers, "2y")
        except MarketDataError as exc:
            self.call_from_thread(self._show_status, f"Price download failed: {exc}")
            return
        except Exception as exc:
            self.call_from_thread(self._show_status, f"Price download failed: {exc}")
            return

        rules = load_rules(SECTORS_FILE)
        rows = build_stock_list(constituents, closes, self.graph, rules, latest_us_t())
        as_of = closes.index.max().date().isoformat() if len(closes.index) else "unknown"
        self.call_from_thread(self._set_stocks, rows, constituents, as_of)

    def _set_stocks(self, rows: list[StockRow], constituents: list, as_of: str) -> None:
        self.stocks = rows
        self.company_names = {c.ticker: c.company for c in constituents}
        self._render_stock_table()
        missing = sum(1 for r in rows if r.last is None)
        message = f"Loaded {len(rows)} stocks. Latest prices: {as_of}."
        if missing:
            message += f" {missing} have no price data."
        self._show_status(message)

    # ----- right pane ---------------------------------------------------------

    def _render(self) -> None:
        if self.view == "screen":
            self._show_screen_results()
            return
        if self.view == "movers":
            self._show_movers()
            return
        if self.selected is None:
            return
        ticker = self.selected
        total = len(self.graph.links(ticker))
        self.query_one("#summary", Static).update(
            f"{ticker}  |  {total} link(s) recorded  |  {VIEW_LABELS[self.view]}"
        )
        self.query_one("#hint", Static).update("")
        if self.view in GRAPH_VIEWS:
            self._show_graph_view(ticker)
            return
        if self.view == "fundamentals":
            self._show_fundamentals(ticker)  # reads the local cache only; no network
            return
        if self.view == "deals":
            self._show_deals(ticker)  # reads the local deals history only
            return
        if self.view == "position":
            self._show_position(ticker)
            return
        cached = self._results.get((self.view, ticker))
        if cached is not None:
            self._populate(self.view, cached)
        elif self.view == "correlation":
            self._show_message("Loading prices and computing correlations...")
            self._load_correlation(ticker)
        else:
            self._show_message("Loading news...")
            self._load_news(ticker)

    def _show_message(self, text: str) -> None:
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        table.add_column("STATUS", key="status")
        table.add_row(text, key="status-row")

    def _show_graph_view(self, ticker: str) -> None:
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        table.add_column("TICKER", key="other")
        table.add_column("TYPE", key="type")
        table.add_column("DIRECTION", key="direction")
        table.add_column("CONF", key="conf")
        table.add_column("RATIONALE", key="why")
        links = getattr(self.graph, self.view)(ticker)
        for link in links:
            table.add_row(link.other, link.relation, link.direction or "mutual",
                          link.confidence, link.rationale)
        if self.view == "competitors":
            # statistical peers come from price history; label them so they are not
            # mistaken for recorded business competitors
            for peer in self.peers.get(ticker, []):
                table.add_row(
                    peer.peer, "stat-peer", "mutual", f"corr {peer.corr:.2f}",
                    f"same industry ({peer.industry}); prices move together, not a business link",
                )
        if table.row_count == 0:
            self.query_one("#hint", Static).update(
                EMPTY_HINT.format(view=VIEW_LABELS[self.view].lower(), ticker=ticker)
            )

    def _show_fundamentals(self, ticker: str) -> None:
        snap = load_snapshot(ticker)
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        table.add_column("METRIC", key="metric")
        table.add_column("VALUE", key="value")
        if snap is None:
            self.query_one("#hint", Static).update(FUNDAMENTALS_HINT.format(ticker=ticker, index=self.index_name))
            return
        for metric, value in fundamentals_rows(snap):
            table.add_row(metric, value)
        self.query_one("#hint", Static).update(f"Source: yfinance, fetched {snap.get('fetched_at', '?')}")

    def _show_position(self, ticker: str) -> None:
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        table.add_column("METRIC", key="metric")
        table.add_column("VALUE", key="value")
        position = find_position(self.positions, ticker)
        hint = self.query_one("#hint", Static)
        if position is None:
            hint.update(f"{ticker} is not in the watchlist. Press a to add it.")
            return
        row = next((r for r in self.stocks if r.ticker == ticker), None)
        for metric, value in position_rows(position, None if row is None else row.last):
            table.add_row(metric, value)
        hint.update("Set buy price and quantity: python -m indiabloom watchlist add "
                    f"{ticker} --buy PRICE --qty N")

    def _show_deals(self, ticker: str) -> None:
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        for key, label in (("date", "DATE"), ("kind", "TYPE"), ("side", "SIDE"),
                           ("client", "CLIENT"), ("qty", "QTY"), ("price", "PRICE"), ("value", "VALUE CR")):
            table.add_column(label, key=key)
        deals = deals_for(ticker, load_deals())
        for d in deals:
            table.add_row(d.date, d.kind, d.side, d.client, f"{d.quantity:,}",
                          f"{d.price:,.2f}", f"{d.value_cr:,.2f}")
        hint = self.query_one("#hint", Static)
        if deals:
            hint.update("Bulk/block deals only: large trades, not all institutional flows. "
                        "History grows each time `python -m indiabloom deals` runs.")
        else:
            hint.update(f"No bulk or block deals recorded for {ticker}. History starts from the "
                        "first `python -m indiabloom deals` run.")

    def _populate(self, view: str, data: object) -> None:
        table = self.query_one("#links", DataTable)
        table.clear(columns=True)
        if view == "correlation":
            table.add_column("OTHER", key="other")
            table.add_column("METHOD", key="method")
            table.add_column("LEADER", key="leader")
            table.add_column("N", key="n")
            table.add_column("CORR", key="corr")
            table.add_column("BETA", key="beta")
            for m in data:  # type: ignore[attr-defined]
                other = m.b if m.a == self.selected else m.a
                table.add_row(other, m.method, m.leader or "-", str(m.n_obs),
                              _fmt(m.corr), _fmt(m.beta))
            if not data:
                self.query_one("#hint", Static).update("No linked stocks with price data.")
        elif view == "news":
            table.add_column("TIME", key="time")
            table.add_column("SENT", key="sent")
            table.add_column("HEADLINE", key="headline")
            table.add_column("MENTIONS", key="mentions")
            for item in data:  # type: ignore[attr-defined]
                when = item.published.strftime("%Y-%m-%d %H:%M") if item.published else "-"
                score = sentiment(item.title)
                mentions = ", ".join(sorted(find_mentions(item.title, self.names))) or "-"
                table.add_row(when, sentiment_label(score), item.title, mentions)
            if not data:
                self.query_one("#hint", Static).update("No headlines found.")

    def _search_name(self, ticker: str) -> str | None:
        """Company name to search news for: our names file first, then the index list."""
        if ticker in self.names:
            return self.names[ticker][0]
        return self.company_names.get(ticker)

    # ----- background loading -------------------------------------------------

    @work(thread=True, exclusive=True, group="detail")
    def _load_correlation(self, ticker: str) -> None:
        others = [link.other for link in self.graph.links(ticker)]
        try:
            closes = self.services.prices([ticker, *others], "2y")
            data = []
            for other in others:
                if ticker in closes.columns and other in closes.columns:
                    data.append(pair_metrics(ticker, other, closes))
        except Exception as exc:  # network or data failure: show it instead of hanging
            data = _error(f"correlation failed: {exc}")
        self.call_from_thread(self._store_result, "correlation", ticker, data)

    @work(thread=True, exclusive=True, group="detail")
    def _load_news(self, ticker: str) -> None:
        name = self._search_name(ticker)
        if name is None:
            data = _error(f"no company name known for {ticker}")
        else:
            try:
                data = self.services.news(f"{name} stock")
            except Exception as exc:
                data = _error(f"news failed: {exc}")
        self.call_from_thread(self._store_result, "news", ticker, data)

    def _store_result(self, view: str, ticker: str, data: object) -> None:
        if isinstance(data, _Error):
            if self.selected == ticker and self.view == view:
                self._show_message(data.message)
            return
        self._results[(view, ticker)] = data
        if self.selected == ticker and self.view == view:
            self._populate(view, data)


class _Error:
    """Marker for a failed background load, shown in place of results."""

    def __init__(self, message: str) -> None:
        self.message = message


def _error(message: str) -> _Error:
    return _Error(message)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"
