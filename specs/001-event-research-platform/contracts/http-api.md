# HTTP API Contract

Base path: `/api/v1`. JSON bodies use the contracts in [data-model.md](../data-model.md).
The generated OpenAPI document at `/openapi.json` is the authoritative schema; this file
lists the endpoints and their behaviour.

Common rules:

- List endpoints accept `limit` (default 50, max 500) and `offset`.
- An empty data store returns `200` with an empty list, never invented rows.
- A missing single resource returns `404` with `{"detail": "..."}`.
- Invalid input returns `422`.

## Health

| Method | Path | Response |
|--------|------|----------|
| GET | `/health` | `{"status": "ok"}` whenever the process is up |
| GET | `/ready` | `{"ready": bool, "checks": {name: {"ok": bool, "detail": str}}}`; `ready` is false when no posts or candles are stored |
| GET | `/api/v1/status` | Counts of posts, events, candles, features; latest post time; market data provider and quality; broker name; kill switch state |

## Posts and events

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/v1/posts` | `list[SocialPost]`, newest first; filters `since`, `until`, `q` |
| GET | `/api/v1/events` | `list[MarketEvent]`, newest first; filters `category`, `symbol`, `since`, `until` |
| GET | `/api/v1/events/{event_id}` | `EventDetail{event, posts, features, predictions}` |
| POST | `/api/v1/ingest/run` | Runs incremental ingestion and the downstream pipeline; returns `IngestReport` |

## Market data

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/v1/universe` | `list[UniverseMember]` |
| GET | `/api/v1/market/candles` | `list[StockCandle]`; required `symbol`, `interval`; optional `start`, `end` |
| GET | `/api/v1/market/features` | `list[MarketFeature]`; filters `event_id`, `symbol`, `window` |

## Research

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/v1/research/event-study` | Latest `EventStudyReport`, or `404` when none exists |
| POST | `/api/v1/research/event-study/run` | Runs the study; returns `EventStudyReport` |
| GET | `/api/v1/backtests` | `list[BacktestSummary]` |
| GET | `/api/v1/backtests/{run_id}` | `BacktestResult` |
| POST | `/api/v1/backtests/run` | Body `BacktestRequest{strategy, config}`; returns `BacktestResult` |

## Models

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/v1/models` | `list[ModelReport]`: versions, split periods, metrics, baselines |
| POST | `/api/v1/models/predict` | Body `PredictRequest{text, symbols?, window?}`; returns `list[ModelPrediction]`; `409` when no model is trained; `409` when `model_version` is given and does not match |
| GET | `/api/v1/predictions` | `list[ModelPrediction]`; filters `event_id`, `symbol` |

## Signals and paper trading

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/v1/signals` | `list[TradingSignal]`; filter `strategy` |
| GET | `/api/v1/trading/orders` | `list[PaperOrder]` |
| POST | `/api/v1/trading/orders` | Body `TradingSignal`; returns `PaperOrder` (status may be `blocked` with a reason) |
| GET | `/api/v1/trading/positions` | `list[Position{symbol, qty, avg_price, market_value}]` |
| GET | `/api/v1/trading/portfolio` | `Portfolio{cash, equity, day_pnl, gross_exposure, broker}` |
| GET | `/api/v1/trading/risk` | `RiskState{kill_switch, daily_loss_limit, day_pnl, loss_limit_breached}` |
| POST | `/api/v1/trading/kill-switch` | Body `{"enabled": bool}`; returns `RiskState` |

## Live stream

`WS /api/v1/stream` sends JSON messages `{"type": str, "data": object, "ts": datetime}` with
`type` in `event`, `prediction`, `signal`, `order`, `status`. The server sends a `status`
message on connect.

## Safety contract

- No endpoint accepts a broker URL or a live-trading flag.
- `POST /api/v1/trading/orders` never returns an order with a broker other than `simulator`
  or `alpaca-paper`.
