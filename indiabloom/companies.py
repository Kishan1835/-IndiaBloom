"""Company names used to match news headlines to tickers."""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_COMPANIES = Path(__file__).resolve().parent.parent / "data" / "companies.json"


class CompanyFileError(ValueError):
    """Raised when data/companies.json does not match the expected shape."""


def load_companies(path: str | Path = DEFAULT_COMPANIES) -> dict[str, tuple[str, ...]]:
    """Map ticker -> tuple of names. The first name is used as the search term."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CompanyFileError("top level must be a JSON object of ticker -> names")
    names: dict[str, tuple[str, ...]] = {}
    for ticker, aliases in raw.items():
        if not isinstance(aliases, list) or not aliases or not all(
            isinstance(a, str) and a.strip() for a in aliases
        ):
            raise CompanyFileError(f"{ticker}: names must be a non-empty list of strings")
        names[ticker.strip().upper()] = tuple(a.strip() for a in aliases)
    return names


def find_mentions(text: str, names: dict[str, tuple[str, ...]]) -> set[str]:
    """Tickers whose company name (or $cashtag) appears as a whole word in `text`."""
    found: set[str] = set()
    for ticker, aliases in names.items():
        base = ticker.split(".")[0]
        patterns = [re.escape(a) for a in aliases] + [re.escape("$" + base)]
        for pattern in patterns:
            if re.search(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", text, re.IGNORECASE):
                found.add(ticker)
                break
    return found
