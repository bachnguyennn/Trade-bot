# Tasks: TradeBot Event Research and Paper-Trading Platform

**Input**: Design documents from `/specs/001-event-research-platform/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required. The spec (FR-038) and the constitution (Principle V) require tests for
every feature. Tests run offline by default.

**Organization**: Tasks are grouped by user story. Owner areas follow the project brief:
A0 architecture, A1 ingestion, A2 market data, A3 ML, A4 research and strategy, A5 backend
and trading, A6 frontend, A7 QA and infrastructure.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story the task belongs to (US1 to US8)

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create the repository skeleton: `src/{contracts,core,ingestion,pipelines,market_data,ml,strategies,backtesting,trading,api}/__init__.py`, `tests/{unit,integration,contract,fixtures}/`, `docs/`, `infra/`
- [X] T002 Create `pyproject.toml` with runtime dependencies (pydantic, pydantic-settings, polars, pyarrow, httpx, fastapi, uvicorn, typer, scikit-learn, exchange-calendars, yfinance), a `dev` extra (pytest, pytest-asyncio, ruff, mypy), the `tradebot` script entry, and ruff, mypy, and pytest configuration (offline default, `live` marker)
- [X] T003 [P] Create `.env.example` listing every setting with placeholder values and `README.md` with purpose, safety statement, setup, and commands
- [X] T004 [P] Create `.github/workflows/ci.yml` running ruff, mypy, pytest, and the frontend type check, build, and tests
- [X] T005 [P] Create `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/API_CONTRACTS.md`, `docs/AGENT_STATUS.md`, `docs/DECISIONS.md`, `docs/DATA_SOURCES.md`, `docs/SECURITY.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared contracts and core services every story depends on.

- [X] T006 Implement enumerations in `src/contracts/enums.py` exactly as listed in data-model.md (`IngestionMode`, `EventCategory`, `EntityType`, `DataQuality`, `EventWindow`, `Direction`, `SignalAction`, `StrategyName`, `OrderSide`, `OrderStatus`)
- [X] T007 Implement `SocialPost`, `Entity`, `MarketEvent` in `src/contracts/posts.py` with `extra="forbid"`, timezone-aware datetime validation, and "`categories`: at least one" on `MarketEvent`
- [X] T008 [P] Implement `StockCandle`, `UniverseMember`, `MarketFeature` in `src/contracts/market.py` with "`low <= open, close <= high`", non-negative volume, and "`unavailable_reason` required when `available` is false"
- [X] T009 [P] Implement `ModelPrediction`, `TradingSignal` in `src/contracts/signals.py` with probabilities in 0 to 1, "`target_weight` 0 for `no_trade`", and required `reason`
- [X] T010 [P] Implement `BacktestMetrics`, `BacktestTrade`, `EquityPoint`, `BacktestResult`, `PaperOrder`, `OrderStatusChange` in `src/contracts/trading.py` with "`qty > 0`" and "`reject_reason` required for `rejected` and `blocked`"
- [X] T011 Export all contracts from `src/contracts/__init__.py`
- [X] T012 [P] Implement `Settings` (pydantic-settings, `TRADEBOT_` prefix) in `src/core/settings.py`: data directory, latencies, provider, Alpaca keys, unverified-source flag, risk limits
- [X] T013 [P] Implement `ensure_utc`, `parse_timestamp`, and `availability_time(post, assumed_latency)` in `src/core/timeutils.py` per research R6
- [X] T014 [P] Implement storage paths and Parquet read, write, and atomic replace helpers in `src/core/storage.py` per the Storage Layout table
- [X] T015 [P] Implement structured JSON logging setup in `src/core/logging.py`
- [X] T016 [P] Contract tests for every model's validation rules in `tests/contract/test_contracts.py`
- [X] T017 [P] Unit tests for time rules and storage helpers in `tests/unit/core/test_timeutils.py` and `tests/unit/core/test_storage.py`

**Checkpoint**: Contracts are importable and tested. Story work can start in parallel.

---

