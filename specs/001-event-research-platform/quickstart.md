# Quickstart: validate the platform end to end

Contracts: [data-model.md](./data-model.md), [contracts/http-api.md](./contracts/http-api.md),
[contracts/cli.md](./contracts/cli.md).

## Prerequisites

- Python 3.12
- Node.js 20 or later (dashboard only)
- Optional: Alpaca API keys for deeper intraday history and paper trading

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
cp .env.example .env              # optional; defaults work without keys
```

## Scenario 1: offline checks (SC-010)

```bash
ruff check src tests
mypy src
pytest
```

Expected: all pass with no network access.

## Scenario 2: historical import is idempotent (SC-001, SC-002)

```bash
python -m src.cli ingest posts --source stiles
python -m src.cli ingest posts --source stiles
python -m src.cli status
```

Expected: the second run reports zero new posts; `status` shows the same post count; every
post has UTC publication and retrieval times.

## Scenario 3: event study on real data (SC-003, SC-004, SC-005)

```bash
python -m src.cli ingest market --interval 1d --start 2022-01-01
python -m src.cli build events
python -m src.cli build features
python -m src.cli research event-study
python -m src.cli research event-study
```

Expected: two report files with identical results. Pick one event from the report and
recompute its `1d` return from `data/silver/candles/1d/<symbol>.parquet`; it matches to four
decimal places.

## Scenario 4: baseline model and backtests (SC-006, SC-007)

```bash
python -m src.cli model train --window 1d
python -m src.cli backtest run --strategy immediate_reaction
python -m src.cli backtest run --strategy momentum_continuation
python -m src.cli backtest run --strategy mean_reversion
```

Expected: the model report lists train, validation, and test periods in time order with
naive baselines. Each backtest report has the full metric set, a benchmark, stated
assumptions, and no entry before the event's availability time.

## Scenario 5: API and dashboard (SC-009)

```bash
python -m src.cli serve --port 8000
cd frontend && npm install && npm run dev
```

Expected: `GET http://localhost:8000/health` returns `ok`. The dashboard at
`http://localhost:5173` shows real results in each section. With an empty `data/` directory
every section shows an empty state and no numbers.

## Scenario 6: paper-trading safety (SC-008)

```bash
pytest tests/unit/trading tests/integration/test_paper_trading.py
```

Expected: duplicate signals create one order; the kill switch blocks all orders; the paper
adapter refuses any non-paper endpoint.
