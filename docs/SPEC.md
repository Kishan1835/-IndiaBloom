# IndiaBloom — Specification

Status: v0.1 (initial build)
Scope: a command-line terminal that shows which global (US) stocks move which
listed Indian (NSE) stocks, so a user can take exposure to a foreign theme
through an Indian listing.

## 1. Problem

A user wants exposure to, for example, Micron (MU), which is not directly
accessible from India. Some Indian listed companies may be suppliers,
customers, competitors, or thematic proxies for that global company. IndiaBloom
must:

1. Store curated links between global and Indian stocks, with a rationale and a
   confidence level for each.
2. Measure how strongly the Indian stock actually tracks the global stock, using
   price history.
3. Account for time zones: the US session closes after the Indian session, so
   a US move on day *t* is first priced into Indian stocks on day *t+1*.
4. Rank the Indian candidates and show the expected next-session move implied
   by the latest US move.

## 2. Goals and non-goals

Goals
- Offline-testable core (analytics, graph, scanner) with no network calls.
- Explicit, auditable relationship data (`data/relations.json`).
- A CLI with three commands: `relations`, `correlate`, `scan`.
- Honest output: every number carries its sample size and confidence label.

Non-goals (v0.1)
- No trading, order placement, or broker integration.
- No investment advice. Output is analysis only.
- No automated discovery of supply-chain links. Links are curated by a human.
- No real-time streaming. Data is end-of-day.
- No web UI. A terminal UI can come later (see section 10).

## 3. Users

A single retail user who runs the tool locally. Prior knowledge of equities is
assumed. The user is responsible for verifying every link before acting on it.

## 4. Architecture

```
            +-------------------+
            | data/relations.json|  curated links (global -> Indian)
            +---------+---------+
                      |
                      v
+-----------+   +-----------+   +------------+
| market.py |-->| scanner.py|-->| cli.py     |  relations / correlate / scan
| yfinance  |   | ranking   |   | (argparse) |
+-----+-----+   +-----+-----+   +------------+
      |               |
      v               v
+-----------+   +-----------+
| analytics |<--| graph.py  |  load + validate relations
| corr/beta |   |           |
+-----------+   +-----------+
```

Modules (package `indiabloom/`)
- `models.py`: `Relation` dataclass and the allowed enum values.
- `graph.py`: loads and validates the relations file; lookup by ticker.
- `analytics.py`: pure functions on pandas Series (returns, correlation, lag,
  beta). No I/O.
- `market.py`: the only module that touches the network (yfinance). It is
  imported lazily so tests never need it.
- `scanner.py`: combines graph + prices + analytics into ranked rows.
- `cli.py`: argument parsing and table printing.

## 5. Data model

`data/relations.json` is a JSON array. Each item:

Schema v2 (replaces v1, which used global_ticker/indian_ticker and could not
express Indian-to-Indian competitors):

| field          | type   | rules                                                             |
|----------------|--------|-------------------------------------------------------------------|
| source         | string | valid ticker: US symbol (`MU`) or Indian with `.NS`/`.BO`         |
| target         | string | valid ticker, must differ from `source`                           |
| relation       | string | `supplier` (directed: source supplies target), `peer`, `thematic` |
| confidence     | string | one of `low`, `medium`, `high`                                    |
| rationale      | string | non-empty, one sentence, the reason for the link                  |
| sources        | list   | optional list of URLs supporting the link                         |

Undirected types (`peer`, `thematic`) are unique per unordered pair. Directed
`supplier` links are unique per ordered pair. Competitors are `peer` links on
either side. The UI shows Suppliers (links where the stock is the target of a
`supplier` row) and Customers (links where it is the source).

The v1 `customer` relation type was removed. Use `supplier` in the reverse
direction instead.

Validation (in `graph.py`) rejects bad values, duplicate pairs, and tickers with
the wrong suffix. A validation error stops the CLI with a clear message.

Confidence weights used in ranking: `high`=1.0, `medium`=0.6, `low`=0.3.

## 6. Algorithms

Input: daily closing prices for the global ticker G and the Indian ticker I
over the requested period.

6.1 Returns. `r_t = ln(P_t / P_{t-1})`. Days missing on either side are dropped
by an inner join on dates.

6.2 Same-day correlation. Pearson `corr(r_G[t], r_I[t])`. Shown for reference
only. It is misleading for cross-timezone pairs because the markets do not
trade at the same time.

