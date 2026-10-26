"""`log-signals` and `score-signals` commands: the forward accuracy record."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

from indiabloom.analytics import log_returns
from indiabloom.ledger import (
    append_entries,
    already_logged,
    build_entries,
    read_ledger,
    score_entries,
    summarize,
    wilson_interval,
)

LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "ledger" / "signals.csv"
NSE_CALENDAR = "^NSEI"  # Nifty 50 index: its dates are the Indian trading calendar
EXIT_OK, EXIT_DATA = 0, 3


IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving time
INDIAN_OPEN = time(9, 15)
SCORE_AFTER = time(15, 45)  # a bit after the 15:30 close, so the last bar is final


def drop_open_session(closes: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Remove today's bar until the Indian session has closed.

    During the session yfinance returns a partial bar for today. Scoring it would
    grade a prediction on an incomplete move, so today's bar is dropped until
    SCORE_AFTER IST.
    """
    if now.time() >= SCORE_AFTER:
        return closes
    return closes[closes.index.date < now.date()]


def logging_window_open(target: date, now: datetime) -> bool:
    """True only before the Indian session on `target` opens.

    A prediction logged after the target session has opened is not a forward
    prediction, so it must not enter the ledger. `now` must be timezone-aware
    (IST) so the comparison is correct on any PC clock.
    """
    local = now.astimezone(IST)
    if local.date() < target:
        return True
    return local.date() == target and local.time() < INDIAN_OPEN


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def cmd_log_signals(args: argparse.Namespace) -> int:
    from indiabloom.market import download_bulk
    from indiabloom.universe import UniverseError, load_index
    from indiabloom.universe_scan import scan_universe

    try:
        constituents = load_index(args.index)
    except UniverseError as exc:
        print(f"universe error: {exc}", file=sys.stderr)
        return EXIT_DATA

    leader = args.leader.strip().upper()
    tickers = [c.ticker for c in constituents]
    closes = download_bulk(tickers + [leader, NSE_CALENDAR], period="2y", use_cache=not args.refresh)
    if leader not in closes.columns:
        print(f"error: no price data for leader {leader}", file=sys.stderr)
        return EXIT_DATA

    leader_r = log_returns(closes[leader])
    if leader_r.empty:
        print(f"error: no usable returns for {leader}", file=sys.stderr)
        return EXIT_DATA
    leader_session = leader_r.index[-1].date()
    leader_return = float(leader_r.iloc[-1])

    if already_logged(args.ledger, leader, leader_session):
        print(f"already logged: {leader} session {leader_session}. Nothing to do.")
        return EXIT_OK

    # The Indian session that reacts is the first one after the leader session.
    # Use the next weekday as the target; scoring moves it to the real session.
    target_session = (pd.Timestamp(leader_session) + pd.offsets.BDay(1)).date()

    if not logging_window_open(target_session, datetime.now(IST)):
        print(f"not logged: the Indian session for {target_session} has already opened. "
              "A late prediction is not a forward prediction, so it is skipped.")
        return EXIT_OK

    scan_closes = closes.drop(columns=[NSE_CALENDAR])
    labels = {c.ticker: (c.company, c.industry) for c in constituents}
    rows = scan_universe(leader, scan_closes, labels)
    today = date.today()
    entries = build_entries(rows, leader, leader_session, target_session,
                            leader_return, today, top_n=args.top)
    if not entries:
        print("no usable predictions today (all betas or returns are zero)")
        return EXIT_OK

    append_entries(args.ledger, entries)
    top = [e for e in entries if e.in_top]
    print(f"logged {len(entries)} predictions ({len(top)} top picks) for {target_session}")
    print(f"leader {leader} session {leader_session}: {leader_return * 100:+.2f}%")
    print(f"ledger: {args.ledger}")
    print("Scored later with `score-signals` once the target session has traded.")
    return EXIT_OK


def cmd_score_signals(args: argparse.Namespace) -> int:
    from indiabloom.market import download_bulk

    entries = read_ledger(args.ledger)
    if not entries:
        print(f"ledger is empty: {args.ledger}. Run `log-signals` first.")
        return EXIT_OK

    tickers = sorted({e.ticker for e in entries})
    closes = download_bulk(tickers, period="2y", use_cache=False)  # scoring always needs fresh prices
    closes = drop_open_session(closes, datetime.now(IST))
    scored = score_entries(entries, closes)
    summary = summarize(scored)

    print(f"ledger entries: {len(entries)}   sessions scored: {summary.sessions_scored}   "
          f"pending: {summary.pending}")
    if summary.universe_predictions == 0:
        print("nothing scored yet. Target sessions have not traded. Check back after the next session.")
        return EXIT_OK

    top_ci = wilson_interval(summary.top_hits, summary.top_picks)
    uni_ci = wilson_interval(summary.universe_hits, summary.universe_predictions)
    print(f"\ntop picks    : {summary.top_hits}/{summary.top_picks} = {_pct(summary.top_hit_rate)}"
          + (f"   95% CI {_pct(top_ci[0])}-{_pct(top_ci[1])}" if top_ci else ""))
    print(f"whole universe: {summary.universe_hits}/{summary.universe_predictions} = "
          f"{_pct(summary.universe_hit_rate)}"
          + (f"   95% CI {_pct(uni_ci[0])}-{_pct(uni_ci[1])}" if uni_ci else ""))
    if summary.top_hit_rate is not None and summary.universe_hit_rate is not None:
        edge = (summary.top_hit_rate - summary.universe_hit_rate) * 100
        print(f"edge of top picks over universe: {edge:+.1f} points")
    print("\nThe top-pick sample is a few sessions. Days share one market move, so these "
          "hits are not independent. Treat the interval as optimistic.")

    # Per-session breakdown for the most recent resolved sessions.
    by_session: dict[tuple[str, str], list] = {}
    for s in scored:
        if s.hit is None:
            continue
        by_session.setdefault((s.entry.leader, s.entry.target_session.isoformat()), []).append(s)
    rows = []
    for (leader, target), items in sorted(by_session.items(), key=lambda kv: kv[0][1])[-args.recent:]:
        top = [s for s in items if s.entry.in_top]
        uni_hits = sum(1 for s in items if s.hit)
        rows.append([
            target, leader,
            f"{sum(1 for s in top if s.hit)}/{len(top)}",
            f"{uni_hits}/{len(items)}",
            _pct(uni_hits / len(items)),
        ])
    if rows:
        widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in
                  enumerate(["TARGET", "LEADER", "TOP HITS", "ALL HITS", "ALL RATE"])]
        headers = ["TARGET", "LEADER", "TOP HITS", "ALL HITS", "ALL RATE"]
        print("\n" + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
        for r in rows:
            print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    return EXIT_OK


def add_signal_parsers(sub: argparse._SubParsersAction) -> None:
    p_log = sub.add_parser("log-signals", help="log today's predictions to the forward ledger")
    p_log.add_argument("--index", default="nifty500",
                       choices=["nifty50", "nifty100", "nifty200", "nifty500"])
    p_log.add_argument("--leader", default="^GSPC")
    p_log.add_argument("--top", type=int, default=20, help="how many picks count as 'top'")
    p_log.add_argument("--refresh", action="store_true", help="ignore the price cache")
    p_log.add_argument("--ledger", type=Path, default=LEDGER_PATH)

    p_score = sub.add_parser("score-signals", help="score logged predictions against actual moves")
    p_score.add_argument("--recent", type=int, default=10, help="sessions to show")
    p_score.add_argument("--ledger", type=Path, default=LEDGER_PATH)
