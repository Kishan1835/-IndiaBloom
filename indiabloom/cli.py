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