## Phase 3: User Story 1 - Build a trustworthy history of posts (Priority: P1) MVP

**Goal**: Import an archive into Bronze and Silver with deduplication, edits, rejections,
and incremental updates.

**Independent Test**: Import `tests/fixtures/posts_sample.json` twice; counts are unchanged,
timestamps are UTC, Bronze holds the raw records.

- [X] T018 [P] [US1] Create the synthetic fixture `tests/fixtures/posts_sample.json` covering a normal post, a duplicate, an edited post, a repost, a media-only post, and a record with no timestamp
- [X] T019 [P] [US1] Unit tests for HTML cleaning, repost detection, hashing, and record normalisation in `tests/unit/ingestion/test_normalize.py`
- [X] T020 [P] [US1] Unit tests for retry, backoff, and rate-limit handling with a mock transport in `tests/unit/ingestion/test_http.py`
- [X] T021 [P] [US1] Integration tests for idempotent import, edit versioning, deletion marking, and the rejection report in `tests/integration/test_post_pipeline.py`
- [X] T022 [US1] Implement the async HTTP client with retries, exponential backoff, and `Retry-After` support in `src/ingestion/http.py`
- [X] T023 [US1] Implement `PostSource` protocol and `ArchiveFileSource`, `StilesArchiveSource`, `CnnArchiveSource` (refuses unless the unverified-source flag is set) in `src/ingestion/sources.py`
- [X] T024 [US1] Implement HTML-to-text cleaning, repost detection, content hashing, and raw-to-`SocialPost` normalisation in `src/ingestion/normalize.py`
- [X] T025 [US1] Implement the Bronze writer (append-only, one file per fetch, fetch metadata) in `src/ingestion/bronze.py`
- [X] T026 [US1] Implement the Bronze-to-Silver build with deduplication, version tracking, deletion marking, and `IngestReport` in `src/pipelines/posts.py`
- [X] T027 [US1] Add `tradebot ingest posts` and `tradebot status` to `src/cli.py`

**Checkpoint**: Posts can be imported and re-imported safely.

---

## Phase 4: User Story 2 - Market data that matches the posts (Priority: P1)

**Goal**: Store labelled candles for a defined universe and compute window returns that
respect sessions and missing data.

**Independent Test**: With fixture candles, request every window after a weekday timestamp
and after a weekend timestamp.

- [X] T028 [P] [US2] Unit tests for the calendar (session lookup, next open, holiday, early close) in `tests/unit/market_data/test_calendar.py`
- [X] T029 [P] [US2] Unit tests for window returns: in-session, shifted to open, missing bars, crossing the close, coarse bars, `1d`, `close_to_close` in `tests/unit/market_data/test_windows.py`
- [X] T030 [P] [US2] Unit tests for the candle store (upsert, quality label preserved, range read) and the universe (eligibility dates) in `tests/unit/market_data/test_store.py`
- [X] T031 [US2] Implement the XNYS calendar wrapper in `src/market_data/calendar.py`
- [X] T032 [P] [US2] Implement the universe (about 60 symbols with sector, themes, `eligible_from`) and benchmark in `src/market_data/universe.py`
- [X] T033 [US2] Implement the `MarketDataProvider` protocol, `AlpacaProvider`, and `YFinanceProvider` with quality labels in `src/market_data/providers.py`
- [X] T034 [US2] Implement the candle store (per symbol and interval Parquet, upsert by key) in `src/market_data/store.py`
- [X] T035 [US2] Implement window computation per research R7 returning `MarketFeature` in `src/market_data/windows.py`
- [X] T036 [US2] Add `tradebot ingest market` to `src/cli.py`

**Checkpoint**: Any timestamp can be matched to market windows.

---

## Phase 5: User Story 3 - Which posts matter and what they touch (Priority: P1)

**Goal**: Classify relevance and categories, recognise entities, map to symbols, and build
clustered Gold events.

**Independent Test**: Classify a labelled sample; categories, entities, and symbols match.

