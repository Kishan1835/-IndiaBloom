"""Command-line interface.

Commands:
  relations  every recorded link for a stock
  correlate  correlation between one US and one Indian stock
  scan       rank Indian counterparts of a US stock
  news       recent headlines for a company, with sentiment
  watch      headlines about US companies in the graph, with their Indian links
  ui         interactive terminal UI
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from indiabloom.analytics import (
    lagged_beta,
    lagged_correlation,
    log_returns,
    same_day_correlation,
)
from indiabloom.companies import DEFAULT_COMPANIES, CompanyFileError, load_companies
from indiabloom.graph import Graph, RelationValidationError, load_relations
from indiabloom.market import MarketDataError, fetch_closes
from indiabloom.news import NewsError, fetch_news, sentiment, sentiment_label
from indiabloom.scanner import scan
from indiabloom.services import Services
from indiabloom.signals_cli import add_signal_parsers, cmd_log_signals, cmd_score_signals
from indiabloom.watch import build_watch

DEFAULT_RELATIONS = Path(__file__).resolve().parent.parent / "data" / "relations.json"
EXIT_OK, EXIT_USAGE, EXIT_DATA = 0, 2, 3


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def _disclaimer() -> None:
    print("\nAnalysis only. Verify each link before acting. Not investment advice.")


def cmd_relations(args: argparse.Namespace, graph: Graph) -> int:
    links = graph.links(args.ticker)
    if not links:
        print(f"no relations recorded for {args.ticker.upper()}")
        return EXIT_OK
    rows = [[l.other, l.relation, l.direction or "mutual", l.confidence, l.rationale] for l in links]
    _print_table(["OTHER", "TYPE", "DIRECTION", "CONF", "RATIONALE"], rows)
    return EXIT_OK


def cmd_correlate(args: argparse.Namespace) -> int:
    closes = fetch_closes([args.global_ticker, args.indian_ticker], period=args.period)
    g = args.global_ticker.upper()
    i = args.indian_ticker.upper()
    if g not in closes or i not in closes:
        print("error: missing price data for one of the tickers", file=sys.stderr)
        return EXIT_DATA
    gr = log_returns(closes[g])
    ir = log_returns(closes[i])
    rows = [
        ["same-day corr (reference only)", _fmt(same_day_correlation(gr, ir))],
        ["next-session corr", _fmt(lagged_correlation(gr, ir, args.extra_lag))],
        ["beta", _fmt(lagged_beta(gr, ir, args.extra_lag))],
    ]
    _print_table(["METRIC", "VALUE"], rows)
    return EXIT_OK


def cmd_scan(args: argparse.Namespace, graph: Graph) -> int:
    counterparts_rel = graph.indian_counterparts(args.ticker)
    if not counterparts_rel:
        print(f"no Indian counterparts recorded for {args.ticker.upper()}")
        return EXIT_OK

    counterparts = [r.other(args.ticker.upper()) for r in counterparts_rel]
    if args.offline_demo:
        from indiabloom.demo import synthetic_closes

        followers = {t: 0.3 + 0.1 * idx for idx, t in enumerate(counterparts)}
        closes = synthetic_closes(args.ticker.upper(), followers, days=252)
    else:
        closes = fetch_closes([args.ticker] + counterparts, period=args.period)

    rows = scan(args.ticker, graph, closes, extra_lag=args.extra_lag)[: args.top]
    table = [
        [
            r.indian_ticker, r.relation, r.confidence, str(r.n_obs),
            _fmt(r.next_session_corr), _fmt(r.beta),
            _fmt(r.implied_move_pct, 2) + ("%" if r.implied_move_pct is not None else ""),
            _fmt(r.score), r.note,
        ]
        for r in rows
    ]
    _print_table(["INDIAN", "TYPE", "CONF", "N", "NEXT-CORR", "BETA", "IMPLIED", "SCORE", "NOTE"], table)
    _disclaimer()
    return EXIT_OK


def cmd_news(args: argparse.Namespace) -> int:
    names = load_companies(args.companies)
    ticker = args.ticker.upper()
    if ticker not in names:
        print(f"no company name recorded for {ticker} in {args.companies}", file=sys.stderr)
        return EXIT_USAGE
    items = fetch_news(f"{names[ticker][0]} stock", limit=args.limit)
    if not items:
        print(f"no headlines found for {names[ticker][0]}")
        return EXIT_OK
    rows = [
        [
            item.published.strftime("%Y-%m-%d %H:%M") if item.published else "-",
            sentiment_label(sentiment(item.title)),
            item.title,
        ]
        for item in items
    ]
    _print_table(["TIME", "SENT", "HEADLINE"], rows)
    _disclaimer()
    return EXIT_OK


def cmd_watch(args: argparse.Namespace, graph: Graph) -> int:
    names = load_companies(args.companies)
    rows = build_watch(graph, names, lambda q: fetch_news(q, limit=args.limit),
                       per_company=args.limit)
    if not rows:
        print("no recent headlines name a US company in the graph")
        _disclaimer()
        return EXIT_OK
    table = [
        [
            r.published.strftime("%Y-%m-%d") if r.published else "-",
            r.global_ticker, r.sentiment, ", ".join(r.indian_links) or "-", r.headline,
        ]
        for r in rows
    ]
    _print_table(["DATE", "US", "SENT", "INDIAN LINKS", "HEADLINE"], table)
    _disclaimer()
    return EXIT_OK


def cmd_universe(args: argparse.Namespace) -> int:
    from indiabloom.universe import UniverseError, load_index

    try:
        constituents = load_index(args.index)
    except UniverseError as exc:
        print(f"universe error: {exc}", file=sys.stderr)
        return EXIT_DATA
    rows = [[c.symbol, c.company, c.industry] for c in constituents]
    _print_table(["SYMBOL", "COMPANY", "INDUSTRY"], rows)
    print(f"\n{len(constituents)} constituents in {args.index}")
    return EXIT_OK


def cmd_universe_scan(args: argparse.Namespace) -> int:
    from datetime import date

    from indiabloom.market import download_bulk
    from indiabloom.universe import UniverseError, load_index
    from indiabloom.universe_scan import holdout_hit_rate, scan_universe

    try:
        constituents = load_index(args.index)
    except UniverseError as exc:
        print(f"universe error: {exc}", file=sys.stderr)
        return EXIT_DATA

    leader = args.leader.strip().upper()
    labels = {c.ticker: (c.company, c.industry) for c in constituents}
    closes = download_bulk([c.ticker for c in constituents] + [leader], period=args.period,
                           use_cache=not args.refresh)
    if leader not in closes.columns:
        print(f"error: no price data for leader {leader}", file=sys.stderr)
        return EXIT_DATA

    rows = scan_universe(leader, closes, labels, extra_lag=args.extra_lag)
    top = rows[: args.top]
    holdout: dict[str, object] = {}
    if args.validate:
        leader_r = log_returns(closes[leader])
        for row in top:
            holdout[row.ticker] = holdout_hit_rate(leader_r, log_returns(closes[row.ticker]),
                                                   extra_lag=args.extra_lag)

    table = []
    for row in top:
        cells = [row.ticker, row.company[:32], row.industry[:20], str(row.n_obs),
                 _fmt(row.corr), _fmt(row.t_stat, 2), _fmt(row.beta)]
        if args.validate:
            h = holdout[row.ticker]
            cells += [("-" if h.hit_rate is None else f"{h.hit_rate * 100:.0f}%"), str(h.n_test)]
        table.append(cells)
    headers = ["TICKER", "COMPANY", "INDUSTRY", "N", "CORR", "T", "BETA"]
    if args.validate:
        headers += ["HOLDOUT HIT", "N-TEST"]
    _print_table(headers, table)

    if args.validate:
        leader_r = log_returns(closes[leader])
        hits = [
            holdout_hit_rate(leader_r, log_returns(closes[r.ticker]), extra_lag=args.extra_lag).hit_rate
            for r in rows
        ]
        known = [h for h in hits if h is not None]
        if known:
            print(f"base rate: median out-of-sample hit across all {len(known)} stocks = "
                  f"{float(np.median(known)) * 100:.0f}% (50% is chance)")
    skipped = len(constituents) - len(rows)
    print(f"\nscanned {len(rows)} stocks vs {leader} ({skipped} skipped: missing or too little data)")
    print("|t| above ~2 is a usual threshold; expect some false positives across hundreds of stocks.")

    report_dir = Path(__file__).resolve().parent.parent / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    safe = leader.replace("^", "")
    path = report_dir / f"{args.index}_{safe}_{date.today().isoformat()}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("ticker,company,industry,n_obs,corr,t_stat,beta\n")
        for row in rows:
            fh.write(f'{row.ticker},"{row.company}","{row.industry}",{row.n_obs},'
                     f"{row.corr:.6f},{row.t_stat:.4f},{row.beta:.6f}\n")
    print(f"full ranking saved to {path}")
    _disclaimer()
    return EXIT_OK


def cmd_peers(args: argparse.Namespace) -> int:
    from indiabloom.market import download_bulk
    from indiabloom.peers import PEERS_FILE, save_peers, statistical_peers
    from indiabloom.universe import UniverseError, load_index

    try:
        constituents = load_index(args.index)
    except UniverseError as exc:
        print(f"universe error: {exc}", file=sys.stderr)
        return EXIT_DATA
    industries = {c.ticker: c.industry for c in constituents}
    closes = download_bulk(list(industries), period="2y", use_cache=not args.refresh)
    peers = statistical_peers(closes, industries, k=args.top)
    save_peers(PEERS_FILE, peers)
    ranked = len({p.ticker for p in peers})
    print(f"saved {len(peers)} statistical peers for {ranked} stocks to {PEERS_FILE}")
    print("Peers are same-industry stocks whose prices move together. They are not competitors.")
    print("Recorded competitors come from data/relations.json.")
    _disclaimer()
    return EXIT_OK


def cmd_fundamentals(args: argparse.Namespace) -> int:
    from indiabloom.fundamentals import FUNDAMENTALS_DIR, run_fundamentals
    from indiabloom.universe import UniverseError, load_index

    try:
        constituents = load_index(args.index)
    except UniverseError as exc:
        print(f"universe error: {exc}", file=sys.stderr)
        return EXIT_DATA
    tickers = [c.ticker for c in constituents]

    def progress(done: int, total: int, ticker: str) -> None:
        print(f"[{done}/{total}] {ticker}", flush=True)

    report = run_fundamentals(tickers, FUNDAMENTALS_DIR, sleep_s=args.sleep, progress=progress,
                              refresh=args.refresh)
    print(f"fetched {report.fetched}, already fresh {report.skipped_fresh}, "
          f"failed {len(report.failed)} of {len(tickers)} in {args.index}")
    for failure in report.failed:
        print(f"  failed {failure.ticker}: {failure.reason}", file=sys.stderr)
    print(f"cache: {FUNDAMENTALS_DIR}  (rerun to retry failures; cached stocks are skipped)")
    print("Source: yfinance (unofficial). Ratios are as reported by Yahoo Finance.")
    _disclaimer()
    return EXIT_OK if not report.failed else EXIT_DATA


def cmd_deals(args: argparse.Namespace) -> int:
    from indiabloom.deals import DEALS_FILE, DealsError, load_history, update_deals

    try:
        fetched, added = update_deals()
    except DealsError as exc:
        print(f"deals error: {exc}", file=sys.stderr)
        return EXIT_DATA
    total = len(load_history())
    print(f"NSE bulk and block deals: {fetched} rows in today's files, {added} new, {total} in history")
    print(f"history: {DEALS_FILE}")
    print("These are large trades only (bulk: over 0.5% of a company's shares; block: negotiated).")
    _disclaimer()
    return EXIT_OK


def cmd_ui(args: argparse.Namespace, graph: Graph) -> int:
    from indiabloom.tui import IndiaBloomApp

    names = load_companies(args.companies)
    IndiaBloomApp(graph, names, Services()).run()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="indiabloom", description="Global <-> India stock relationships")
    parser.add_argument("--relations", type=Path, default=DEFAULT_RELATIONS,
                        help="path to relations.json")
    parser.add_argument("--companies", type=Path, default=DEFAULT_COMPANIES,
                        help="path to companies.json (company names for news)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rel = sub.add_parser("relations", help="list every link for a ticker")
    p_rel.add_argument("ticker")

    p_cor = sub.add_parser("correlate", help="correlation between one US and one Indian ticker")
    p_cor.add_argument("global_ticker")
    p_cor.add_argument("indian_ticker")
    p_cor.add_argument("--period", default="1y")
    p_cor.add_argument("--extra-lag", type=int, default=0,
                       help="extra US sessions back (0 = newest completed session)")

    p_scan = sub.add_parser("scan", help="rank Indian counterparts for a US ticker")
    p_scan.add_argument("ticker")
    p_scan.add_argument("--period", default="1y")
    p_scan.add_argument("--extra-lag", type=int, default=0,
                        help="extra US sessions back (0 = newest completed session)")
    p_scan.add_argument("--top", type=int, default=10)
    p_scan.add_argument("--offline-demo", action="store_true", help="synthetic prices; no network")

    p_news = sub.add_parser("news", help="recent headlines for a company")
    p_news.add_argument("ticker")
    p_news.add_argument("--limit", type=int, default=15)

    p_watch = sub.add_parser("watch", help="headlines about US companies in the graph")
    p_watch.add_argument("--limit", type=int, default=10,
                         help="headlines to read per company")

    sub.add_parser("ui", help="open the interactive terminal UI")

    p_uni = sub.add_parser("universe", help="list constituents of a Nifty index")
    p_uni.add_argument("--index", default="nifty50",
                       choices=["nifty50", "nifty100", "nifty200", "nifty500"])

    p_us = sub.add_parser("universe-scan",
                          help="rank index stocks by lead-lag correlation with a leader")
    p_us.add_argument("--index", default="nifty500",
                      choices=["nifty50", "nifty100", "nifty200", "nifty500"])
    p_us.add_argument("--leader", default="^GSPC",
                      help="leader ticker, e.g. ^GSPC (S&P 500), ^IXIC (Nasdaq), MU")
    p_us.add_argument("--period", default="2y")
    p_us.add_argument("--extra-lag", type=int, default=0)
    p_us.add_argument("--top", type=int, default=30)
    p_us.add_argument("--validate", action="store_true",
                      help="add out-of-sample hit rate for the top rows")
    p_us.add_argument("--refresh", action="store_true", help="ignore the price cache")
    add_signal_parsers(sub)

    p_peers = sub.add_parser("peers", help="compute same-industry statistical peers for an index")
    p_peers.add_argument("--index", default="nifty500",
                         choices=["nifty50", "nifty100", "nifty200", "nifty500"])
    p_peers.add_argument("--top", type=int, default=5, help="peers per stock")
    p_peers.add_argument("--refresh", action="store_true", help="ignore the price cache")
    p_fund = sub.add_parser("fundamentals", help="fetch valuation and financial snapshots for an index")
    p_fund.add_argument("--index", default="nifty500",
                        choices=["nifty50", "nifty100", "nifty200", "nifty500"])
    p_fund.add_argument("--sleep", type=float, default=0.5, help="seconds between requests")
    p_fund.add_argument("--refresh", action="store_true", help="refetch even if the cache is fresh")
    sub.add_parser("deals", help="fetch today's NSE bulk and block deals into the history")
    p_wl = sub.add_parser("watchlist", help="manage your watchlist and show P&L for positions with a cost")
    p_wl.add_argument("action", choices=["add", "remove", "show"])
    p_wl.add_argument("ticker", nargs="?", help="e.g. INFY.NS (Indian stocks need the .NS suffix)")
    p_wl.add_argument("--buy", type=float, default=None, help="buy price per share")
    p_wl.add_argument("--qty", type=float, default=None, help="number of shares")
    p_scr = sub.add_parser("screen", help="filter an index on cached fundamentals, e.g. --where 'roe>15'")
    p_scr.add_argument("--index", default="nifty500",
                       choices=["nifty50", "nifty100", "nifty200", "nifty500"])
    p_scr.add_argument("--where", action="append", default=[],
                       help="condition such as pe_trailing<20, roe>=15, sector=bank (repeatable)")
    p_scr.add_argument("--sort", default="market_cap_cr", help="field to sort by")
    p_scr.add_argument("--asc", action="store_true", help="sort ascending instead of descending")
    p_scr.add_argument("--top", type=int, default=None, help="show at most this many stocks")
    p_al = sub.add_parser("alerts", help="price, move, deal and headline alerts for stocks")
    al_sub = p_al.add_subparsers(dest="alerts_action", required=True)
    p_add = al_sub.add_parser("add", help="add a rule for a stock")
    p_add.add_argument("ticker", help="e.g. INFY.NS")
    p_add.add_argument("--above", type=float, help="alert when the price is at or above this")
    p_add.add_argument("--below", type=float, help="alert when the price is at or below this")
    p_add.add_argument("--move-up", type=float, help="alert when the day change is at or above this percent")
    p_add.add_argument("--move-down", type=float, help="alert when the day change is at or below this percent (negative)")
    p_add.add_argument("--deals", action="store_true", help="alert on new NSE bulk or block deals")
    p_add.add_argument("--news", action="store_true", help="alert on new headlines")
    al_sub.add_parser("list", help="list rules")
    p_rm = al_sub.add_parser("remove", help="remove a rule by id")
    p_rm.add_argument("id", type=int)
    p_check = al_sub.add_parser("check", help="check all rules once and log what fired")
    p_check.add_argument("--refresh", action="store_true", help="also fetch today's NSE deals first")
    p_watch = al_sub.add_parser("watch", help="check repeatedly while this terminal stays open")
    p_watch.add_argument("--every", type=float, default=15, help="minutes between checks")
    p_watch.add_argument("--refresh", action="store_true", help="also fetch today's NSE deals each time")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "extra_lag", 0) < 0:
        parser.error("--extra-lag must be >= 0")

    try:
        if args.command == "correlate":
            return cmd_correlate(args)
        if args.command == "news":
            return cmd_news(args)
        if args.command == "universe":
            return cmd_universe(args)
        if args.command == "universe-scan":
            return cmd_universe_scan(args)
        if args.command == "log-signals":
            return cmd_log_signals(args)
        if args.command == "score-signals":
            return cmd_score_signals(args)
        if args.command == "peers":
            return cmd_peers(args)
        if args.command == "fundamentals":
            return cmd_fundamentals(args)
        if args.command == "deals":
            return cmd_deals(args)
        if args.command == "watchlist":
            return cmd_watchlist(args)
        if args.command == "screen":
            return cmd_screen(args)
        if args.command == "alerts":
            return cmd_alerts(args)
        graph = Graph(load_relations(args.relations))
        if args.command == "relations":
            return cmd_relations(args, graph)
        if args.command == "scan":
            return cmd_scan(args, graph)
        if args.command == "watch":
            return cmd_watch(args, graph)
        return cmd_ui(args, graph)
    except RelationValidationError as exc:
        print(f"relations file invalid: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except CompanyFileError as exc:
        print(f"companies file invalid: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except MarketDataError as exc:
        print(f"data error: {exc}", file=sys.stderr)
        return EXIT_DATA
    except NewsError as exc:
        print(f"news error: {exc}", file=sys.stderr)
        return EXIT_DATA
    except FileNotFoundError as exc:
        print(f"file not found: {exc}", file=sys.stderr)
        return EXIT_USAGE


def cmd_watchlist(args: argparse.Namespace) -> int:
    from indiabloom.market import MarketDataError, download_bulk
    from indiabloom.watchlist import (
        add_position,
        find_position,
        load_watchlist,
        remove_position,
        save_watchlist,
    )

    positions = load_watchlist()
    if args.action == "add":
        if not args.ticker:
            print("usage: watchlist add TICKER [--buy PRICE] [--qty N]", file=sys.stderr)
            return EXIT_USAGE
        ticker = args.ticker.upper()
        positions = add_position(positions, ticker, args.buy, args.qty)
        save_watchlist(positions)
        print(f"saved {ticker} (buy {args.buy if args.buy is not None else '-'}, "
              f"qty {args.qty if args.qty is not None else '-'}) in the watchlist")
        return EXIT_OK
    if args.action == "remove":
        if not args.ticker:
            print("usage: watchlist remove TICKER", file=sys.stderr)
            return EXIT_USAGE
        ticker = args.ticker.upper()
        if find_position(positions, ticker) is None:
            print(f"{ticker} is not in the watchlist")
            return EXIT_USAGE
        save_watchlist(remove_position(positions, ticker))
        print(f"removed {ticker}")
        return EXIT_OK

    # show: last price from the cached price download, then P&L where cost is known
    if not positions:
        print("watchlist is empty. Add a stock: python -m indiabloom watchlist add INFY.NS --buy 1500 --qty 10")
        return EXIT_OK
    try:
        closes = download_bulk([p.ticker for p in positions], period="5d")
    except MarketDataError as exc:
        print(f"data error: {exc}", file=sys.stderr)
        return EXIT_DATA
    rows = []
    total_cost = 0.0
    total_value = 0.0
    for p in positions:
        series = closes[p.ticker].dropna() if p.ticker in closes.columns else []
        last = float(series.iloc[-1]) if len(series) else None
        cost = p.buy_price * p.quantity if p.buy_price is not None and p.quantity is not None else None
        value = last * p.quantity if last is not None and p.quantity is not None else None
        if cost is not None and value is not None:
            total_cost += cost
            total_value += value
        pnl = value - cost if cost is not None and value is not None else None
        rows.append([
            p.ticker,
            "-" if p.buy_price is None else f"{p.buy_price:,.2f}",
            "-" if p.quantity is None else f"{p.quantity:,g}",
            "-" if last is None else f"{last:,.2f}",
            "-" if pnl is None else f"{pnl:+,.2f}",
            "-" if pnl is None or not cost else f"{pnl / cost * 100:+.2f}%",
        ])
    _print_table(["TICKER", "BUY", "QTY", "LAST", "P&L", "P&L %"], rows)
    if total_cost:
        print(f"\nholdings with a cost basis: cost {total_cost:,.2f}, value {total_value:,.2f}, "
              f"P&L {total_value - total_cost:+,.2f} ({(total_value - total_cost) / total_cost * 100:+.2f}%)")
    _disclaimer()
    return EXIT_OK


def cmd_screen(args: argparse.Namespace) -> int:
    from indiabloom.fundamentals import load_snapshot
    from indiabloom.screener import ScreenError, metric, parse_condition, screen
    from indiabloom.universe import UniverseError, load_index

    try:
        conditions = [parse_condition(text) for text in args.where]
        constituents = load_index(args.index)
    except (ScreenError, UniverseError) as exc:
        print(f"screen error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    snapshots = []
    missing = 0
    for c in constituents:
        snap = load_snapshot(c.ticker)
        if snap is None:
            missing += 1
            continue
        snapshots.append(snap)
    try:
        hits = screen(snapshots, conditions, sort_by=args.sort, descending=not args.asc, top=args.top)
    except ScreenError as exc:
        print(f"screen error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    def fmt(value: object, digits: int = 1) -> str:
        return "-" if value is None or isinstance(value, str) else f"{value:,.{digits}f}"

    rows = []
    for s in hits:
        rows.append([
            s["ticker"],
            (s.get("name") or "")[:28],
            (s.get("sector") or "-")[:16],
            fmt(metric(s, "market_cap_cr"), 0),
            fmt(s.get("pe_trailing")),
            fmt(metric(s, "roe")),
            fmt(s.get("pb")),
        ])
    print(f"{len(hits)} of {len(snapshots)} cached stocks match "
          f"({' and '.join(args.where) or 'no filters'}), sorted by {args.sort}")
    if rows:
        _print_table(["TICKER", "NAME", "SECTOR", "MCAP CR", "PE", "ROE %", "PB"], rows)
    if missing:
        print(f"{missing} stocks have no fundamentals cache yet; run: python -m indiabloom fundamentals --index {args.index}")
    _disclaimer()
    return EXIT_OK


def _alert_news_query(ticker: str) -> str:
    from indiabloom.companies import DEFAULT_COMPANIES, load_companies

    names = load_companies(DEFAULT_COMPANIES)
    code = ticker.removesuffix(".NS")
    return f"{names[ticker][0] if ticker in names else code} stock"


def _run_alert_check(refresh: bool) -> list:
    """Fetch prices, deals and headlines for every rule, evaluate, save state and log. Returns alerts."""
    from datetime import date, datetime

    from indiabloom.alerts import ALERTS_FILE, append_log, evaluate, load_rules, save_rules
    from indiabloom.deals import DealsError, load_history, update_deals
    from indiabloom.market import MarketDataError, download_bulk
    from indiabloom.news import NewsError, fetch_news

    rules, next_id = load_rules()
    if not rules:
        print("no alert rules yet. Add one: python -m indiabloom alerts add INFY.NS --above 1700")
        return []
    if refresh:
        try:
            update_deals()
        except DealsError as exc:
            print(f"deals refresh skipped: {exc}", file=sys.stderr)
    tickers = sorted({r.ticker for r in rules})
    quotes: dict = {}
    try:
        closes = download_bulk(tickers, period="5d")
    except MarketDataError as exc:
        print(f"price data unavailable, price alerts skipped: {exc}", file=sys.stderr)
        closes = None
    if closes is not None:
        for t in tickers:
            if t not in closes.columns:
                continue
            series = closes[t].dropna()
            if len(series) == 0:
                continue
            last = float(series.iloc[-1])
            change = (last / float(series.iloc[-2]) - 1) * 100 if len(series) >= 2 else None
            quotes[t] = (last, change)
    headlines: dict = {}
    for r in rules:
        if r.kind == "news" and r.ticker not in headlines:
            try:
                headlines[r.ticker] = [item.title for item in fetch_news(_alert_news_query(r.ticker))]
            except NewsError as exc:
                print(f"news unavailable for {r.ticker}: {exc}", file=sys.stderr)
    alerts, rules = evaluate(rules, quotes, load_history(), headlines, date.today())
    save_rules(rules, next_id)
    append_log(alerts, datetime.now())
    return alerts


def cmd_alerts(args: argparse.Namespace) -> int:
    from indiabloom.alerts import AlertError, Rule, deal_key, describe, load_rules, save_rules, validate
    from indiabloom.deals import load_history
    from indiabloom.news import NewsError, fetch_news

    if args.alerts_action == "check":
        alerts = _run_alert_check(args.refresh)
        for a in alerts:
            print(f"ALERT  {a.message}")
        if not alerts:
            print("no alerts fired")
        return EXIT_OK

    if args.alerts_action == "watch":
        import time
        from datetime import datetime

        print(f"checking every {args.every} minutes; Ctrl+C to stop. Log: data/alerts/log.csv")
        try:
            while True:
                for a in _run_alert_check(args.refresh):
                    print(f"{datetime.now():%H:%M} ALERT  {a.message}", flush=True)
                time.sleep(args.every * 60)
        except KeyboardInterrupt:
            print("stopped")
        return EXIT_OK

    rules, next_id = load_rules()
    if args.alerts_action == "list":
        if not rules:
            print("no alert rules")
            return EXIT_OK
        _print_table(["ID", "TICKER", "RULE", "LAST PRICE ALERT"],
                     [[str(r.id), r.ticker, describe(r), r.last_fired or "-"]
                      for r in sorted(rules, key=lambda r: r.id)])
        return EXIT_OK

    if args.alerts_action == "remove":
        remaining = [r for r in rules if r.id != args.id]
        if len(remaining) == len(rules):
            print(f"no rule with id {args.id}", file=sys.stderr)
            return EXIT_USAGE
        save_rules(remaining, next_id)
        print(f"removed rule {args.id}")
        return EXIT_OK

    # add: exactly one rule type
    choices = [
        ("price_above", args.above), ("price_below", args.below),
        ("move_above", args.move_up), ("move_below", args.move_down),
        ("deal", True if args.deals else None), ("news", True if args.news else None),
    ]
    chosen = [(kind, value) for kind, value in choices if value is not None]
    if len(chosen) != 1:
        print("choose exactly one rule: --above, --below, --move-up, --move-down, --deals or --news",
              file=sys.stderr)
        return EXIT_USAGE
    kind, value = chosen[0]
    ticker = args.ticker.upper()
    threshold = None if kind in ("deal", "news") else float(value)
    try:
        validate(kind, threshold)
    except AlertError as exc:
        print(f"alert error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    # Existing deals and headlines are marked seen, so only new ones alert later.
    seen: list[str] = []
    if kind == "deal":
        code = ticker.removesuffix(".NS")
        seen = [deal_key(d) for d in load_history() if d.symbol == code]
    elif kind == "news":
        try:
            seen = [item.title for item in fetch_news(_alert_news_query(ticker))]
        except NewsError as exc:
            print(f"could not read current headlines ({exc}); the first check may alert on old news",
                  file=sys.stderr)
    rule = Rule(id=next_id, ticker=ticker, kind=kind, threshold=threshold, seen=seen[-200:])
    save_rules([*rules, rule], next_id + 1)
    print(f"added rule {rule.id}: {ticker} {describe(rule)}")
    return EXIT_OK
