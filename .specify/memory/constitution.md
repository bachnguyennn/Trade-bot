# TradeBot Constitution

TradeBot (TruthTrade AI) is a real-time, event-driven stock market research and paper-trading
platform. It studies how publicly available political posts relate to short-term market moves.
These principles bind every specification, plan, task, and change in this repository.

## Core Principles

### I. Research Integrity (NON-NEGOTIABLE)

- Market data, backtest results, and model metrics MUST come from real computation on real data.
  They MUST NOT be invented, hand-edited, or extrapolated.
- Test fixtures and synthetic data MUST be labelled as such and MUST NOT appear in any report,
  API response, or dashboard view presented as research output.
- Models MUST be evaluated on chronological train/validation/test splits. Random splits across
  time are prohibited.
- Backtests MUST guard against look-ahead bias, survivorship bias, train/test contamination,
  and double-counting of overlapping events.
- A strategy or model MUST NOT be described as profitable or predictive without out-of-sample
  evidence that includes transaction costs and slippage.
- Reports MUST NOT claim that a post caused a price move. They report association and state
  the alternative explanations that were not ruled out.
- When data is missing, the system MUST show an explicit empty or unavailable state.

Rationale: the project's only output of value is evidence. A single fabricated or leaked number
makes every other result untrustworthy.

### II. Paper Trading Only (NON-NEGOTIABLE)

- The system MUST NOT submit real-money orders. No code path, configuration flag, or
  environment variable may enable live trading.
- Brokerage access MUST sit behind an execution interface with a simulated implementation and
  a paper implementation. The paper implementation MUST refuse to start against any endpoint
  that is not a paper-trading endpoint.
- Order submission MUST pass through a kill switch, a daily loss limit, market-hours
  validation, and duplicate-order prevention. A tripped kill switch MUST block all new orders.
- Documentation and UI MUST state that the system is for research and offers no expectation
  of investment returns.

Rationale: an accidental live order is the one failure that costs real money and cannot be
undone, so the boundary is structural rather than a setting.

### III. Legal Data Access Only

- Data MUST come from sources whose terms permit the use: public archives, licensed providers,
  or official APIs.
- The system MUST NOT bypass authentication, rate limits, robots directives, or any other
  access restriction, and MUST NOT scrape a service whose terms prohibit it.
- Every data source MUST be recorded in `docs/DATA_SOURCES.md` with its licence or terms,
  its limitations, and the date the terms were reviewed.
- Delayed, partial, or single-venue market data MUST be labelled as such. It MUST NOT be
  presented as consolidated real-time data.

Rationale: results built on improperly obtained data cannot be published, shared, or relied on.

### IV. Contract-First Modular Architecture

- Cross-module data MUST use the shared contracts in `src/contracts/`: `SocialPost`,
  `MarketEvent`, `StockCandle`, `MarketFeature`, `ModelPrediction`, `TradingSignal`,
  `BacktestResult`, `PaperOrder`.
- Each module has one owner area (`ingestion`, `pipelines`, `market_data`, `ml`, `strategies`,
  `backtesting`, `api`, `trading`, `frontend`). A module MUST NOT import another module's
  internals; it uses contracts and published interfaces.
- A change to a shared contract or public interface MUST be recorded in
  `docs/API_CONTRACTS.md` and `docs/DECISIONS.md` in the same change, with every consumer
  updated.
- Business logic MUST stay separate from framework code (HTTP handlers, CLI entry points,
  UI components).
- Frontend types MUST be derived from, or verified against, the backend OpenAPI schema.

Rationale: the pipeline spans seven areas of work; stable contracts are what let them progress
in parallel and integrate without rework.

### V. Test-Backed Delivery

- Every feature MUST ship with tests that exercise its acceptance criteria.
- A feature MUST NOT be reported as complete until those tests pass. Skipped or failing tests
  are reported as such.
- Tests MUST run without network access or credentials by default. Tests that need a live
  provider are marked and excluded from the default run.
- Required edge cases include: duplicate, edited, and deleted posts; missing timestamps; posts
  outside market hours; several posts in one event window; missing candles and trading halts;
  network interruptions; duplicate signals; broker rejection; model version mismatch.
- Continuous integration MUST run linting, type checks, and the default test suite on every
  push.

Rationale: research code that is not tested produces results nobody can tell from bugs.

### VI. Point-in-Time Correctness

- All stored timestamps MUST be timezone-aware UTC.
- Every post MUST carry both its publication time and the time it became available to the
  system. Decisions, features, and simulated fills MUST key off the availability time plus a
  configured latency, never the publication time alone.
- Features, labels, universe membership, and corporate-action adjustments MUST use only
  information available at the decision timestamp.
- Raw source records MUST be kept unmodified (Bronze) so that any derived table can be rebuilt.

Rationale: almost every false positive in event-driven research traces back to information
that was not yet knowable at the moment of the simulated decision.

### VII. Security and Low Cost

- Secrets MUST be supplied through environment variables and MUST NOT be committed. A
  `.env.example` documents required variables with placeholder values.
- External input MUST be validated at the system boundary. Credentials MUST have the least
  privilege that works.
- Development MUST run locally on free or open-source tooling and free-tier data. A paid
  service requires a recorded justification in `docs/DECISIONS.md` before it is introduced.
- Dependencies MUST be justified by need; unused dependencies are removed.

Rationale: the project has no budget and holds brokerage credentials, so cost and exposure
are both kept at the minimum.

## Technology and Data Constraints

- Backend: Python 3.12, Pydantic v2 contracts, FastAPI, Polars and Parquet for analytical
  storage, pytest for tests.
- Storage follows a Bronze/Silver/Gold layout: raw records, cleaned and deduplicated records,
  then market-relevant events and features.
- Frontend: React, TypeScript, Tailwind CSS, and a charting library.
- Local-first: the default setup MUST work with file-based storage and no paid infrastructure.
  PostgreSQL, Redis, and Docker are optional layers added only when a requirement needs them.
- Simple baselines MUST be built and evaluated before more expensive models are introduced.

## Development Workflow and Quality Gates

- Work follows the Spec Kit flow: constitution, specification, plan, tasks, implementation.
- The living documents `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/API_CONTRACTS.md`,
  `docs/AGENT_STATUS.md`, and `docs/DECISIONS.md` MUST be updated in the same change as the
  implementation they describe.
- A change is ready to merge when linting, type checks, and the default test suite pass, and
  the change does not violate a principle above.
- Commits are authored solely by the repository owner under the local Git configuration.
  Commit messages and pull request descriptions MUST NOT carry AI attribution trailers,
  footers, or signatures.
- Commit messages are concise and conventional (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
  Work is pushed regularly in small, coherent increments.

## Governance

- This constitution supersedes other practices in the repository. Where a plan or task
  conflicts with it, the constitution wins or the constitution is amended first.
- Amendments are made by editing this file with a version bump and a dated entry in
  `docs/DECISIONS.md` stating what changed and why.
- Versioning is semantic: MAJOR for removing or redefining a principle, MINOR for adding a
  principle or materially expanding guidance, PATCH for clarifications.
- Every plan MUST include a Constitution Check. Any deviation MUST be listed with its
  justification and the simpler alternative that was rejected.
- Principles I and II admit no exceptions.

**Version**: 1.0.0 | **Ratified**: 2026-11-11 | **Last Amended**: 2026-11-11
