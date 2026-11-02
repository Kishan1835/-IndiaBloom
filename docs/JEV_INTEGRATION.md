# Jev headline-classification integration

## Current status

The integration boundary is implemented in `indiabloom/jev.py`, but the Jev
transport is intentionally not enabled yet. The repository does not contain an
official Jev endpoint, SDK contract, authentication scheme, or response schema.
We will not guess those details.

The backtest and ranking logic remain local and price-based. Jev will not choose
stocks or create buy/sell recommendations.

## Planned flow

```text
Google News RSS
    -> normalized NewsItem
    -> Jev adapter (optional, headline text/link only)
    -> validated HeadlineClassification
    -> News/Alerts TUI and CLI
```

The planned result contains:

- `sentiment`: positive, negative, or neutral
- `relevance`: high, medium, or low
- `confidence`: a number from 0 to 1
- `status`: accepted at confidence >= 0.80, otherwise review_required
- `rationale`: bounded explanatory text
- provider and model identifiers

The adapter validates every field. It must return exactly one decision per
submitted headline. A provider failure falls back to the local word-count
heuristic unless strict mode is requested.

## Privacy boundary

Only normalized headline title, link, and a generated headline key are sent to
the classifier. IndiaBloom never sends holdings, watchlists, alert rules,
prices, or account information through this boundary.

The future API key will be read from an environment variable or `.env` file and
must never be placed in source code, command arguments, logs, or Git.

## What is implemented now

- Typed `HeadlineClassification` result.
- Stable headline identity for caching.
- Strict provider-response validation.
- Local fallback classifier.
- Provider-neutral JSON adapter for mocked tests and the future official Jev transport.
- Cache-key generation.

## Before enabling the real Jev call

Obtain the official API documentation or SDK details for:

1. Endpoint or package name.
2. Authentication header and key environment variable.
3. Request shape and batch size.
4. Response shape and confidence semantics.
5. Rate limits, timeout, and cost.
6. Whether data is retained or used for training.

Once those are known, add one transport class to `jev.py`, inject it through
`Services`, and add TUI/CLI classification columns. Do not add the key to the
GitHub Action unless a separate repository secret and explicit workflow step are
approved.
