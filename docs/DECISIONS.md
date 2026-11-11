# Decisions

Each entry: what was decided, why, and what was rejected. Newest last.

## D-001: Local-first storage in Parquet (2026-11-11)

**Decision**: Bronze, Silver, and Gold are Parquet files written with Polars. SQLite holds
paper-order state. PostgreSQL and Redis are not used.

**Why**: The data is small (30,000 posts, under a million candles). Files need no setup, cost
nothing, and every derived table can be rebuilt. Order state needs transactions and a unique
key, which SQLite provides from the standard library.

**Rejected**: PostgreSQL from the start (setup cost with no present need). Revisit if several
processes must write concurrently.

## D-002: The backend is imported as the `src` package (2026-11-11)

**Decision**: Modules live at `src/ingestion`, `src/market_data`, and so on, and are imported
as `src.<module>` with the repository root on the path.

**Why**: The project brief assigns ownership by those exact paths. A nested `src/tradebot/`
would have moved them.

**Trade-off**: `src` is an unusual package name. It is acceptable for an application that is
not published as a library.

## D-003: Post source is a CC0 archive; the continuation is opt-in (2026-11-11)

**Decision**: Historical posts come from the `stiles` archive (CC0-1.0). The hosted
continuation is available only behind `TRADEBOT_ALLOW_UNVERIFIED_SOURCES=true`.

**Why**: The archive has a clear licence. The continuation's reuse terms could not be
confirmed, so using it must be a deliberate choice by the operator.

**Consequence**: Out of the box there is no source of posts after October 2025.

## D-004: Availability time is modelled, not assumed instant (2026-11-11)

**Decision**: A live post is available when collected. A backfilled post is available
`assumed_latency` (60 s) after publication. Decisions add `decision_latency` (30 s).

**Why**: A backfilled post's retrieval time is years late and cannot be used, while trading
at the publication instant is unrealistic. An explicit, configurable assumption is testable.

## D-005: Missing data makes a window unavailable (2026-11-11)

**Decision**: A window with missing, misaligned, or too-coarse bars is marked unavailable
with a reason. Nothing is interpolated or taken from a coarser interval.

**Why**: Constitution Principle I. An estimated return is an invented number.

## D-006: Market-adjusted abnormal returns (2026-11-11)

**Decision**: Abnormal return is symbol return minus SPY return over the same window.

**Why**: Transparent and recomputable by hand. A market-model beta needs an estimation
window, more parameters, and more ways to leak. For short windows the difference is small.

**Rejected for now**: Market model or factor model. Listed on the roadmap.

## D-007: Rule-based classifier first (2026-11-11)

**Decision**: Relevance, categories, and entities come from a lexicon and gazetteer
(`rules-v1`). Ambiguous company names need business context or no symbol is assigned.

**Why**: There is no labelled data to train on. Rules are auditable and deterministic.

**Known weakness**: Precision and recall are unmeasured. Campaign endorsements had to be
excluded by an explicit rule after inspection of real output.

## D-008: Event study reports baseline-adjusted, session-clustered statistics (2026-11-11)

**Decision**: Alongside the per-event t-test, the study reports the same symbols' average
abnormal return over all sessions (baseline) and a t-test over per-session averages.

**Why**: On real data the naive next-day statistic was t = -4.1. Events entering on the same
session share one market move. After clustering by session and subtracting the baseline it
is t = -1.5. Without these controls the platform would have reported a false finding.

## D-009: "Beats baseline" requires the accuracy interval to clear every naive rate (2026-11-11)

**Decision**: A model is flagged as beating baselines only if the lower bound of its 95%
accuracy interval exceeds the majority-class, always-up, and coin-flip accuracies, and its
log loss beats a constant rate.

**Why**: The first version compared against the training-majority class only and flagged a
model with 51.7% accuracy as a success when always predicting "up" scored 54.1%.

## D-010: Strategy A trades only on walk-forward predictions (2026-11-11)

**Decision**: Training stores expanding-window out-of-sample predictions. The Strategy A
backtest uses only those, and the live cycle does not store predictions for backfilled events.

**Why**: A model's predictions on its own training period would make the backtest look far
better than it is.

**Consequence**: Strategy A is tested on a shorter period than B and C.

## D-011: No live-trading code path (2026-11-11)

**Decision**: `ExecutionBroker` has a simulator and a paper adapter. The paper URL is a
constant checked in the constructor. `Settings` has no trading URL or live flag.

**Why**: Constitution Principle II. A structural boundary cannot be flipped by a
configuration mistake.

## D-012: Staleness is measured from publication (2026-11-11)

**Decision**: The live cycle does not trade an event whose anchor post was published more
than 30 minutes ago, even if it was only just collected.

**Why**: An "immediate reaction" strategy has no basis for trading a post the market has
already had hours to absorb.

## D-013: yfinance as the keyless market-data fallback (2026-11-11)

**Decision**: Without Alpaca keys, market data comes from Yahoo Finance through `yfinance`,
labelled `delayed`, stored locally, and never redistributed.

**Why**: It lets the historical pipeline run with no account. The label and the
[data source notes](DATA_SOURCES.md) keep its limits visible.

**Constraint**: Yahoo's terms allow personal, non-commercial use only. Any other use needs a
licensed provider.

## D-014: Constitution adopted at version 1.0.0 (2026-11-11)

Seven principles: research integrity, paper trading only, legal data access, contract-first
architecture, test-backed delivery, point-in-time correctness, security and low cost.
See `.specify/memory/constitution.md`.
