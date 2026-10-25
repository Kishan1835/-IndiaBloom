# IndiaBloom

A terminal tool for stock relationships between US and listed Indian
(NSE/BSE) companies. Pick a stock to see its competitors, suppliers and
customers, live prices, correlations with linked stocks, and recent news.
Use it to find Indian stocks that move with a US stock you cannot buy
directly.

Design: [docs/SPEC.md](docs/SPEC.md).

## Setup

```powershell
cd g:\IndiaBloom
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Terminal UI

```powershell
python -m indiabloom ui
```

- **Left pane:** sector tabs and the stock list (Nifty 500 plus stocks in the
  relationship graph). Columns: ticker, last price, day change, US-T (S&P 500
  t-stat from the latest universe report), and sector.
- **Sector tabs:** `1` All, `2` IT, `3` Banks, `4` Manufacturing (labelled Mfg),
  `5` Pharma, `6` US (the US stocks in the graph).
- **Right pane:** one view at a time. `c` Competitors, `s` Suppliers,
  `u` Customers, `r` Correlation, `n` News. Click or use the buttons too.
- `q` quits. Prices and news load in the background, so the screen stays responsive.
- The first start downloads two years of prices for about 500 stocks. That takes
  about a minute and is cached for 12 hours.

Sector rules live in `data/sectors.json`. Edit them to move a stock between tabs.
Banks are picked out by name inside Financial Services, so NBFCs are not counted
as banks. The Manufacturing tab is broad: it includes capital goods, autos,
chemicals, metals, FMCG and textiles.

## Command line

```powershell
python -m indiabloom relations INFY.NS           # every recorded link for a stock
python -m indiabloom news MU --limit 15          # headlines with a crude sentiment label
python -m indiabloom watch                       # US headlines mapped to linked Indian stocks
python -m indiabloom scan MU --period 2y         # rank Indian counterparts by lead-lag correlation
python -m indiabloom correlate MU KAYNES.NS      # one pair, with beta
python -m indiabloom scan ACN --offline-demo     # same as scan, on synthetic data
```

### What the numbers mean

- **NEXT-CORR / CORR:** correlation between a US stock's newest completed
  session and the Indian stock's next session. This is how the US move reaches
  India. For two stocks in the same market the tool uses same-day correlation.
- **BETA:** expected Indian move per unit US move.
- **IMPLIED:** beta times the latest US daily return. A rough estimate, not a
  forecast.
- **SENT:** word count of positive and negative terms in a headline. Crude. Read
  the headline before acting.

## Data

- **Prices:** yfinance (unofficial Yahoo Finance wrapper), end of day. Cached
  in `data/cache/` for 12 hours.
- **News:** Google News RSS search, pulled per company name. The results are
  whatever Google indexes, and the feed sometimes has broken characters in
  apostrophes.
- **Relationships:** `data/relations.json`, curated by hand. Each link has a
  `source`, `target`, `relation` (`supplier`, `peer`, `thematic`), `confidence`,
  and rationale. `supplier` is directed (source supplies target). `peer` means
  competitor.
- **Company names:** `data/companies.json`, used to match headlines to tickers.

The relationship file is the weakest part. It has 17 competitor and thematic
links and **no supplier links yet**. The Suppliers view is empty until you add
them. I did not add supplier links without a source, because a wrong supplier
claim is worse than an empty pane. Add a link with a `sources` URL to a filing
or announcement.

## Tests

```powershell
pytest -q
```

57 tests. None uses the network. The UI tests drive the real Textual app with
fake data services.

## Limits

- Analysis only. Not investment advice, not a trading system.
- Correlation is not causation. A high number can come from shared macro
  factors.
- Headline matching is by company name, so "Apple" can match fruit stories.
  The watch only keeps headlines that name the company.
- Indian residents generally cannot buy most US stocks through a domestic
  broker. Check current RBI and SEBI rules for LRS, overseas funds and ADRs,
  and consult a SEBI-registered advisor.

## Index universe scan (new)

```powershell
python -m indiabloom universe --index nifty200                 # constituents
python -m indiabloom universe-scan --index nifty500 --leader ^GSPC --period 2y --top 30 --validate
```

- `--index`: `nifty50`, `nifty100`, `nifty200` or `nifty500`. Lists come from the
  NSE archive and are cached for 7 days.
- `--leader`: any ticker. `^GSPC` (S&P 500) and `^IXIC` (Nasdaq) are the usual
  choices. A US stock works too, e.g. `MU`.
- `T` is the t-statistic of the lead-lag correlation. Above about 2 is the usual
  threshold, and expect false positives across hundreds of stocks.
- `--validate` adds an out-of-sample hit rate: the model is fit on the first 70%
  of the history and tested on the rest. The run prints a base rate across all
  stocks. 50% is chance.
- The full ranking is saved to `data/reports/`.

Read the results with two cautions. The top stocks are mostly high-beta names
that respond to the same US factor, so a high T says "moves with the US", not
"has its own edge". In the first run, the top stocks' hit rates (53-66%) were
close to the universe median (57%).

## Forward accuracy ledger (new)

The ledger records predictions before they happen, then scores them against
actual moves. It is the honest test of whether the signals work.

```powershell
python -m indiabloom log-signals --index nifty500 --top 20   # once per US session
python -m indiabloom score-signals                           # after Indian sessions trade
```

- `log-signals` writes every stock's predicted direction for the next Indian
  session to `data/ledger/signals.csv`. Running it twice for the same US session
  does nothing.
- `score-signals` compares each prediction with the stock's actual move. It
  reports the top picks and the whole universe, with 95% confidence intervals.
  Pending predictions stay pending until their session has traded.
- Only forward logging is valid. Backfilling old scans would use future data.
- `scripts/daily.ps1` runs either step. Schedule `-Mode log` before the Indian
  open and `-Mode score` after the close with Windows Task Scheduler.

Read the result over weeks, not days. Top picks on one day share one market
move, so a few sessions tell you almost nothing.
