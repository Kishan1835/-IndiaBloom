"""Text price charts for the terminal: 1M, 6M and 1Y windows from daily closes.

Ranges are counted in trading days (about 21 per month, 126 per six months,
252 per year), so holidays and weekends are skipped automatically.
"""

from __future__ import annotations

RANGES = (("1M", 21), ("6M", 126), ("1Y", 252))
LABEL_WIDTH = 12


def render_chart(values: list[float], width: int = 60, height: int = 8) -> list[str]:
    """Line chart as text rows: one '*' per column at the close's height, high at top.

    The series is sampled evenly to `width` columns. Each line starts with the
    high and low price labels on the first and last rows.
    """
    if len(values) < 2 or width < 2 or height < 2:
        return []
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    last = len(values) - 1
    grid = [[" "] * width for _ in range(height)]
    for col in range(width):
        value = values[round(col * last / (width - 1))]
        row = round((value - lo) / span * (height - 1))
        grid[height - 1 - row][col] = "*"
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
    shows the start date values.
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