- [X] T037 [P] [US3] Unit tests for category rules (single, multi-label, not relevant) in `tests/unit/ml/test_classifier.py`
- [X] T038 [P] [US3] Unit tests for entity recognition, ambiguity handling, and symbol mapping in `tests/unit/ml/test_entities.py`
- [X] T039 [P] [US3] Integration tests for event building and clustering in `tests/integration/test_event_pipeline.py`
- [X] T040 [US3] Implement the category lexicon and `RuleBasedClassifier` (`rules-v1`) in `src/ml/classifier.py`
- [X] T041 [US3] Implement the gazetteer and `EntityRecognizer` with context checks for ambiguous names in `src/ml/entities.py`
- [X] T042 [US3] Implement post-to-event building, symbol mapping by entity and theme, and clustering per research R8 in `src/pipelines/events.py`
- [X] T043 [US3] Add `tradebot build events` to `src/cli.py`

**Checkpoint**: Gold events exist for relevant posts.

---

## Phase 6: User Story 4 - Reproduce an event study (Priority: P1)

**Goal**: Compute features for every event, symbol, and window, and a reproducible study.

**Independent Test**: Run the study twice; results are identical; one event recomputes by hand.

- [X] T044 [P] [US4] Unit tests for study aggregation, t-statistics, and determinism in `tests/unit/backtesting/test_event_study.py`
- [X] T045 [P] [US4] Integration test from fixture posts and candles to a study report in `tests/integration/test_event_study_pipeline.py`
- [X] T046 [US4] Implement the feature build over events, symbols, and windows in `src/pipelines/features.py`
- [X] T047 [US4] Implement the event study (per event, per category and window: mean, median, count, t-statistic, share positive) and `EventStudyReport` in `src/backtesting/event_study.py`
- [X] T048 [US4] Add `tradebot build features` and `tradebot research event-study` to `src/cli.py`

**Checkpoint**: Historical research MVP. Stories 1 to 4 run end to end on real data.

---

## Phase 7: User Story 5 - Train and evaluate prediction models honestly (Priority: P2)

**Goal**: Leak-free baseline model with honest evaluation and versioned inference.

**Independent Test**: Train on fixture events; splits are chronological; report includes
naive baselines; training refuses on too few samples.

- [X] T049 [P] [US5] Unit tests for the chronological split, embargo, and leakage guard in `tests/unit/ml/test_dataset.py`
- [X] T050 [P] [US5] Unit tests for training, evaluation against baselines, refusal on small data, and version mismatch in `tests/unit/ml/test_model.py`
- [X] T051 [US5] Implement dataset assembly and `chronological_split` with embargo in `src/ml/dataset.py`
- [X] T052 [US5] Implement the TF-IDF plus logistic and ridge baseline, model registry, and versioning in `src/ml/baseline.py`
- [X] T053 [US5] Implement evaluation metrics, naive baselines, and `ModelReport` in `src/ml/evaluation.py`
- [X] T054 [US5] Implement the inference service returning `ModelPrediction` in `src/ml/inference.py`
- [X] T055 [US5] Add `tradebot model train` and `tradebot model predict` to `src/cli.py`

---

## Phase 8: User Story 6 - Backtest strategies with realistic assumptions (Priority: P2)

**Goal**: Three strategies, an event-driven engine with costs and risk limits, and metrics.

**Independent Test**: Backtest each strategy on fixture data; no entry precedes
availability; costs reduce returns; metric set is complete.

