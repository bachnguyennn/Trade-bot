# Feature Specification: TradeBot Event Research and Paper-Trading Platform

**Feature Branch**: `001-event-research-platform`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "TradeBot (TruthTrade AI) platform foundation and historical research MVP: collect Truth Social posts by Donald Trump from legally accessible sources, identify market-relevant posts, measure and predict stock reactions, backtest event-driven strategies, paper trade, and present everything in a research dashboard. Phased delivery; prioritise a working historical event-study pipeline over deep-learning complexity."

## User Scenarios & Testing *(mandatory)*

The primary user is a **researcher**: a single person who runs the platform locally to study
whether political posts carry a tradable signal. There are no other user roles in this feature.

### User Story 1 - Build a trustworthy history of posts (Priority: P1)

The researcher imports the historical archive of posts from a permitted source and gets a
clean, deduplicated record in which every post keeps its original identity, publication time,
retrieval time, source link, and repost status. Running the import again adds only what is new.

**Why this priority**: Every later result depends on this record. Without a reliable,
point-in-time post history there is nothing to study.

**Independent Test**: Run the import against a sample archive file, then run it a second time,
and confirm the post count is unchanged, timestamps are in UTC, and raw records are preserved.

**Acceptance Scenarios**:

1. **Given** an archive containing posts, **When** the researcher runs the historical import,
   **Then** every valid post is stored with its ID, text, publication time, retrieval time,
   source link, and repost flag, and the raw records are kept unmodified.
2. **Given** an import has already run, **When** the same archive is imported again,
   **Then** no duplicate posts are created.
3. **Given** an archive containing a record with no usable publication time, **When** it is
   imported, **Then** the record is kept in the raw layer, excluded from the clean layer, and
   counted in a rejection report with its reason.
4. **Given** a post that appears twice with different text, **When** it is imported, **Then**
   the clean layer holds one record marked as edited and the earlier version stays retrievable
   from the raw layer.
5. **Given** the source is unreachable or rate-limited, **When** an incremental fetch runs,
   **Then** it retries with backoff, reports the failure, and leaves stored data intact.

---

### User Story 2 - Get market data that matches the posts (Priority: P1)

The researcher loads price history for a defined set of liquid stocks and ETFs and can ask for
the price path of any symbol around any moment, with the system knowing when the market was
open, closed, or on holiday.

**Why this priority**: A post can only be studied against prices. This story and Story 1
together are the minimum needed for any analysis.

**Independent Test**: Load price history for the universe and request the return of a symbol
over each supported window after a chosen timestamp, including one that falls on a weekend.

**Acceptance Scenarios**:

1. **Given** a universe of symbols, **When** the researcher loads price history, **Then**
   open, high, low, close, and volume are stored per symbol and interval, labelled with their
   source and whether the data is consolidated, delayed, or partial.
2. **Given** a timestamp outside trading hours, **When** a window is requested, **Then** the
   window starts at the next regular session open and the result says so.
3. **Given** a symbol with a split in the period, **When** returns are computed across it,
   **Then** the returns reflect the adjustment and are not distorted by the split.
4. **Given** candles are missing for part of a window, **When** a return is requested,
   **Then** the result is marked unavailable rather than filled with an estimate.

---

### User Story 3 - See which posts matter and what they touch (Priority: P1)

The researcher sees each post tagged with whether it is market-relevant, which policy
categories it belongs to, and which companies, sectors, countries, and commodities it names,
with those mapped to tradable symbols in the universe.

**Why this priority**: Most posts have nothing to do with markets. Selecting the relevant ones
and their affected symbols defines the events the rest of the platform studies.

**Independent Test**: Run classification over a labelled sample of posts and check that
categories, entities, and symbol mappings match expectations.

**Acceptance Scenarios**:

1. **Given** a post about tariffs on a named country, **When** it is classified, **Then** it is
   marked market-relevant with the trade category and the named country, and is mapped to the
   symbols in the universe exposed to that theme.
2. **Given** a post that touches several themes, **When** it is classified, **Then** it carries
   every applicable category.
3. **Given** a post unrelated to markets, **When** it is classified, **Then** it is marked not
   relevant and produces no event.
4. **Given** a post naming a company by an ambiguous word, **When** entities are resolved,
   **Then** the mapping is made only when the context supports it; otherwise no symbol is
   assigned.

---

### User Story 4 - Reproduce an event study (Priority: P1)

The researcher runs an event study that measures how affected symbols moved, relative to the
market, in each window after posts became available, summarised by category, and can rerun it
to get the same numbers.

**Why this priority**: This is the core research question: do these posts coincide with
abnormal moves? It is the first result the platform must deliver.

**Independent Test**: Run the study twice on the same stored data and compare the outputs;
check one event by hand against the stored prices.

**Acceptance Scenarios**:

1. **Given** stored posts and prices, **When** an event study runs, **Then** it reports
   abnormal returns for 5 minutes, 15 minutes, 30 minutes, 1 hour, 4 hours, and the next
   trading day, per event and averaged by category, with sample counts and a significance
   measure.
2. **Given** two posts on the same theme within one window, **When** the study runs, **Then**
   they are treated as one event cluster and not counted twice.
3. **Given** the same data and settings, **When** the study runs again, **Then** the results
   are identical.
4. **Given** intraday data is unavailable for an event, **When** the study runs, **Then** the
   intraday windows for that event are reported as unavailable and the daily window is still
   computed.

---

### User Story 5 - Train and evaluate prediction models honestly (Priority: P2)

The researcher trains a simple baseline model and, later, stronger models, to predict the
direction and size of abnormal returns and the chance of unusual volatility. Each model is
judged on data from after its training period and compared with naive baselines.

**Why this priority**: Prediction adds value only after the event study shows there is
something to predict. It builds on Stories 1 to 4.

**Independent Test**: Train the baseline on stored events, confirm the evaluation uses only
later events, and confirm a report is produced with real metrics next to naive baselines.

**Acceptance Scenarios**:

1. **Given** stored events with outcomes, **When** a model is trained, **Then** the training,
   validation, and test periods are in time order with no overlap, and the report states them.
2. **Given** a trained model, **When** it is evaluated, **Then** the report shows its metrics
   alongside a majority-class baseline and a no-skill baseline.
3. **Given** a new post, **When** a prediction is requested, **Then** the result includes
   direction, expected magnitude, volatility probability, a confidence value, and the model
   version that produced it.
4. **Given** too few events to train on, **When** training is requested, **Then** it refuses
   and reports the shortfall instead of producing a model.

---

### User Story 6 - Backtest strategies with realistic assumptions (Priority: P2)

The researcher backtests three strategies — immediate reaction, momentum continuation, and
mean reversion — with costs, slippage, sizing, risk limits, and exit rules, and compares each
against simple benchmarks.

**Why this priority**: This answers whether any signal survives realistic trading frictions.
It depends on the event and prediction work.

**Independent Test**: Run each strategy over stored events and confirm trades are entered only
after the post was available, costs are applied, and the metric set is complete.

**Acceptance Scenarios**:

1. **Given** stored events, **When** a backtest runs, **Then** every entry is priced at or
   after the time the post became available plus the configured delay.
2. **Given** a backtest result, **When** it is reviewed, **Then** it reports cumulative return,
   Sharpe ratio, Sortino ratio, maximum drawdown, win rate, profit factor, turnover, trade
   count, and results per category, alongside a buy-and-hold benchmark.
3. **Given** a signal below the confidence threshold or one that would breach an exposure
   limit, **When** the strategy evaluates it, **Then** it records a no-trade decision with
   the reason.
4. **Given** a position that reaches its stop-loss or holding limit, **When** the backtest
   advances, **Then** the position is closed under the configured exit rule.
5. **Given** a backtest with zero costs and one with configured costs, **When** both run,
   **Then** the second shows lower or equal returns and both state their assumptions.

---

### User Story 7 - Paper trade safely (Priority: P3)

The researcher lets valid signals place simulated orders, watches orders and positions, and
can stop all new orders at once.

**Why this priority**: Paper trading is the forward test of what the backtests suggest. It
comes last because it needs a working signal path.

**Independent Test**: Submit signals to the simulated execution service and verify order
tracking, duplicate rejection, the loss limit, market-hours checks, and the kill switch.

**Acceptance Scenarios**:

1. **Given** a valid signal during market hours, **When** it is submitted, **Then** a paper
   order is created, its status is tracked to completion, and the position is updated.
2. **Given** the same signal arrives twice, **When** it is submitted again, **Then** no second
   order is created.
3. **Given** the kill switch is on, **When** any signal arrives, **Then** no order is placed
   and the refusal is logged.
4. **Given** the day's losses reach the configured limit, **When** a new signal arrives,
   **Then** it is refused until the next trading day.
5. **Given** the broker rejects an order or the connection fails, **When** the service
   retries, **Then** it does not create duplicate orders and records the outcome.
6. **Given** any configuration, **When** the system starts, **Then** no real-money order can
   be submitted.

---

### User Story 8 - Review everything in one dashboard (Priority: P2)

The researcher opens a dashboard with six sections — Overview, Political Event Feed, Stock
Market Analysis, Strategy Research, Paper Trading, and Model Analytics — and sees real results
where they exist and a clear empty state where they do not.

**Why this priority**: The dashboard makes the research usable day to day, but the results
must exist first.

**Independent Test**: Open the dashboard with an empty data store and confirm every section
shows an empty state; then open it with processed data and confirm the values match the
stored results.

**Acceptance Scenarios**:

1. **Given** no data has been processed, **When** the dashboard opens, **Then** each section
   states that no data is available and shows no placeholder numbers.
2. **Given** processed events, **When** the event feed is viewed, **Then** each post shows its
   text, publication time, collection time, categories, identified companies, and any
   predictions.
3. **Given** a symbol and an event, **When** the market analysis view opens, **Then** the
   price chart marks the event and shows the before-and-after move and abnormal return.
4. **Given** a completed backtest, **When** strategy research is viewed, **Then** the equity
   curve, drawdown, benchmark comparison, and configuration are shown.
5. **Given** the backend is unreachable, **When** the dashboard loads, **Then** it reports the
   connection problem instead of showing stale or invented values.

---

### Edge Cases

- Duplicate posts, and posts that were edited or deleted after first collection.
- Records with missing or unparseable timestamps.
- Posts published overnight, at weekends, or on market holidays.
- Several posts on the same theme inside one event window.
- Reposts and posts that contain only media or a link with no usable text.
- Symbols that were halted, delisted, or not yet listed at the time of a post.
- Missing candles inside an event window, and windows that span a session close.
- Network interruptions and rate limits during ingestion or order submission.
- A prediction request when no model has been trained, or when the stored model version does
  not match what the caller expects.
- Duplicate trade signals and broker rejections.
- A day on which the daily loss limit is reached mid-session.

## Requirements *(mandatory)*

### Functional Requirements

**Posts**

- **FR-001**: System MUST import historical posts from sources whose terms permit the use and
  MUST record each source's terms and limitations.
- **FR-002**: System MUST store for each post its source ID, text, publication time, retrieval
  time, source link, and repost information.
- **FR-003**: System MUST normalise all timestamps to UTC.
- **FR-004**: System MUST keep raw records unmodified, separate from cleaned records and from
  derived market events.
- **FR-005**: System MUST deduplicate posts and MUST track edits and deletions without losing
  earlier versions.
- **FR-006**: System MUST support incremental collection that adds only new or changed posts.
- **FR-007**: System MUST retry failed or rate-limited fetches with backoff and MUST report
  rejected records with reasons.

**Market data**

- **FR-008**: System MUST maintain a defined universe of liquid stocks and ETFs with sector
  and theme tags, and MUST record when each symbol was eligible.
- **FR-009**: System MUST store open, high, low, close, and volume per symbol at daily and
  available intraday intervals.
- **FR-010**: System MUST label market data with its source and whether it is consolidated,
  delayed, or partial, and MUST NOT present delayed or partial data as consolidated real-time.
- **FR-011**: System MUST know regular trading sessions, holidays, and early closes, and MUST
  identify pre-market and after-hours periods where the data supports them.
- **FR-012**: System MUST account for splits and dividends in return calculations.
- **FR-013**: System MUST compute returns, volatility, and volume change for windows of 5, 15,
  30 minutes, 1 hour, 4 hours, and the next trading day, and MUST mark a window unavailable
  when its data is incomplete.

**Events and analysis**

- **FR-014**: System MUST decide whether each post is market-relevant and assign zero or more
  categories from: tariffs and trade; energy and oil; technology and semiconductors; defence;
  banking and monetary policy; immigration and employment; government spending; sanctions and
  international relations.
- **FR-015**: System MUST identify companies, tickers, countries, industries, commodities, and
  government bodies in a post and map them to symbols in the universe.
- **FR-016**: System MUST NOT assign a symbol when an entity is ambiguous and the context does
  not resolve it.
- **FR-017**: System MUST measure abnormal returns relative to a market benchmark for each
  event and window, using the time the post became available to the system.
- **FR-018**: System MUST group overlapping posts on the same theme into one event so they are
  not counted twice.
- **FR-019**: System MUST produce reproducible event-study reports with per-category averages,
  sample counts, and a significance measure.

**Prediction**

- **FR-020**: System MUST train models on chronological splits and MUST NOT use any
  information dated after the prediction timestamp.
- **FR-021**: System MUST predict direction of abnormal return, expected magnitude,
  probability of unusual volatility, and a confidence value.
- **FR-022**: System MUST evaluate every model against naive baselines and MUST publish only
  metrics computed on held-out later data.
- **FR-023**: System MUST version every trained model and attach the version to each
  prediction.
- **FR-024**: System MUST refuse to train or predict when data is insufficient and MUST say
  why.

**Strategies and backtesting**

- **FR-025**: System MUST provide three strategies: immediate reaction, momentum continuation,
  and mean reversion.
- **FR-026**: Each strategy MUST support configurable holding period, position sizing, risk
  limits, stop-loss and exit rules, transaction costs, slippage, maximum exposure, and a
  no-trade decision.
- **FR-027**: System MUST backtest in time order and MUST price entries no earlier than the
  post's availability time plus a configured delay.
