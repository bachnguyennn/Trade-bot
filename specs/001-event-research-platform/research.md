# Research: TradeBot Event Research and Paper-Trading Platform

Reviewed 2026-11-11. Each entry records the decision, why, and what else was considered.

## R1. Source of historical posts

- **Decision**: Use the published archive from the `stiles/trump-truth-social-archive`
  project (`truth_archive.json`, about 15 MB). The repository is licensed CC0-1.0. Fields:
  `id`, `created_at`, `content` (HTML), `url`, `media`, engagement counts. Its update job was
  disabled on 2025-10-26, so it is a frozen historical source.
- **Rationale**: Clear public-domain dedication, one file, stable schema, post IDs and
  publication timestamps preserved. The platform downloads a published dataset; it does not
  contact Truth Social.
- **Alternatives considered**:
  - Zenodo "Truth Social Dataset" (Feb to Sep 2022): open, but covers all users for a short
    period, not one account over time.
  - "Unfiltered Conversations" dataset (2022 to 2024): keyword-sampled, not a full account
    record; licence not confirmed.
  - UCSB American Presidency Project: curated documents, no confirmed bulk download or licence.
  - Scraping Truth Social or using paid scraper services: rejected. Terms and access
    restrictions make this incompatible with Principle III.

## R2. Source of new posts

- **Decision**: Incremental ingestion is an interface (`PostSource.fetch_since`). The first
  implementation re-reads a published archive and keeps only new or changed posts. A
  continuation of the same archive is hosted at `ix.cnn.io/data/truth-social/truth_archive.json`
  and is reported by the archive's author to update every five minutes. Its reuse terms were
  not confirmed, so it is an opt-in source that requires an explicit acknowledgement setting.
- **Rationale**: Gives a near-live path without scraping, and keeps the unverified source off
  by default. Latency is the archive's refresh interval plus the polling interval, and is
  recorded as `retrieved_at` on every post.
- **Alternatives considered**: Direct platform API (not permitted without authorisation);
  licensed news or social data vendors (paid; deferred until needed).

## R3. Market data provider

- **Decision**: A `MarketDataProvider` interface with two implementations.
  - **Alpaca** (used when API keys are set). The free plan serves historical consolidated
    (SIP) bars older than 15 minutes and real-time bars from the IEX venue only. Historical
    bars are labelled `consolidated`; IEX real-time bars are labelled `partial_venue`.
  - **yfinance** (keyless fallback). Daily bars with full history; 1-hour bars for about the
    last 730 days; 5-minute bars for about the last 60 days; 1-minute for about 7 days. It is
    an unofficial client for Yahoo Finance, whose terms limit use to personal, non-commercial
    purposes. Bars are labelled `delayed` and the data is not redistributed.
- **Rationale**: Alpaca is the same vendor as the paper broker and has deep intraday history.
  The keyless fallback lets the historical pipeline run with no account. Labels keep the two
  from being confused.
- **Alternatives considered**: Stooq (daily only); Polygon and Tiingo free tiers (tight rate
  limits or short history); paid real-time SIP (not justified for research).

## R4. Trading calendar

- **Decision**: `exchange-calendars` (XNYS) for sessions, holidays, and early closes.
- **Rationale**: Maintained, covers early closes, avoids hand-written holiday rules.
- **Alternatives considered**: `pandas-market-calendars` (similar; heavier API); a custom
  rule set (error-prone).

## R5. Storage

- **Decision**: Parquet files via Polars in `data/bronze`, `data/silver`, `data/gold`. Bronze
  is append-only, one file per fetch. Silver and Gold are rebuilt deterministically from the
  layer below. SQLite holds paper-order state because it needs transactional updates.
- **Rationale**: Zero infrastructure, fast, reproducible. The dataset is small.
- **Alternatives considered**: PostgreSQL from the start (adds setup cost with no present
  need); DuckDB (good option later for ad hoc queries over the same Parquet files).

## R6. Availability time

- **Decision**: One function defines when a post could first be acted on.
  - Live-collected post: `retrieved_at`.
  - Historically imported post: `published_at + assumed_latency` (default 60 seconds).
  - Decisions then add `decision_latency` (default 30 seconds).