6.3 Next-session correlation (primary). `corr(r_G[t-1], r_I[t])`. This is the
US move that is priced into the next Indian session. This is the number used
for ranking.

6.4 Beta. `beta = cov(r_I, r_G_lag) / var(r_G_lag)` using the same lag. It
gives the expected Indian move per unit US move.

6.5 Implied move. `implied = beta * r_G[latest]`, where `r_G[latest]` is the
most recent US daily return. It is an estimate, not a forecast.

6.6 Score. `score = |corr_next| * weight(confidence)`. The scanner sorts by
score descending.

Minimum sample: 30 aligned observations. Below that the row is marked
`insufficient data` and is not ranked.

## 7. CLI

```
python -m indiabloom relations MU
python -m indiabloom correlate MU KAYNES.NS --period 2y
python -m indiabloom scan MU --period 1y --top 10
python -m indiabloom scan MU --offline-demo        # synthetic data, no network
```

Output is a plain-text table. Numbers are shown with 3 decimals for correlation
and 2 decimals for percentages. Every row shows `n` (sample size).

Exit codes: 0 success, 2 bad arguments or validation error, 3 data fetch
failure.

## 8. Error handling

- Unknown global ticker with no relations: print a message and exit 0 with an
  empty result (not an error).
- Network or yfinance failure: exit 3 with the failing ticker named.
- Fewer than 30 observations: row marked `insufficient data`.
- Missing or empty prices for a ticker: skipped with a warning on stderr.

## 9. Testing

- Unit tests for analytics using synthetic series with known correlation.
- Graph tests for validation (bad suffix, bad enum, duplicates).
- Scanner tests with synthetic prices: a planted lag must be recovered.
- CLI smoke test with `--offline-demo`.
- No test calls the network.

## 10. Roadmap

- v0.2: cache downloaded prices to a local CSV/Parquet file.
- v0.3: rolling-window correlation to show whether a link is stable over time.
- v0.4: Textual-based terminal UI with a watchlist.
- v0.5: add more links, with source URLs for each.

## 11. Risks and limitations

- Curated links can be wrong or out of date. Each row must be verified.
- Correlation is not causation. A high number can come from shared macro
  factors (rates, dollar, sector sentiment).
- Short history and low liquidity give unstable estimates.
- yfinance is an unofficial Yahoo Finance wrapper. Its data can change or be
  delayed. Use it for analysis, not for execution.
- Access: Indian residents generally cannot buy most US-listed stocks through a
  domestic broker. Foreign-equity access routes (LRS remittance, overseas
  funds, or ADRs listed on US exchanges) have their own limits and rules. Check
  current RBI and SEBI rules and speak to a SEBI-registered advisor. This tool
  gives no legal or tax advice.

## 12. Acceptance criteria

1. `pytest` passes with no network access.
2. `scan` on the bundled relations file runs in offline demo mode and prints a
   ranked table.
3. Relations validation rejects a file with a missing field or a `.XX` suffix.
4. The lag test recovers a planted one-day lead within a 0.05 tolerance.


## 13. v0.2 additions

- **Live quotes:** last price and day change per stock (yfinance `fast_info`).
- **Price cache:** CSV files in `data/cache/`, reused for 12 hours.
- **Pair metrics:** a US and an Indian stock use the next-session lead; two
  stocks in the same market use same-day correlation. Each row shows the method
  and the leader.
- **News:** Google News RSS per company name, with publisher suffixes stripped
  so one story from several outlets is one headline. Sentiment is a crude
  word count.
- **Watch:** headlines that name a US company in the graph, grouped with all of
  its Indian links. Loose matches (a headline that does not name the company)
  are dropped.
- **UI views:** Competitors, Suppliers, Customers, Correlation, News. Slow loads
  run in background threads. A stale result is discarded if the user has moved
  on.
- **Services layer:** prices, quotes, and news are injected through `Services`,
  so the UI and CLI can be tested without the network.
- **Lag alignment fix:** the lead now uses the newest completed US session
  dated on or before the Indian date minus one day. US holidays and long
  weekends use the real session dates. The earlier version used row position,
  which was wrong across holidays.

Known gaps: sentiment is a word count, not a model. Supplier links are empty.
Price history is end-of-day only. Google News results depend on what Google
indexes.
