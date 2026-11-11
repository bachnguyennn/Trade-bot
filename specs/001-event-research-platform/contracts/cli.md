# CLI Contract

Entry point: `python -m src.cli` (installed as `tradebot`). Every command exits `0` on
success and non-zero on failure, logs to stderr, and prints a short JSON summary to stdout.

| Command | Purpose | Key options |
|---------|---------|-------------|
| `tradebot ingest posts` | Import posts into Bronze, rebuild Silver | `--source stiles\|cnn\|file`, `--path FILE`, `--mode historical\|live` |
| `tradebot ingest market` | Download candles for the universe and benchmark | `--interval 1d\|1h\|5m`, `--start DATE`, `--end DATE`, `--provider alpaca\|yfinance` |
| `tradebot build events` | Classify posts, resolve entities, cluster into events (Gold) | `--cluster-gap-minutes N` |
| `tradebot build features` | Compute window features for every event and symbol | `--decision-latency-seconds N` |
| `tradebot research event-study` | Run the event study and write a report | `--window W` (repeatable) |
| `tradebot model train` | Train and evaluate the baseline model | `--window W`, `--min-samples N` |
| `tradebot model predict` | Predict for a text | `--text TEXT`, `--symbol S` (repeatable) |
| `tradebot backtest run` | Run a strategy backtest and write a report | `--strategy NAME`, `--cost-bps N`, `--slippage-bps N` |
| `tradebot pipeline run` | Run ingest, build, study, train, and all three backtests in order | `--skip-download` |
| `tradebot serve` | Start the API | `--host`, `--port` |
| `tradebot status` | Print store counts and data quality | |

Rules:

- `--source cnn` fails unless `TRADEBOT_ALLOW_UNVERIFIED_SOURCES=true` is set.
- `--provider alpaca` fails with a clear message when API keys are missing.
- No command places orders with a live brokerage.