- [X] T056 [P] [US6] Unit tests for metrics (return, Sharpe, Sortino, drawdown, win rate, profit factor, turnover) in `tests/unit/backtesting/test_metrics.py`
- [X] T057 [P] [US6] Unit tests for the engine: entry timing, costs, slippage, stop-loss, exposure cap, no overlapping position, no look-ahead in `tests/unit/backtesting/test_engine.py`
- [X] T058 [P] [US6] Unit tests for the three strategies including no-trade decisions in `tests/unit/strategies/test_strategies.py`
- [X] T059 [US6] Implement the strategy base, configuration, and sizing in `src/strategies/base.py`
- [X] T060 [P] [US6] Implement Strategy A in `src/strategies/immediate_reaction.py`
- [X] T061 [P] [US6] Implement Strategy B in `src/strategies/momentum_continuation.py`
- [X] T062 [P] [US6] Implement Strategy C in `src/strategies/mean_reversion.py`
- [X] T063 [US6] Implement performance metrics in `src/backtesting/metrics.py`
- [X] T064 [US6] Implement the event-driven engine and benchmark comparison in `src/backtesting/engine.py`
- [X] T065 [US6] Implement the backtest runner that writes `BacktestResult` reports in `src/backtesting/runner.py` and add `tradebot backtest run` and `tradebot pipeline run` to `src/cli.py`

---

## Phase 9: User Story 8 - Review everything in one dashboard (Priority: P2)

**Goal**: API over stored results and a six-section dashboard with empty states.

**Independent Test**: With an empty store every endpoint returns empty lists and every
section shows an empty state; with data the values match the store.

- [X] T066 [P] [US8] API tests on an empty store and a populated store in `tests/integration/test_api.py`
- [X] T067 [P] [US8] Contract test that the OpenAPI schema contains every documented path and contract in `tests/contract/test_openapi.py`
- [X] T068 [US8] Implement the FastAPI app, dependencies, and health, ready, and status routes in `src/api/app.py` and `src/api/routers/system.py`
- [X] T069 [P] [US8] Implement posts, events, and ingest routes in `src/api/routers/events.py`
- [X] T070 [P] [US8] Implement universe, candles, and features routes in `src/api/routers/market.py`
- [X] T071 [P] [US8] Implement event-study, backtest, model, prediction, and signal routes in `src/api/routers/research.py`
- [X] T072 [US8] Implement the WebSocket stream and broadcaster in `src/api/stream.py` and add `tradebot serve` to `src/cli.py`
- [X] T073 [US8] Scaffold the Vite, React, TypeScript, and Tailwind project in `frontend/` with the layout shell and navigation in `frontend/src/App.tsx`
- [X] T074 [P] [US8] Implement the typed API client and contract types in `frontend/src/api/client.ts` and `frontend/src/api/types.ts`
- [X] T075 [P] [US8] Implement shared components (`EmptyState`, `ErrorState`, `StatCard`, `DataQualityBadge`) in `frontend/src/components/`
- [X] T076 [P] [US8] Implement the Overview and Political Event Feed pages in `frontend/src/pages/Overview.tsx` and `frontend/src/pages/EventFeed.tsx`
- [X] T077 [P] [US8] Implement the Stock Market Analysis page with event markers in `frontend/src/pages/MarketAnalysis.tsx`
- [X] T078 [P] [US8] Implement the Strategy Research and Model Analytics pages in `frontend/src/pages/StrategyResearch.tsx` and `frontend/src/pages/ModelAnalytics.tsx`
- [X] T079 [P] [US8] Implement the Paper Trading page in `frontend/src/pages/PaperTrading.tsx`
- [X] T080 [US8] Frontend tests for empty and error states in `frontend/src/__tests__/states.test.tsx`

---

## Phase 10: User Story 7 - Paper trade safely (Priority: P3)

**Goal**: Simulated and paper execution behind one interface with all safety checks.

**Independent Test**: Unit and integration tests for dedupe, kill switch, loss limit, hours
check, broker rejection, and the paper-endpoint guard.

