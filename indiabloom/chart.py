"""Text price charts for the terminal.

Single stock: 1M, 6M and 1Y windows from daily closes.
Compare: several stocks on one chart, each rebased to 100 at the first date
they all share, so a stock priced at Rs 50 and one at Rs 5000 can be compared.

Ranges are counted in trading days (about 21 per month, 126 per six months,
252 per year), so holidays and weekends are skipped automatically.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN, MARKET_CLOSE = time(9, 15), time(15, 30)

RANGES = (("1M", 21), ("6M", 126), ("1Y", 252))
LABEL_WIDTH = 12
SYMBOLS = "*+o#%@"  # one plotting character per compared stock, in order


def _plot(series: list[tuple[str, list[float]]], width: int, height: int) -> list[str]:
    """Draw one or more series on a shared grid. Later series overwrite earlier points."""
    all_values = [v for _, values in series for v in values]
    lo, hi = min(all_values), max(all_values)
    span = (hi - lo) or 1.0
    grid = [[" "] * width for _ in range(height)]
    for index, (_, values) in enumerate(series):
        symbol = SYMBOLS[index % len(SYMBOLS)]
        last = len(values) - 1
        for col in range(width):
            value = values[round(col * last / (width - 1))]
            row = round((value - lo) / span * (height - 1))
            grid[height - 1 - row][col] = symbol
    lines = []
    for r, cells in enumerate(grid):
        if r == 0:
            label = f"{hi:,.1f}"
        elif r == height - 1:
            label = f"{lo:,.1f}"
        else:
            label = ""
        lines.append(f"{label:>{LABEL_WIDTH - 2}} |" + "".join(cells))
    return lines


def render_chart(values: list[float], width: int = 60, height: int = 8) -> list[str]:
    """Line chart as text rows: one '*' per column at the close's height, high at top."""
    if len(values) < 2 or width < 2 or height < 2:
        return []
    return _plot([("", values)], width, height)


def range_summary(values: list[float]) -> str:
    """Start, end, percent change, high and low for one window."""
    start, end = values[0], values[-1]
    change = (end / start - 1) * 100 if start else 0.0
    return (f"start {start:,.2f}  end {end:,.2f}  change {change:+.2f}%  "
            f"high {max(values):,.2f}  low {min(values):,.2f}")


def chart_lines(closes: list[float], width: int = 60, height: int = 8) -> list[str]:
    """All three ranges, each with a header line, its chart and a blank separator.

    closes must be oldest first. A window with fewer than two closes says so
    instead of drawing. A window longer than the history uses all of it, so a
    6M or 1Y header can cover less than the period its label names; the header
    shows the start value.
    """
    out: list[str] = []
    for label, days in RANGES:
        window = closes[-(days + 1):]  # days returns need days + 1 closes
        if len(window) < 2:
            out.append(f"{label}: not enough price history")
        else:
            out.append(f"{label}  {range_summary(window)}")
            out.extend(render_chart(window, width, height))
        out.append("")
    return out[:-1]  # drop the trailing blank line


def rebase_common(closes: pd.DataFrame, tickers: list[str]) -> tuple[dict[str, list[float]], list[str]]:
    """Closes for the tickers rebased to 100 on the first date all of them traded.

    Returns (series by ticker, tickers missing from the download). Rows where any
    chosen ticker has no close are dropped, so every series has the same dates.
    """
    present = [t for t in tickers if t in closes.columns]
    missing = [t for t in tickers if t not in closes.columns]
    if len(present) < 2:
        return {}, missing
    frame = closes[present].dropna()
    if len(frame) < 2:
        return {}, missing
    rebased = frame / frame.iloc[0] * 100
    return {t: [float(v) for v in rebased[t]] for t in present}, missing


def compare_lines(closes: pd.DataFrame, tickers: list[str], width: int = 60, height: int = 12) -> list[str]:
    """Rebased comparison chart with a legend: one line per stock showing its end value."""
    series, missing = rebase_common(closes, tickers)
    out: list[str] = []
    if missing:
        out.append(f"No price data for: {', '.join(missing)}")
    if not series:
        out.append("Need at least two stocks with price data over the same dates.")
        return out
    names = list(series)
    out.extend(_plot([(n, series[n]) for n in names], width, height))
    out.append("")
    out.append("All start at 100 on the first common date.")
    for index, name in enumerate(names):
        end = series[name][-1]
        out.append(f"  {SYMBOLS[index % len(SYMBOLS)]} {name:<16} end {end:7.1f}  ({end - 100:+.1f}%)")
    return out


def is_market_open(now: datetime) -> bool:
    """True on weekdays between the Indian open and close (IST). Holidays are not known here."""
    local = now.astimezone(IST)
    return local.weekday() < 5 and MARKET_OPEN <= local.time() <= MARKET_CLOSE


def live_lines(bars: list[tuple[str, float]], previous_close: float | None,
               width: int = 60, height: int = 12) -> list[str]:
    """Today's 5-minute bars as a chart, with a header of last price and change on the day.

    bars are (time label, close), oldest first. Fewer than two bars means the
    session has not produced a chart yet.
    """
    if len(bars) < 2:
        return ["No intraday bars yet. The chart fills in after the 09:15 IST open."]
    times = [t for t, _ in bars]
    values = [v for _, v in bars]
    last = values[-1]
    change = ""
    if previous_close:
        change = f"  |  change {(last / previous_close - 1) * 100:+.2f}% vs previous close {previous_close:,.2f}"
    header = (f"Last {last:,.2f} at {times[-1]} IST  |  high {max(values):,.2f}  low {min(values):,.2f}"
              f"{change}")
    axis = " " * LABEL_WIDTH + times[0] + " " * max(1, width - len(times[0]) - len(times[-1])) + times[-1]
    return [header, ""] + render_chart(values, width, height) + [axis]
