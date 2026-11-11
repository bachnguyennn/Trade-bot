# TradeBot

An event-driven market research and paper-trading platform. It collects publicly archived
Truth Social posts by Donald Trump, finds the ones that touch financial markets, measures how
related stocks and ETFs moved afterwards, trains and evaluates prediction models, backtests
trading strategies with costs, and paper trades through a simulated broker.

> **Research software. Paper trading only.** The platform cannot place real-money orders:
> there is no live-trading adapter and no setting that enables one. Nothing here is
> investment advice, and no result is evidence of future returns.

## What it does

| Stage | What happens | Command |
|-------|--------------|---------|
| Posts | Imports a public-domain archive into raw (Bronze) and clean (Silver) tables; re-runs add only what is new | `tradebot ingest posts` |
| Market data | Downloads daily and intraday candles for about 75 liquid stocks and ETFs, labelled with source and quality | `tradebot ingest market` |
| Events | Classifies posts into eight policy categories, recognises companies, countries, and commodities, maps them to symbols, and merges overlapping posts | `tradebot build events` |
| Measurements | Abnormal return versus SPY over 5m, 15m, 30m, 1h, 4h, and next-day windows, entered only after the post was available | `tradebot build features` |
| Event study | Per-category statistics with a baseline control and session-clustered significance | `tradebot research event-study` |
| Models | TF-IDF baseline on chronological splits, compared with naive baselines | `tradebot model train` |
| Backtests | Immediate reaction, momentum continuation, and mean reversion, with costs, slippage, stops, and exposure limits | `tradebot backtest run` |
| Paper trading | Simulated or Alpaca paper orders behind a kill switch, daily loss limit, market-hours check, and duplicate prevention | API |
| Dashboard | Overview, event feed, market analysis, strategy research, paper trading, model analytics | `npm run dev` |

Current findings on real data are in [docs/RESEARCH_RESULTS.md](docs/RESEARCH_RESULTS.md).
The short version: no strategy tested so far beats buy-and-hold, and the baseline model shows
no demonstrated skill.

## Quick start

Requirements: Python 3.12. Node.js 20 or later for the dashboard. No account or API key is
needed for the default setup.

```bash
python -m venv .venv
.venv/Scripts/activate              # Windows. Elsewhere: source .venv/bin/activate
pip install -e ".[dev]"

# Run the whole historical pipeline on real data (downloads about 20 MB, takes a few minutes)
python -m src.cli pipeline run

# Start the API
python -m src.cli serve --port 8000

# In another terminal: start the dashboard at http://localhost:5173
cd frontend
npm install
npm run dev
```

Individual steps, in order:

```bash
python -m src.cli ingest posts --source stiles
python -m src.cli ingest market --interval 1d --start 2021-12-01
python -m src.cli ingest market --interval 1h
python -m src.cli build events
python -m src.cli build features
python -m src.cli research event-study
python -m src.cli model train --window 1d
python -m src.cli backtest run --strategy momentum_continuation
python -m src.cli status
```

With Docker: `docker compose -f infra/docker-compose.yml up --build`.

## Checks

```bash
ruff check src tests
ruff format --check src tests
mypy src
pytest                               # offline; no network or credentials needed
cd frontend && npm run typecheck && npm test && npm run build
```

## Configuration

Copy `.env.example` to `.env`. Every setting is optional.

| Setting | Default | Meaning |
|---------|---------|---------|
| `TRADEBOT_MARKET_PROVIDER` | `auto` | `alpaca` when keys are set, otherwise `yfinance` |
| `TRADEBOT_ALPACA_API_KEY`, `TRADEBOT_ALPACA_API_SECRET` | empty | Deeper intraday history and the paper broker |
| `TRADEBOT_BROKER` | `simulator` | `simulator` or `alpaca-paper`. There is no live option |
| `TRADEBOT_ASSUMED_LATENCY_SECONDS` | `60` | How long after publication a historical post is assumed to reach the system |
| `TRADEBOT_DECISION_LATENCY_SECONDS` | `30` | Extra delay before any simulated decision |
| `TRADEBOT_COST_BPS`, `TRADEBOT_SLIPPAGE_BPS` | `1.0`, `2.0` | Per-side backtest frictions |
| `TRADEBOT_DAILY_LOSS_LIMIT_PCT` | `0.02` | Paper trading stops for the day at this loss |
| `TRADEBOT_ALLOW_UNVERIFIED_SOURCES` | `false` | Required before the `cnn` post source can be used |

## Data sources and their limits

- **Posts**: the `stiles/trump-truth-social-archive` dataset (CC0-1.0), 29,409 posts from
  February 2022 to October 2025. Its updates stopped on 2025-10-26.
- **Market data without keys**: Yahoo Finance through `yfinance`, labelled `delayed`.
  Hourly bars reach back about two years and 5-minute bars about 60 days, so short windows
  are unavailable for older events and are reported as such.
- **Market data with keys**: Alpaca historical consolidated bars.

Details, licences, and review dates are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Repository layout

```text
src/contracts     shared Pydantic models used by every module
src/core          settings, logging, time rules, storage
src/ingestion     post sources, HTTP retries, Bronze layer
src/pipelines     posts, events, features, market, and live workflows
src/market_data   providers, trading calendar, universe, candle store, event windows
src/ml            classifier, entities, dataset splits, baseline model, inference
src/strategies    the three strategies
src/backtesting   event study, engine, metrics, runner
src/trading       execution interface, simulator, paper adapter, order service
src/api           FastAPI application
frontend          React dashboard
tests             unit, integration, and contract tests (synthetic data only)
infra             Dockerfiles and Compose
docs              architecture, roadmap, contracts, decisions, data sources, security
specs             Spec Kit specification, plan, and tasks
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API contracts](docs/API_CONTRACTS.md)
- [Research results](docs/RESEARCH_RESULTS.md)
- [Data sources](docs/DATA_SOURCES.md)
- [Security](docs/SECURITY.md)
- [Roadmap](docs/ROADMAP.md), [decisions](docs/DECISIONS.md), [status](docs/AGENT_STATUS.md)
- Interactive API reference at `http://localhost:8000/docs` when the API is running