- [X] T081 [P] [US7] Unit tests for the simulator and the paper-endpoint guard in `tests/unit/trading/test_brokers.py`
- [X] T082 [P] [US7] Unit tests for the order service: dedupe, kill switch, loss limit, market hours, rejection, retry without duplicates in `tests/unit/trading/test_order_service.py`
- [X] T083 [P] [US7] Integration test from signal to reconciled order through the API in `tests/integration/test_paper_trading.py`
- [X] T084 [US7] Implement the `ExecutionBroker` protocol and `SimulatedBroker` in `src/trading/broker.py`
- [X] T085 [US7] Implement `AlpacaPaperBroker` that accepts only `https://paper-api.alpaca.markets` in `src/trading/alpaca_paper.py`
- [X] T086 [US7] Implement the SQLite order and risk state store in `src/trading/state.py`
- [X] T087 [US7] Implement `OrderService` with kill switch, daily loss limit, market-hours check, idempotency, reconciliation, and decision logging in `src/trading/service.py`
- [X] T088 [US7] Implement trading routes (orders, positions, portfolio, risk, kill switch) in `src/api/routers/trading.py`
- [X] T089 [US7] Implement the live processing workflow (new post to event, prediction, signal, order, stream message) in `src/pipelines/live.py`

---

## Phase 11: Polish & Cross-Cutting Concerns

- [X] T090 [P] Add `infra/Dockerfile.api`, `infra/Dockerfile.frontend`, and `infra/docker-compose.yml`
- [X] T091 [P] Add a leakage and reproducibility guard suite in `tests/integration/test_research_integrity.py`
- [X] T092 Run the quickstart scenarios on real data and record the outcome in `docs/AGENT_STATUS.md`
- [X] T093 [P] Update `docs/ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, and `README.md` to match the implementation
- [ ] T094 [P] Phase 3 extension: optional transformer-embedding model and comparison report in `src/ml/embeddings.py` (deferred: the baseline shows no signal yet; see docs/ROADMAP.md)

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1) has no dependencies.
- Foundational (Phase 2) depends on Setup and blocks every story.
- US1 and US2 depend only on Foundational and can run in parallel.
- US3 depends on US1 (posts) and the universe from US2 (T032).
- US4 depends on US2 (windows) and US3 (events).
- US5 depends on US4 (features as labels).
- US6 depends on US4; Strategy A also uses US5 predictions when present.
- US8 API depends on Foundational; each route returns empty results until its story lands.
  The frontend depends on the API contract only.
- US7 depends on Foundational and the calendar (T031); the live workflow (T089) depends on
  US3, US5, and US6.
- Polish depends on the stories it documents.

### Within Each User Story

- Tests are written with the implementation and must pass before the story is closed.
- Contracts before services, services before CLI and endpoints.

### Parallel Opportunities

- After Phase 2: A1 on US1, A2 on US2, A5 on T068 to T072, A6 on T073 to T080, A7 on T004
  and T090 can proceed at the same time; they own different directories.
- Within US6, the three strategy files (T060 to T062) are independent.
- Within US8, the router files and the page files are independent.

## Parallel Example: after Foundational

```text
A1: T018-T027  src/ingestion, src/pipelines/posts.py
A2: T028-T036  src/market_data
A5: T066-T072  src/api
A6: T073-T080  frontend
A7: T004, T090 .github, infra
```

## Implementation Strategy

### MVP First

1. Phases 1 and 2.
2. US1, US2, US3, US4 in dependency order.
3. Stop and validate with quickstart Scenarios 1 to 3 on real data.

### Incremental Delivery

1. MVP (US1 to US4): reproducible event study.
2. US5 and US6: predictions and cost-aware backtests.
3. US8: API and dashboard over real results.
4. US7: paper trading and the live workflow.
5. Each increment is committed and pushed when its tests pass.

## Completion Notes (2026-11-11)

- T001 to T093 are complete. T094 is deferred.
- T092: quickstart scenarios 1 to 4 and 6 passed on real data. Scenario 5: the API was
  verified with real data and the dashboard was built and served, but it was not viewed in
  a browser.
- T090: Docker files were written but not run locally (no Docker on the machine). CI
  validates the Compose file.
- Additions beyond the original list: `src/pipelines/market.py`, `src/api/services.py`,
  `src/api/deps.py`, `tests/contract/test_frontend_types.py`, `docs/RESEARCH_RESULTS.md`.

## Notes

- A task is done only when its tests pass.
- Fixtures are synthetic and labelled; they never appear in reports or API responses.
- Commit after each task group; push regularly.
