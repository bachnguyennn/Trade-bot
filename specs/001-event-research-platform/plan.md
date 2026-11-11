# Implementation Plan: TradeBot Event Research and Paper-Trading Platform

**Branch**: `001-event-research-platform` | **Date**: 2026-11-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-event-research-platform/spec.md`

## Summary

Build a local-first research platform that turns an archive of political posts into
point-in-time market events, measures abnormal returns around them, trains leak-free baseline
models, backtests three event-driven strategies with costs, and paper trades through a
simulated broker. The backend is a Python package with shared Pydantic contracts and
file-based Bronze/Silver/Gold storage; a FastAPI service exposes results to a React dashboard.
The historical event-study path (Stories 1 to 4) is delivered first.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5 (frontend)

**Primary Dependencies**: Pydantic v2, pydantic-settings, Polars, PyArrow, httpx, FastAPI,
Uvicorn, Typer, scikit-learn, exchange-calendars, yfinance (optional provider); React 18,
Vite, Tailwind CSS, Recharts

**Storage**: Parquet files under `data/{bronze,silver,gold}/` written with Polars; JSON
reports under `data/reports/`; SQLite (standard library) for paper-trading order state.
PostgreSQL is deferred until a requirement needs it.

**Testing**: pytest (offline by default, `live` marker for provider tests), ruff, mypy;
Vitest for the frontend

**Target Platform**: Developer workstation (Windows, macOS, Linux); GitHub Actions for CI

**Project Type**: Web application: Python backend with CLI, plus a separate frontend

**Performance Goals**: Full historical import and event study over about 30,000 posts and 60
symbols completes in under 5 minutes on a laptop, excluding downloads. API list endpoints
respond in under 500 ms on local data.

**Constraints**: No paid services. Tests run offline. No real-money execution path. All
timestamps UTC. Decisions use availability time plus configured latency.

**Scale/Scope**: One user, one monitored account, about 30,000 posts, about 60 symbols, daily
bars from 2022 and intraday bars where the provider offers them.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. Research Integrity | Metrics come only from computed results; fixtures are labelled synthetic and never served by the API; chronological splits enforced in code; reports state assumptions and avoid causal claims | Pass |
| II. Paper Trading Only | `ExecutionBroker` interface with simulator and paper adapter; paper adapter rejects any base URL other than the paper endpoint; no live adapter exists; kill switch, loss limit, hours check, dedupe in the order service | Pass |
| III. Legal Data Access | Posts from a CC0-1.0 published archive; no scraping of the platform; opt-in sources require an explicit acknowledgement flag; every source recorded in `docs/DATA_SOURCES.md`; candles carry a quality label | Pass |
| IV. Contract-First | Eight contracts in `src/contracts/`; modules import only contracts and published interfaces; TypeScript types checked against the OpenAPI schema | Pass |
| V. Test-Backed Delivery | Each task group has tests; default suite offline; CI runs ruff, mypy, pytest | Pass |
| VI. Point-in-Time | `published_at`, `retrieved_at`, and a single `availability_time()` rule used by features, models, and backtests; Bronze kept unmodified | Pass |
| VII. Security and Low Cost | Settings from environment; `.env.example`; no paid dependency | Pass |

Post-design re-check: no violations. One documented limitation, not a violation: the symbol
universe is curated today, so results carry survivorship bias for symbols that would have
been chosen differently in the past. Each symbol has `eligible_from` so that symbols are not
traded before they were listed, and the limitation is stated in every report.

## Project Structure

### Documentation (this feature)

```text
specs/001-event-research-platform/
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   |-- http-api.md
|   `-- cli.md
|-- checklists/requirements.md
`-- tasks.md
```

### Source Code (repository root)

```text
src/
|-- contracts/       # Shared Pydantic models and enums (Agent 0)
|-- core/            # Settings, logging, time rules, storage paths (Agent 0)
|-- ingestion/       # Post sources, HTTP client with retry, Bronze writer (Agent 1)
|-- pipelines/       # Bronze -> Silver -> Gold orchestration (Agent 1)
|-- market_data/     # Providers, calendar, universe, candle store, windows (Agent 2)
|-- ml/              # Classifier, entities, dataset, models, evaluation (Agent 3)
|-- strategies/      # Strategies A, B, C and shared sizing/risk (Agent 4)
|-- backtesting/     # Event study, engine, metrics, benchmarks (Agent 4)
|-- trading/         # ExecutionBroker, simulator, paper adapter, order service (Agent 5)
|-- api/             # FastAPI app, routers, WebSocket stream (Agent 5)
`-- cli.py           # `tradebot` command

frontend/            # React + TypeScript dashboard (Agent 6)
tests/
|-- unit/
|-- integration/
|-- contract/
`-- fixtures/        # Small synthetic files, labelled as such
infra/               # Dockerfiles and docker-compose.yml (Agent 7)
.github/workflows/   # CI (Agent 7)
docs/                # ARCHITECTURE, ROADMAP, API_CONTRACTS, AGENT_STATUS, DECISIONS, DATA_SOURCES, SECURITY
data/                # Bronze/Silver/Gold and reports; not committed
```

**Structure Decision**: Web application. The backend lives directly under `src/` so that the
module paths match the ownership areas in the project brief; it is imported as the `src`
package with the repository root on the path. The frontend is a separate Vite project in
`frontend/`. Tests sit at the repository root.

## Delivery Phases

| Phase | Scope | Stories | Exit test |
|-------|-------|---------|-----------|
| 1. Foundation | Contracts, settings, storage, repo skeleton, CI, dashboard shell, API scaffold | setup | Local environment starts, CI green, initial tests pass |
| 2. Historical research MVP | Post import, market data, classification, event study, baseline model, simple backtest, API and dashboard on real results | 1, 2, 3, 4, part of 5, 6, 8 | A real post is matched to market data and an event study reproduces |
| 3. Models and strategies | Stronger models, full strategy evaluation with costs and benchmarks, leakage guards, experiment views | 5, 6 | Holdout evaluation and cost-inclusive strategy results reproduce |
| 4. Real-time paper trading | Incremental post feed, live market data, signal to paper order path, live monitoring, failure tests | 7 | New post produces a prediction, a signal, and a reconciled paper order; kill switch stops orders |

## Complexity Tracking

No constitution violations to justify.
