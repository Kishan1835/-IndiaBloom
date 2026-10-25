"""Index constituent lists (Nifty 50 / 100 / 200 / 500) from NSE archives.

Each file is a CSV with at least: Company Name, Industry, Symbol, Series, ISIN Code.
Symbols are NSE codes; the yfinance ticker is the symbol plus ".NS".
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

UNIVERSE_DIR = Path(__file__).resolve().parent.parent / "data" / "universe"
NSE_URL = "https://archives.nseindia.com/content/indices/ind_{name}list.csv"
INDEXES = ("nifty50", "nifty100", "nifty200", "nifty500")
REQUIRED_HEADERS = ("Company Name", "Industry", "Symbol")
MAX_AGE = timedelta(days=7)  # constituents change rarely; refresh weekly
USER_AGENT = "Mozilla/5.0 (IndiaBloom research tool)"


class UniverseError(RuntimeError):
    """Raised when an index list cannot be fetched or does not match the expected format."""


@dataclass(frozen=True)
class Constituent:
    symbol: str  # NSE code, e.g. INFY
    ticker: str  # yfinance ticker, e.g. INFY.NS
    company: str
    industry: str


def parse_constituents(text: str) -> list[Constituent]:
    """Parse an NSE index CSV. Raises UniverseError on a wrong header or empty list."""
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    missing = [h for h in REQUIRED_HEADERS if h not in fields]
    if missing:
        raise UniverseError(f"index file is missing columns: {', '.join(missing)}")

    out: list[Constituent] = []
    seen: set[str] = set()
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(Constituent(
            symbol=symbol,
            ticker=f"{symbol}.NS",
            company=(row.get("Company Name") or "").strip(),
            industry=(row.get("Industry") or "").strip(),
        ))
    if not out:
        raise UniverseError("index file contained no constituents")
    return out


def _cache_file(name: str, cache_dir: Path) -> Path:
    return cache_dir / f"{name}.csv"


def load_index(name: str, cache_dir: Path = UNIVERSE_DIR, now: datetime | None = None,
               timeout: float = 20.0) -> list[Constituent]:
    """Constituents for an index, from a fresh cache or the NSE archive."""
    if name not in INDEXES:
        raise UniverseError(f"unknown index '{name}'; choose one of {', '.join(INDEXES)}")
    current = now or datetime.now()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_file(name, cache_dir)

    if path.exists() and current - datetime.fromtimestamp(path.stat().st_mtime) <= MAX_AGE:
        return parse_constituents(path.read_text(encoding="utf-8-sig"))

    request = urllib.request.Request(NSE_URL.format(name=name), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8-sig")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if path.exists():  # stale cache beats no data; the caller can see the age in the file
            return parse_constituents(path.read_text(encoding="utf-8-sig"))
        raise UniverseError(f"could not fetch {name} constituents: {exc}") from exc

    constituents = parse_constituents(text)  # validate before caching
    path.write_text(text, encoding="utf-8")
    return constituents
