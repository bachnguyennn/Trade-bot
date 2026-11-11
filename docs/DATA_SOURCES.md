# Data sources

Every source the platform reads, the terms it is used under, and its limits. Terms were
reviewed on **2026-11-11**. Review them again before any use beyond personal research, and
whenever a source changes.

The platform never contacts Truth Social, never bypasses authentication or rate limits, and
never scrapes a site. It reads published datasets and official or documented APIs.

## Posts

### `stiles`: Trump Truth Social archive (default)

| | |
|-|-|
| What | JSON archive of posts from the `@realDonaldTrump` account |
| Where | `https://stilesdata.com/trump-truth-social-archive/truth_archive.json`, published by the `stiles/trump-truth-social-archive` project on GitHub |
| Licence | CC0-1.0 (public-domain dedication), as declared on the repository |
| Coverage | 29,409 posts, 2022-02-14 to 2025-10-25 |
| Status | Frozen. The project's update job was disabled on 2025-10-26 |
| Fields used | `id`, `created_at`, `content`, `url`, `media` |
| Limits | Engagement counts are a snapshot. Deleted posts may be absent. Reposts appear as text starting with `RT` |
| How it is used | Downloaded as one file with retries and backoff; stored unmodified in Bronze |

The dataset's licence covers the compilation. The post text itself was written by a third
party; this project stores it locally for research and does not redistribute it.

### `cnn`: hosted continuation of the same archive (off by default)

| | |
|-|-|
| What | A continuation of the archive above, described by its author as updating every five minutes |
| Where | `https://ix.cnn.io/data/truth-social/truth_archive.json` |
| Terms | **Not verified.** No licence or reuse statement was found for this file |
| Status | Opt-in. The source refuses to run unless `TRADEBOT_ALLOW_UNVERIFIED_SOURCES=true` |
| Why it is here | It is the only identified source of posts after October 2025 that does not require scraping |

Do not enable this source until you have read the host's terms and are satisfied that your
use is permitted. Until then, the platform has no source of new posts, and the live workflow
can only be exercised with a local archive file.

### `file`: local archive file

Any JSON file in the same format. Used by tests (with clearly labelled synthetic posts) and
for data you have obtained under your own licence.

### Sources considered and not used

| Source | Reason |
|--------|--------|
| Truth Social website or API | No public API for this use; scraping conflicts with the platform's terms |
| Paid scraping services | Same underlying issue, plus cost |
| Zenodo "Truth Social Dataset" | Covers all users for a few months of 2022, not one account over time |
| "Unfiltered Conversations" dataset | Keyword-sampled; licence not confirmed |
| UCSB American Presidency Project | No confirmed bulk download or licence |

## Market data

### Yahoo Finance through `yfinance` (default when no keys are set)

| | |
|-|-|
| What | Daily and intraday OHLCV bars |
| Terms | `yfinance` is an unofficial client. Yahoo's terms limit the data to personal, non-commercial use and prohibit redistribution |
| Quality label | `delayed` |
| History | Daily: full. 1-hour: about 730 days. 5, 15, 30-minute: about 60 days. 1-minute: about 7 days |
| Adjustments | Daily bars are adjusted for splits and dividends. Intraday bars are adjusted for splits only |
| Limits | Not an official feed; prices can differ slightly from consolidated prints. Requests can fail and are retried once per symbol |
| How it is used | Stored locally in Silver. Not redistributed and not committed to Git |

Because intraday history is short, the 5, 15, and 30-minute windows are unavailable for
almost all historical events, and the 1-hour and 4-hour windows only for recent ones. The
platform reports those windows as unavailable; it does not approximate them from coarser bars.

### Alpaca Market Data (used when API keys are set)

| | |
|-|-|
| What | Historical bars from the consolidated (SIP) feed |
| Terms | Alpaca's market data agreement, accepted when you create an account |
| Quality label | `consolidated` for historical bars |
| Free plan limits | SIP data from the most recent 15 minutes is not served. Real-time data on the free plan comes from the IEX venue only, a small share of total volume |
| How it is used | Requests end at least 16 minutes in the past and always name the `sip` feed. The provider does not request IEX real-time bars; if it ever does, they must be labelled `partial_venue` |

### Trading calendar

`exchange-calendars` (Apache-2.0) supplies NYSE sessions, holidays, and early closes.
No network access is needed.

## Paper brokerage

| Broker | Endpoint | Notes |
|--------|----------|-------|
| Built-in simulator | none | Default. Fills at the latest stored close with slippage |
| Alpaca paper trading | `https://paper-api.alpaca.markets` only | Requires paper API keys. The adapter refuses any other URL |

## Data quality labels

| Label | Meaning |
|-------|---------|
| `consolidated` | Full-market prices |
| `delayed` | Not real-time and not guaranteed to match consolidated prints |
| `partial_venue` | One exchange only |
| `synthetic` | Generated for tests. Never real market data |

A stored bar is never replaced by a lower-quality bar. Every feature, report, and backtest
carries the lowest label among the bars it used, and the dashboard shows it.
