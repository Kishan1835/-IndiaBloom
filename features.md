# IndiaBloom features since the last push

Everything below was added after commit `2a57fb5`. Commands run from the repo folder. The TUI starts with `python -m indiabloom ui`. Press `?` inside it to see every key.

Data files that are personal or git-ignored (watchlist, alerts, exports, fundamentals and events caches, holdings history) stay on your PC. Only the ledger and the NSE deals history are committed by the GitHub Action.

## Watchlist and positions

Track stocks you follow, and optionally your buy price and quantity to see P&L.

- TUI: `a` adds or removes the selected stock. `7` shows the Watch tab. `p` shows the Position view.
- CLI: `python -m indiabloom watchlist add INFY.NS --buy 1500 --qty 10`, then `watchlist show`.

Example: Infosys at a buy price of 1500 for 10 shares, with a last price of 1153.80, shows P&L of -3,462.00 (-23.08%).

## Fundamentals screener

Filter the Nifty 500 on valuation and financials, using the local cache.

- CLI: `python -m indiabloom screen --where "pe_trailing<20" --where "roe>=15" --where "market_cap_cr>=50000" --sort roe --top 15`
- TUI: `x`, then type conditions separated by commas, for example `pe_trailing<20, roe>=15`. Enter on a result opens that stock.
- Fields: P/E, P/B, EPS, ROE, margins, debt to equity, market cap in crore, sector and industry text.

Example: that screen returned 15 of 499 cached stocks. Hindustan Zinc, TCS and Infosys were among them. High ROE can come from low book equity, so check the other columns.

## Fundamentals view and cache

`python -m indiabloom fundamentals --index nifty500` caches valuation and four years of financials per stock. It is resumable and skips stocks cached within the last seven days. `--refresh` forces a refetch.

- TUI: `f` shows the cached snapshot for the selected stock.
- Some companies report statements in USD while trading in INR. The view labels the currency. Infosys revenue shows as 20,158 USD mn.
- ROE is computed from net income and equity when Yahoo does not provide it, and the label says so.

## NSE deals (bulk and block trades)

Who bought and sold large blocks, from NSE's daily bulk and block files.

- CLI: `python -m indiabloom deals` appends today's files to `data/deals/deals.csv`. Each run adds to the history.
- TUI: `d` lists the deals for the selected stock.

Example: BONFIG on 23-Oct-2026. CATAMARAN VENTURES LLP bought 1,045,000 shares at 581.35, about Rs 60.8 crore. These are large trades only. They are not all institutional flows, and they don't show customers or suppliers.

## Event calendar

Next results date, ex-dividend date, past results (estimate vs reported EPS), dividends and splits, from Yahoo.

- CLI: `python -m indiabloom events --index nifty500` builds the cache (refreshed after a day). `python -m indiabloom calendar --days 30` lists upcoming dates. Add `--watch` to limit it to your watchlist.
- TUI: `k` shows the events for the selected stock.

Example: Infosys has an ex-dividend date of 2026-11-03 and next results on 2027-01-13. Dates from Yahoo can change, so confirm with the company.

## Shareholding history

Insider and institution percentages over time. yfinance gives only aggregate figures, not named holders or FII/DII splits.

- CLI: `python -m indiabloom holders INFY.NS`. Each fundamentals run adds a point, so changes appear after the next refresh.

Example: Infosys on 2026-10-25 shows insiders 15.99% and institutions 51.28%.

## Price chart

Text chart of daily closes over 1M, 6M and 1Y, with start, end, change, high and low.

- TUI: `h` on the selected stock. Loads in the background.

## Compare

Up to six stocks on one chart, each rebased to 100 on the first common date.

- TUI: `o`, then type tickers separated by commas, for example `INFY.NS, TCS.NS, MU`.

Example: over the last year INFY.NS ended at 76.7, TCS.NS at 119.4 and MU at 150.0.

## Movers

Largest day gainers and losers from the loaded prices.

- TUI: `m`. Enter on a row opens that stock.

## Search (Ctrl+F)

Find a stock by ticker or company name. Enter jumps to it and shows the All tab. Esc closes.

- Examples: `infy`, `INFY.NS`, or `consultancy` (matches TCS).

## Command palette (Ctrl+P)

Pick any view, stock-list tab or action by name, such as "View: Chart" or "Export this view (CSV)".

## Help panel (?)

Lists every key. It is generated from the app's actual bindings, so it stays accurate.

## CSV export

- TUI: `e` saves the table on the right. Ctrl+E saves the stock list, or the watchlist with P&L on the Watch tab.
- Files go to `data/exports/`, with UTF-8 BOM so Excel reads names correctly.

## Alerts

Rules for price levels, day moves, new deals and new headlines. Price and move alerts fire once a day. Deal and headline alerts fire only for items that appear after the rule was created.

- CLI: `python -m indiabloom alerts add INFY.NS --below 100000`, then `alerts check`. `alerts list`, `alerts remove ID`, and `alerts watch --every 15` (runs while the terminal stays open).
- Example: that rule fired on the check at 1,153.80. Fired alerts go to `data/alerts/log.csv`.
- TUI: `l` shows your rules and recent fired alerts. Ctrl+L adds or removes a rule, for example `MU move_down -3`, `TCS.NS news` or `remove 3`.

## Scheduled runs on your PC

`scripts/alerts.ps1` runs from Windows Task Scheduler.

- `-Mode check` runs the alert check (every 15 minutes).
- `-Mode daily` refreshes NSE deals and events, then runs the alert check. On Sundays it also refreshes fundamentals.
- Output goes to `data/alerts/runner.log`. Task Scheduler commands are in the alerts notes. They are not registered yet.

## GitHub Action changes

`.github/workflows/daily-signals.yml` now also runs `python -m indiabloom deals` after the Indian close and commits `data/deals/deals.csv` with the ledger. The deals step can fail without blocking the ledger, because NSE may block GitHub's IP addresses.

## Known limits

- Yahoo data (fundamentals, events, holdings) is unofficial. Coverage varies, and dates and ratios can change.
- Deals show large trades only, not customers, suppliers or full FII/DII flows.
- Alerts only run while your PC is on and the scheduled task is registered, or while `alerts watch` is running.
- The TUI reads files when a view opens. It does not update in the background.