- **FR-028**: System MUST report cumulative return, Sharpe ratio, Sortino ratio, maximum
  drawdown, win rate, profit factor, turnover, trade count, and performance by category, with
  a benchmark comparison.
- **FR-029**: System MUST state the cost, slippage, and execution assumptions with every
  backtest result.

**Paper trading**

- **FR-030**: System MUST submit paper orders, track their status, monitor positions, and
  reconcile its portfolio state with the paper broker.
- **FR-031**: System MUST prevent duplicate orders for the same signal.
- **FR-032**: System MUST provide a kill switch that blocks all new orders, a daily loss limit,
  and market-hours validation.
- **FR-033**: System MUST log every order decision, including refusals and their reasons.
- **FR-034**: System MUST NOT be able to submit real-money orders under any configuration.

**Access and presentation**

- **FR-035**: System MUST expose posts, events, market data, predictions, signals, backtests,
  trades, portfolio state, and health status through a documented service interface, with a
  live stream for new events.
- **FR-036**: System MUST provide a dashboard with Overview, Political Event Feed, Stock
  Market Analysis, Strategy Research, Paper Trading, and Model Analytics sections.
- **FR-037**: The dashboard MUST show an explicit empty or error state when data is
  unavailable and MUST NOT show fabricated or placeholder financial values.

**Quality and operations**

- **FR-038**: System MUST ship automated tests that run without network access or credentials,
  and a continuous integration check that runs them on every push.
- **FR-039**: System MUST read all credentials from the environment and MUST NOT store them in
  the repository.
- **FR-040**: System MUST provide a documented, repeatable local setup and MUST keep
  architecture, roadmap, interface, status, and decision documents current.

### Key Entities

- **Social Post**: One post from the monitored account. Identity, text, publication time,
  retrieval time, source link, repost flag, edit and deletion state.
- **Market Event**: A market-relevant post or cluster of posts. Categories, recognised
  entities, affected symbols, and the time it became available to the system.
- **Stock Candle**: Price and volume for one symbol over one interval, with source and data
  quality label.
- **Market Feature**: A measured quantity for a symbol around an event: return, abnormal
  return, volatility, or volume change over a named window.
- **Model Prediction**: A model's forecast for one event and symbol: direction, magnitude,
  volatility probability, confidence, and model version.
- **Trading Signal**: A strategy's decision for one event and symbol: buy, sell, or no-trade,
  with size, holding period, and reason.
- **Backtest Result**: The outcome of running one strategy configuration over a period:
  metrics, trades, equity curve, and stated assumptions.
- **Paper Order**: A simulated order derived from a signal: side, size, status history, fill
  details, and the signal it came from.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Importing the same archive twice leaves the number of stored posts unchanged.
- **SC-002**: 100% of stored posts carry both a publication time and a retrieval time in UTC;
  records that cannot meet this are listed in a rejection report.
- **SC-003**: A researcher can go from a fresh checkout to a completed event study on real
  data by following the setup guide, in under 30 minutes excluding download time.
- **SC-004**: Running the event study twice on the same stored data yields identical results.
- **SC-005**: For any event the researcher selects, the reported return for each window can
  be recomputed by hand from the stored prices and matches to four decimal places.
- **SC-006**: Every published model metric comes from data dated after the model's training
  period, and each report shows at least one naive baseline for comparison.
- **SC-007**: In every backtest, zero trades are entered before the post's availability time.
- **SC-008**: With the kill switch on, zero orders are placed across all tests; duplicate
  signals never create a second order.
- **SC-009**: With an empty data store, every dashboard section shows an empty state and no
  numeric financial values.
- **SC-010**: The automated checks complete in under 5 minutes on a developer machine with no
  network access and pass on every push.
- **SC-011**: The full development setup runs at no monetary cost.

## Assumptions

- The platform has a single local user; sign-in, multi-user access, and public hosting are out
  of scope.
- Only the one monitored account is in scope; other accounts and platforms are not.
- Historical posts come from a public archive or licensed dataset. If no permitted source of
  new posts is available, near-live collection uses periodic import from the same archive and
  its latency is reported rather than hidden.
- Free-tier market data may be delayed or limited to one venue and to a limited intraday
  history. The platform labels this, and intraday windows are reported as unavailable for
  events older than the available intraday history.
- The universe is a curated list of liquid US stocks and sector ETFs, large enough to cover
  the eight categories. A broad market ETF is the benchmark for abnormal returns.
- Paper trading uses a paper-trading account supplied by the researcher. Without credentials,
  the built-in simulated execution is used.
- Delivery is phased: foundation, then the historical research MVP, then stronger models and
  strategy evaluation, then real-time paper trading. Stories 1 to 4 form the MVP.
- No result of this platform is investment advice. Observed associations are not treated as
  proof that a post caused a price move.
