"""Terminal UI: browse stocks by sector, then see links, correlations, and news.

Left pane: sector tabs, a status line, and the stock list (Nifty 500 plus the
stocks in the relationship graph). Columns: ticker, last price, day change,
S&P 500 t-stat from the latest universe scan, and sector group.

Right pane: one view at a time.

Keys
  1 All   2 IT   3 Banks   4 Manufacturing   5 Pharma   6 US
  c competitors   s suppliers   u customers   r correlation   n news   q quit

The status line under the stock list shows loading progress: the index list,
the price download, and the result (with the date of the latest prices).
Slow data loads in background threads, so the screen stays responsive.
"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Static

from indiabloom.companies import find_mentions
from indiabloom.graph import Graph
from indiabloom.news import sentiment, sentiment_label
from indiabloom.scanner import pair_metrics
from indiabloom.sectors import SECTORS_FILE, load_rules
from indiabloom.services import Services
from indiabloom.stock_list import (
    StockRow,
    build_stock_list,
    filter_group,
    latest_us_t,
)

GRAPH_VIEWS = ("competitors", "suppliers", "customers")
DATA_VIEWS = ("correlation", "news")
VIEW_LABELS = {
    "competitors": "Competitors",
    "suppliers": "Suppliers",
    "customers": "Customers",
    "correlation": "Correlation",
    "news": "News",
}
VIEW_KEYS = {"c": "competitors", "s": "suppliers", "u": "customers", "r": "correlation", "n": "news"}

# tab key -> (button label, sector group or None for all)
TABS = {
    "all": ("All", None),
    "it": ("IT", "IT"),
    "banks": ("Banks", "Banks"),
    "mfg": ("Mfg", "Manufacturing"),
    "pharma": ("Pharma", "Pharma"),
    "us": ("US", "US"),
}
TAB_NUMBER_KEYS = {"1": "all", "2": "it", "3": "banks", "4": "mfg", "5": "pharma", "6": "us"}
EMPTY_HINT = (
    "Nothing recorded under {view} for {ticker}. Add links to data/relations.json "
    "(supplier links are directed: source supplies target)."
)
INDEX_NAME = "nifty500"


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
    """
    BINDINGS = (
        [(key, f"tab('{name}')", TABS[name][0]) for key, name in TAB_NUMBER_KEYS.items()]
        + [(key, f"show('{view}')", VIEW_LABELS[view]) for key, view in VIEW_KEYS.items()]
        + [("q", "quit", "Quit")]
    )

    def __init__(self, graph: Graph, names: dict[str, tuple[str, ...]] | None = None,
                 services: Services | None = None, index_name: str = INDEX_NAME) -> None:
        super().__init__()
        self.graph = graph
        self.names = names or {}
        self.services = services or Services()
        self.index_name = index_name
        self.stocks: list[StockRow] = []
        self.company_names: dict[str, str] = {}  # ticker -> company name from the index list
        self.group: str | None = None
        self.tab = "all"
        self.selected: str | None = None
        self.view = "competitors"
        self._results: dict[tuple[str, str], object] = {}

    # ----- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
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
                yield Static("Choose a stock on the left.", id="summary")
                with Horizontal(id="buttons"):
                    for view in (*GRAPH_VIEWS, *DATA_VIEWS):
                        variant = "primary" if view == self.view else "default"
                        yield Button(VIEW_LABELS[view], id=f"btn-{view}", variant=variant)
                yield DataTable(id="links", cursor_type="row", zebra_stripes=True)
                yield Static("", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self._select_first_graph_node()
        self._load_market()

    def _select_first_graph_node(self) -> None:
        nodes = self.graph.nodes()
        if nodes:
            self.select_stock(nodes[0])

    # ----- events -------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "stocks" and event.row_key.value is not None:
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
        self._render()

    # ----- stock list and loading status --------------------------------------

    def _show_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _render_stock_table(self) -> None:
        table = self.query_one("#stocks", DataTable)
        table.clear()
        shown = filter_group(self.stocks, self.group)
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
        if not links:
            self.query_one("#hint", Static).update(
                EMPTY_HINT.format(view=VIEW_LABELS[self.view].lower(), ticker=ticker)
            )
            return
        for link in links:
            table.add_row(link.other, link.relation, link.direction or "mutual",
                          link.confidence, link.rationale)

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