- **Rationale**: A backfilled post has a retrieval time years after publication, so retrieval
  time cannot be used for history. An explicit, configurable assumption is honest and
  testable. Live posts use the real collection time.
- **Alternatives considered**: Using publication time directly (assumes instant reaction;
  rejected by the spec).

## R7. Event windows and abnormal returns

- **Decision**: Market-adjusted abnormal return: symbol return minus benchmark (SPY) return
  over the same window.
  - Intraday windows (5m, 15m, 30m, 1h, 4h): entry at the open of the first regular-session
    bar at or after the anchor; exit at the close of the last bar inside the window. A window
    is available only if stored bars are at least as fine as the window, fully cover it, and
    it does not cross the session close.
  - Next trading day (`1d`): entry at the open of the first session opening at or after the
    anchor; exit at that session's close. Tradable with daily bars.
  - `close_to_close`: last close before the anchor to the first close after it. Descriptive
    only: it includes the overnight gap and is not a tradable return.
- **Rationale**: Simple, transparent, recomputable by hand (SC-005). A market-model beta
  adjustment can be added later; for very short windows the difference is small.
- **Alternatives considered**: Market model with estimated beta (more parameters, more
  leakage risk in estimation windows); raw returns (confounded by market moves).

## R8. Event clustering

- **Decision**: Posts with at least one shared category whose availability times fall within
  a configurable gap (default 60 minutes) merge into one event, anchored at the first post.
- **Rationale**: Prevents the same market reaction from being counted several times.

## R9. Relevance, categories, and entities

- **Decision**: Start with a transparent rule-based classifier (`rules-v1`): a keyword and
  phrase lexicon per category and a gazetteer for companies, tickers, countries, commodities,
  and government bodies. Ambiguous names require supporting context. Themes map to sector
  ETFs and representative symbols.
- **Rationale**: There is no labelled dataset to train a relevance model on. Rules give an
  auditable baseline and produce the weak labels a later model can learn from.
- **Alternatives considered**: Zero-shot transformer classification (slow on CPU, harder to
  audit; planned for Phase 3 as a comparison); LLM labelling (cost and reproducibility).

## R10. Predictive baseline

- **Decision**: TF-IDF features plus one-hot categories and symbol sector, with logistic
  regression for direction and unusual volatility, and ridge regression for magnitude.
  Chronological 70/15/15 split with an embargo equal to the longest label window. Compared
  against majority-class and coin-flip baselines. Training refuses below a minimum sample.
- **Rationale**: Cheap, fast, hard to overfit silently. Stronger models (FinBERT embeddings,
  gradient boosting) are added only if the baseline shows signal.

## R11. Backtesting engine

- **Decision**: A time-ordered event queue over signals and bars. Entries fill at the first
  bar open at or after the decision time, with slippage in basis points against the trader
  and a per-side cost in basis points. Exits by holding period, stop-loss (checked on bar
  lows and highs, filled at the stop level or the bar open if gapped), or end of data.
  Limits: per-position weight, gross exposure, one open position per symbol.
- **Rationale**: Matches the tradable window definitions and keeps execution assumptions
  explicit and conservative.

## R12. Paper trading

- **Decision**: `ExecutionBroker` protocol with `SimulatedBroker` (default) and
  `AlpacaPaperBroker`, which only accepts `https://paper-api.alpaca.markets`. There is no
  live adapter. `OrderService` applies kill switch, daily loss limit, market-hours check, and
  idempotency on `signal_id` before calling any broker.
- **Rationale**: The safety boundary is in the type system and constructor, not a setting.

## R13. Frontend

- **Decision**: React 18, TypeScript, Vite, Tailwind CSS, Recharts. A typed API client whose
  types mirror the backend contracts; a contract test compares them with the OpenAPI schema.
- **Rationale**: Standard, free, quick to build. Recharts is enough for equity curves and
  event markers on daily or hourly prices.

## R14. Development environment

- **Finding**: The development machine has Python 3.12 but no Node.js and no Docker.
- **Decision**: Backend runs in a local virtual environment. Frontend is built and tested
  with a portable Node.js runtime kept outside the repository. Docker Compose files are
  provided and validated in CI rather than locally.
